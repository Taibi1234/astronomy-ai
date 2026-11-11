"""OD-2 authorization document tests: hashing, binding, location, validity and scope."""

from __future__ import annotations

import ast
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from research import generalization as gen  # noqa: E402
from research import phase11  # noqa: E402
from research import phase11_authz as authz  # noqa: E402
from research import phase11_v2 as v2  # noqa: E402

MANIFEST_DIR = gen.project_root() / "reports" / "phase11_generalization"
FIT = {"Q00", "Q15"}
TEST = {"Q02", "Q09"}
DOC_SCOPE = "fit_and_evaluate"
REQUIRED = "campaign"
FIXED_NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)


def _manifests() -> dict[str, str]:
    protocol, _digest = v2.load_protocol_v21(MANIFEST_DIR / v2.AUTHORIZED_PROTOCOL_NAME)
    return v2.validate_manifests(MANIFEST_DIR, protocol)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _doc(**overrides) -> dict:
    doc = {
        "campaign_id": "c-1",
        "approver": "owner",
        "operator": "operator",
        "issued_at": _iso(FIXED_NOW - timedelta(hours=1)),
        "expires_at": _iso(FIXED_NOW + timedelta(hours=23)),
        "scope": DOC_SCOPE,
        "authorized_quarters": sorted(FIT),
        "authorized_test_quarters": sorted(TEST),
        "protocol_sha256": v2.AUTHORIZED_PROTOCOL_SHA256,
        "manifest_hashes": _manifests(),
        "single_run_ack": True,
    }
    doc.update(overrides)
    return doc


def _approved(tmp_path: Path) -> Path:
    path = tmp_path / authz.AUTHORIZATION_DIRNAME
    path.mkdir(exist_ok=True)
    return path


def _ref(
    tmp_path: Path,
    doc: dict,
    *,
    digest: str | None = None,
    campaign_id: str = "c-1",
    directory: Path | None = None,
    name: str = "authorization.json",
) -> authz.AuthorizationRef:
    approved = _approved(tmp_path) if directory is None else directory
    approved.mkdir(parents=True, exist_ok=True)
    path = approved / name
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return authz.AuthorizationRef(
        path=path, sha256=digest or v2.sha256_file(path), campaign_id=campaign_id
    )


def _load(ref: authz.AuthorizationRef, tmp_path: Path, **overrides):
    arguments = {
        "protocol_sha256": v2.AUTHORIZED_PROTOCOL_SHA256,
        "manifest_hashes": _manifests(),
        "location": authz.DocumentLocation(MANIFEST_DIR, tmp_path, _approved(tmp_path)),
        "fit_quarters": FIT,
        "test_quarters": TEST,
        "required_scope": REQUIRED,
    }
    arguments.update(overrides)
    return authz.load_authorization_document(ref, **arguments)


def test_valid_document_loads_and_binds(tmp_path):
    ref = _ref(tmp_path, _doc())
    doc, digest = _load(ref, tmp_path, now=FIXED_NOW)

    assert doc["campaign_id"] == "c-1"
    assert digest == v2.sha256_file(ref.path)
    binding = authz.authorization_binding(doc, digest)
    assert binding["campaign_id"] == "c-1"
    assert binding["authorization_sha256"] == digest
    assert binding["manifest_hashes"] == _manifests()


def test_expired_document_is_refused_through_the_public_loader(tmp_path):
    ref = _ref(tmp_path, _doc())

    with pytest.raises(phase11.GateError, match="expired"):
        _load(ref, tmp_path, now=FIXED_NOW + timedelta(days=2))


def test_production_callers_never_inject_the_validity_clock():
    """The clock override is for tests; production modules must inherit the real UTC clock."""

    research_dir = BACKEND_DIR / "research"
    sites: list[str] = []

    for module_path in sorted(research_dir.glob("*.py")):
        if module_path.name == "phase11_authz.py":
            continue
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "load_authorization_document":
                continue
            sites.append(f"{module_path.name}:{node.lineno}")
            assert not any(keyword.arg == "now" for keyword in node.keywords), (
                f"{module_path.name}:{node.lineno} passes now= to "
                "load_authorization_document; production must use the real clock"
            )

    assert len(sites) >= 3, f"expected the production call sites, found {sites}"


def test_plain_dictionary_is_refused(tmp_path):
    with pytest.raises(phase11.GateError, match="AuthorizationRef"):
        _load({"campaign_id": "c-1"}, tmp_path)


def test_missing_document_is_refused(tmp_path):
    ref = authz.AuthorizationRef(
        path=_approved(tmp_path) / "absent.json", sha256="a" * 64, campaign_id="c-1"
    )

    with pytest.raises(phase11.GateError, match="missing"):
        _load(ref, tmp_path)


