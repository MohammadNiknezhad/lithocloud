"""Amendment A2, session B: the ricp method parameters.

params_register.json regrouped (untitled frequently-used section + collapsed
Advanced), eight method fields that travel through extra_arguments, and the
exact to_argv() token lists per fine method - the report Mohammad asked for.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

from lithocloud.core import load_params

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = REPO_ROOT / "engines" / "ricp"
PARAMS = ENGINE_DIR / "params_register.json"


def _load_adapter():
    spec = importlib.util.spec_from_file_location("ricp_adapter_b", ENGINE_DIR / "adapter.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = _load_adapter()

real_engine = pytest.mark.skipif(
    importlib.util.find_spec("ricp_engine") is None, reason="ricp_engine not installed"
)

METHOD_KEYS = (
    "plane_radius",
    "m3c2_core_points",
    "m3c2_normal_radius",
    "m3c2_projection_radius",
    "m3c2_max_depth",
    "m3c2_scale_mode",
    "m3c2_max_scale_factor",
    "m3c2_max_levels",
)
M3C2_KEYS = METHOD_KEYS[1:]

#: Every new field filled - the "with every new field filled in" case.
FILLED = {
    "plane_radius": "0.35",
    "m3c2_core_points": "8000",
    "m3c2_normal_radius": "0.9",
    "m3c2_projection_radius": "0.6",
    "m3c2_max_depth": "1.5",
    "m3c2_scale_mode": "fixed",
    "m3c2_max_scale_factor": "2.5",
    "m3c2_max_levels": "3",
}
PLANE_TOKENS = ["--plane-radius", "0.35"]
M3C2_TOKENS = [
    "--m3c2-core-points", "8000",
    "--m3c2-normal-radius", "0.9",
    "--m3c2-projection-radius", "0.6",
    "--m3c2-max-depth", "1.5",
    "--m3c2-scale-mode", "fixed",
    "--m3c2-max-scale-factor", "2.5",
    "--m3c2-max-levels", "3",
]


def defaults() -> dict:
    return load_params(PARAMS).defaults()


# --------------------------------------------------------------------------- #
# params_register.json layout
# --------------------------------------------------------------------------- #


def test_the_file_is_schema_v2() -> None:
    assert json.loads(PARAMS.read_text(encoding="utf-8"))["version"] == 2


def test_two_sections_untitled_then_a_collapsed_advanced() -> None:
    spec = load_params(PARAMS)
    assert spec.groups() == (None, "Advanced")
    assert spec.is_collapsed("Advanced") is True
    assert [f.key for f in spec.fields_in(None)] == [
        "fine_method", "stability_seeds", "seed", "plane_radius", "m3c2_core_points",
    ]


def test_advanced_order_m3c2_block_then_precision_then_general_then_extra_last() -> None:
    spec = load_params(PARAMS)
    assert [f.key for f in spec.fields_in("Advanced")] == [
        "m3c2_normal_radius", "m3c2_projection_radius", "m3c2_max_depth",
        "m3c2_scale_mode", "m3c2_max_scale_factor", "m3c2_max_levels",
        "reference_precision_mm", "align_precision_mm", "registration_uncertainty_mm",
        "coarse_mode", "coarse_review", "accept_poor_coarse", "coarse_parameters",
        "fit_tilt", "target_points", "max_registration_points", "max_evaluation_points",
        "dense_report_points", "overlap", "report_thresholds_mm",
        "comparison_equivalence_mm", "extra_arguments",
    ]


def test_visibility_rules_follow_the_spec_tables() -> None:
    spec = load_params(PARAMS)
    assert spec.field("plane_radius").visible_when.values == ("local-plane", "all")
    for key in M3C2_KEYS + (
        "reference_precision_mm", "align_precision_mm", "registration_uncertainty_mm"
    ):
        assert spec.field(key).visible_when.values == ("m3c2", "all"), key
    assert spec.field("extra_arguments").visible_when is None       # always visible
    for key in ("fine_method", "stability_seeds", "seed", "coarse_mode", "target_points"):
        assert spec.field(key).visible_when is None, key


def test_new_fields_default_to_empty_meaning_engine_default() -> None:
    spec = load_params(PARAMS)
    for key in METHOD_KEYS:
        assert spec.field(key).default == "", key
    mode = spec.field("m3c2_scale_mode")
    assert mode.type == "choice" and mode.choices == ("", "adaptive", "fixed")
    for key in METHOD_KEYS:
        if key != "m3c2_scale_mode":
            assert spec.field(key).type == "str"


def test_help_states_the_engine_default_transcribed_from_ricp() -> None:
    spec = load_params(PARAMS)
    expect = {
        "plane_radius": "4x measured spacing",
        "m3c2_normal_radius": "6x measured spacing",
        "m3c2_projection_radius": "4x measured spacing",
        "m3c2_max_depth": "10x measured spacing",
        "m3c2_scale_mode": "adaptive",
        "m3c2_max_scale_factor": "(4)",
        "m3c2_max_levels": "(5)",
        "m3c2_core_points": "(5000)",
    }
    for key, phrase in expect.items():
        assert phrase in spec.field(key).help, key
    assert "Neighborhood radius used to fit local planes." in spec.field("plane_radius").help
    assert spec.field("m3c2_core_points").help.startswith(
        "Number of representative locations used by the M3C2-guided registration. "
        "More points increase coverage and processing time."
    )


def test_every_v2_field_is_still_a_valid_form() -> None:
    spec = load_params(PARAMS)
    assert spec.validate(spec.defaults()) == spec.defaults()


# --------------------------------------------------------------------------- #
# method_argument_tokens
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("method", ["paper-c2c", "local-plane", "m3c2", "all"])
def test_defaults_emit_nothing_for_every_method(method: str) -> None:
    assert adapter.method_argument_tokens({**defaults(), "fine_method": method}) == []


def test_tokens_per_method_with_every_field_filled() -> None:
    p = {**defaults(), **FILLED}
    assert adapter.method_argument_tokens({**p, "fine_method": "paper-c2c"}) == []
    assert adapter.method_argument_tokens({**p, "fine_method": "local-plane"}) == PLANE_TOKENS
    assert adapter.method_argument_tokens({**p, "fine_method": "m3c2"}) == M3C2_TOKENS
    assert adapter.method_argument_tokens({**p, "fine_method": "all"}) == PLANE_TOKENS + M3C2_TOKENS


def test_one_token_per_element_no_joins_no_quotes() -> None:
    tokens = adapter.method_argument_tokens({**defaults(), **FILLED, "fine_method": "all"})
    assert len(tokens) == 16
    for token in tokens:
        assert " " not in token and "," not in token and '"' not in token


def test_a_single_filled_field_emits_just_that_flag() -> None:
    p = {**defaults(), "fine_method": "m3c2", "m3c2_max_levels": "7"}
    assert adapter.method_argument_tokens(p) == ["--m3c2-max-levels", "7"]


def test_whitespace_around_a_value_is_ignored() -> None:
    p = {**defaults(), "fine_method": "local-plane", "plane_radius": "  0.35 "}
    assert adapter.method_argument_tokens(p) == ["--plane-radius", "0.35"]


@pytest.mark.parametrize(
    ("method", "key", "value", "message"),
    [
        ("local-plane", "plane_radius", "0", "plane_radius: must be a finite number > 0"),
        ("local-plane", "plane_radius", "-1", "plane_radius: must be a finite number > 0"),
        ("local-plane", "plane_radius", "inf", "plane_radius: must be a finite number > 0"),
        ("local-plane", "plane_radius", "abc", "plane_radius: 'abc' is not a number"),
        ("m3c2", "m3c2_core_points", "99", "m3c2_core_points: must be a whole number >= 100"),
        ("m3c2", "m3c2_core_points", "50.5", "m3c2_core_points: '50.5' is not a whole number"),
        ("m3c2", "m3c2_normal_radius", "0", "m3c2_normal_radius: must be a finite number > 0"),
        ("m3c2", "m3c2_projection_radius", "nan", "m3c2_projection_radius: must be a finite"),
        ("m3c2", "m3c2_max_depth", "-0.1", "m3c2_max_depth: must be a finite number > 0"),
        ("m3c2", "m3c2_max_scale_factor", "0.5", "m3c2_max_scale_factor: must be a finite number >= 1"),
        ("m3c2", "m3c2_max_levels", "0", "m3c2_max_levels: must be a whole number >= 1"),
        ("all", "m3c2_max_levels", "two", "m3c2_max_levels: 'two' is not a whole number"),
    ],
)
def test_invalid_values_are_rejected_naming_the_field(method, key, value, message) -> None:
    with pytest.raises(adapter.AdapterError, match=message):
        adapter.method_argument_tokens({**defaults(), "fine_method": method, key: value})


def test_bounds_mirror_ricps_own_edges() -> None:
    """Decided 2026-09-19: the engine's real bounds, checked before any cloud loads."""
    ok = adapter.method_argument_tokens
    assert ok({**defaults(), "fine_method": "m3c2", "m3c2_core_points": "100"}) == ["--m3c2-core-points", "100"]
    assert ok({**defaults(), "fine_method": "m3c2", "m3c2_max_scale_factor": "1"}) == ["--m3c2-max-scale-factor", "1"]
    assert ok({**defaults(), "fine_method": "m3c2", "m3c2_max_levels": "1"}) == ["--m3c2-max-levels", "1"]


