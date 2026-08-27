"""tlsphoto engine: manifest, params files, and the adapter's command building.

No cloud data needed - command building is a pure function. The one
end-to-end test generates its own three-point text file and runs the real
tlsphoto ingest through the adapter.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from lithocloud.core import discover_engines, load_manifest, load_params

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = REPO_ROOT / "engines" / "tlsphoto"


def _load_adapter():
    spec = importlib.util.spec_from_file_location(
        "tlsphoto_adapter", ENGINE_DIR / "adapter.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = _load_adapter()


@pytest.fixture()
def engine():
    return load_manifest(ENGINE_DIR)


def defaults_for(action: str) -> dict:
    """The form defaults for one action - exactly what the shell would send."""
    engine = load_manifest(ENGINE_DIR)
    spec = load_params(engine.params_path(action))
    return spec.defaults()


# --------------------------------------------------------------------------- #
# Manifest + params files
# --------------------------------------------------------------------------- #


def test_the_engine_is_discovered(engine) -> None:
    engines, problems = discover_engines(REPO_ROOT)
    assert problems == []
    assert "tlsphoto" in [e.id for e in engines]


def test_actions_match_the_spec(engine) -> None:
    assert engine.action_ids == (
        "ingest",
        "register",
        "fuse",
        "compare",
        "split",
        "export",
        "info",
    )
    assert engine.version == "0.5.6"
    assert not any(a.interactive for a in engine.actions)  # verified: none are


def test_every_params_file_loads_and_forms_would_build(engine) -> None:
    for action in engine.actions:
        spec = load_params(engine.params_path(action))
        assert spec.validate(spec.defaults()) == spec.defaults()


def test_cli_defaults_are_transcribed_faithfully() -> None:
    """Spot-check the values Mohammad chose to keep at CLI defaults."""
    fuse = defaults_for("fuse")
    assert fuse["mode"] == "uniform"
    assert fuse["tolerance"] == ""      # CLI default None = from registration QA
    assert fuse["q_max"] == 0.1
    assert fuse["axial_max_deg"] == 30.0
    assert fuse["cell"] == 0.02

    register = defaults_for("register")
    assert register["sample_voxel"] == 0.05
    assert register["corr_factor"] == 3.0
    assert register["qa_threshold"] == 0.1
    assert register["workers"] == -1

    ingest = defaults_for("ingest")
    assert ingest["chunk_size"] == 2000000
    assert ingest["scale"] == 0.001
    assert ingest["extra_dtype"] == "float32"


def test_calibrated_values_are_documented_not_defaulted(engine) -> None:
    spec = load_params(engine.params_path("fuse"))
    assert "max_tls" in spec.field("mode").help
    assert "0.05" in spec.field("tolerance").help
    assert "0.20" in spec.field("q_max").help
    assert "50.0" in spec.field("axial_max_deg").help


# --------------------------------------------------------------------------- #
# Command building (string-compare per the acceptance criteria)
# --------------------------------------------------------------------------- #


def test_ingest_command_matches_a_hand_written_one(tmp_path: Path) -> None:
    params = {
        **defaults_for("ingest"),
        "in_files": r"D:\raw\scan one.pts;D:\raw\scan two.pts",
        "role": "tls",
        "scanners": r"D:\raw\scanners.csv",
    }
    argv = adapter.build_cli_argv("ingest", params, {}, tmp_path)

    hand_written = [
        "ingest",
        "--role", "tls",
        "--in", r"D:\raw\scan one.pts", r"D:\raw\scan two.pts",
        "--out", str(tmp_path / "canonical.laz"),
        "--scanners", r"D:\raw\scanners.csv",
        "--scanid-offset", "0",
        "--chunk-size", "2000000",
        "--scale", "0.001",
        "--extra-dtype", "float32",
    ]
    assert argv == hand_written
    # the spaced path is ONE argument, not two
    assert r"D:\raw\scan one.pts" in argv


def test_ingest_columns_and_encodings(tmp_path: Path) -> None:
    params = {
        **defaults_for("ingest"),
        "in_files": "cloud.txt",
        "columns": "X Y Z Intensity R G B",
        "map": "Reflectance=Intensity Sf1=skip",
        "scan_ids": "3 7",
        "rgb_encoding": "8bit",
        "intensity_encoding": "pts",
        "drop_unknown": True,
        "dry_run": True,
    }
    argv = adapter.build_cli_argv("ingest", params, {}, tmp_path)

    joined = " ".join(argv)
    assert "--columns X Y Z Intensity R G B" in joined
    assert "--map Reflectance=Intensity Sf1=skip" in joined
    assert "--scan-ids 3 7" in joined
    assert "--rgb-encoding 8bit" in joined
    assert "--intensity-encoding pts" in joined
    assert "--drop-unknown" in joined
    assert "--dry-run" in joined


def test_ingest_auto_encodings_are_not_passed(tmp_path: Path) -> None:
    params = {**defaults_for("ingest"), "in_files": "a.las"}
    argv = adapter.build_cli_argv("ingest", params, {}, tmp_path)
    assert "--rgb-encoding" not in argv
    assert "--intensity-encoding" not in argv
    assert "--columns" not in argv
    assert "--crs" not in argv


def test_ingest_requires_in_files(tmp_path: Path) -> None:
    with pytest.raises(adapter.AdapterError, match="in_files"):
        adapter.build_cli_argv("ingest", defaults_for("ingest"), {}, tmp_path)


def test_register_command_matches_a_hand_written_one(tmp_path: Path) -> None:
    params = {
        **defaults_for("register"),
        "pairs_tls": r"D:\picks\tls_picks.txt",
        "pairs_photo": r"D:\picks\photo_picks.txt",
        "holdout": 2,
    }
    inputs = {"tls": r"D:\proj\runs\a\tls.laz", "photo": r"D:\proj\runs\b\photo.laz"}
    argv = adapter.build_cli_argv("register", params, inputs, tmp_path)

    hand_written = [
        "register",
        "--tls", r"D:\proj\runs\a\tls.laz",
        "--photo", r"D:\proj\runs\b\photo.laz",
        "--out-dir", str(tmp_path),
        "--pairs", r"D:\picks\tls_picks.txt", r"D:\picks\photo_picks.txt",
        "--holdout", "2",
        "--auto-voxel", "0.5",
        "--topview-cell", "0.25",
        "--sample-voxel", "0.05",
        "--max-sample", "8000000",
        "--max-points", "2000000",
        "--coarse-voxel", "0.5",
        "--corr-factor", "3.0",
        "--qa-threshold", "0.1",
        "--chunk-size", "2000000",
        "--workers", "-1",
    ]
    assert argv == hand_written


def test_register_optional_blocks(tmp_path: Path) -> None:
    params = {
        **defaults_for("register"),
        "init": "identity",
        "topview": True,
        "yaw_hint": "40 30",
        "levels": "0.5 0.2 0.1 0.05",
        "shift_tls": "1000 2000 0",
        "no_icp": True,
        "no_apply": True,
    }
    inputs = {"tls": "t.laz", "photo": "p.laz"}
    joined = " ".join(adapter.build_cli_argv("register", params, inputs, tmp_path))

    assert "--init identity" in joined
    assert "--topview " in joined or joined.endswith("--topview")
    assert "--yaw-hint 40 30" in joined
    assert "--levels 0.5 0.2 0.1 0.05" in joined
    assert "--shift-tls 1000 2000 0" in joined
    assert "--no-icp" in joined
    assert "--no-apply" in joined
    assert "--pairs" not in joined
    assert "--check" not in joined


def test_register_rejects_half_a_pair(tmp_path: Path) -> None:
    params = {**defaults_for("register"), "pairs_tls": "only_one.txt"}
    with pytest.raises(adapter.AdapterError, match="both files or neither"):
        adapter.build_cli_argv(
            "register", params, {"tls": "t.laz", "photo": "p.laz"}, tmp_path
        )


def test_register_requires_both_clouds(tmp_path: Path) -> None:
    with pytest.raises(adapter.AdapterError, match="'photo' is required"):
        adapter.build_cli_argv(
            "register", defaults_for("register"), {"tls": "t.laz"}, tmp_path
        )


def test_register_rejects_a_bad_shift(tmp_path: Path) -> None:
    params = {**defaults_for("register"), "shift_tls": "1 2"}
    with pytest.raises(adapter.AdapterError, match="three numbers"):
        adapter.build_cli_argv(
            "register", params, {"tls": "t.laz", "photo": "p.laz"}, tmp_path
        )


def test_fuse_command_matches_a_hand_written_one(tmp_path: Path) -> None:
    params = {**defaults_for("fuse")}
    inputs = {"tls": "reg.laz", "photo": "photo.laz"}
    argv = adapter.build_cli_argv("fuse", params, inputs, tmp_path)

    hand_written = [
        "fuse",
        "--tls", "reg.laz",
        "--photo", "photo.laz",
        "--out-dir", str(tmp_path),
        "--cell", "0.02",
        "--mode", "uniform",
        "--support-radius", "0.12",
        "--surface-radius", "0.12",
        "--rep-nmin", "8",
        "--q-max", "0.1",
        "--products", "layers",
        "--axial-max-deg", "30.0",
        "--rgb-dist", "0.15",
        "--chunk-size", "2000000",
        "--workers", "-1",
    ]
    assert argv == hand_written
    assert "--tolerance" not in argv  # empty = from registration QA


def test_fuse_with_mohammads_calibrated_values(tmp_path: Path) -> None:
    params = {
        **defaults_for("fuse"),
        "mode": "max_tls",
        "tolerance": "0.05",
        "q_max": 0.2,
        "axial_max_deg": 50.0,
    }
    joined = " ".join(
        adapter.build_cli_argv("fuse", params, {"tls": "t", "photo": "p"}, tmp_path)
    )
    assert "--mode max_tls" in joined
    assert "--tolerance 0.05" in joined
    assert "--q-max 0.2" in joined
    assert "--axial-max-deg 50.0" in joined


def test_fuse_rejects_a_non_numeric_tolerance(tmp_path: Path) -> None:
    params = {**defaults_for("fuse"), "tolerance": "auto"}
    with pytest.raises(adapter.AdapterError, match="not a number"):
        adapter.build_cli_argv("fuse", params, {"tls": "t", "photo": "p"}, tmp_path)


def test_compare_passes_the_folders_of_the_picked_artifacts(tmp_path: Path) -> None:
    inputs = {
        "old": r"D:\proj\runs\2026-01-01_0900_tlsphoto_fuse\tls_colored.laz",
        "new": r"D:\proj\runs\2026-02-01_0900_tlsphoto_fuse\tls_colored.laz",
    }
    argv = adapter.build_cli_argv("compare", defaults_for("compare"), inputs, tmp_path)

    assert argv == [
        "compare",
        "--old", r"D:\proj\runs\2026-01-01_0900_tlsphoto_fuse",
        "--new", r"D:\proj\runs\2026-02-01_0900_tlsphoto_fuse",
        "--out-dir", str(tmp_path),
        "--chunk-size", "2000000",
    ]


def test_split_passes_the_folder(tmp_path: Path) -> None:
    inputs = {"fusedir": r"D:\proj\runs\old_fuse\fused.laz"}
    argv = adapter.build_cli_argv("split", defaults_for("split"), inputs, tmp_path)

    assert argv == [
        "split",
        "--fuse-dir", r"D:\proj\runs\old_fuse",
        "--out-dir", str(tmp_path),
        "--support-radius", "0.12",
    ]


def test_export_command(tmp_path: Path) -> None:
    params = {**defaults_for("export"), "header": "cc", "rgb": "8bit"}
    argv = adapter.build_cli_argv("export", params, {"cloud": "fused.laz"}, tmp_path)

    assert argv == [
        "export",
        "--in", "fused.laz",
        "--out", str(tmp_path / "export.txt"),
        "--delimiter", " ",
        "--precision", "4",
        "--header", "cc",
        "--rgb", "8bit",
        "--chunk-size", "2000000",
    ]


def test_info_command(tmp_path: Path) -> None:
    argv = adapter.build_cli_argv("info", {}, {"cloud": "tls.laz"}, tmp_path)
    assert argv == ["info", "--in", "tls.laz"]


def test_missing_folder_inputs_are_reported(tmp_path: Path) -> None:
    with pytest.raises(adapter.AdapterError, match="no artifact chosen"):
        adapter.build_cli_argv("compare", defaults_for("compare"), {}, tmp_path)


# --------------------------------------------------------------------------- #
# outputs.json collection
# --------------------------------------------------------------------------- #


def touch(folder: Path, *names: str) -> None:
    for name in names:
        (folder / name).write_text("x", encoding="utf-8")


def test_collect_outputs_ingest(tmp_path: Path) -> None:
    touch(tmp_path, "canonical.laz", "canonical.laz.json")
    outputs = adapter.collect_outputs(
        "ingest", {"out_name": "canonical.laz"}, {}, tmp_path
    )
    assert outputs == {"canonical": ["canonical.laz", "canonical.laz.json"]}


def test_collect_outputs_ingest_dry_run_produced_nothing(tmp_path: Path) -> None:
    outputs = adapter.collect_outputs(
        "ingest", {"out_name": "canonical.laz"}, {}, tmp_path
    )
    assert outputs == {}  # shell will warn 'canonical missing' - correct


def test_collect_outputs_register(tmp_path: Path) -> None:
    touch(
        tmp_path,
        "tls_registered.laz",
        "tls_registered.laz.json",
        "transform.json",
        "transform_tls_to_photo.txt",
        "registration_report.txt",
        "qa_tls_sample.laz",
    )
    outputs = adapter.collect_outputs(
        "register", {}, {"tls": r"D:\somewhere\tls.laz"}, tmp_path
    )
    assert outputs == {
        "registered": ["tls_registered.laz", "tls_registered.laz.json"],
        "transform": ["transform.json", "transform_tls_to_photo.txt"],
        "report": ["registration_report.txt"],
    }


def test_collect_outputs_register_no_apply(tmp_path: Path) -> None:
    touch(tmp_path, "transform.json", "transform_tls_to_photo.txt",
          "registration_report.txt")
    outputs = adapter.collect_outputs(
        "register", {}, {"tls": "tls.laz"}, tmp_path
    )
    assert "registered" not in outputs
    assert outputs["transform"] == ["transform.json", "transform_tls_to_photo.txt"]


def test_collect_outputs_fuse(tmp_path: Path) -> None:
    touch(
        tmp_path,
        "tls_colored.laz",
        "tls_colored.laz.json",
        "photo_surface_consistent.laz",
        "photo_outside_tls_support.laz",
        "photo_ambiguous.laz",
        "fusion_report.txt",
        "fusion.json",
        "photo_rejected.laz",
    )
    outputs = adapter.collect_outputs("fuse", {}, {}, tmp_path)
    assert set(outputs) == {
        "tls_colored",
        "photo_surface_consistent",
        "photo_outside_tls_support",
        "photo_ambiguous",
        "report",
    }
    assert outputs["report"] == ["fusion_report.txt", "fusion.json"]


def test_collect_outputs_compare_with_and_without_transitions(tmp_path: Path) -> None:
    touch(tmp_path, "compare_report.txt")
    assert adapter.collect_outputs("compare", {}, {}, tmp_path) == {
        "report": ["compare_report.txt"]
    }

    touch(tmp_path, "ambiguous_to_consistent.laz", "outside_support_to_ambiguous.laz")
    outputs = adapter.collect_outputs("compare", {}, {}, tmp_path)
    assert outputs["transitions"] == [
        "ambiguous_to_consistent.laz",
        "outside_support_to_ambiguous.laz",
    ]


# --------------------------------------------------------------------------- #
# End-to-end dry proof (the acceptance criterion)
# --------------------------------------------------------------------------- #


def test_ingest_runs_end_to_end_on_a_tiny_generated_sample(tmp_path: Path) -> None:
    """Real tlsphoto, real laspy, three points, through the real adapter CLI."""
    sample = tmp_path / "tiny sample cloud.txt"  # spaces on purpose
    sample.write_text(
        "1.0 2.0 3.0 0.5\n4.0 5.0 6.0 0.6\n7.0 8.0 9.0 0.7\n", encoding="utf-8"
    )
    run_dir = tmp_path / "run dir"
    run_dir.mkdir()

    params = {
        **defaults_for("ingest"),
        "in_files": str(sample),
        "role": "tls",
        "columns": "X Y Z Intensity",
        "units": "m",
    }
    params_file = run_dir / "params.json"
    params_file.write_text(json.dumps(params), encoding="utf-8")

    rc = adapter.main(
        [
            "ingest",
            "--params", str(params_file),
            "--out", str(run_dir),
            "--tls=", "--photo=", "--cloud=", "--old=", "--new=", "--fuse-src=",
        ]
    )

    assert rc == 0
    assert (run_dir / "canonical.laz").is_file()
    assert (run_dir / "canonical.laz.json").is_file()

    outputs = json.loads((run_dir / "outputs.json").read_text(encoding="utf-8"))
    assert outputs == {"canonical": ["canonical.laz", "canonical.laz.json"]}

    # the canonical file really is a 3-point LAZ
    import laspy

    with laspy.open(run_dir / "canonical.laz") as reader:
        assert reader.header.point_count == 3

    # and the tlsphoto manifest records the ingest
    manifest = json.loads((run_dir / "canonical.laz.json").read_text(encoding="utf-8"))
    assert manifest["role"] == "tls"


def test_adapter_error_exits_2_without_invoking_tlsphoto(tmp_path: Path) -> None:
    params_file = tmp_path / "params.json"
    params_file.write_text(json.dumps(defaults_for("ingest")), encoding="utf-8")

    rc = adapter.main(
        ["ingest", "--params", str(params_file), "--out", str(tmp_path)]
    )
    assert rc == 2  # in_files missing
    assert not (tmp_path / "outputs.json").exists()

    # the message is persisted so it survives a closed console window
    error_text = (tmp_path / "adapter_error.txt").read_text(encoding="utf-8")
    assert "in_files" in error_text




# --------------------------------------------------------------------------- #
# Full stack: engine.yaml -> render_argv -> adapter subprocess -> registration
# --------------------------------------------------------------------------- #


def test_ingest_through_the_real_job_runner(qtbot, tmp_path: Path, engine) -> None:
    """The shared command template (with inputs this action does not declare)
    must render, launch the adapter, and register the canonical artifact."""
    from lithocloud.core import scan_project
    from lithocloud.ui.job_runner import JobRequest, JobRunner

    sample = tmp_path / "tiny sample.txt"
    sample.write_text("1 2 3\n4 5 6\n7 8 9\n", encoding="utf-8")
    workspace = tmp_path / "site with spaces"
    workspace.mkdir()

    params = {
        **defaults_for("ingest"),
        "in_files": str(sample),
        "role": "photo",
        "columns": "X Y Z",
        "units": "m",
    }
    runner = JobRunner(workspace)
    results = []
    runner.job_finished.connect(lambda job, code, ok: results.append((job, code, ok)))
    runner.submit(
        JobRequest(engine=engine, action=engine.action("ingest"), params=params)
    )
    qtbot.waitUntil(lambda: len(results) == 1, timeout=120_000)

    job, code, ok = results[0]
    assert ok and code == 0, "ingest failed - see run log"
    assert (job.run_dir / "canonical.laz").is_file()

    artifacts = scan_project(workspace)
    assert len(artifacts) == 1
    assert artifacts[0].type == "pointcloud"
    assert artifacts[0].engine == "tlsphoto"
    assert artifacts[0].engine_version == "0.5.6"
    assert artifacts[0].action == "ingest"
    assert artifacts[0].exists