def test_altered_document_is_refused(tmp_path):
    ref = _ref(tmp_path, _doc())
    ref.path.write_text(ref.path.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(phase11.GateError, match="does not match the pinned"):
        _load(ref, tmp_path)


def test_bad_digest_format_is_refused(tmp_path):
    ref = authz.AuthorizationRef(
        path=_approved(tmp_path) / "x.json", sha256="not-a-hash", campaign_id="c-1"
    )

    with pytest.raises(phase11.GateError, match="64 lowercase hex"):
        _load(ref, tmp_path)


def test_malformed_json_is_refused(tmp_path):
    path = _approved(tmp_path) / "authorization.json"
    path.write_bytes(b"{not json")
    ref = authz.AuthorizationRef(path=path, sha256=v2.sha256_file(path), campaign_id="c-1")

    with pytest.raises(phase11.GateError, match="not readable JSON"):
        _load(ref, tmp_path)


def test_non_object_document_is_refused(tmp_path):
    path = _approved(tmp_path) / "authorization.json"
    path.write_text("[]", encoding="utf-8")
    ref = authz.AuthorizationRef(path=path, sha256=v2.sha256_file(path), campaign_id="c-1")

    with pytest.raises(phase11.GateError, match="JSON object"):
        _load(ref, tmp_path)


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"campaign_id": "other"}, "campaign id"),
        ({"protocol_sha256": "0" * 64}, "protocol pin"),
        ({"scope": "analysis"}, "does not cover"),
        ({"single_run_ack": False}, "single-run"),
        ({"authorized_quarters": sorted(FIT - {"Q00"})}, "fit quarters"),
        ({"authorized_quarters": sorted(FIT | {"Q04"})}, "fit quarters"),
        ({"authorized_test_quarters": sorted(TEST - {"Q02"})}, "test quarters"),
        ({"authorized_test_quarters": sorted(TEST | {"Q04"})}, "test quarters"),
        ({"issued_at": _iso(FIXED_NOW).replace("Z", "")}, "timezone"),
        ({"issued_at": "yesterday"}, "ISO timestamp"),
        ({"expires_at": "soon"}, "ISO timestamp"),
        ({"approver": ""}, "non-empty string"),
        ({"manifest_hashes": {"split.json": "0" * 64}}, "manifest set"),
        ({"authorized_quarters": "Q00"}, "must list quarters"),
    ],
)
def test_document_mismatches_are_refused(tmp_path, overrides, message):
    with pytest.raises(phase11.GateError, match=message):
        _load(_ref(tmp_path, _doc(**overrides)), tmp_path)


def test_stale_manifest_digest_is_refused(tmp_path):
    hashes = _manifests()
    hashes["split.json"] = "0" * 64
    with pytest.raises(phase11.GateError, match="stale"):
        _load(_ref(tmp_path, _doc()), tmp_path, manifest_hashes=hashes)


def test_missing_field_is_refused(tmp_path):
    doc = _doc()
    doc.pop("approver")
    with pytest.raises(phase11.GateError, match="missing required fields"):
        _load(_ref(tmp_path, doc), tmp_path)


def test_campaign_scope_requires_test_quarters(tmp_path):
    doc = _doc()
    doc.pop("authorized_test_quarters")
    with pytest.raises(phase11.GateError, match="authorized_test_quarters"):
        _load(_ref(tmp_path, doc), tmp_path)


def test_fit_only_scope_cannot_run_a_campaign(tmp_path):
    with pytest.raises(phase11.GateError, match="does not cover 'campaign'"):
        _load(_ref(tmp_path, _doc(scope="fit_only")), tmp_path)


def test_wrong_protocol_argument_is_refused(tmp_path):
    with pytest.raises(phase11.GateError, match="not the authorized pin"):
        _load(_ref(tmp_path, _doc()), tmp_path, protocol_sha256="0" * 64)


# --- M5: approved directory ---------------------------------------------------


def test_approved_directory_is_documented():
    assert authz.AUTHORIZATION_DIRNAME == "authorization"
    approved = authz.approved_authorization_dir(gen.project_root())
    assert approved.name == "authorization"
    assert approved.parent == gen.project_root().resolve()


