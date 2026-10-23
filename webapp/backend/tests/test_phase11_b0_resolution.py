"""B0 tests: effective-protocol resolution for the pinned v2.3 / v1 / experiment-config triple.

Synthetic fixtures only. The real frozen artifacts are read (never written) and skipped when
absent. No model is fitted, no trial is generated, no sealed data is read and no campaign
runs.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from research import generalization as gen  # noqa: E402
from research import phase11 as p11  # noqa: E402
from research import phase11_runner as runner  # noqa: E402
from research import phase11_v2 as v2  # noqa: E402

MANIFEST_DIR = gen.project_root() / "reports" / "phase11_generalization"
FROZEN_NAMES = (
    "protocol_v2_3.json",
    "protocol_v2_3.sha256",
    "protocol.json",
    "protocol.sha256",
    "experiment_config.json",
)
SYNTHETIC_V23_PIN = "f" * 64
SYNTHETIC_V1_PIN = "e" * 64
SYNTHETIC_CONFIG_SHA = "a" * 64


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _synthetic_v1() -> dict:
    return {
        "phase": "11b",
        "schema_version": 1,
        "features": {
            "sets": {"L2_snr_only": {"features": ["snr"]}},
            "forbidden": ["injected", "requested_depth_ppm"],
            "detector_outputs": ["snr", "depth_ppm", "duration_days"],
            "flux_features": ["flux_std"],
        },
        "preprocessing": {"fit_splits": ["train"]},
        "models": {
            "logistic_regression": {"penalty": "l2"},
            "random_forest": {"n_estimators": 200},
            "dummy": {"strategy": "prior"},
        },
        "seeds": {"model": 20261025, "split": 20261022},
        "campaign": {
            "modes": {"smoke": {"quarters": ["Q00"], "window_days": 5.0}},
            "order": ["fit", "evaluate"],
        },
    }


def _synthetic_v23(config_sha: str = SYNTHETIC_CONFIG_SHA) -> dict:
    return {
        "phase": "11b",
        "schema_version": 2,
        "version": "synthetic-v2.3",
        "campaign_ready": False,
        "execution_ready": False,
        "inherits_from_v1": {
            "rule": "prose metadata only",
            "features": "see v1",
            "preprocessing": "see v1",
            "models": "see v1",
            "seeds": "see v1",
            "campaign_modes": "see v1",
            "campaign_order": "see v1",
            "note": "prose metadata only",
        },
        "thresholds": {
            "target_fpr": 0.05,
            "min_calibration_n_per_stratum": 30,
            "floor_snr_detector": 3.0,
            "floor_snr_l7": None,
        },
        "frozen_inputs": {"files": {"experiment_config.json": config_sha}},
    }


def _synthetic_config(**extra) -> dict:
    return {
        "phase": "11a",
        "injection": {"noise_conditions": ["observed", "amplified_x2"]},
        **extra,
    }


@pytest.fixture
def synthetic_pins(monkeypatch):
    """Pin the synthetic digests so the pure merge reaches its own validation rules."""
    monkeypatch.setattr(v2, "AUTHORIZED_PROTOCOL_SHA256", SYNTHETIC_V23_PIN)
    monkeypatch.setattr(v2, "V1_PROTOCOL_SHA256", SYNTHETIC_V1_PIN)


def _merge(payload: dict, config: dict | None = None, **overrides):
    arguments = {
        "protocol_v2_3_sha256": SYNTHETIC_V23_PIN,
        "protocol_v1_sha256": SYNTHETIC_V1_PIN,
        "experiment_config_sha256": SYNTHETIC_CONFIG_SHA,
    }
    arguments.update(overrides)
    return v2.effective_protocol(
        payload,
        arguments["protocol_v2_3_sha256"],
        _synthetic_v1(),
        arguments["protocol_v1_sha256"],
        _synthetic_config() if config is None else config,
        arguments["experiment_config_sha256"],
    )


@pytest.fixture(scope="module")
def frozen_triple() -> Path:
    missing = [name for name in FROZEN_NAMES if not (MANIFEST_DIR / name).is_file()]
    if missing:
        pytest.skip(f"frozen triple unavailable: {missing}")
    return MANIFEST_DIR


# --- successful resolution ---------------------------------------------------


def test_pinned_triple_resolves_with_provenance(frozen_triple):
    effective, provenance = v2.resolve_effective_protocol(frozen_triple)

    assert provenance["protocol_v2_3"]["sha256"] == v2.AUTHORIZED_PROTOCOL_SHA256
    assert provenance["protocol_v1"]["sha256"] == v2.V1_PROTOCOL_SHA256
    assert (
        provenance["experiment_config"]["sha256"]
        == provenance["experiment_config"]["manifest_entry"]
    )
    assert provenance["derived_floors"] == {"detector": 3.0, "l7": None}
    assert provenance["grants_execution_authority"] is False
    assert provenance["inherited_blocks"] == list(v2.INHERITED_BLOCKS)
    assert provenance["copied_from_experiment_config"] == ["injection.noise_conditions"]

    assert effective["injection"] == {"noise_conditions": ["observed", "amplified_x2"]}
    assert effective["thresholds"]["fitted_models"]["floor_snr"] is None
    assert effective["thresholds"]["detector"]["floor_snr"] == 3.0
    assert effective["campaign"]["modes"]
    assert effective["campaign"]["order"]
    for dotted in v2.REQUIRED_EFFECTIVE_KEYS:
        node = effective
        for part in dotted.split("."):
            node = node[part]


def test_resolved_view_feeds_downstream_consumers(frozen_triple):
    effective, _ = v2.resolve_effective_protocol(frozen_triple)

    columns = p11.feature_columns(effective, "L7_detector_plus_clean_flux")
    assert columns
    p11.assert_fit_splits(pd.DataFrame({"split": ["train", "val"]}), effective)
    with pytest.raises(p11.GateError):
        p11.assert_fit_splits(pd.DataFrame({"split": ["train", "test"]}), effective)


def test_resolution_does_not_upgrade_readiness(frozen_triple):
    effective, _ = v2.resolve_effective_protocol(frozen_triple)

    assert effective["campaign_ready"] is False
    assert effective["execution_ready"] is False
    assert runner.MODES == ("preflight", "synthetic")
    with pytest.raises(runner.ReadinessError):
        runner.execute_real()


# --- authentication of the three sources -------------------------------------


def test_caller_supplied_v23_without_matching_digest_is_refused(synthetic_pins):
    payload = _synthetic_v23()
    with pytest.raises(v2.GateError, match="v2.3 digest"):
        v2.effective_protocol(
            payload,
            "0" * 64,
            _synthetic_v1(),
            SYNTHETIC_V1_PIN,
            _synthetic_config(),
            SYNTHETIC_CONFIG_SHA,
        )


def test_v1_digest_mismatch_is_refused(synthetic_pins):
    with pytest.raises(v2.GateError, match="v1 digest"):
        _merge(_synthetic_v23(), protocol_v1_sha256="0" * 64)


def test_l7_floor_is_none_not_a_fallback(synthetic_pins):
    effective = _merge(_synthetic_v23())
    assert effective["thresholds"]["fitted_models"]["floor_snr"] is None
    assert effective["thresholds"]["detector"]["floor_snr"] == 3.0


@pytest.mark.parametrize("expected", ["floor_snr_detector", "floor_snr_l7"])
def test_missing_floor_field_is_refused(synthetic_pins, expected):
    payload = _synthetic_v23()
    del payload["thresholds"][expected]
    with pytest.raises(v2.GateError, match=expected):
        _merge(payload)


# --- manifest entry validation -----------------------------------------------


@pytest.mark.parametrize(
    "frozen_inputs, message",
    [
        (None, "frozen_inputs"),
        ({"files": None}, "files"),
        ({"files": {}}, "no entry"),
        ({"files": {"experiment_config.json": 12}}, "not a string"),
        ({"files": {"experiment_config.json": "a" * 63}}, "64 lowercase hex"),
        ({"files": {"experiment_config.json": "a" * 65}}, "64 lowercase hex"),
        ({"files": {"experiment_config.json": "A" * 64}}, "64 lowercase hex"),
        ({"files": {"experiment_config.json": "g" * 64}}, "64 lowercase hex"),
    ],
)
def test_invalid_manifest_entries_are_refused(frozen_inputs, message):
    protocol = {} if frozen_inputs is None else {"frozen_inputs": frozen_inputs}
    with pytest.raises(v2.GateError, match=message):
        v2.validate_manifest_entry(protocol)


def test_manifest_entry_is_the_runtime_authority(synthetic_pins):
    payload = _synthetic_v23(config_sha="b" * 64)
    with pytest.raises(v2.GateError, match="manifest entry"):
        _merge(payload)


# --- experiment config loading -----------------------------------------------


def test_config_hash_is_checked_before_parsing(tmp_path):
    path = tmp_path / "experiment_config.json"
    path.write_bytes(b"{not json")
    with pytest.raises(v2.GateError, match="does not match the authenticated manifest entry"):
        v2.load_experiment_config(path, expected_sha256="0" * 64)


def test_matching_hash_but_malformed_json_is_refused(tmp_path):
    path = tmp_path / "experiment_config.json"
    raw = b"{not json"
    path.write_bytes(raw)
    with pytest.raises(v2.GateError, match="not readable JSON"):
        v2.load_experiment_config(path, expected_sha256=_digest(raw))


def test_missing_config_is_refused(tmp_path):
    with pytest.raises(v2.GateError, match="not found"):
        v2.load_experiment_config(
            tmp_path / "experiment_config.json", expected_sha256=SYNTHETIC_CONFIG_SHA
        )


@pytest.mark.parametrize(
    "config, message",
    [
        ([], "JSON object"),
        ({}, "no injection"),
        ({"injection": []}, "no injection"),
        ({"injection": {}}, "noise_conditions"),
        ({"injection": {"noise_conditions": []}}, "noise_conditions"),
        ({"injection": {"noise_conditions": "observed"}}, "noise_conditions"),
        ({"injection": {"noise_conditions": ["observed", 3]}}, "non-empty strings"),
        ({"injection": {"noise_conditions": [""]}}, "non-empty strings"),
    ],
)
def test_structurally_invalid_config_is_refused(config, message):
    with pytest.raises(v2.GateError, match=message):
        v2._extract_noise_conditions(config)


# --- inheritance whitelist ---------------------------------------------------


@pytest.mark.parametrize("key", ["thresholds", "injection", "reporting", "data_roles"])
def test_unknown_inherited_key_is_refused(synthetic_pins, key):
    payload = _synthetic_v23()
    payload["inherits_from_v1"][key] = "please inherit me"
    with pytest.raises(v2.GateError, match="unsupported inherits_from_v1 keys"):
        _merge(payload)


@pytest.mark.parametrize("key", sorted(v2.INHERITED_BLOCKS))
def test_missing_inherited_block_is_refused(synthetic_pins, key):
    payload = _synthetic_v23()
    del payload["inherits_from_v1"][key]
    with pytest.raises(v2.GateError, match="missing required blocks"):
        _merge(payload)


def test_missing_inherits_from_v1_is_refused(synthetic_pins):
    payload = _synthetic_v23()
    del payload["inherits_from_v1"]
    with pytest.raises(v2.GateError, match="inherits_from_v1"):
        _merge(payload)


def test_prose_keys_are_not_copied(synthetic_pins):
    effective = _merge(_synthetic_v23())
    assert "rule" not in effective
    assert "note" not in effective
    assert isinstance(effective["inherits_from_v1"], dict)


# --- merge hygiene -----------------------------------------------------------


def test_only_injection_is_copied_from_the_config(synthetic_pins):
    config = _synthetic_config(
        thresholds={"target_fpr": 0.5, "floor_snr_l7": 3.0},
        features={"sets": {}},
        models={"dummy": {"strategy": "override"}},
        seeds={"model": 1},
        campaign={"modes": {}},
        reporting={"primary_family": "overridden"},
    )
    effective = _merge(_synthetic_v23(), config=config)

    assert effective["injection"] == {"noise_conditions": ["observed", "amplified_x2"]}
    assert effective["thresholds"]["target_fpr"] == 0.05
    assert effective["thresholds"]["fitted_models"]["floor_snr"] is None
    assert effective["features"]["sets"] == {"L2_snr_only": {"features": ["snr"]}}
    assert effective["models"]["dummy"] == {"strategy": "prior"}
    assert effective["seeds"] == {"model": 20261025, "split": 20261022}
    assert "reporting" not in effective


def test_inputs_are_not_mutated(synthetic_pins):
    payload = _synthetic_v23()
    v1 = _synthetic_v1()
    config = _synthetic_config()
    before = (copy.deepcopy(payload), copy.deepcopy(v1), copy.deepcopy(config))

    v2.effective_protocol(
        payload, SYNTHETIC_V23_PIN, v1, SYNTHETIC_V1_PIN, config, SYNTHETIC_CONFIG_SHA
    )

    assert (payload, v1, config) == before


# --- loader path independence ------------------------------------------------


def _copy_frozen_manifest(tmp_path: Path, source: Path) -> Path:
    for name in FROZEN_NAMES:
        shutil.copy2(source / name, tmp_path / name)
    return tmp_path


def test_loader_reads_the_supplied_manifest_dir(frozen_triple, tmp_path):
    replica = _copy_frozen_manifest(tmp_path, frozen_triple)

    effective, provenance = v2.resolve_effective_protocol(replica)

    assert provenance["experiment_config"]["path"].startswith(str(replica))
    assert effective["injection"]["noise_conditions"]


def test_tampered_replica_config_is_refused(frozen_triple, tmp_path):
    replica = _copy_frozen_manifest(tmp_path, frozen_triple)
    config = replica / "experiment_config.json"
    config.write_bytes(config.read_bytes() + b" ")

    with pytest.raises(v2.GateError, match="does not match the authenticated manifest entry"):
        v2.resolve_effective_protocol(replica)


def test_missing_replica_config_is_refused(frozen_triple, tmp_path):
    replica = _copy_frozen_manifest(tmp_path, frozen_triple)
    (replica / "experiment_config.json").unlink()

    with pytest.raises(v2.GateError, match="not found"):
        v2.resolve_effective_protocol(replica)


def test_explicit_config_path_overrides_the_default(frozen_triple, tmp_path):
    replica = _copy_frozen_manifest(tmp_path, frozen_triple)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    moved = elsewhere / "experiment_config.json"
    shutil.copy2(replica / "experiment_config.json", moved)

    _, provenance = v2.resolve_effective_protocol(replica, experiment_config_path=moved)

    assert provenance["experiment_config"]["path"] == str(moved)


def test_missing_v1_file_is_refused(frozen_triple, tmp_path):
    replica = _copy_frozen_manifest(tmp_path, frozen_triple)
    (replica / "protocol.json").unlink()

    with pytest.raises(v2.GateError, match="v1 protocol not found"):
        v2.resolve_effective_protocol(replica)


def test_v1_sidecar_mismatch_is_refused(frozen_triple, tmp_path):
    replica = _copy_frozen_manifest(tmp_path, frozen_triple)
    (replica / "protocol.sha256").write_text("0" * 64 + "  protocol.json\n", encoding="utf-8")

    with pytest.raises(v2.GateError, match="does not match its recorded hash"):
        v2.resolve_effective_protocol(replica)


def test_json_round_trip_preserves_the_effective_view(frozen_triple):
    effective, _ = v2.resolve_effective_protocol(frozen_triple)
    reloaded = json.loads(json.dumps(effective))

    assert reloaded == effective
