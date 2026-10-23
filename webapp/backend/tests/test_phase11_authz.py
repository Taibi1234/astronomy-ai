"""OD-2 authorization document tests: hashing, binding, staleness and scope."""

from __future__ import annotations

import json
import sys
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


def _manifests() -> dict[str, str]:
    protocol, _digest = v2.load_protocol_v21(MANIFEST_DIR / v2.AUTHORIZED_PROTOCOL_NAME)
    return v2.validate_manifests(MANIFEST_DIR, protocol)


def _doc(**overrides) -> dict:
    doc = {
        "campaign_id": "c-1",
        "approver": "owner",
        "operator": "operator",
        "issued_at": "2026-10-22T00:00:00Z",
        "scope": DOC_SCOPE,
        "authorized_quarters": sorted(FIT),
        "authorized_test_quarters": sorted(TEST),
        "protocol_sha256": v2.AUTHORIZED_PROTOCOL_SHA256,
        "manifest_hashes": _manifests(),
        "single_run_ack": True,
    }
    doc.update(overrides)
    return doc


def _ref(
    tmp_path: Path, doc: dict, *, digest: str | None = None, campaign_id: str = "c-1"
) -> authz.AuthorizationRef:
    path = tmp_path / "authorization.json"
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return authz.AuthorizationRef(
        path=path, sha256=digest or v2.sha256_file(path), campaign_id=campaign_id
    )


def _load(ref, **overrides):
    arguments = {
        "protocol_sha256": v2.AUTHORIZED_PROTOCOL_SHA256,
        "manifest_hashes": _manifests(),
        "fit_quarters": FIT,
        "test_quarters": TEST,
        "required_scope": REQUIRED,
    }
    arguments.update(overrides)
    return authz.load_authorization_document(ref, **arguments)


def test_valid_document_loads_and_binds(tmp_path):
    doc, digest = _load(_ref(tmp_path, _doc()))

    assert doc["campaign_id"] == "c-1"
    assert digest == v2.sha256_file(tmp_path / "authorization.json")
    binding = authz.authorization_binding(doc, digest)
    assert binding["campaign_id"] == "c-1"
    assert binding["authorization_sha256"] == digest


def test_plain_dictionary_is_refused():
    with pytest.raises(phase11.GateError, match="AuthorizationRef"):
        _load({"campaign_id": "c-1"})


def test_missing_document_is_refused(tmp_path):
    ref = authz.AuthorizationRef(path=tmp_path / "absent.json", sha256="a" * 64, campaign_id="c-1")

    with pytest.raises(phase11.GateError, match="missing"):
        _load(ref)


def test_altered_document_is_refused(tmp_path):
    ref = _ref(tmp_path, _doc())
    path = tmp_path / "authorization.json"
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(phase11.GateError, match="does not match the pinned"):
        _load(ref)


def test_bad_digest_format_is_refused(tmp_path):
    ref = authz.AuthorizationRef(path=tmp_path / "x.json", sha256="not-a-hash", campaign_id="c-1")

    with pytest.raises(phase11.GateError, match="64 lowercase hex"):
        _load(ref)


def test_malformed_json_is_refused(tmp_path):
    path = tmp_path / "authorization.json"
    path.write_bytes(b"{not json")
    ref = authz.AuthorizationRef(path=path, sha256=v2.sha256_file(path), campaign_id="c-1")

    with pytest.raises(phase11.GateError, match="not readable JSON"):
        _load(ref)


def test_non_object_document_is_refused(tmp_path):
    path = tmp_path / "authorization.json"
    path.write_text("[]", encoding="utf-8")
    ref = authz.AuthorizationRef(path=path, sha256=v2.sha256_file(path), campaign_id="c-1")

    with pytest.raises(phase11.GateError, match="JSON object"):
        _load(ref)


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
        ({"issued_at": "2026-10-22T00:00:00"}, "timezone"),
        ({"issued_at": "yesterday"}, "ISO timestamp"),
        ({"approver": ""}, "non-empty string"),
        ({"manifest_hashes": {"split.json": "0" * 64}}, "manifest set"),
        ({"authorized_quarters": "Q00"}, "must list quarters"),
    ],
)
def test_document_mismatches_are_refused(tmp_path, overrides, message):
    with pytest.raises(phase11.GateError, match=message):
        _load(_ref(tmp_path, _doc(**overrides)))


def test_stale_manifest_digest_is_refused(tmp_path):
    hashes = _manifests()
    hashes["split.json"] = "0" * 64
    with pytest.raises(phase11.GateError, match="stale"):
        _load(_ref(tmp_path, _doc()), manifest_hashes=hashes)


def test_missing_field_is_refused(tmp_path):
    doc = _doc()
    doc.pop("approver")
    with pytest.raises(phase11.GateError, match="missing required fields"):
        _load(_ref(tmp_path, doc, digest=None))


def test_campaign_scope_requires_test_quarters(tmp_path):
    doc = _doc()
    doc.pop("authorized_test_quarters")
    with pytest.raises(phase11.GateError, match="authorized_test_quarters"):
        _load(_ref(tmp_path, doc))


def test_fit_only_scope_cannot_run_a_campaign(tmp_path):
    with pytest.raises(phase11.GateError, match="does not cover 'campaign'"):
        _load(_ref(tmp_path, _doc(scope="fit_only")), required_scope="campaign")


def test_wrong_protocol_argument_is_refused(tmp_path):
    with pytest.raises(phase11.GateError, match="not the authorized pin"):
        _load(_ref(tmp_path, _doc()), protocol_sha256="0" * 64)
