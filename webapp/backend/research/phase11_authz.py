"""Phase 11 OD-2 authorization document contract (design decisions D1/D5).

A single hashed document is the only authorization boundary for real-data work. The unsigned
dictionary that earlier stages accepted is gone: every entry point loads the document's exact
bytes, verifies the SHA-256 the caller pinned, parses only afterwards, and then binds the content
to the frozen facts — campaign id, protocol pin, manifest hashes, quarter set and scope.

Nothing here grants scientific authority by itself: the document must exist, be hashed, and match
the frozen inputs, and the caller must already hold an explicit owner approval.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import phase11_v2 as v2
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
    "scope",
    "authorized_quarters",
    "protocol_sha256",
    "manifest_hashes",
    "single_run_ack",
)
CAMPAIGN_FIELDS = ("authorized_test_quarters",)
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
    for field in ("campaign_id", "approver", "operator", "issued_at"):
        value = document.get(field)
        if not isinstance(value, str) or not value.strip():
            raise GateError(f"authorization field {field!r} must be a non-empty string")
    try:
        issued = datetime.fromisoformat(str(document["issued_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise GateError(f"authorization issued_at is not an ISO timestamp: {exc}") from exc
    if issued.tzinfo is None:
        raise GateError("authorization issued_at must carry a timezone")


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
    fit_quarters: set[str],
    test_quarters: set[str],
    required_scope: str,
) -> tuple[dict, str]:
    """Load, hash-verify and bind one authorization document. Returns (document, digest)."""
    if not isinstance(authorization, AuthorizationRef):
        raise GateError("authorization must be an AuthorizationRef, not a plain dictionary")
    if required_scope not in SCOPE_GRANTS:
        raise GateError(f"unknown authorization scope requirement {required_scope!r}")
    if protocol_sha256 != v2.AUTHORIZED_PROTOCOL_SHA256:
        raise GateError("the requested protocol hash is not the authorized pin")
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
    return document, digest


def authorization_binding(document: Mapping, digest: str) -> dict:
    """The provenance block recorded alongside a run, so the authority is auditable."""
    return {
        "campaign_id": str(document["campaign_id"]),
        "authorization_sha256": str(digest),
        "approver": str(document["approver"]),
        "operator": str(document["operator"]),
        "issued_at": str(document["issued_at"]),
        "scope": str(document["scope"]),
    }
