"""ricp multi-cloud projects (Part 2): register_project + validate_stable_areas.

No clouds are ever registered here. The project engine is a stub for the
run/outputs/status paths; the REAL ricp_project module is used only to pin
PROJECT_API_VERSION and to prove the adapter's kwargs build (and validate as)
a genuine RegistrationProjectConfig - construction only, no registration.
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

from lithocloud.core import load_manifest, load_params

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = REPO_ROOT / "engines" / "ricp"
RICP_REPO = REPO_ROOT.parent / "ricp" / "ricp"


def _load_adapter():
    spec = importlib.util.spec_from_file_location("ricp_adapter_p", ENGINE_DIR / "adapter.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = _load_adapter()

real_project = pytest.mark.skipif(
    importlib.util.find_spec("ricp_project") is None, reason="ricp_project not installed"
)


def defaults() -> dict:
    return load_params(ENGINE_DIR / "params_project.json").defaults()


# --------------------------------------------------------------------------- #
# Manifest + params
# --------------------------------------------------------------------------- #


def test_three_actions_and_the_single_pair_one_is_untouched() -> None:
    engine = load_manifest(ENGINE_DIR)
    assert engine.action_ids == ("register", "register_project", "validate_stable_areas")
    register = engine.action("register")
    assert register.interactive is False
    assert [(s.key, s.type, s.optional) for s in register.inputs] == [
        ("reference", "pointcloud", False), ("align", "pointcloud", False), ("coarse", "transform", True)]
    assert [s.key for s in register.outputs] == ["registered", "transform", "uncertainty", "comparison", "plots"]
    assert register.params == "params_register.json"


def test_register_project_action_shape() -> None:
    action = load_manifest(ENGINE_DIR).action("register_project")
    assert action.interactive is True                       # decision 1: the Tk checkpoint can show
    assert [(s.key, s.multiple) for s in action.inputs] == [("reference", False), ("aligns", True)]
    assert [(s.key, s.type, s.indexed) for s in action.outputs] == [
        ("registered_scan", "pointcloud", True), ("transform_scan", "transform", True),
        ("project_summary", "report", False), ("pose_graph_edges", "table", False),
        ("engine_outputs", "report", False), ("project_result", "report", False)]
    text = action.description
    for phrase in ("index 0", "pinned to 'always'", "PARTIAL", "never as a number",
                   "SUSPECT", "NOT a surface error", "kills the whole process"):
        assert phrase in text, phrase


def test_validate_action_shape_and_wording() -> None:
    action = load_manifest(ENGINE_DIR).action("validate_stable_areas")
    assert action.interactive is False
    assert [(s.key, s.type) for s in action.inputs] == [("project", "report"), ("manifest", "report")]
    assert [(s.key, s.type) for s in action.outputs] == [
        ("stable_validation", "report"), ("stable_validation_table", "table")]
    for phrase in ("YOU declare", "never invents", "NOT absolute registration accuracy", "never as zero"):
        assert phrase in action.description, phrase


def test_project_params_reuse_a2_fields_exactly() -> None:
    project = load_params(ENGINE_DIR / "params_project.json")
    single = load_params(ENGINE_DIR / "params_register.json")
    for key in ("plane_radius", "m3c2_core_points", "m3c2_normal_radius", "m3c2_projection_radius",
                "m3c2_max_depth", "m3c2_scale_mode", "m3c2_max_scale_factor", "m3c2_max_levels",
                "stability_seeds", "seed", "reference_precision_mm", "align_precision_mm",
                "registration_uncertainty_mm", "fit_tilt", "target_points",
                "max_registration_points", "max_evaluation_points", "dense_report_points",
                "overlap", "report_thresholds_mm"):
        a, b = project.field(key), single.field(key)
        assert (a.type, a.default, a.min, a.max, a.choices, a.help) == (
            b.type, b.default, b.min, b.max, b.choices, b.help), key


def test_project_params_layout_and_rules() -> None:
    spec = load_params(ENGINE_DIR / "params_project.json")
    assert spec.groups() == (None, "Advanced")
    assert spec.is_collapsed("Advanced") is True
    assert [f.key for f in spec.fields_in(None)] == [
        "mode", "fine_method", "plane_radius", "m3c2_core_points", "stability_seeds", "seed",
        "overlap_edges"]
    fm = spec.field("fine_method")
    assert fm.choices == ("paper-c2c", "local-plane", "m3c2")       # no "all"
    assert fm.default == "local-plane"
    assert "coarse_review" not in spec.keys                          # pinned, never a field
    assert "coarse_parameters" not in spec.keys
    assert "comparison_equivalence_mm" not in spec.keys
    edges = spec.field("overlap_edges")
    assert edges.type == "edge_list" and edges.visible_when.values == ("multiway",)
    assert "a chain without an extra loop cannot check loop consistency" in edges.help.lower() \
        or "chain without an extra loop" in edges.help
    assert spec.field("plane_radius").visible_when.values == ("local-plane",)
    for key in ("m3c2_core_points", "m3c2_normal_radius", "align_precisions_mm",
                "reference_precision_mm", "registration_uncertainty_mm"):
        assert spec.field(key).visible_when.values == ("m3c2",), key
    assert [f.key for f in spec.fields_in("Advanced")][-1] == "extra_arguments"
    assert spec.field("extra_arguments").visible_when is None
    assert "only after inspecting the coarse overlays" in spec.field("accept_poor_coarse").help.lower()
    assert spec.field("continue_on_error").default is True
    assert spec.validate(spec.defaults()) == spec.defaults()


def test_validate_params_file_is_empty_and_valid() -> None:
    spec = load_params(ENGINE_DIR / "params_validate.json")
    assert spec.keys == ()


# --------------------------------------------------------------------------- #
# Graph validation
# --------------------------------------------------------------------------- #


def test_independent_ignores_declared_edges_with_a_note() -> None:
    edges, notes = adapter.validate_project_graph("independent", 3, [[0, 1], [1, 2]])
    assert edges == []
    assert notes and "were not used" in notes[0]
    assert adapter.validate_project_graph("independent", 3, []) == ([], [])


def test_multiway_accepts_a_loop_and_notes_a_chain() -> None:
    edges, notes = adapter.validate_project_graph("multiway", 3, [[0, 1], [1, 2], [2, 3], [3, 0]])
    assert edges == [(0, 1), (1, 2), (2, 3), (3, 0)]
    assert notes == []
    edges, notes = adapter.validate_project_graph("multiway", 3, [[0, 1], [1, 2], [2, 3]])
    assert edges == [(0, 1), (1, 2), (2, 3)]
    assert notes and "no redundant loop" in notes[0] and "loop consistency" in notes[0]


@pytest.mark.parametrize(
    ("edges", "message"),
    [
        ([], "at least one overlap edge"),
        ([[1, 1]], "self-edge"),
        ([[0, 1], [1, 0]], "connected twice"),
        ([[0, 1], [0, 1]], "connected twice"),
        ([[0, 4]], "outside 0..3"),
        ([[0, 1], [2, 3]], "scan\\(s\\) 2, 3 have no path to REF"),
        ([[1, 2], [2, 3]], "have no path to REF"),
    ],
)
def test_multiway_graph_rejections(edges, message: str) -> None:
    with pytest.raises(adapter.AdapterError, match=message):
        adapter.validate_project_graph("multiway", 3, edges)


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(adapter.AdapterError, match="mode"):
        adapter.validate_project_graph("both", 2, [])


# --------------------------------------------------------------------------- #
# Config build
# --------------------------------------------------------------------------- #


def test_independent_config_at_defaults(tmp_path: Path) -> None:
    kwargs, notes = adapter.build_project_kwargs(defaults(), "ref.las", ["a1.las", "a2.las"], tmp_path)
    assert notes == []
    assert kwargs == {
        "reference": "ref.las", "aligns": ["a1.las", "a2.las"], "output_directory": str(tmp_path),
        "mode": "independent", "fine_method": "local-plane", "overlap_edges": [],
        "stability_seeds": (0, 1, 2), "seed": 0,
        "reference_precision_mm": 0.0, "align_precision_mm": 0.0, "align_precisions_mm": None,
        "registration_uncertainty_mm": None, "coarse_mode": "auto", "coarse_review": "always",
        "accept_poor_coarse": False, "fit_tilt": True, "target_points": "auto",
        "dense_report_points": "auto", "overlap": "auto", "report_thresholds_mm": "auto",
        "extra_arguments": (), "continue_on_error": True,
    }


def test_multiway_config_with_edges_precisions_and_method_tokens(tmp_path: Path) -> None:
    params = {**defaults(), "mode": "multiway", "fine_method": "m3c2",
              "overlap_edges": [[0, 1], [1, 2], [2, 0]],
              "align_precisions_mm": "2, 30", "m3c2_core_points": "8000",
              "extra_arguments": "--m3c2-core-points 9000"}
    kwargs, notes = adapter.build_project_kwargs(params, "ref.las", ["a1.las", "a2.las"], tmp_path)
    assert kwargs["mode"] == "multiway"
    assert kwargs["overlap_edges"] == [(0, 1), (1, 2), (2, 0)]
    assert kwargs["align_precisions_mm"] == [2.0, 30.0]
    # A2 mapping reused: generated tokens first, the hand-typed flag after (wins)
    assert kwargs["extra_arguments"] == ("--m3c2-core-points", "8000", "--m3c2-core-points", "9000")
    assert kwargs["coarse_review"] == "always"
    assert notes == []


def test_coarse_review_is_pinned_whatever_the_form_says(tmp_path: Path) -> None:
    """No code path can emit anything but 'always' for a project."""
    for injected in ("never", "if-poor", "", None):
        params = {**defaults(), "coarse_review": injected}
        kwargs, _ = adapter.build_project_kwargs(params, "r.las", ["a.las"], tmp_path)
        assert kwargs["coarse_review"] == "always"
    source = (ENGINE_DIR / "adapter.py").read_text(encoding="utf-8")
    project_part = source[source.index("def build_project_kwargs"):source.index("def _rel_in")]
    assert '"never"' not in project_part and "'never'" not in project_part
    assert 'PROJECT_COARSE_REVIEW = "always"' in source


def test_all_is_refused_before_the_engine(tmp_path: Path) -> None:
    with pytest.raises(adapter.AdapterError, match="'all' is diagnostic-only"):
        adapter.build_project_kwargs({**defaults(), "fine_method": "all"}, "r.las", ["a.las"], tmp_path)


def test_no_aligns_is_refused(tmp_path: Path) -> None:
    with pytest.raises(adapter.AdapterError, match="at least one ALIGN"):
        adapter.build_project_kwargs(defaults(), "r.las", [], tmp_path)


@pytest.mark.parametrize(
    ("text", "message"),
    [("2", "1 value\\(s\\) given for 2 align"), ("2,3,4", "3 value\\(s\\) given for 2"),
     ("2,x", "not a number"), ("2,-1", "finite and >= 0")],
)
def test_per_scan_precisions_are_length_and_value_checked(tmp_path: Path, text: str, message: str) -> None:
    params = {**defaults(), "fine_method": "m3c2", "align_precisions_mm": text}
    with pytest.raises(adapter.AdapterError, match=message):
        adapter.build_project_kwargs(params, "r.las", ["a.las", "b.las"], tmp_path)


def test_method_tokens_for_the_three_production_methods(tmp_path: Path) -> None:
    filled = {"plane_radius": "0.35", "m3c2_core_points": "8000", "m3c2_max_levels": "3"}
    for method, expected in (
        ("paper-c2c", ()),
        ("local-plane", ("--plane-radius", "0.35")),
        ("m3c2", ("--m3c2-core-points", "8000", "--m3c2-max-levels", "3")),
    ):
        kwargs, _ = adapter.build_project_kwargs({**defaults(), **filled, "fine_method": method},
                                                 "r.las", ["a.las"], tmp_path)
        assert kwargs["extra_arguments"] == expected, method


# --------------------------------------------------------------------------- #
# Real module: API version pin and a genuine config for each mode
# --------------------------------------------------------------------------- #


@real_project
def test_project_api_version_is_pinned() -> None:
    import ricp_project

    assert ricp_project.PROJECT_API_VERSION == adapter.PROJECT_API_VERSION_EXPECTED == "0.3.0"


@real_project
@pytest.mark.parametrize("mode", ["independent", "multiway"])
def test_each_mode_builds_a_real_config_that_validates(tmp_path: Path, mode: str) -> None:
    import ricp_project

    ref, a1, a2 = tmp_path / "REF.las", tmp_path / "s1.las", tmp_path / "s2.las"
    for p in (ref, a1, a2):
        p.write_bytes(b"x")
    params = {**defaults(), "mode": mode, "overlap_edges": [[0, 1], [1, 2], [2, 0]]}
    kwargs, _ = adapter.build_project_kwargs(params, str(ref), [str(a1), str(a2)], tmp_path / "run")
    config = ricp_project.RegistrationProjectConfig(**kwargs)
    config.validate()                                        # the engine accepts it as-is
    assert config.coarse_review == "always"
    assert config.fine_method == "local-plane"
    expected_edges = (() if mode == "independent"
                      else (ricp_project.RegistrationEdge(0, 1), ricp_project.RegistrationEdge(1, 2),
                            ricp_project.RegistrationEdge(2, 0)))
    if mode == "independent":
        assert config.edges() == (ricp_project.RegistrationEdge(0, 1), ricp_project.RegistrationEdge(0, 2))
    else:
        assert config.edges() == expected_edges


@real_project
def test_the_real_engine_rejects_never_for_auto_coarse(tmp_path: Path) -> None:
    """Why the pin matters: the engine refuses auto coarse without review."""
    import ricp_project

    ref, a1 = tmp_path / "REF.las", tmp_path / "s1.las"
    ref.write_bytes(b"x"); a1.write_bytes(b"x")
    kwargs, _ = adapter.build_project_kwargs(defaults(), str(ref), [str(a1)], tmp_path / "run")
    bad = ricp_project.RegistrationProjectConfig(**{**kwargs, "coarse_review": "never"})
    with pytest.raises(ricp_project.RICPConfigurationError, match="coarse_review='always'"):
        bad.validate()


# --------------------------------------------------------------------------- #
# Stub project engine: statuses, outputs, record
# --------------------------------------------------------------------------- #


class StubConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class StubEdge:
    fixed: int
    moving: int


@dataclass(frozen=True)
class StubProjectConfig:
    reference: str
    aligns: list
    output_directory: str
    mode: str
    fine_method: str
    overlap_edges: list = field(default_factory=list)
    stability_seeds: tuple = (0, 1, 2)
    seed: int = 0
    reference_precision_mm: float = 0.0
    align_precision_mm: float = 0.0
    align_precisions_mm: object = None
    registration_uncertainty_mm: object = None
    coarse_mode: str = "auto"
    coarse_review: str = "always"
    accept_poor_coarse: bool = False
    fit_tilt: bool = True
    target_points: object = "auto"
    max_registration_points: int = 1_500_000
    max_evaluation_points: int = 500_000
    dense_report_points: object = "auto"
    overlap: object = "auto"
    report_thresholds_mm: str = "auto"
    extra_arguments: tuple = ()
    continue_on_error: bool = True
    stable_validation_manifest: object = None

    def validate(self) -> None:
        if self.fine_method == "all":
            raise StubConfigurationError("fine_method='all' is diagnostic-only")


@dataclass(frozen=True)
class StubMethod:
    observability_complete: object = True
    observable_rank: int = 6
    required_observable_rank: int = 6
    scaled_information_condition: float = 1.0
    fitting_tolerance_m: float = 0.01
    fitting_tolerance_is_registration_uncertainty: bool = False


@dataclass(frozen=True)
class StubRegistration:
    status: str
    methods: dict


@dataclass(frozen=True)
class StubPair:
    edge_number: int
    fixed_index: int
    moving_index: int
    registration: StubRegistration
    transform: object = "T"


@dataclass(frozen=True)
class StubScan:
    scan_index: int
    path: Path
    status: str
    transform_path: object
    registered_cloud_path: object
    uncertainty_status: str
    registration_uncertainty_1sigma_m: object = None
    global_transform: object = "T"


@dataclass(frozen=True)
class StubProjectResult:
    status: str
    mode: str
    project_directory: Path
    fine_method: str
    pairs: tuple
    scans: tuple
    artifacts: dict
    stable_validation_status: str = "not-requested"
    error_message: object = None

    def as_dict(self) -> dict:
        return {"status": self.status, "project_directory": str(self.project_directory),
                "scans": [s.scan_index for s in self.scans]}


@pytest.fixture()
def stub(monkeypatch):
    mod = types.ModuleType("ricp_project")
    mod.PROJECT_API_VERSION = "0.3.0"
    mod.RegistrationProjectConfig = StubProjectConfig
    mod.RegistrationEdge = StubEdge
    mod.RICPConfigurationError = StubConfigurationError
    mod.calls = []
    mod.next_result = None
    mod.progress = ["R-ICP MULTI-CLOUD PROJECT", "[pair 1/2; 0 <- 1] COMPLETED"]

    def run_registration_project(config, on_progress=None):
        mod.calls.append((config, on_progress))
        for line in mod.progress:
            on_progress(line)
        return mod.next_result

    mod.run_registration_project = run_registration_project
    monkeypatch.setitem(sys.modules, "ricp_project", mod)
    return mod


def fabricate_project(run_dir: Path, *, mode="multiway", statuses=("registered", "registered"),
                      suspect=False, transform_only=()) -> StubProjectResult:
    project = run_dir / "run_20260921_120000"
    (project / "global_transforms").mkdir(parents=True)
    (project / "registered").mkdir()
    artifacts: dict = {}
    for key, name in (("project_summary", "project_summary.json"),
                      ("project_summary_text", "project_summary.txt"),
                      ("project_summary_csv", "project_summary.csv"),
                      ("outputs", "outputs.json"),
                      ("project_metadata", "project_metadata.json")):
        (project / name).write_text("{}", encoding="utf-8")
        artifacts[key] = project / name
    rows = [{"edge_number": 1, "fixed_index": 0, "moving_index": 1,
             "postfit_p95_point_displacement_m": 0.0042, "postfit_site_error_m": 0.9,
             "consistency_metric": "p95-transform-displacement",
             "consistency": "SUSPECT" if suspect else "OK"}]
    if mode == "multiway":
        (project / "pose_graph_edges.json").write_text(json.dumps(rows), encoding="utf-8")
        (project / "pose_graph_edges.csv").write_text("edge_number\n1\n", encoding="utf-8")
        artifacts["pose_graph_edges"] = project / "pose_graph_edges.json"
        artifacts["pose_graph_edges_csv"] = project / "pose_graph_edges.csv"
    scans = [StubScan(0, Path("REF.las"), "fixed-reference", project / "global_transforms" / "scan_000_reference.txt",
                      None, "fixed-reference", 0.0)]
    (project / "global_transforms" / "scan_000_reference.txt").write_text("I", encoding="utf-8")
    for i, status in enumerate(statuses, 1):
        tpath = cpath = None
        if status != "not-registered":
            tpath = project / "global_transforms" / "scan_{0:03d}_s_to_reference.txt".format(i)
            tpath.write_text("T", encoding="utf-8")
            if i not in transform_only:
                cpath = project / "registered" / "registered_ali_{0}.las".format(i)
                cpath.write_bytes(b"las")
        scans.append(StubScan(
            i, Path("s{0}.las".format(i)), status if cpath or status == "not-registered" else "transform-only",
            tpath, cpath,
            "unavailable-multiway-covariance" if mode == "multiway" else "direct-pair-estimate",
            None if mode == "multiway" else 0.0021,
            "T" if tpath else None))
    pairs = tuple(StubPair(i, 0, i, StubRegistration("completed", {"local-plane": StubMethod()}),
                           transform=("T" if s != "not-registered" else None))
                  for i, s in enumerate(statuses, 1))
    n_ok = sum(1 for s in statuses if s != "not-registered")
    status = "completed" if n_ok == len(statuses) and not suspect else "partial"
    return StubProjectResult(status, mode, project, "local-plane", pairs, tuple(scans), artifacts,
                             error_message=None if status == "completed" else "pair 2 failed")


def run_project_main(tmp_path: Path, stub, result, **params) -> tuple[int, Path]:
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    (run_dir / "manifest.json").write_text(json.dumps({"engine": "ricp", "exit_code": None}), encoding="utf-8")
    ref, a1, a2 = tmp_path / "REF.las", tmp_path / "s1.las", tmp_path / "s2.las"
    for p in (ref, a1, a2):
        p.write_bytes(b"x")
    stub.next_result = result
    params_file = tmp_path / "params.json"
    params_file.write_text(json.dumps({**defaults(), "mode": "multiway",
                                       "overlap_edges": [[0, 1], [1, 2], [2, 0]], **params}), encoding="utf-8")
    rc = adapter.main(["register_project", "--params", str(params_file), "--out", str(run_dir),
                       "--reference=" + str(ref), "--align=", "--coarse-artifact=", "--project=",
                       "--manifest=", "--aligns", str(a1), str(a2)])
    return rc, run_dir


def test_completed_project_registers_everything(tmp_path: Path, stub, capsys) -> None:
    result = fabricate_project(tmp_path / "run")
    rc, run_dir = run_project_main(tmp_path, stub, result)
    assert rc == 0
    outputs = json.loads((run_dir / "outputs.json").read_text(encoding="utf-8"))
    stamp = "run_20260921_120000"
    assert outputs["registered_scan1"] == [stamp + "/registered/registered_ali_1.las"]
    assert outputs["registered_scan2"] == [stamp + "/registered/registered_ali_2.las"]
    assert outputs["transform_scan1"] == [stamp + "/global_transforms/scan_001_s_to_reference.txt"]
    assert outputs["project_summary"] == [stamp + "/project_summary.json", stamp + "/project_summary.txt",
                                          stamp + "/project_summary.csv"]
    assert outputs["pose_graph_edges"] == [stamp + "/pose_graph_edges.csv", stamp + "/pose_graph_edges.json"]
    assert outputs["engine_outputs"] == [stamp + "/outputs.json"]      # the ENGINE's, nested
    assert outputs["project_result"] == ["ricp_project_result.json"]  # ours, at the root
    assert "registered_scan0" not in outputs and "transform_scan0" not in outputs

    record = json.loads((run_dir / "ricp_project_result.json").read_text(encoding="utf-8"))
    assert record["project_status"] == "completed"
    assert record["config"]["coarse_review"] == "always"
    assert json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["project_status"] == "completed"

    (config, callback), = stub.calls
    assert config.coarse_review == "always" and config.mode == "multiway"
    out = capsys.readouterr().out
    assert "=== PROJECT COMPLETED - 2 of 2 pairs succeeded ===" in out
    assert "[pair 1/2; 0 <- 1] COMPLETED" in out                       # progress streamed
    assert "95th-percentile transform disagreement 4.200 mm" in out
    assert "unavailable-multiway-covariance" in out                     # the sentence...
    assert "0.000 mm" not in out and "(0.0" not in out                  # ...never a number, never zero
    assert "postfit_site_error" not in out


def test_partial_project_exits_zero_with_an_unmistakable_banner(tmp_path: Path, stub, capsys) -> None:
    result = fabricate_project(tmp_path / "run", statuses=("registered", "not-registered"))
    rc, run_dir = run_project_main(tmp_path, stub, result)
    assert rc == 0
    outputs = json.loads((run_dir / "outputs.json").read_text(encoding="utf-8"))
    assert "registered_scan1" in outputs and "registered_scan2" not in outputs
    assert json.loads((run_dir / "ricp_project_result.json").read_text(encoding="utf-8"))["project_status"] == "partial"
    assert json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["project_status"] == "partial"
    out = capsys.readouterr().out
    assert "=== PROJECT PARTIAL - 1 of 2 pairs succeeded ===" in out
    assert "PROJECT COMPLETED" not in out
    assert not (run_dir / "adapter_error.txt").exists()


def test_suspect_edge_wording(tmp_path: Path, stub, capsys) -> None:
    result = fabricate_project(tmp_path / "run", suspect=True)
    rc, _ = run_project_main(tmp_path, stub, result)
    assert rc == 0                                                      # engine says partial
    out = capsys.readouterr().out
    assert "SUSPECT = unresolved loop disagreement, not proven pairwise failure" in out


def test_transform_only_scan_registers_its_transform(tmp_path: Path, stub, capsys) -> None:
    result = fabricate_project(tmp_path / "run", mode="independent", transform_only=(2,))
    rc, run_dir = run_project_main(tmp_path, stub, result, mode="independent")
    assert rc == 0
    outputs = json.loads((run_dir / "outputs.json").read_text(encoding="utf-8"))
    assert "transform_scan2" in outputs and "registered_scan2" not in outputs
    assert "registered_scan1" in outputs
    assert "pose_graph_edges" not in outputs                            # independent: no graph
    out = capsys.readouterr().out
    assert "scan 2 (s2.las) is transform-only" in out
    assert "direct-pair-estimate (2.100 mm, direct pair, 1-sigma)" in out   # independent may show the number


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_failed_and_cancelled_exit_nonzero_and_register_nothing(tmp_path: Path, stub, status: str) -> None:
    good = fabricate_project(tmp_path / "run")
    result = StubProjectResult(status, good.mode, good.project_directory, good.fine_method, good.pairs,
                               good.scans, good.artifacts, error_message="operator cancelled pair 1")
    rc, run_dir = run_project_main(tmp_path, stub, result)
    assert rc == 1
    assert not (run_dir / "outputs.json").exists()
    error = (run_dir / "adapter_error.txt").read_text(encoding="utf-8")
    assert status in error and "operator cancelled pair 1" in error and "finished pairs remain" in error
    assert json.loads((run_dir / "ricp_project_result.json").read_text(encoding="utf-8"))["project_status"] == status


def test_observability_warning_is_printed_and_recorded(tmp_path: Path, stub, capsys) -> None:
    good = fabricate_project(tmp_path / "run")
    weak = StubPair(1, 0, 1, StubRegistration("completed", {"local-plane": StubMethod(
        observability_complete=False, observable_rank=5)}))
    result = StubProjectResult(good.status, good.mode, good.project_directory, good.fine_method,
                               (weak,) + good.pairs[1:], good.scans, good.artifacts)
    rc, run_dir = run_project_main(tmp_path, stub, result)
    assert rc == 0
    out = capsys.readouterr().out
    assert "WARNING: pair 1 [0 <- 1] method local-plane: observability incomplete (rank 5 of 6)" in out
    record = json.loads((run_dir / "ricp_project_result.json").read_text(encoding="utf-8"))
    entry = record["observability"][0]
    assert entry["observability_complete"] is False
    assert "fitting_tolerance_m" in entry["fitting_diagnostics"]      # under diagnostics, never uncertainty


def test_a_bad_graph_never_reaches_the_engine(tmp_path: Path, stub) -> None:
    rc, run_dir = run_project_main(tmp_path, stub, None, overlap_edges=[[0, 1], [0, 1]])
    assert rc == 2 and stub.calls == []
    assert "connected twice" in (run_dir / "adapter_error.txt").read_text(encoding="utf-8")


def test_laz_inputs_get_index_prefixed_copies(tmp_path: Path, stub, monkeypatch) -> None:
    import laspy
    import numpy as np

    def laz(path: Path) -> Path:
        las = laspy.LasData(laspy.LasHeader(point_format=3, version="1.4"))
        las.x = np.array([1.0]); las.y = np.array([2.0]); las.z = np.array([3.0])
        las.write(str(path)); return path
    run_dir = tmp_path / "run"; run_dir.mkdir()
    a = laz(tmp_path / "d1" / "scan.laz") if (tmp_path / "d1").mkdir() is None else None
    b = laz(tmp_path / "d2" / "scan.laz") if (tmp_path / "d2").mkdir() is None else None
    ref = tmp_path / "REF.las"; ref.write_bytes(b"x")
    stub.next_result = fabricate_project(run_dir)
    params_file = tmp_path / "params.json"
    params_file.write_text(json.dumps({**defaults(), "mode": "independent"}), encoding="utf-8")
    adapter.main(["register_project", "--params", str(params_file), "--out", str(run_dir),
                  "--reference=" + str(ref), "--aligns", str(a), str(b)])
    (config, _), = stub.calls
    assert [Path(p).name for p in config.aligns] == ["scan01_scan.las", "scan02_scan.las"]  # no collision


# --------------------------------------------------------------------------- #
# validate_stable_areas against a stub validator
# --------------------------------------------------------------------------- #


@pytest.fixture()
def stub_validation(monkeypatch, tmp_path: Path):
    mod = types.ModuleType("ricp_project_validation")
    mod.RICPConfigurationError = StubConfigurationError
    mod.calls = []

    def validate_registration_project(project_directory, manifest):
        mod.calls.append((Path(project_directory), Path(manifest)))
        out = Path(project_directory) / "stable_validation" / "run_20260921_130000"
        (out / "maps").mkdir(parents=True)
        files = {}
        for key, name, text in (("stable_validation", "stable_validation.json", '{"status": "evaluated"}'),
                                ("stable_validation_text", "stable_validation.txt", "ok"),
                                ("stable_validation_csv", "stable_validation.csv", "a,b\n"),
                                ("stable_validation_manifest", "manifest_resolved.json", "{}")):
            (out / name).write_text(text, encoding="utf-8"); files[key] = out / name
        (out / "maps" / "north_wall.ply").write_bytes(b"ply")
        return files

    mod.validate_registration_project = validate_registration_project
    monkeypatch.setitem(sys.modules, "ricp_project_validation", mod)
    return mod


def _old_project(tmp_path: Path) -> tuple[Path, Path]:
    old_run = tmp_path / "old_run"
    project = old_run / "run_20260921_120000"
    project.mkdir(parents=True)
    (project / "project_summary.json").write_text("{}", encoding="utf-8")
    (project / "project_metadata.json").write_text("{}", encoding="utf-8")
    (old_run / "ricp_project_result.json").write_text(
        json.dumps({"engine": {"project_directory": str(project)}}), encoding="utf-8")
    return old_run, project


def test_project_directory_is_found_from_any_project_artifact(tmp_path: Path) -> None:
    old_run, project = _old_project(tmp_path)
    assert adapter.project_directory_from(str(project / "project_summary.json")) == project.resolve()
    assert adapter.project_directory_from(str(project)) == project.resolve()
    assert adapter.project_directory_from(str(old_run / "ricp_project_result.json")) == project
    with pytest.raises(adapter.AdapterError, match="not inside an R-ICP project folder"):
        adapter.project_directory_from(str(tmp_path / "REF.las"))
    with pytest.raises(adapter.AdapterError, match="pick the previous project"):
        adapter.project_directory_from("")


def test_validation_end_to_end_copies_reports_and_registers(tmp_path: Path, stub_validation, capsys) -> None:
    old_run, project = _old_project(tmp_path)
    manifest = tmp_path / "stable_areas.json"
    manifest.write_text("{}", encoding="utf-8")
    run_dir = tmp_path / "vrun"; run_dir.mkdir()
    params_file = tmp_path / "p.json"; params_file.write_text(json.dumps({}), encoding="utf-8")

    rc = adapter.main(["validate_stable_areas", "--params", str(params_file), "--out", str(run_dir),
                       "--project=" + str(project / "project_summary.json"), "--manifest=" + str(manifest)])
    assert rc == 0
    (called_dir, called_manifest), = stub_validation.calls
    assert called_dir == project.resolve() and called_manifest == manifest
    outputs = json.loads((run_dir / "outputs.json").read_text(encoding="utf-8"))
    assert outputs == {
        "stable_validation": ["stable_validation.json", "stable_validation.txt", "stable_validation_source.txt"],
        "stable_validation_table": ["stable_validation.csv"],
    }
    for name in outputs["stable_validation"] + outputs["stable_validation_table"]:
        assert (run_dir / name).is_file()                                # copies, inside OUR run
    assert (project / "stable_validation" / "run_20260921_130000" / "maps" / "north_wall.ply").is_file()  # untouched
    note = (run_dir / "stable_validation_source.txt").read_text(encoding="utf-8")
    assert str(project / "stable_validation" / "run_20260921_130000") in note
    assert "not absolute registration accuracy" in note
    out = capsys.readouterr().out
    assert "NOT absolute registration accuracy" in out
    assert "status: evaluated" in out


def test_validation_needs_a_manifest(tmp_path: Path, stub_validation) -> None:
    _, project = _old_project(tmp_path)
    run_dir = tmp_path / "vrun"; run_dir.mkdir()
    params_file = tmp_path / "p.json"; params_file.write_text("{}", encoding="utf-8")
    rc = adapter.main(["validate_stable_areas", "--params", str(params_file), "--out", str(run_dir),
                       "--project=" + str(project), "--manifest="])
    assert rc == 2 and stub_validation.calls == []
    assert "stable_areas.json" in (run_dir / "adapter_error.txt").read_text(encoding="utf-8")


def test_the_engines_refusal_is_reported_not_crashed(tmp_path: Path, stub_validation) -> None:
    _, project = _old_project(tmp_path)
    manifest = tmp_path / "m.json"; manifest.write_text("{}", encoding="utf-8")

    def refuse(project_directory, manifest):
        raise StubConfigurationError("stable area 'north' core cloud not found")
    stub_validation.validate_registration_project = refuse
    run_dir = tmp_path / "vrun"; run_dir.mkdir()
    params_file = tmp_path / "p.json"; params_file.write_text("{}", encoding="utf-8")
    rc = adapter.main(["validate_stable_areas", "--params", str(params_file), "--out", str(run_dir),
                       "--project=" + str(project), "--manifest=" + str(manifest)])
    assert rc == 2
    assert "core cloud not found" in (run_dir / "adapter_error.txt").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# The command template renders for every action; ../ricp untouched
# --------------------------------------------------------------------------- #


def test_the_shared_template_renders_for_all_three_actions(tmp_path: Path) -> None:
    from lithocloud.core import render_argv

    engine = load_manifest(ENGINE_DIR)
    argv = render_argv(engine, "register_project", python="py", run_dir="r", params_file="p",
                       inputs={"reference": "REF.las", "aligns": ["a 1.las", "a2.las"]})
    assert argv[-3:] == ["--aligns", "a 1.las", "a2.las"]               # one token per file
    assert "--align=" in argv and "--project=" in argv                  # undeclared inputs render empty
    single = render_argv(engine, "register", python="py", run_dir="r", params_file="p",
                         inputs={"reference": "r", "align": "a"})
    assert single[-1] == "--aligns" and "--align=a" in single           # bare flag takes zero values
    val = render_argv(engine, "validate_stable_areas", python="py", run_dir="r", params_file="p",
                      inputs={"project": "s.json", "manifest": "m.json"})
    assert "--project=s.json" in val and "--manifest=m.json" in val


@pytest.mark.skipif(not (RICP_REPO / ".git").exists(), reason="../ricp/ricp is not a git checkout")
def test_nothing_under_ricp_was_modified() -> None:
    out = subprocess.run(["git", "-C", str(RICP_REPO), "status", "--porcelain", "--untracked-files=no"],
                         capture_output=True, text=True, check=True).stdout
    assert out.strip() == "", "tracked files changed under ../ricp:\n" + out