def test_an_invalid_value_in_a_hidden_field_does_not_block_another_method() -> None:
    """paper-c2c hides every method field; their contents are irrelevant to it."""
    junk = {key: "garbage" for key in METHOD_KEYS if key != "m3c2_scale_mode"}
    p = {**defaults(), **junk, "fine_method": "paper-c2c"}
    assert adapter.method_argument_tokens(p) == []
    # local-plane hides the m3c2 fields: their junk stays irrelevant too
    p = {**defaults(), **junk, "fine_method": "local-plane", "plane_radius": "0.4"}
    assert adapter.method_argument_tokens(p) == ["--plane-radius", "0.4"]
    # ...and the moment m3c2 is selected the junk IS validated
    with pytest.raises(adapter.AdapterError, match="m3c2_core_points"):
        adapter.method_argument_tokens({**defaults(), **junk, "fine_method": "m3c2"})


# --------------------------------------------------------------------------- #
# build_config_kwargs: tokens before the user's extra arguments
# --------------------------------------------------------------------------- #


def test_method_tokens_come_before_user_extra_arguments(tmp_path: Path) -> None:
    p = {**defaults(), "fine_method": "m3c2", "m3c2_max_levels": "3",
         "extra_arguments": "--m3c2-max-levels 9 --other x"}
    kwargs = adapter.build_config_kwargs(p, "r.las", "a.las", tmp_path)
    assert kwargs["extra_arguments"] == (
        "--m3c2-max-levels", "3", "--m3c2-max-levels", "9", "--other", "x"
    )  # argparse keeps the last occurrence: the hand-typed 9 wins


