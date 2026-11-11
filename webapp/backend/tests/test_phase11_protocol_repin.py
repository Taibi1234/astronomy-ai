"""Focused tests for the v2.3 protocol repin.

Synthetic copies live in ``tmp_path``; the real protocol files are only read. No campaign,
fitting, trial generation or sealed-test access occurs.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from research import generalization as gen  # noqa: E402
from research import phase11_v2 as v2  # noqa: E402
from research import run_phase11_v2 as cli  # noqa: E402

MANIFEST_DIR = gen.project_root() / "reports" / "phase11_generalization"
V23_PATH = MANIFEST_DIR / "protocol_v2_3.json"
V22_PATH = MANIFEST_DIR / "protocol_v2_2.json"
V21_PATH = MANIFEST_DIR / "protocol_v2_1.json"
V1_PATH = MANIFEST_DIR / "protocol.json"

EXPECTED_V23 = "e1dc5cc9ed4e6e2dc4645a82efc4f7638fb0f3128248b9810c67ba339f32c154"
EXPECTED_V23_SIDECAR = "07950fc3a780e4b4c15abaa98fc50088dd1b68e0f4485a978d4e9d0b7ee7c2c3"
EXPECTED_V22 = "61f671986814b2b6d1f02d1d8da1e31e613ddc24ef1e545e54f68666f124814a"

needs_frozen = pytest.mark.skipif(
    not V23_PATH.is_file(), reason="frozen protocol_v2_3.json is not present"
)


def _copy(tmp_path: Path, *, mutate=None, sidecar_digest: str | None = None) -> Path:
    raw = V23_PATH.read_bytes()
    if mutate is not None:
        payload = json.loads(raw)
        mutate(payload)
        raw = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    target = tmp_path / "protocol_v2_3.json"
    target.write_bytes(raw)
    digest = sidecar_digest if sidecar_digest is not None else hashlib.sha256(raw).hexdigest()
    (tmp_path / "protocol_v2_3.sha256").write_bytes(f"{digest}  protocol_v2_3.json\n".encode())
    return target


# --- accepted identity ------------------------------------------------------


def test_pin_constants_are_the_authorized_v23_identity():
    assert v2.AUTHORIZED_PROTOCOL_NAME == "protocol_v2_3.json"
    assert v2.AUTHORIZED_PROTOCOL_SHA256 == EXPECTED_V23
    assert v2.AUTHORIZED_PROTOCOL_VERSION == "phase11b-protocol-v2.3-proposal"


@needs_frozen
def test_v23_is_accepted_when_hash_and_version_match():
    payload, digest = v2.load_protocol_v21(V23_PATH)
    assert digest == EXPECTED_V23
    assert payload["version"] == v2.AUTHORIZED_PROTOCOL_VERSION
    assert payload["schema_version"] == 2
    assert payload["immediate_predecessor"]["sha256"] == EXPECTED_V22


@needs_frozen
def test_frozen_protocol_and_sidecar_are_unchanged_by_the_repin():
    assert v2.sha256_file(V23_PATH) == EXPECTED_V23
    assert v2.sha256_file(V23_PATH.with_name("protocol_v2_3.sha256")) == EXPECTED_V23_SIDECAR
    assert v2.sha256_file(V22_PATH) == EXPECTED_V22
    # Predecessors keep their own historical identities.
    assert v2.sha256_file(V21_PATH).startswith("bae1cc583e6dc85f")
    assert v2.sha256_file(V1_PATH).startswith("ded2bd5eea3cfb3c")


# --- refused identities -----------------------------------------------------


@needs_frozen
@pytest.mark.parametrize("path", [V22_PATH, V21_PATH])
def test_earlier_versions_are_not_accepted_by_the_v23_pin(path):
    with pytest.raises(v2.GateError, match="not the authorized protocol"):
        v2.load_protocol_v21(path)


@needs_frozen
def test_a_changed_byte_is_rejected(tmp_path):
    raw = V23_PATH.read_bytes() + b" "
    target = tmp_path / "protocol_v2_3.json"
    target.write_bytes(raw)
    (tmp_path / "protocol_v2_3.sha256").write_bytes(
        f"{EXPECTED_V23}  protocol_v2_3.json\n".encode()
    )
    with pytest.raises(v2.GateError, match="does not match its recorded hash"):
        v2.load_protocol_v21(target)


@needs_frozen
def test_wrong_expected_hash_is_rejected():
    with pytest.raises(v2.GateError, match="not the authorized protocol"):
        v2.load_protocol_v21(V23_PATH, expected_sha256="0" * 64)


@needs_frozen
def test_wrong_version_string_is_rejected(tmp_path):
    def downgrade(payload):
        payload["version"] = "phase11b-protocol-v2.2"

    target = _copy(tmp_path, mutate=downgrade)
    with pytest.raises(v2.GateError, match="is not authorized"):
        v2.load_protocol_v21(target, expected_sha256=v2.sha256_file(target))


@needs_frozen
def test_invalid_or_missing_sidecar_is_rejected(tmp_path):
    target = _copy(tmp_path, sidecar_digest="0" * 64)
    with pytest.raises(v2.GateError, match="does not match its recorded hash"):
        v2.load_protocol_v21(target)

    (tmp_path / "protocol_v2_3.sha256").unlink()
    with pytest.raises(v2.GateError, match="missing hash sidecar"):
        v2.load_protocol_v21(target)


@needs_frozen
def test_operative_invariants_still_guard_a_tampered_protocol(tmp_path):
    def loosen(payload):
        payload["thresholds"]["min_calibration_n_per_stratum"] = 50

    target = _copy(tmp_path, mutate=loosen)
    with pytest.raises(v2.GateError, match="min_calibration_n_per_stratum"):
        v2.load_protocol_v21(target, expected_sha256=v2.sha256_file(target))


# --- MMD and execution surface ---------------------------------------------


@needs_frozen
def test_mmd_remains_unset_and_overrides_are_refused():
    payload, _digest = v2.load_protocol_v21(V23_PATH)
    assert payload["approval_decisions"]["D1_minimum_meaningful_difference"]["value"] is None
    assert v2.MINIMUM_MEANINGFUL_DIFFERENCE is None
    frame = pd.DataFrame(
        {
            "quarter": [f"Q{index:02d}" for index in range(5) for _ in range(2)],
            "trial_id": [f"{index}-{repeat}" for index in range(5) for repeat in range(2)],
            "rec_l7": 1.0,
            "rec_physics": 0.0,
        }
    )
    with pytest.raises(v2.GateError, match="caller-supplied overrides are refused"):
        v2.paired_comparison(frame, mmd=0.05, resamples=100)


def test_no_execution_surface_was_introduced():
    for name in ("evaluate_test", "run_campaign", "fit_models", "run_smoke", "evaluate"):
        assert not hasattr(v2, name), f"{name} must not exist in the v2 module"
    source = Path(v2.__file__).read_text(encoding="utf-8")
    for token in ("run_campaign(", "evaluate_test(", "fit_models("):
        assert token not in source
    assert cli.ENABLED_MODES == ("preflight",)
    cli_source = Path(cli.__file__).read_text(encoding="utf-8")
    assert 'add_argument("--execute"' not in cli_source
    assert '"--execute"' not in cli_source.replace("`--execute`", "").replace("--execute`", "")
