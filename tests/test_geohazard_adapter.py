"""geohazard engine: manifest, params, command building, outputs collection.

No real pipeline run here - the acceptance smoke run happens with Mohammad
present. Command building is a pure function, string-compared against
hand-written correct commands.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from rockslope_studio.core import discover_engines, load_manifest, load_params

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = REPO_ROOT / "engines" / "geohazard"


def _load_adapter():
    spec = importlib.util.spec_from_file_location(
        "geohazard_adapter", ENGINE_DIR / "adapter.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = _load_adapter()


@pytest.fixture()
def engine():
    return load_manifest(ENGINE_DIR)


def defaults_for(action: str) -> dict:
    engine = load_manifest(ENGINE_DIR)
    return load_params(engine.params_path(action)).defaults()


# --------------------------------------------------------------------------- #
# Manifest + params
# --------------------------------------------------------------------------- #


def test_the_engine_is_discovered(engine) -> None:
    engines, problems = discover_engines(REPO_ROOT)
    assert problems == []
    assert "geohazard" in [e.id for e in engines]


def test_actions_are_interactive_console_runs(engine) -> None:
    assert engine.action_ids == ("run", "redo_stage")
    assert all(a.interactive for a in engine.actions)  # prompts need a console


def test_every_params_file_loads(engine) -> None:
    for action in engine.actions:
        spec = load_params(engine.params_path(action))
        assert spec.validate(spec.defaults()) == spec.defaults()


def test_config_defaults_are_transcribed_faithfully() -> None:
    """Spot-check against config.py - transcription, not invention."""
    p = defaults_for("run")
    assert p["random_seed"] == 42
    assert p["facets_normal_radius_mult"] == 5.0
    assert p["facets_rg_angle_deg"] == 12.0
    assert p["facets_rg_knn"] == 12
    assert p["facets_rg_min_facet_points"] == 30
    assert p["facets_joint_set_max_k"] == 8
    assert p["facets_joint_set_fixed_k"] == ""       # None in config.py
    assert p["edges_adjacency_tol_mult"] == 2.5
    assert p["edges_min_internormal_angle_deg"] == 12.0
    assert p["edges_min_edge_length_mult"] == 4.0
    assert p["sectors_mode"] == "auto"
    assert p["sectors_max_drift_deg"] == 15.0
    assert p["stereonet_display_friction_deg"] == 30.0
    assert p["stereonet_min_chain_length_m"] == 0.0
    assert p["stereonet_exclude_sets"] == ""         # empty = ask at run time
    assert p["stereonet_length_weighted"] is True
    assert p["stereonet_dpi"] == 300
    assert p["hazard_grid_cell_m"] == 2.0
    assert p["hazard_friction_sweep_deg"] == "25 30 35 40"
    assert p["hazard_toppling_phi_deg"] == 30.0
    assert p["point_density_enabled"] is True
    assert p["point_density_radius_m"] == ""         # None = propose at runtime
    assert p["to_stage"] == "06_hazard"              # CLI --to default


def test_redo_params_add_the_redo_choice(engine) -> None:
    spec = load_params(engine.params_path("redo_stage"))
    assert spec.field("redo").choices == adapter.STAGES
    assert "in_file" not in spec.keys  # a redo never takes a raw file


# --------------------------------------------------------------------------- #
# Config overrides
# --------------------------------------------------------------------------- #


def test_config_overrides_nest_into_pipeline_sections() -> None:
    config = adapter.build_config_overrides(defaults_for("run"))

    assert config["random_seed"] == 42
    assert config["facets"]["normal_radius_mult"] == 5.0
    assert config["facets"]["joint_set_fixed_k"] is None
    assert config["edges"]["adjacency_tol_mult"] == 2.5
    assert config["sectors"]["mode"] == "auto"
    assert config["stereonet"]["display_friction_deg"] == 30.0
    assert config["hazard"]["friction_sweep_deg"] == [25.0, 30.0, 35.0, 40.0]
    assert config["point_density"]["radius_m"] is None


def test_empty_exclude_sets_is_left_out_so_the_pipeline_asks() -> None:
    config = adapter.build_config_overrides(defaults_for("run"))
    assert "exclude_sets" not in config["stereonet"]

    config = adapter.build_config_overrides(
        {**defaults_for("run"), "stereonet_exclude_sets": "-1"}
    )
    assert config["stereonet"]["exclude_sets"] == [-1]

    config = adapter.build_config_overrides(
        {**defaults_for("run"), "stereonet_exclude_sets": "2 5"}
    )
    assert config["stereonet"]["exclude_sets"] == [2, 5]


def test_fixed_k_parses_int_or_none() -> None:
    config = adapter.build_config_overrides(
        {**defaults_for("run"), "facets_joint_set_fixed_k": "4"}
    )
    assert config["facets"]["joint_set_fixed_k"] == 4

    with pytest.raises(adapter.AdapterError, match="whole number"):
        adapter.build_config_overrides(
            {**defaults_for("run"), "facets_joint_set_fixed_k": "four"}
        )


def test_bad_friction_sweep_is_reported() -> None:
    with pytest.raises(adapter.AdapterError, match="not a number"):
        adapter.build_config_overrides(
            {**defaults_for("run"), "hazard_friction_sweep_deg": "25 thirty"}
        )


def test_the_config_round_trips_through_the_real_pipeline_config(tmp_path: Path) -> None:
    """PipelineConfig.from_json must accept what the adapter writes."""
    import sys

    sys.path.insert(0, str(adapter.GEOHAZARD_REPO))
    try:
        from geohazard_pipeline.config import PipelineConfig
    finally:
        sys.path.remove(str(adapter.GEOHAZARD_REPO))

    config = adapter.build_config_overrides(
        {
            **defaults_for("run"),
            "facets_rg_angle_deg": 10.0,
            "stereonet_exclude_sets": "0",
            "hazard_friction_sweep_deg": "20 45",
        }
    )
    path = tmp_path / "config_overrides.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    cfg = PipelineConfig.from_json(path)
    assert cfg.facets.rg_angle_deg == 10.0
    assert cfg.stereonet.exclude_sets == (0,)
    assert cfg.hazard.friction_sweep_deg == (20.0, 45.0)
    assert cfg.random_seed == 42
    # unexposed fields stay at pipeline defaults
    assert cfg.edges.nms_enabled is True
    assert cfg.facets.sliver_planarity_rel == 0.75


# --------------------------------------------------------------------------- #
# Command building (the two acceptance string-compares)
# --------------------------------------------------------------------------- #


def test_fresh_run_to_03_matches_a_hand_written_command(tmp_path: Path) -> None:
    params = {
        **defaults_for("run"),
        "in_file": r"D:\clouds\francon south face.txt",
        "to_stage": "03_facets",
        "tag": "test",
    }
    argv = adapter.build_cli_argv("run", params, {}, tmp_path)

    hand_written = [
        r"D:\clouds\francon south face.txt",
        "--config", str(tmp_path / "config_overrides.json"),
        "--to", "03_facets",
        "--runs-dir", str(tmp_path),
        "--tag", "test",
    ]
    assert argv == hand_written
    assert r"D:\clouds\francon south face.txt" in argv  # spaces intact


def test_resume_redo_05_matches_a_hand_written_command(tmp_path: Path) -> None:
    # fabricate the previous run: studio run folder > native folder > stages
    old_native = tmp_path / "old_studio_run" / "2026-08-20_10-00-00"
    (old_native / "05_stereonet").mkdir(parents=True)
    (old_native / "manifest.json").write_text(
        json.dumps({"input_file": r"D:\clouds\cloud.las"}), encoding="utf-8"
    )
    report_artifact = old_native / "manifest.json"

    new_run = tmp_path / "new_studio_run"
    new_run.mkdir()
    params = {**defaults_for("redo_stage"), "redo": "05_stereonet", "batch_yes": True}
    argv = adapter.build_cli_argv(
        "redo_stage", params, {"previous": str(report_artifact)}, new_run
    )

    hand_written = [
        r"D:\clouds\cloud.las",
        "--config", str(new_run / "config_overrides.json"),
        "--to", "06_hazard",
        "--resume", str(old_native.resolve()),
        "--redo", "05_stereonet",
        "--runs-dir", str(new_run),
        "--yes",
    ]
    assert argv == hand_written


def test_run_requires_exactly_one_input(tmp_path: Path) -> None:
    with pytest.raises(adapter.AdapterError, match="exactly ONE input"):
        adapter.build_cli_argv("run", defaults_for("run"), {}, tmp_path)

    params = {**defaults_for("run"), "in_file": "a.txt"}
    with pytest.raises(adapter.AdapterError, match="exactly ONE input"):
        adapter.build_cli_argv("run", params, {"cloud": "b.laz"}, tmp_path)


def test_run_accepts_a_picked_artifact(tmp_path: Path) -> None:
    argv = adapter.build_cli_argv(
        "run", defaults_for("run"), {"cloud": r"D:\ws\runs\x\canonical.laz"}, tmp_path
    )
    assert argv[0] == r"D:\ws\runs\x\canonical.laz"
    assert "--tag" not in argv     # empty tag not passed
    assert "--yes" not in argv     # batch off by default
    assert "--resume" not in argv


def test_redo_walks_up_to_the_native_folder(tmp_path: Path) -> None:
    """The picked artifact may be deep inside a stage folder."""
    native = tmp_path / "studio_run" / "2026-08-20_10-00-00"
    (native / "03_facets").mkdir(parents=True)
    (native / "manifest.json").write_text(
        json.dumps({"input_file": "cloud.txt"}), encoding="utf-8"
    )
    # the studio run folder above it also has a manifest.json (the studio's own)
    (tmp_path / "studio_run" / "manifest.json").write_text("{}", encoding="utf-8")
    deep_artifact = native / "03_facets" / "facets.csv"
    deep_artifact.write_text("a,b\n", encoding="utf-8")

    assert adapter._native_run_dir_of(str(deep_artifact)) == native.resolve()


def test_redo_rejects_a_file_outside_any_run(tmp_path: Path) -> None:
    stray = tmp_path / "stray.csv"
    stray.write_text("x", encoding="utf-8")
    with pytest.raises(adapter.AdapterError, match="not inside a geohazard run"):
        adapter._native_run_dir_of(str(stray))


def test_redo_reports_a_manifest_without_input_file(tmp_path: Path) -> None:
    native = tmp_path / "2026-08-20_10-00-00"
    (native / "05_stereonet").mkdir(parents=True)
    (native / "manifest.json").write_text("{}", encoding="utf-8")

    params = {**defaults_for("redo_stage")}
    with pytest.raises(adapter.AdapterError, match="no input_file"):
        adapter.build_cli_argv(
            "redo_stage", params, {"previous": str(native / "manifest.json")}, tmp_path
        )


# --------------------------------------------------------------------------- #
# outputs.json collection
# --------------------------------------------------------------------------- #


def make_native(run_dir: Path, *, to_stage: int = 6) -> Path:
    """Fabricate a plausible native run folder up to the given stage."""
    native = run_dir / "2026-08-27_12-00-00"
    native.mkdir(parents=True)
    (native / "manifest.json").write_text("{}", encoding="utf-8")

    def touch(*names: str) -> None:
        for name in names:
            path = native / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")

    if to_stage >= 1:
        touch("01_ingest/spacing.json", "01_ingest/columns.json", "01_ingest/_DONE.json")
    if to_stage >= 3:
        touch(
            "03_facets/facets.csv",
            "03_facets/joint_sets.csv",
            "03_facets/point_attrs.npz",
            "03_facets/_DONE.json",
        )
    if to_stage >= 4:
        touch("04_edges/edges.csv", "04_edges/chains.csv", "04_edges/_DONE.json")
    if to_stage >= 5:
        touch(
            "05_stereonet/stereonet_panels.png",
            "05_stereonet/stereonet_planes.png",
            "05_stereonet/stereonet_panels.pdf",
            "05_stereonet/kinematic_summary.json",
            "05_stereonet/sector_kinematics.csv",
            "05_stereonet/_DONE.json",
        )
    if to_stage >= 6:
        touch(
            "06_hazard/map_face_wedge25.png",
            "06_hazard/map_plan_wedge25.png",
            "06_hazard/grid_cells_face.csv",
            "06_hazard/grid_cells_plan.csv",
            "06_hazard/_DONE.json",
        )
    return native


def test_collect_outputs_full_run(tmp_path: Path) -> None:
    native = make_native(tmp_path)
    outputs = adapter.collect_outputs(tmp_path)
    stamp = native.name

    assert outputs["facets"] == [stamp + "/03_facets/facets.csv"]
    assert outputs["joint_sets"] == [stamp + "/03_facets/joint_sets.csv"]
    assert outputs["edges"] == [
        stamp + "/04_edges/edges.csv",
        stamp + "/04_edges/chains.csv",
    ]
    assert outputs["stereonet_figures"] == [
        stamp + "/05_stereonet/stereonet_panels.png",
        stamp + "/05_stereonet/stereonet_planes.png",
    ]
    assert outputs["kinematics"] == [
        stamp + "/05_stereonet/kinematic_summary.json",
        stamp + "/05_stereonet/sector_kinematics.csv",
    ]
    assert outputs["hazard_maps"] == [
        stamp + "/06_hazard/map_face_wedge25.png",
        stamp + "/06_hazard/map_plan_wedge25.png",
    ]
    assert outputs["hazard_tables"] == [
        stamp + "/06_hazard/grid_cells_face.csv",
        stamp + "/06_hazard/grid_cells_plan.csv",
    ]
    assert outputs["report"] == [stamp + "/manifest.json"]


def test_collect_outputs_partial_run_omits_later_stages(tmp_path: Path) -> None:
    make_native(tmp_path, to_stage=3)
    outputs = adapter.collect_outputs(tmp_path)

    assert "facets" in outputs
    assert "joint_sets" in outputs
    assert "report" in outputs
    assert "edges" not in outputs
    assert "stereonet_figures" not in outputs
    assert "hazard_maps" not in outputs


def test_collect_outputs_without_a_native_folder(tmp_path: Path) -> None:
    assert adapter.collect_outputs(tmp_path) == {}


def test_declared_outputs_match_what_collect_can_produce(engine) -> None:
    """Every key collect_outputs may emit is declared in the manifest."""
    declared = {slot.key for slot in engine.action("run").outputs}
    collectable = {
        "facets",
        "joint_sets",
        "edges",
        "stereonet_figures",
        "kinematics",
        "hazard_maps",
        "hazard_tables",
        "report",
    }
    assert collectable == declared
