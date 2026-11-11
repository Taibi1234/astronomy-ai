"""Phase 11 OD-2 authorization document contract (design decisions D1/D5).

A single hashed document is the only authorization boundary for real-data work. The unsigned
dictionary that earlier stages accepted is gone: every entry point loads the document's exact
bytes, verifies the SHA-256 the caller pinned, parses only afterwards, and then binds the content
to the frozen facts — campaign id, protocol pin, manifest hashes, quarter set and scope.

Nothing here grants scientific authority by itself: the document must exist, be hashed, and match
the frozen inputs, and the caller must already hold an explicit owner approval.

Trust model (H3, an owner decision, deliberately not resolved here): the SHA-256 pin is supplied by
the caller and proves only that the bytes did not change after the pin was taken. It does **not**
authenticate the issuer — anyone able to run this code can mint a matching document and digest.
A real campaign therefore relies on procedural control (the owner distributes the digest out of
band and schedules the run). No signing key, certificate or registry is invented here.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import phase11_v2 as v2
from . import safeguards
from .phase11 import GateError

FIT_SOURCE = "real-campaign-fit-v2"
TEST_SOURCE = "real-campaign-v2"
SCOPES = ("fit_only", "fit_and_evaluate")
SCOPE_GRANTS = {"fit": ("fit_only", "fit_and_evaluate"), "campaign": ("fit_and_evaluate",)}
REQUIRED_FIELDS = (
    "campaign_id",
    "approver",
    "operator",
    "issued_at",
    "expires_at",
    "scope",
    "authorized_quarters",
    "protocol_sha256",
    "manifest_hashes",
    "single_run_ack",
)
CAMPAIGN_FIELDS = ("authorized_test_quarters",)
AUTHORIZATION_DIRNAME = "authorization"
MAX_VALIDITY_DAYS = 30
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class AuthorizationRef:
    """Caller-supplied binding: the document path, its pinned digest and the campaign id."""

    path: Path
    sha256: str
    campaign_id: str


def _digest_bytes(data: bytes) -> str:
    return v2.sha256_bytes(data)


def _read_document(path: Path, expected_sha256: str) -> tuple[dict, str]:
    path = Path(path)
    if not isinstance(expected_sha256, str) or _HEX64.fullmatch(expected_sha256.lower()) is None:
        raise GateError("authorization digest must be 64 lowercase hex characters")
    if not path.is_file():
        raise GateError(f"authorization document is missing: {path}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise GateError(f"authorization document is unreadable: {exc}") from exc
    digest = _digest_bytes(raw)
    if digest != expected_sha256.lower():
        raise GateError(
            f"authorization document hash {digest} does not match the pinned {expected_sha256}"
        )
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError("authorization document is not readable JSON") from exc
    if not isinstance(document, Mapping):
        raise GateError("authorization document must be a JSON object")
    return dict(document), digest


def _assert_identity(document: Mapping) -> None:
    for field in ("campaign_id", "approver", "operator", "issued_at", "expires_at"):
        value = document.get(field)
        if not isinstance(value, str) or not value.strip():
            raise GateError(f"authorization field {field!r} must be a non-empty string")


def _parse_utc(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise GateError(f"authorization {field} is not an ISO timestamp: {exc}") from exc
    if parsed.tzinfo is None:
        raise GateError(f"authorization {field} must carry a timezone")
    return parsed


def _assert_validity(document: Mapping, *, now: datetime | None = None) -> None:
    """Documented policy: issued_at <= now <= expires_at, and at most 30 days of validity."""
    issued = _parse_utc(str(document["issued_at"]), "issued_at")
    expires = _parse_utc(str(document["expires_at"]), "expires_at")
    current = now or datetime.now(UTC)
    if expires <= issued:
        raise GateError("authorization expires_at must be after issued_at")
    if expires - issued > timedelta(days=MAX_VALIDITY_DAYS):
        raise GateError(
            f"authorization validity exceeds {MAX_VALIDITY_DAYS} days "
            f"({issued.isoformat()} to {expires.isoformat()})"
        )
    if issued > current:
        raise GateError(f"authorization is future-dated (issued_at {issued.isoformat()})")
    if expires < current:
        raise GateError(f"authorization expired at {expires.isoformat()}")


@dataclass(frozen=True)
class DocumentLocation:
    """Where the document must live and which frozen tree it must avoid."""

    manifest_dir: Path
    repo_root: Path
    authorization_dir: Path | None = None

    def approved_dir(self) -> Path:
        if self.authorization_dir is not None:
            return Path(self.authorization_dir)
        return approved_authorization_dir(self.repo_root)


def approved_authorization_dir(repo_root: Path) -> Path:
    """The single approved location for authorization documents: ``<repo>/authorization``."""
    return Path(repo_root).resolve() / AUTHORIZATION_DIRNAME


def _assert_location(
    path: Path,
    manifest_dir: Path,
    repo_root: Path,
    authorization_dir: Path,
) -> Path:
    """Enforce the approved directory, refusing symlinks and parent-path escapes."""
    root = Path(repo_root).resolve()
    frozen = Path(manifest_dir).resolve()
    approved = Path(authorization_dir).resolve()
    if not approved.is_relative_to(root):
        raise GateError(f"approved authorization directory {approved} escapes the repository")
    if approved == frozen or approved.is_relative_to(frozen):
        raise GateError("the approved authorization directory is inside the frozen manifest tree")
    scientific = root / "data"
    if approved == scientific or approved.is_relative_to(scientific):
        raise GateError("the approved authorization directory is inside the scientific data tree")
    try:
        safeguards.assert_not_protected_directory(
            approved, root=root, purpose="authorization directory"
        )
    except safeguards.SafeguardError as exc:
        raise GateError(str(exc)) from exc
    raw = Path(path)
    if raw.is_symlink():
        raise GateError("authorization document must not be a symlink")
    resolved = raw.resolve()
    if resolved.parent != approved:
        raise GateError(f"authorization document must live directly in {approved}")
    return resolved


def _quarter_set(value: object, field: str) -> set[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise GateError(f"authorization field {field!r} must list quarters")
    return {str(quarter) for quarter in value}


def _assert_quarters(
    document: Mapping, fit_quarters: set[str], test_quarters: set[str], required_scope: str
) -> None:
    named = _quarter_set(document["authorized_quarters"], "authorized_quarters")
    extra = sorted(named - set(fit_quarters))
    missing = sorted(set(fit_quarters) - named)
    if extra or missing:
        raise GateError(
            "authorization fit quarters do not match the frozen set "
            f"(extra={extra}, missing={missing})"
        )
    if required_scope != "campaign":
        return
    if "authorized_test_quarters" not in document:
        raise GateError("a campaign authorization must list authorized_test_quarters")
    named_test = _quarter_set(document["authorized_test_quarters"], "authorized_test_quarters")
    extra = sorted(named_test - set(test_quarters))
    missing = sorted(set(test_quarters) - named_test)
    if extra or missing:
        raise GateError(
            "authorization test quarters do not match the frozen set "
            f"(extra={extra}, missing={missing})"
        )


def _assert_bindings(
    document: Mapping,
    *,
    campaign_id: str,
    protocol_sha256: str,
    manifest_hashes: Mapping[str, str],
    fit_quarters: set[str],
    test_quarters: set[str],
    required_scope: str,
) -> None:
    if document["campaign_id"] != campaign_id:
        raise GateError(
            f"authorization campaign id {document['campaign_id']!r} does not match {campaign_id!r}"
        )
    if document["protocol_sha256"] != protocol_sha256:
        raise GateError("authorization does not bind the authorized protocol pin")
    declared = document["manifest_hashes"]
    if not isinstance(declared, Mapping):
        raise GateError("authorization manifest_hashes must be a mapping")
    if set(declared) != set(manifest_hashes):
        raise GateError(
            f"authorization names manifest set {sorted(declared)} but the frozen set is "
            f"{sorted(manifest_hashes)}"
        )
    stale = sorted(name for name, digest in manifest_hashes.items() if declared.get(name) != digest)
    if stale:
        raise GateError(f"authorization is stale for the frozen manifests {stale}")
    _assert_quarters(document, fit_quarters, test_quarters, required_scope)
    scope = document["scope"]
    if scope not in SCOPES or scope not in SCOPE_GRANTS[required_scope]:
        raise GateError(
            f"authorization scope {scope!r} does not cover {required_scope!r}; "
            f"required one of {SCOPE_GRANTS[required_scope]}"
        )
    if document["single_run_ack"] is not True:
        raise GateError("authorization must acknowledge the single-run condition")


def load_authorization_document(
    authorization: AuthorizationRef,
    *,
    protocol_sha256: str,
    manifest_hashes: Mapping[str, str],
    location: DocumentLocation,
    fit_quarters: set[str],
    test_quarters: set[str],
    required_scope: str,
    now: datetime | None = None,
) -> tuple[dict, str]:
    """Load, hash-verify and bind one authorization document. Returns (document, digest).

    ``now`` pins the validity clock for tests; production callers must omit it and inherit
    the real UTC clock. Forwarding a caller-supplied value here would weaken the expiry gate.
    """
    if not isinstance(authorization, AuthorizationRef):
        raise GateError("authorization must be an AuthorizationRef, not a plain dictionary")
    if required_scope not in SCOPE_GRANTS:
        raise GateError(f"unknown authorization scope requirement {required_scope!r}")
    if protocol_sha256 != v2.AUTHORIZED_PROTOCOL_SHA256:
        raise GateError("the requested protocol hash is not the authorized pin")
    _assert_location(
        Path(authorization.path),
        location.manifest_dir,
        location.repo_root,
        location.approved_dir(),
    )
    document, digest = _read_document(Path(authorization.path), authorization.sha256)
    required = REQUIRED_FIELDS + (CAMPAIGN_FIELDS if required_scope == "campaign" else ())
    missing = [field for field in required if field not in document]
    if missing:
        raise GateError(f"authorization is missing required fields {missing}")
    _assert_identity(document)
    _assert_bindings(
        document,
        campaign_id=authorization.campaign_id,
        protocol_sha256=protocol_sha256,
        manifest_hashes=manifest_hashes,
        fit_quarters=fit_quarters,
        test_quarters=test_quarters,
        required_scope=required_scope,
    )
    if document["single_run_ack"] is not True:
        raise GateError("authorization must acknowledge the single-run condition")
    _assert_validity(document, now=now)
    return document, digest


def authorization_binding(document: Mapping, digest: str) -> dict:
    """The provenance block recorded alongside a run, so the authority is auditable."""
    return {
        "campaign_id": str(document["campaign_id"]),
        "authorization_sha256": str(digest),
        "approver": str(document["approver"]),
        "operator": str(document["operator"]),
        "issued_at": str(document["issued_at"]),
        "expires_at": str(document["expires_at"]),
        "scope": str(document["scope"]),
        "manifest_hashes": {
            str(name): str(value) for name, value in document["manifest_hashes"].items()
        },
        "protocol_sha256": str(document["protocol_sha256"]),
    }