def test_nothing_else_in_the_mapping_changed(tmp_path: Path) -> None:
    kwargs = adapter.build_config_kwargs({**defaults(), **FILLED, "fine_method": "all"},
                                         "r.las", "a.las", tmp_path)
    assert kwargs["extra_arguments"] == tuple(PLANE_TOKENS + M3C2_TOKENS)
    # the precision fields stay typed - they never ride in extra_arguments
    assert kwargs["reference_precision_mm"] == 0.0
    assert kwargs["align_precision_mm"] == 0.0
    assert kwargs["registration_uncertainty_mm"] is None
    assert "--m3c2-reference-precision-mm" not in kwargs["extra_arguments"]


def test_a_hidden_value_is_saved_but_absent_from_the_arguments(tmp_path: Path) -> None:
    """What the shell writes to params.json keeps the hidden value; the engine
    never sees it."""
    p = {**defaults(), "fine_method": "paper-c2c", "plane_radius": "0.35",
         "m3c2_core_points": "8000"}
    saved = tmp_path / "params.json"
    saved.write_text(json.dumps(p), encoding="utf-8")

    reloaded = json.loads(saved.read_text(encoding="utf-8"))
    assert reloaded["plane_radius"] == "0.35" and reloaded["m3c2_core_points"] == "8000"

    kwargs = adapter.build_config_kwargs(reloaded, "r.las", "a.las", tmp_path)
    assert kwargs["extra_arguments"] == ()


# --------------------------------------------------------------------------- #
# The report: exact to_argv() token lists, against the REAL ricp_engine
# --------------------------------------------------------------------------- #


def _base_argv(ref: Path, ali: Path, out: Path, method: str) -> list[str]:
    return [
        str(ref.resolve()), str(ali.resolve()), "-o", str(out.resolve()),
        "--fine-method", method,
        "--stability-seeds", "0,1,2",
        "--seed", "0",
        "--m3c2-reference-precision-mm", "0.0",
        "--m3c2-align-precision-mm", "0.0",
        "--m3c2-registration-uncertainty-mm", "auto",
        "--coarse-mode", "auto",
        "--coarse-review", "never",
        "--target-points", "auto",
        "--max-registration-points", "1500000",
        "--max-evaluation-points", "500000",
        "--dense-report-points", "auto",
        "--overlap", "auto",
        "--report-thresholds-mm", "auto",
        "--comparison-equivalence-mm", "auto",
    ]


EXPECTED_FILLED = {
    "paper-c2c": [],
    "local-plane": PLANE_TOKENS,
    "m3c2": M3C2_TOKENS,
    "all": PLANE_TOKENS + M3C2_TOKENS,
}