def test_document_outside_the_approved_directory_is_refused(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    ref = _ref(tmp_path, _doc(), directory=elsewhere)

    with pytest.raises(phase11.GateError, match="must live directly in"):
        _load(ref, tmp_path)


def test_path_traversal_out_of_the_approved_directory_is_refused(tmp_path):
    trailing = tmp_path / "authorization.json"
    trailing.write_text(json.dumps(_doc(), indent=2), encoding="utf-8")
    ref = authz.AuthorizationRef(
        path=_approved(tmp_path) / ".." / "authorization.json",
        sha256=v2.sha256_file(trailing),
        campaign_id="c-1",
    )

    with pytest.raises(phase11.GateError, match="must live directly in"):
        _load(ref, tmp_path)


def test_symlinked_document_is_refused(tmp_path):
    target = _approved(tmp_path) / "real.json"
    target.write_text(json.dumps(_doc(), indent=2), encoding="utf-8")
    link = _approved(tmp_path) / "link.json"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform dependent
        pytest.skip(f"symlinks unavailable: {exc}")
    ref = authz.AuthorizationRef(path=link, sha256=v2.sha256_file(target), campaign_id="c-1")

    with pytest.raises(phase11.GateError, match="must not be a symlink"):
        _load(ref, tmp_path)


def test_approved_directory_outside_the_repository_is_refused(tmp_path):
    outside = tmp_path.parent / "outside-authorization"
    outside.mkdir(exist_ok=True)
    ref = _ref(tmp_path, _doc(), directory=outside)
    location = authz.DocumentLocation(MANIFEST_DIR, tmp_path, outside)

    with pytest.raises(phase11.GateError, match="escapes the repository"):
        _load(ref, tmp_path, location=location)


def test_approved_directory_inside_the_frozen_tree_is_refused(tmp_path):
    ref = _ref(tmp_path, _doc())
    location = authz.DocumentLocation(MANIFEST_DIR, gen.project_root(), MANIFEST_DIR)

    with pytest.raises(phase11.GateError, match="frozen manifest tree"):
        _load(ref, tmp_path, location=location)


# --- M5: validity policy ------------------------------------------------------


def test_validity_boundaries_with_an_injected_clock(tmp_path):
    doc = _doc(
        issued_at=_iso(FIXED_NOW - timedelta(days=1)),
        expires_at=_iso(FIXED_NOW),
    )
    authz._assert_validity(doc, now=FIXED_NOW)
    with pytest.raises(phase11.GateError, match="expired"):
        authz._assert_validity(doc, now=FIXED_NOW + timedelta(seconds=1))


def test_future_dated_document_is_refused_with_injected_clock(tmp_path):
    doc = _doc(
        issued_at=_iso(FIXED_NOW + timedelta(seconds=1)),
        expires_at=_iso(FIXED_NOW + timedelta(days=1)),
    )
    with pytest.raises(phase11.GateError, match="future-dated"):
        authz._assert_validity(doc, now=FIXED_NOW)


def test_non_utc_offset_is_compared_correctly(tmp_path):
    offset = datetime(2026, 10, 23, 17, 30, 0, tzinfo=UTC)  # 23:00 at +05:30
    doc = _doc(
        issued_at=_iso(offset - timedelta(hours=1)),
        expires_at=_iso(offset + timedelta(hours=1)),
    )
    authz._assert_validity(doc, now=offset + timedelta(minutes=30))


def test_missing_expiry_is_refused(tmp_path):
    doc = _doc()
    doc.pop("expires_at")
    with pytest.raises(phase11.GateError, match="missing required fields"):
        _load(_ref(tmp_path, doc), tmp_path)


@pytest.mark.parametrize(
    "issued, expires, message",
    [
        (FIXED_NOW - timedelta(hours=2), FIXED_NOW - timedelta(hours=3), "after issued_at"),
        (FIXED_NOW - timedelta(hours=1), FIXED_NOW + timedelta(days=31), "validity exceeds"),
        (FIXED_NOW - timedelta(days=2), FIXED_NOW - timedelta(seconds=1), "expired"),
        (FIXED_NOW + timedelta(seconds=1), FIXED_NOW + timedelta(hours=1), "future-dated"),
    ],
)
def test_validity_bounds_are_enforced(issued, expires, message):
    doc = _doc(issued_at=_iso(issued), expires_at=_iso(expires))

    with pytest.raises(phase11.GateError, match=message):
        authz._assert_validity(doc, now=FIXED_NOW)


def test_max_validity_is_documented():
    assert authz.MAX_VALIDITY_DAYS == 30


def test_approved_directory_inside_the_data_tree_is_refused(tmp_path):
    ref = _ref(tmp_path, _doc())
    location = authz.DocumentLocation(MANIFEST_DIR, gen.project_root(), gen.project_root() / "data")

    with pytest.raises(phase11.GateError, match="scientific data tree"):
        _load(ref, tmp_path, location=location)
