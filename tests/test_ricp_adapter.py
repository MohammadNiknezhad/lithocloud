"""ricp plug v2: manifest, params -> RegistrationConfig, result -> outputs.json.

The run itself is stubbed: a fake ``ricp_engine`` module is injected into
``sys.modules`` so no registration is ever computed here. The one place the
REAL module is used is to prove the form's defaults reproduce
``RegistrationConfig``'s own defaults field for field - constructing a frozen
dataclass is not heavy compute.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from lithocloud.core import discover_engines, load_manifest, load_params

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = REPO_ROOT / "engines" / "ricp"
RICP_REPO = REPO_ROOT.parent / "ricp" / "ricp"


def _load_adapter():
    spec = importlib.util.spec_from_file_location("ricp_adapter", ENGINE_DIR / "adapter.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = _load_adapter()


def _real_engine_importable() -> bool:
    return importlib.util.find_spec("ricp_engine") is not None


real_engine = pytest.mark.skipif(
    not _real_engine_importable(), reason="ricp_engine is not installed in this env"
)


@pytest.fixture()
def engine():
    return load_manifest(ENGINE_DIR)


def defaults() -> dict:
    return load_params(ENGINE_DIR / "params_register.json").defaults()


# --------------------------------------------------------------------------- #
# A stub ricp_engine - the shape the adapter relies on, nothing more
# --------------------------------------------------------------------------- #


class StubConfigurationError(ValueError):
    pass


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
    registration_uncertainty_mm: float | None = None
    coarse_mode: str = "auto"
    coarse_review: str = "never"
    accept_poor_coarse: bool = False
    coarse_matrix: str | None = None
    coarse_parameters: tuple | None = None
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
        if self.coarse_matrix and self.coarse_parameters:
            raise StubConfigurationError("choose coarse_matrix or coarse_parameters")
        if self.seed < 0:
            raise StubConfigurationError("seed must be non-negative")


@dataclass(frozen=True)
class StubMethod:
    method: str
    status: str
    directory: Path
    transform_path: Path | None
    registered_cloud_path: Path | None

    def as_dict(self) -> dict:
        return {"method": self.method, "status": self.status}


@dataclass(frozen=True)
class StubResult:
    status: str
    exit_code: int
    run_directory: Path | None
    methods: dict
    recommended_method: str | None
    comparison_outcome: str | None
    artifacts: dict
    log: str = ""
    error_message: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "completed" and self.exit_code == 0

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "exit_code": self.exit_code,
            "succeeded": self.succeeded,
            "run_directory": str(self.run_directory) if self.run_directory else None,
            "methods": {k: v.as_dict() for k, v in self.methods.items()},
            "recommended_method": self.recommended_method,
            "comparison_outcome": self.comparison_outcome,
            "artifacts": {k: str(v) for k, v in self.artifacts.items()},
            "log": self.log,
            "error_message": self.error_message,
        }


@pytest.fixture()
def stub_engine(monkeypatch):
    """Inject a fake ricp_engine. ``stub.next_result`` is what a run returns;
    ``stub.calls`` records the config and callback it was given."""
    stub = types.ModuleType("ricp_engine")
    stub.RegistrationConfig = StubConfig
    stub.RICPConfigurationError = StubConfigurationError
    stub.SUPPORTED_INPUT_SUFFIXES = set(adapter.RICP_READABLE)
    stub.calls = []
    stub.next_result = None
    stub.progress_lines = ["Loading reference", "Run folder: (set by test)", "done"]

    def run_registration(config, on_progress=None):
        stub.calls.append((config, on_progress))
        if on_progress is not None:
            for line in stub.progress_lines:
                on_progress(line)
        return stub.next_result

    stub.run_registration = run_registration
    monkeypatch.setitem(sys.modules, "ricp_engine", stub)
    return stub


def fabricate_run(run_dir: Path, *, methods=("paper-c2c", "local-plane", "m3c2"),
                  single: bool = False, overlays: bool = True) -> tuple[Path, dict]:
    """A plausible ricp run_... tree inside the studio run folder."""
    native = run_dir / "run_20260909_120000"
    native.mkdir(parents=True)
    artifacts: dict[str, Path] = {}
    for name, filename in (
        ("registration_uncertainty", "registration_uncertainty.json"),
        ("method_comparison", "method_comparison.json"),
        ("sampling_stability", "sampling_stability.json"),
        ("method_transform_differences", "method_transform_differences.csv"),
    ):
        path = native / filename
        path.write_text("{}", encoding="utf-8")
        artifacts[name] = path
    if overlays:
        for name in ("coarse_overlay_top", "coarse_overlay_side"):
            path = native / (name + ".png")
            path.write_bytes(b"png")
            artifacts[name] = path

    method_results = {}
    for m in methods:
        mdir = native if single else native / "methods" / m
        mdir.mkdir(parents=True, exist_ok=True)
        (mdir / "transform_final.txt").write_text("1 0 0 0\n", encoding="utf-8")
        (mdir / "registered_ali.las").write_bytes(b"las")
        (mdir / "convergence.png").write_bytes(b"png")
        (mdir / "spatial_residual.png").write_bytes(b"png")
        method_results[m] = StubMethod(
            method=m,
            status="ok",
            directory=mdir,
            transform_path=mdir / "transform_final.txt",
            registered_cloud_path=mdir / "registered_ali.las",
        )
    return native, {"artifacts": artifacts, "methods": method_results}


def write_params(folder: Path, **overrides) -> Path:
    path = folder / "params.json"
    path.write_text(json.dumps({**defaults(), **overrides}), encoding="utf-8")
    return path


def write_clouds(folder: Path) -> tuple[Path, Path]:
    ref = folder / "ref.las"
    ali = folder / "ali.las"
    ref.write_bytes(b"ref")
    ali.write_bytes(b"ali")
    return ref, ali


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #


def test_the_engine_is_discovered(engine) -> None:
    engines, problems = discover_engines(REPO_ROOT)
    assert problems == []
    assert "ricp" in [e.id for e in engines]


def test_one_non_interactive_action_with_the_spec_slots(engine) -> None:
    assert engine.version == "0.2.0"
    assert engine.action_ids == ("register",)
    action = engine.action("register")
    assert action.interactive is False
    assert [(s.key, s.type, s.optional) for s in action.inputs] == [
        ("reference", "pointcloud", False),
        ("align", "pointcloud", False),
        ("coarse", "transform", True),
    ]
    assert [(s.key, s.type) for s in action.outputs] == [
        ("registered", "pointcloud"),
        ("transform", "transform"),
        ("uncertainty", "report"),
        ("comparison", "report"),
        ("plots", "figure"),
    ]


def test_the_old_plug_is_gone() -> None:
    assert not (ENGINE_DIR / "params_coarse.json").exists()
    source = (ENGINE_DIR / "adapter.py").read_text(encoding="utf-8")
    for old in ("_coarse_only", "build_cli_argv", "register_gui", "sys.path.insert"):
        assert old not in source, old
    assert adapter.ACTIONS == ("register",)


# --------------------------------------------------------------------------- #
# params_register.json
# --------------------------------------------------------------------------- #


def test_params_load_and_defaults_are_the_engines(engine) -> None:
    spec = load_params(engine.params_path("register"))
    assert spec.validate(spec.defaults()) == spec.defaults()
    p = spec.defaults()
    assert p["fine_method"] == "all"
    assert p["stability_seeds"] == "0,1,2"
    assert p["seed"] == 0
    assert p["reference_precision_mm"] == 0.0
    assert p["align_precision_mm"] == 0.0
    assert p["registration_uncertainty_mm"] == ""      # None
    assert p["coarse_mode"] == "auto"
    assert p["coarse_review"] == "never"
    assert p["accept_poor_coarse"] is False
    assert p["coarse_parameters"] == ""                # None
    assert p["fit_tilt"] is True
    assert p["target_points"] == "auto"
    assert p["max_registration_points"] == ""          # engine default, never drifts
    assert p["max_evaluation_points"] == ""
    assert p["dense_report_points"] == "auto"
    assert p["overlap"] == "auto"
    assert p["report_thresholds_mm"] == "auto"
    assert p["comparison_equivalence_mm"] == "auto"
    assert p["extra_arguments"] == ""


def test_params_cover_every_config_field_except_the_three_the_adapter_owns(engine) -> None:
    spec = load_params(engine.params_path("register"))
    config_fields = set(StubConfig.__dataclass_fields__)
    owned = {"reference", "align", "output_directory", "coarse_matrix"}
    assert set(spec.keys) == config_fields - owned


def test_help_text_carries_the_required_warnings(engine) -> None:
    spec = load_params(engine.params_path("register"))
    for key in ("reference_precision_mm", "align_precision_mm"):
        text = spec.field(key).help.lower()
        assert "one-sigma" in text
        assert "not point spacing" in text
        assert "c2c mean" in text
        assert "registration error" in text
        assert "incomplete" in text
    assert "0,1,2,3,4,5,6,7,8,9" in spec.field("stability_seeds").help


# --------------------------------------------------------------------------- #
# params -> RegistrationConfig
# --------------------------------------------------------------------------- #


def test_defaults_form_maps_to_every_engine_default(tmp_path: Path) -> None:
    kwargs = adapter.build_config_kwargs(defaults(), "r.las", "a.las", tmp_path)
    config = StubConfig(**kwargs)
    assert config == StubConfig(reference="r.las", align="a.las", output_directory=str(tmp_path))
    # the two max_* fields were NOT passed, so the engine's own defaults applied
    assert "max_registration_points" not in kwargs
    assert "max_evaluation_points" not in kwargs


@real_engine
def test_defaults_form_equals_the_real_registration_config_defaults(tmp_path: Path) -> None:
    """The load-bearing faithfulness check, against the installed ricp_engine."""
    import ricp_engine

    kwargs = adapter.build_config_kwargs(defaults(), "r.las", "a.las", tmp_path)
    built = ricp_engine.RegistrationConfig(**kwargs)
    reference = ricp_engine.RegistrationConfig(
        reference="r.las", align="a.las", output_directory=str(tmp_path)
    )
    assert built == reference
    assert set(adapter.RICP_READABLE) == set(ricp_engine.SUPPORTED_INPUT_SUFFIXES)


def test_every_field_is_translated(tmp_path: Path) -> None:
    kwargs = adapter.build_config_kwargs(
        {
            **defaults(),
            "fine_method": "m3c2",
            "stability_seeds": "0,1,2,3,4,5,6,7,8,9",
            "seed": 7,
            "reference_precision_mm": 30.0,
            "align_precision_mm": 25.5,
            "registration_uncertainty_mm": "4.2",
            "coarse_mode": "none",
            "coarse_review": "if-poor",
            "accept_poor_coarse": True,
            "coarse_parameters": "1 2 3 45",
            "fit_tilt": False,
            "target_points": "5000",
            "max_registration_points": "2000000",
            "max_evaluation_points": "250000",
            "dense_report_points": "off",
            "overlap": "12.5",
            "report_thresholds_mm": "5,10,20",
            "comparison_equivalence_mm": "2",
            "extra_arguments": "--foo bar",
        },
        r"D:\ws\ref cloud.las",
        r"D:\ws\align cloud.las",
        tmp_path,
    )
    assert kwargs["reference"] == r"D:\ws\ref cloud.las"
    assert kwargs["output_directory"] == str(tmp_path)
    assert kwargs["fine_method"] == "m3c2"
    assert kwargs["stability_seeds"] == tuple(range(10))
    assert kwargs["seed"] == 7
    assert kwargs["reference_precision_mm"] == 30.0
    assert kwargs["align_precision_mm"] == 25.5
    assert kwargs["registration_uncertainty_mm"] == 4.2
    assert kwargs["coarse_mode"] == "none"
    assert kwargs["coarse_review"] == "if-poor"
    assert kwargs["accept_poor_coarse"] is True
    assert kwargs["coarse_matrix"] is None
    assert kwargs["coarse_parameters"] == (1.0, 2.0, 3.0, 45.0)
    assert kwargs["fit_tilt"] is False
    assert kwargs["target_points"] == 5000
    assert kwargs["max_registration_points"] == 2_000_000
    assert kwargs["max_evaluation_points"] == 250_000
    assert kwargs["dense_report_points"] == "off"
    assert kwargs["overlap"] == 12.5
    assert kwargs["report_thresholds_mm"] == "5,10,20"
    assert kwargs["comparison_equivalence_mm"] == 2.0
    assert kwargs["extra_arguments"] == ("--foo", "bar")


def test_the_coarse_artifact_becomes_coarse_matrix(tmp_path: Path) -> None:
    kwargs = adapter.build_config_kwargs(
        defaults(), "r.las", "a.las", tmp_path, coarse_matrix=r"D:\runs\x\transform_final.txt"
    )
    assert kwargs["coarse_matrix"] == r"D:\runs\x\transform_final.txt"


def test_empty_seeds_means_off(tmp_path: Path) -> None:
    kwargs = adapter.build_config_kwargs(
        {**defaults(), "stability_seeds": ""}, "r.las", "a.las", tmp_path
    )
    assert kwargs["stability_seeds"] == ()


@pytest.mark.parametrize(
    ("overrides", "coarse", "message"),
    [
        ({"stability_seeds": "0,x"}, None, "stability_seeds"),
        ({"coarse_parameters": "1 2 3"}, None, "four numbers"),
        ({"coarse_parameters": "1 2 3 4"}, "m.txt", "not both"),
        ({"target_points": "many"}, None, "target_points"),
        ({"dense_report_points": "some"}, None, "dense_report_points"),
        ({"overlap": "wide"}, None, "overlap"),
        ({"comparison_equivalence_mm": "tight"}, None, "comparison_equivalence_mm"),
        ({"registration_uncertainty_mm": "n/a"}, None, "registration_uncertainty_mm"),
        ({"max_registration_points": "lots"}, None, "max_registration_points"),
    ],
)
def test_bad_values_are_rejected_before_the_engine_runs(
    tmp_path: Path, overrides: dict, coarse, message: str
) -> None:
    with pytest.raises(adapter.AdapterError, match=message):
        adapter.build_config_kwargs(
            {**defaults(), **overrides}, "r.las", "a.las", tmp_path, coarse_matrix=coarse
        )


# --------------------------------------------------------------------------- #
# Input preparation (unchanged from v1: LAZ is decompressed, never passed)
# --------------------------------------------------------------------------- #


def test_readable_extensions_pass_through(tmp_path: Path) -> None:
    for name in ("a.las", "a.txt", "a.xyz", "a.csv", "a.pts", "a.asc", "A.LAS"):
        assert adapter.prepare_input(name, tmp_path, what="reference") == name


def test_an_unsupported_extension_and_a_missing_input_are_reported(tmp_path: Path) -> None:
    with pytest.raises(adapter.AdapterError, match="unsupported extension"):
        adapter.prepare_input("cloud.e57", tmp_path, what="reference")
    with pytest.raises(adapter.AdapterError, match="no cloud chosen"):
        adapter.prepare_input("", tmp_path, what="align")


def test_laz_is_converted_to_las_in_the_run_folder(tmp_path: Path) -> None:
    import numpy as np
    import laspy

    source = tmp_path / "canonical.laz"
    las = laspy.LasData(laspy.LasHeader(point_format=3, version="1.4"))
    las.x = np.array([1.0, 2.0, 3.0])
    las.y = np.array([4.0, 5.0, 6.0])
    las.z = np.array([7.0, 8.0, 9.0])
    las.write(str(source))
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    prepared = adapter.prepare_input(str(source), run_dir, what="reference")

    assert prepared == str(run_dir / "canonical.las")
    assert len(laspy.read(prepared).points) == 3


# --------------------------------------------------------------------------- #
# result -> outputs.json
# --------------------------------------------------------------------------- #


def test_all_methods_run_registers_the_recommended_method(tmp_path: Path) -> None:
    native, parts = fabricate_run(tmp_path)
    result = StubResult(
        status="completed", exit_code=0, run_directory=native,
        methods=parts["methods"], recommended_method="m3c2",
        comparison_outcome="decisive", artifacts=parts["artifacts"],
    )

    outputs, notes = adapter.collect_outputs(result, tmp_path)
    stamp = native.name

    assert notes == []
    assert outputs["registered"] == [stamp + "/methods/m3c2/registered_ali.las"]
    assert outputs["transform"] == [stamp + "/methods/m3c2/transform_final.txt"]
    assert outputs["uncertainty"] == [stamp + "/registration_uncertainty.json"]
    assert outputs["comparison"] == [stamp + "/method_comparison.json"]
    assert outputs["plots"] == [
        stamp + "/coarse_overlay_top.png",
        stamp + "/coarse_overlay_side.png",
        stamp + "/methods/m3c2/convergence.png",
        stamp + "/methods/m3c2/spatial_residual.png",
    ]
    # the two methods that were not recommended contribute nothing
    assert not any("paper-c2c" in f or "local-plane" in f for files in outputs.values() for f in files)


def test_single_method_run_registers_that_method_without_a_recommendation(tmp_path: Path) -> None:
    native, parts = fabricate_run(tmp_path, methods=("local-plane",), single=True)
    result = StubResult(
        status="completed", exit_code=0, run_directory=native,
        methods=parts["methods"], recommended_method=None,
        comparison_outcome=None, artifacts=parts["artifacts"],
    )

    outputs, notes = adapter.collect_outputs(result, tmp_path)

    assert notes == []
    assert adapter.chosen_method(result) == "local-plane"
    assert outputs["registered"] == [native.name + "/registered_ali.las"]
    assert outputs["transform"] == [native.name + "/transform_final.txt"]
    assert outputs["comparison"] == [native.name + "/method_comparison.json"]


def test_no_recommendation_among_several_methods_registers_reports_only(tmp_path: Path) -> None:
    """Decided 2026-09-09: the adapter never picks a method the evidence did not."""
    native, parts = fabricate_run(tmp_path)
    result = StubResult(
        status="completed", exit_code=0, run_directory=native,
        methods=parts["methods"], recommended_method=None,
        comparison_outcome="undecided", artifacts=parts["artifacts"],
    )

    outputs, notes = adapter.collect_outputs(result, tmp_path)

    assert adapter.chosen_method(result) is None
    assert "registered" not in outputs
    assert "transform" not in outputs
    assert set(outputs) == {"uncertainty", "comparison", "plots"}
    assert outputs["plots"] == [
        native.name + "/coarse_overlay_top.png",
        native.name + "/coarse_overlay_side.png",
    ]
    assert len(notes) == 1
    assert "no recommended method" in notes[0]
    assert "undecided" in notes[0]
    assert "fine_method" in notes[0]


def test_a_recommendation_that_did_not_run_is_ignored(tmp_path: Path) -> None:
    native, parts = fabricate_run(tmp_path, methods=("paper-c2c", "m3c2"))
    result = StubResult(
        status="completed", exit_code=0, run_directory=native,
        methods=parts["methods"], recommended_method="local-plane",
        comparison_outcome="decisive", artifacts=parts["artifacts"],
    )
    assert adapter.chosen_method(result) is None


def test_missing_files_are_left_out_not_invented(tmp_path: Path) -> None:
    native, parts = fabricate_run(tmp_path, overlays=False)
    (native / "methods" / "m3c2" / "registered_ali.las").unlink()
    result = StubResult(
        status="completed", exit_code=0, run_directory=native,
        methods=parts["methods"], recommended_method="m3c2",
        comparison_outcome="decisive", artifacts=parts["artifacts"],
    )

    outputs, notes = adapter.collect_outputs(result, tmp_path)

    assert "registered" not in outputs
    assert outputs["transform"] == [native.name + "/methods/m3c2/transform_final.txt"]
    assert all("coarse_overlay" not in f for f in outputs["plots"])
    assert any("not found on disk" in n for n in notes)


def test_a_file_outside_the_run_folder_is_refused(tmp_path: Path) -> None:
    native, parts = fabricate_run(tmp_path / "studio_run")
    stray = tmp_path / "elsewhere.json"
    stray.write_text("{}", encoding="utf-8")
    parts["artifacts"]["method_comparison"] = stray
    result = StubResult(
        status="completed", exit_code=0, run_directory=native,
        methods=parts["methods"], recommended_method="m3c2",
        comparison_outcome="decisive", artifacts=parts["artifacts"],
    )

    outputs, notes = adapter.collect_outputs(result, tmp_path / "studio_run")

    assert "comparison" not in outputs
    assert any("outside the run folder" in n for n in notes)


# --------------------------------------------------------------------------- #
# main() end to end, against the stub engine
# --------------------------------------------------------------------------- #


def run_main(tmp_path: Path, stub, result, *, coarse: str = "", **params) -> int:
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    ref, ali = write_clouds(tmp_path)
    stub.next_result = result
    return adapter.main(
        [
            "register",
            "--params", str(write_params(tmp_path, **params)),
            "--out", str(run_dir),
            "--reference=" + str(ref),
            "--align=" + str(ali),
            "--coarse-artifact=" + coarse,
        ]
    )


def test_success_writes_outputs_and_the_result_record(tmp_path: Path, stub_engine, capsys) -> None:
    run_dir = tmp_path / "run"
    native, parts = fabricate_run(run_dir)
    result = StubResult(
        status="completed", exit_code=0, run_directory=native,
        methods=parts["methods"], recommended_method="m3c2",
        comparison_outcome="decisive", artifacts=parts["artifacts"], log="the log",
    )

    rc = run_main(tmp_path, stub_engine, result, reference_precision_mm=30.0)

    assert rc == 0
    outputs = json.loads((run_dir / "outputs.json").read_text(encoding="utf-8"))
    assert set(outputs) == {"registered", "transform", "uncertainty", "comparison", "plots"}
    record = json.loads((run_dir / "ricp_result.json").read_text(encoding="utf-8"))
    assert record["recommended_method"] == "m3c2"
    assert record["succeeded"] is True
    assert record["log"] == "the log"
    assert not (run_dir / "adapter_error.txt").exists()

    # the engine received a RegistrationConfig rooted at the studio run folder
    (config, callback), = stub_engine.calls
    assert config.output_directory == str(run_dir)
    assert config.reference_precision_mm == 30.0
    assert callback is not None

    # and progress streamed to stdout, line by line
    out = capsys.readouterr().out
    for line in stub_engine.progress_lines:
        assert line in out
    assert "recommended method = m3c2" in out


def test_progress_callback_writes_to_the_real_stdout_not_a_redirected_one(
    tmp_path: Path, stub_engine, capsys
) -> None:
    """The engine swaps sys.stdout during a run; a naive print would feed the
    engine's own capture stream. The callback must target the ORIGINAL stdout."""
    import contextlib
    import io

    run_dir = tmp_path / "run"
    native, parts = fabricate_run(run_dir)
    result = StubResult(
        status="completed", exit_code=0, run_directory=native,
        methods=parts["methods"], recommended_method="m3c2",
        comparison_outcome="decisive", artifacts=parts["artifacts"],
    )

    seen_inside: list[str] = []

    def run_registration(config, on_progress=None):
        stub_engine.calls.append((config, on_progress))
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink):   # what ricp_engine does
            on_progress("progress while redirected")
        seen_inside.append(sink.getvalue())
        return result

    stub_engine.run_registration = run_registration

    assert run_main(tmp_path, stub_engine, result) == 0
    assert seen_inside == [""]                      # nothing leaked into the redirect
    assert "progress while redirected" in capsys.readouterr().out