@real_engine
@pytest.mark.parametrize("method", ["paper-c2c", "local-plane", "m3c2", "all"])
def test_exact_to_argv_at_defaults_and_filled(tmp_path: Path, method: str) -> None:
    import ricp_engine

    ref, ali = tmp_path / "ref.las", tmp_path / "ali.las"
    ref.write_bytes(b"x")
    ali.write_bytes(b"x")
    out = tmp_path / "run"

    at_defaults = ricp_engine.RegistrationConfig(
        **adapter.build_config_kwargs({**defaults(), "fine_method": method}, str(ref), str(ali), out)
    ).to_argv()
    assert at_defaults == _base_argv(ref, ali, out, method)

    filled = ricp_engine.RegistrationConfig(
        **adapter.build_config_kwargs({**defaults(), **FILLED, "fine_method": method},
                                      str(ref), str(ali), out)
    ).to_argv()
    assert filled == _base_argv(ref, ali, out, method) + EXPECTED_FILLED[method]


@real_engine
def test_a_hidden_junk_value_does_not_block_a_real_config(tmp_path: Path) -> None:
    import ricp_engine

    ref, ali = tmp_path / "ref.las", tmp_path / "ali.las"
    ref.write_bytes(b"x")
    ali.write_bytes(b"x")
    p = {**defaults(), "fine_method": "paper-c2c", "m3c2_core_points": "not a number"}
    config = ricp_engine.RegistrationConfig(
        **adapter.build_config_kwargs(p, str(ref), str(ali), tmp_path / "run")
    )
    config.validate()                               # the engine is fine with it
    assert config.extra_arguments == ()


# --------------------------------------------------------------------------- #
# main() end to end with a stub engine: the saved params vs what ricp gets
# --------------------------------------------------------------------------- #


def test_main_saves_hidden_values_and_sends_only_the_selected_methods_flags(
    tmp_path: Path, monkeypatch
) -> None:
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class StubConfig:
        reference: str
        align: str
        output_directory: str
        fine_method: str = "all"
        stability_seeds: tuple = (0, 1, 2)
        seed: int = 0
        reference_precision_mm: float = 0.0
        align_precision_mm: float = 0.0
        registration_uncertainty_mm: object = None
        coarse_mode: str = "auto"
        coarse_review: str = "never"
        accept_poor_coarse: bool = False
        coarse_matrix: object = None
        coarse_parameters: object = None
        fit_tilt: bool = True
        target_points: object = "auto"
        max_registration_points: int = 1_500_000
        max_evaluation_points: int = 500_000
        dense_report_points: object = "auto"
        overlap: object = "auto"
        report_thresholds_mm: str = "auto"
        comparison_equivalence_mm: object = "auto"
        extra_arguments: tuple = ()

        def validate(self) -> None:
            pass

    @dataclass(frozen=True)
    class StubResult:
        status: str = "failed"
        exit_code: int = 2
        run_directory: object = None
        methods: dict = None
        recommended_method: object = None
        comparison_outcome: object = None
        artifacts: dict = None
        log: str = ""
        error_message: str = "stub"

        @property
        def succeeded(self) -> bool:
            return False

        def as_dict(self) -> dict:
            return {}

    stub = types.ModuleType("ricp_engine")
    stub.RegistrationConfig = StubConfig
    stub.RICPConfigurationError = ValueError
    stub.calls = []
    stub.run_registration = lambda config, on_progress=None: (
        stub.calls.append(config) or StubResult(methods={}, artifacts={})
    )
    monkeypatch.setitem(sys.modules, "ricp_engine", stub)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    ref, ali = tmp_path / "ref.las", tmp_path / "ali.las"
    ref.write_bytes(b"x")
    ali.write_bytes(b"x")
    params = {**defaults(), "fine_method": "local-plane",
              "plane_radius": "0.35", "m3c2_core_points": "8000"}
    params_file = tmp_path / "params.json"
    params_file.write_text(json.dumps(params), encoding="utf-8")

    adapter.main([
        "register", "--params", str(params_file), "--out", str(run_dir),
        "--reference=" + str(ref), "--align=" + str(ali), "--coarse-artifact=",
    ])

    (config,) = stub.calls
    assert config.extra_arguments == ("--plane-radius", "0.35")     # m3c2 field hidden
    saved = json.loads(params_file.read_text(encoding="utf-8"))
    assert saved["m3c2_core_points"] == "8000"                       # ...but kept


def test_nothing_under_ricp_was_modified() -> None:
    import subprocess

    ricp = REPO_ROOT.parent / "ricp" / "ricp"
    if not (ricp / ".git").exists():
        pytest.skip("../ricp/ricp is not a git checkout")
    out = subprocess.run(
        ["git", "-C", str(ricp), "status", "--porcelain", "--untracked-files=no"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert out.strip() == "", "tracked files changed under ../ricp:\n" + out