def test_failure_returns_the_exit_code_and_points_at_the_overlays(
    tmp_path: Path, stub_engine
) -> None:
    run_dir = tmp_path / "run"
    native, parts = fabricate_run(run_dir, methods=())
    result = StubResult(
        status="failed", exit_code=3, run_directory=native, methods={},
        recommended_method=None, comparison_outcome=None,
        artifacts=parts["artifacts"], log="...",
        error_message="coarse placement quality poor; review overlays",
    )

    rc = run_main(tmp_path, stub_engine, result)

    assert rc == 3
    assert not (run_dir / "outputs.json").exists()
    error = (run_dir / "adapter_error.txt").read_text(encoding="utf-8")
    assert "coarse placement quality poor" in error
    assert "coarse_overlay_top.png" in error
    assert "coarse_overlay_side.png" in error
    assert "reviewed coarse transform" in error
    # decided 2026-09-09: the full record is written on failure too
    record = json.loads((run_dir / "ricp_result.json").read_text(encoding="utf-8"))
    assert record["status"] == "failed"
    assert record["error_message"].startswith("coarse placement")


def test_failure_before_a_run_folder_exists(tmp_path: Path, stub_engine) -> None:
    result = StubResult(
        status="failed", exit_code=2, run_directory=None, methods={},
        recommended_method=None, comparison_outcome=None, artifacts={},
        error_message="RICPConfigurationError: boom",
    )
    rc = run_main(tmp_path, stub_engine, result)
    assert rc == 2
    assert "boom" in (tmp_path / "run" / "adapter_error.txt").read_text(encoding="utf-8")
    assert not (tmp_path / "run" / "ricp_result.json").exists()


def test_a_cancelled_run_never_reports_exit_zero(tmp_path: Path, stub_engine) -> None:
    result = StubResult(
        status="cancelled", exit_code=0, run_directory=None, methods={},
        recommended_method=None, comparison_outcome=None, artifacts={},
    )
    assert run_main(tmp_path, stub_engine, result) == 1


def test_a_bad_parameter_never_reaches_the_engine(tmp_path: Path, stub_engine) -> None:
    rc = run_main(tmp_path, stub_engine, None, coarse_parameters="1 2 3")
    assert rc == 2
    assert stub_engine.calls == []
    assert "four numbers" in (tmp_path / "run" / "adapter_error.txt").read_text(encoding="utf-8")


def test_the_engines_own_validation_error_is_persisted(tmp_path: Path, stub_engine) -> None:
    """A rejection raised by RegistrationConfig.validate() itself (something the
    adapter does not pre-check) is reported the same way, before any run."""
    rc = run_main(tmp_path, stub_engine, None, seed=-1)
    assert rc == 2
    assert stub_engine.calls == []
    error = (tmp_path / "run" / "adapter_error.txt").read_text(encoding="utf-8")
    assert "invalid configuration" in error
    assert "non-negative" in error


@real_engine
def test_the_real_engine_rejects_a_missing_cloud_before_computing(tmp_path: Path) -> None:
    """No stub: the installed ricp_engine's validate() runs, no registration does."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    rc = adapter.main(
        [
            "register",
            "--params", str(write_params(tmp_path)),
            "--out", str(run_dir),
            "--reference=" + str(tmp_path / "nope.las"),
            "--align=" + str(tmp_path / "nope2.las"),
            "--coarse-artifact=",
        ]
    )
    assert rc == 2
    error = (run_dir / "adapter_error.txt").read_text(encoding="utf-8")
    assert "invalid configuration" in error
    assert "does not exist" in error


# --------------------------------------------------------------------------- #
# The sibling repo is untouched
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not (RICP_REPO / ".git").exists(), reason="../ricp/ricp is not a git checkout")
def test_nothing_under_ricp_was_modified() -> None:
    """Rule 5: ../ricp is read-only. Tracked files must equal HEAD."""
    completed = subprocess.run(
        ["git", "-C", str(RICP_REPO), "status", "--porcelain", "--untracked-files=no"],
        capture_output=True, text=True, check=True,
    )
    assert completed.stdout.strip() == "", (
        "tracked files changed under ../ricp:\n" + completed.stdout
    )
