"""ricp engine: manifest, params, command building, and the EQUIVALENCE test.

The 'coarse' action re-composes ricp.main()'s code path up to
transform_coarse.txt (approved 2026-08-27). That re-composition is only
trustworthy if it reproduces what ricp.py itself produces, so
test_coarse_only_equals_a_real_ricp_run is the load-bearing test here
(architecture section 11): it runs the REAL ricp.py on a generated cloud and
compares the two transform files byte for byte.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import numpy as np
import pytest

# ricp draws plots at the end of a full run; never open a window in tests.
os.environ.setdefault("MPLBACKEND", "Agg")

from rockslope_studio.core import discover_engines, load_manifest, load_params

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = REPO_ROOT / "engines" / "ricp"


def _load_adapter():
    spec = importlib.util.spec_from_file_location(
        "ricp_adapter", ENGINE_DIR / "adapter.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = _load_adapter()

ricp_available = pytest.mark.skipif(
    not (adapter.RICP_REPO / "ricp.py").is_file(),
    reason="../ricp/ricp/ricp.py not present",
)


@pytest.fixture()
def engine():
    return load_manifest(ENGINE_DIR)


def defaults_for(action: str) -> dict:
    engine = load_manifest(ENGINE_DIR)
    return load_params(engine.params_path(action)).defaults()


def write_cloud(path: Path, *, n: int = 6000, shift=(0.0, 0.0, 0.0), seed: int = 7) -> Path:
    """A rough tilted plane - enough structure for spacing and the tilt fit."""
    rng = np.random.default_rng(seed)
    x = rng.uniform(0.0, 20.0, n)
    y = rng.uniform(0.0, 20.0, n)
    z = 0.10 * x + 0.05 * y + rng.normal(0.0, 0.02, n)
    pts = np.column_stack([x + shift[0], y + shift[1], z + shift[2]])
    np.savetxt(path, pts, fmt="%.6f")
    return path


# --------------------------------------------------------------------------- #
# Manifest + params
# --------------------------------------------------------------------------- #


def test_the_engine_is_discovered(engine) -> None:
    engines, problems = discover_engines(REPO_ROOT)
    assert problems == []
    assert "ricp" in [e.id for e in engines]


def test_the_three_actions(engine) -> None:
    assert engine.action_ids == ("coarse", "register", "register_gui")
    # coarse can open the picking GUI (gui mode, or auto's poor-quality
    # fallback) -> console. register has a matrix, so no GUI is reachable.
    assert engine.action("coarse").interactive is True
    assert engine.action("register").interactive is False
    assert engine.action("register_gui").interactive is True


def test_register_requires_a_coarse_transform(engine) -> None:
    """That requirement is what makes non-interactive safe: with the matrix
    supplied, ricp can never fall back to the GUI and hang."""
    coarse_slot = engine.action("register").input("coarse")
    assert coarse_slot.type == "transform"
    assert coarse_slot.optional is False
    assert "coarse" not in [s.key for s in engine.action("register_gui").inputs]


def test_every_params_file_loads(engine) -> None:
    for action in engine.actions:
        spec = load_params(engine.params_path(action))
        assert spec.validate(spec.defaults()) == spec.defaults()


def test_cli_defaults_are_transcribed_faithfully() -> None:
    """Spot-check against ricp.py's argparse block and DEFAULT_* constants."""
    p = defaults_for("register")
    assert p["ci"] == 95.0                    # DEFAULT_CI
    assert p["max_levels"] == 20              # DEFAULT_MAX_LEVELS
    assert p["target_points"] == "300000"     # DEFAULT_TARGET_POINTS
    assert p["icp_max_iter"] == 60            # DEFAULT_ICP_MAX_ITER
    assert p["icp_method"] == "plane"
    assert p["coarse_mode"] == "auto"
    assert p["max_tilt"] == 10.0
    assert p["overlap"] == "auto"
    assert p["equivalence_margin"] == "auto"
    assert p["sigma_floor"] == 0.02
    assert p["seed"] == 0
    assert p["no_polish"] is False
    assert p["no_tilt_fit"] is False
    assert p["validate_swap"] is False
    assert p["cycle_experiment"] is False
    assert p["swap_max_levels"] == ""         # None
    assert p["cycle_tolerance"] == ""         # None
    assert p["coarse_cell"] == ""             # None


def test_the_deprecated_flag_is_not_exposed(engine) -> None:
    """--no-coarse is a deprecated alias for --coarse-mode none."""
    spec = load_params(engine.params_path("register"))
    assert "no_coarse" not in spec.keys


# --------------------------------------------------------------------------- #
# Command building
# --------------------------------------------------------------------------- #


def test_register_command_matches_a_hand_written_one(tmp_path: Path) -> None:
    argv = adapter.build_cli_argv(
        "register",
        defaults_for("register"),
        r"D:\ws\ref cloud.las",
        r"D:\ws\align cloud.las",
        tmp_path,
        coarse_matrix=r"D:\ws\runs\c\transform_coarse.txt",
    )

    hand_written = [
        r"D:\ws\ref cloud.las",
        r"D:\ws\align cloud.las",
        "-o", str(tmp_path),
        "--ci", "95.0",
        "--max-levels", "20",
        "--target-points", "300000",
        "--icp-max-iter", "60",
        "--icp-method", "plane",
        "--coarse-matrix", r"D:\ws\runs\c\transform_coarse.txt",
        "--max-tilt", "10.0",
        "--overlap", "auto",
        "--equivalence-margin", "auto",
        "--sigma-floor", "0.02",
        "--seed", "0",
    ]
    assert argv == hand_written
    assert r"D:\ws\ref cloud.las" in argv  # spaces intact


def test_register_gui_passes_coarse_mode_instead(tmp_path: Path) -> None:
    argv = adapter.build_cli_argv(
        "register_gui", defaults_for("register"), "ref.las", "ali.las", tmp_path
    )
    assert "--coarse-mode" in argv
    assert argv[argv.index("--coarse-mode") + 1] == "auto"
    assert "--coarse-matrix" not in argv


def test_register_refuses_to_run_without_a_matrix(tmp_path: Path) -> None:
    with pytest.raises(adapter.AdapterError, match="coarse transform artifact is required"):
        adapter.build_cli_argv(
            "register", defaults_for("register"), "ref.las", "ali.las", tmp_path
        )


def test_optional_flags_and_diagnostics(tmp_path: Path) -> None:
    params = {
        **defaults_for("register"),
        "no_polish": True,
        "no_tilt_fit": True,
        "validate_swap": True,
        "cycle_experiment": True,
        "swap_max_levels": "5",
        "cycle_tolerance": "0.03",
        "coarse": "1 2 3 45",
        "coarse_cell": "0.5",
        "overlap": "off",
        "equivalence_margin": "0.005",
        "icp_method": "point",
    }
    joined = " ".join(
        adapter.build_cli_argv("register_gui", params, "r.las", "a.las", tmp_path)
    )
    assert "--no-polish" in joined
    assert "--no-tilt-fit" in joined
    assert "--validate-swap" in joined
    assert "--cycle-experiment" in joined
    assert "--swap-max-levels 5" in joined
    assert "--cycle-tolerance 0.03" in joined
    assert "--coarse 1 2 3 45" in joined
    assert "--coarse-cell 0.5" in joined
    assert "--overlap off" in joined
    assert "--equivalence-margin 0.005" in joined
    assert "--icp-method point" in joined


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"target_points": "500"}, "must be >= 2000"),
        ({"target_points": "many"}, "whole number or 'auto'"),
        ({"sigma_floor": 0.0}, "must be > 0"),
        ({"equivalence_margin": "-1"}, "must be >= 0"),
        ({"equivalence_margin": "tight"}, "not a number"),
        ({"overlap": "wide"}, "not a number"),
        ({"coarse": "1 2 3"}, "four numbers"),
        ({"swap_max_levels": "0"}, "must be >= 1"),
        ({"cycle_tolerance": "0"}, "must be > 0"),
    ],
)
def test_invalid_values_are_rejected_before_ricp_runs(
    tmp_path: Path, overrides: dict, message: str
) -> None:
    params = {**defaults_for("register"), **overrides}
    with pytest.raises(adapter.AdapterError, match=message):
        adapter.build_cli_argv("register_gui", params, "r.las", "a.las", tmp_path)


def test_target_points_auto_is_allowed(tmp_path: Path) -> None:
    params = {**defaults_for("register"), "target_points": "auto"}
    argv = adapter.build_cli_argv("register_gui", params, "r.las", "a.las", tmp_path)
    assert argv[argv.index("--target-points") + 1] == "auto"


# --------------------------------------------------------------------------- #
# Input preparation (LAZ auto-conversion)
# --------------------------------------------------------------------------- #


def test_readable_extensions_pass_through(tmp_path: Path) -> None:
    for name in ("a.las", "a.txt", "a.xyz", "a.csv", "a.pts", "a.asc", "A.LAS"):
        assert adapter.prepare_input(name, tmp_path, what="reference") == name


def test_an_unsupported_extension_is_reported(tmp_path: Path) -> None:
    with pytest.raises(adapter.AdapterError, match="unsupported extension"):
        adapter.prepare_input("cloud.e57", tmp_path, what="reference")


def test_a_missing_input_is_reported(tmp_path: Path) -> None:
    with pytest.raises(adapter.AdapterError, match="no cloud chosen"):
        adapter.prepare_input("", tmp_path, what="align")


def test_laz_is_converted_to_las_in_the_run_folder(tmp_path: Path) -> None:
    """ricp cannot read .laz by design; the adapter writes an uncompressed
    copy (decided 2026-08-27) rather than failing on tlsphoto's output."""
    import laspy

    source = tmp_path / "canonical.laz"
    header = laspy.LasHeader(point_format=3, version="1.4")
    las = laspy.LasData(header)
    las.x = np.array([1.0, 2.0, 3.0])
    las.y = np.array([4.0, 5.0, 6.0])
    las.z = np.array([7.0, 8.0, 9.0])
    las.write(str(source))

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    prepared = adapter.prepare_input(str(source), run_dir, what="reference")

    assert prepared == str(run_dir / "canonical.las")
    assert Path(prepared).is_file()
    # the points survived the conversion
    converted = laspy.read(prepared)
    assert len(converted.points) == 3
    assert np.allclose(np.asarray(converted.x), [1.0, 2.0, 3.0])


# --------------------------------------------------------------------------- #
# THE EQUIVALENCE TEST (architecture section 11)
# --------------------------------------------------------------------------- #


@ricp_available
def test_coarse_only_equals_a_real_ricp_run(tmp_path: Path) -> None:
    """The re-composed coarse path must reproduce ricp.py byte for byte.

    coarse-mode 'none' is used because it is fully deterministic and needs no
    GUI, while still exercising everything that matters: load_cloud, the RNG
    draw order, subsampling, the DEM tilt fit, and the savetxt formatting.
    """
    ref = write_cloud(tmp_path / "ref.txt")
    ali = write_cloud(tmp_path / "ali.txt", shift=(0.35, -0.2, 0.12))

    params = {
        **defaults_for("coarse"),
        "coarse_mode": "none",
        "target_points": "2000",
        "seed": 0,
    }

    # --- the adapter's re-composed path ---
    adapter_out = tmp_path / "adapter_run"
    adapter_out.mkdir()
    ricp = adapter._import_ricp()
    written = adapter._coarse_only(ricp, params, str(ref), str(ali), adapter_out)
    adapter_text = Path(written).read_text(encoding="utf-8")

    # --- the real ricp.py, same inputs and seed ---
    real_out = tmp_path / "real_run"
    real_out.mkdir()
    real_argv = adapter.build_cli_argv(
        "register_gui",
        {**defaults_for("register"), **params, "max_levels": 1, "no_polish": True},
        str(ref),
        str(ali),
        real_out,
    )
    try:
        ricp.main(real_argv)
    except BaseException:
        # transform_coarse.txt is written BEFORE R-ICP starts, so whatever the
        # rest of the run does, the coarse comparison is still valid.
        pass

    native = adapter.find_native_run_dir(real_out)
    assert native is not None, "ricp.py created no run folder"
    real_file = native / "transform_coarse.txt"
    assert real_file.is_file(), "ricp.py wrote no transform_coarse.txt"

    assert adapter_text == real_file.read_text(encoding="utf-8"), (
        "the re-composed coarse path DIVERGED from ricp.py - do not trust the "
        "'coarse' action until this is resolved"
    )


@ricp_available
def test_coarse_only_equivalence_with_target_points_auto(tmp_path: Path) -> None:
    """Same check through the spacing-driven branch (subsample_to_spacing +
    density_parity), which is the other half of the mirrored block."""
    ref = write_cloud(tmp_path / "ref.txt", n=4000)
    ali = write_cloud(tmp_path / "ali.txt", n=4000, shift=(0.2, 0.1, 0.05), seed=11)

    params = {
        **defaults_for("coarse"),
        "coarse_mode": "none",
        "target_points": "auto",
        "seed": 3,
    }

    adapter_out = tmp_path / "adapter_run"
    adapter_out.mkdir()
    ricp = adapter._import_ricp()
    written = adapter._coarse_only(ricp, params, str(ref), str(ali), adapter_out)

    real_out = tmp_path / "real_run"
    real_out.mkdir()
    real_argv = adapter.build_cli_argv(
        "register_gui",
        {**defaults_for("register"), **params, "max_levels": 1, "no_polish": True},
        str(ref),
        str(ali),
        real_out,
    )
    try:
        ricp.main(real_argv)
    except BaseException:
        pass

    native = adapter.find_native_run_dir(real_out)
    assert native is not None
    assert Path(written).read_text(encoding="utf-8") == (
        (native / "transform_coarse.txt").read_text(encoding="utf-8")
    )


@ricp_available
def test_coarse_action_end_to_end_registers_a_transform(tmp_path: Path) -> None:
    ref = write_cloud(tmp_path / "ref.txt", n=3000)
    ali = write_cloud(tmp_path / "ali.txt", n=3000, shift=(0.1, 0.1, 0.05), seed=5)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    params_file = run_dir / "params.json"
    params_file.write_text(
        json.dumps(
            {
                **defaults_for("coarse"),
                "coarse_mode": "none",
                "target_points": "2000",
            }
        ),
        encoding="utf-8",
    )

    rc = adapter.main(
        [
            "coarse",
            "--params", str(params_file),
            "--out", str(run_dir),
            "--reference=" + str(ref),
            "--align=" + str(ali),
            "--coarse-artifact=",
        ]
    )

    assert rc == 0
    outputs = json.loads((run_dir / "outputs.json").read_text(encoding="utf-8"))
    assert list(outputs) == ["transform"]
    assert outputs["transform"][0].endswith("transform_coarse.txt")
    assert (run_dir / outputs["transform"][0]).is_file()

    matrix = np.loadtxt(run_dir / outputs["transform"][0])
    assert matrix.shape == (4, 4)


# --------------------------------------------------------------------------- #
# outputs.json collection
# --------------------------------------------------------------------------- #


def make_native(run_dir: Path, *, align_stem: str = "ali") -> Path:
    native = run_dir / "run_20260827_120000"
    (native / "plots").mkdir(parents=True)

    def touch(*names: str) -> None:
        for name in names:
            path = native / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")

    touch(
        "registered_{0}.las".format(align_stem),
        "transform_final.txt",
        "transform_coarse.txt",
        "transform_icp.txt",
        "stats.csv",
        "report.txt",
        "c2c_check.txt",
        "plots/convergence_levels.png",
        "plots/convergence_icp.png",
        "plots/c2c_level_00.png",
    )
    return native


def test_collect_outputs_full_register(tmp_path: Path) -> None:
    native = make_native(tmp_path)
    outputs = adapter.collect_outputs("register", tmp_path)
    stamp = native.name

    assert outputs["registered"] == [stamp + "/registered_ali.las"]
    assert outputs["transform"] == [
        stamp + "/transform_final.txt",
        stamp + "/transform_coarse.txt",
        stamp + "/transform_icp.txt",
    ]
    assert outputs["report"] == [
        stamp + "/report.txt",
        stamp + "/stats.csv",
        stamp + "/c2c_check.txt",
    ]
    assert outputs["plots"] == [
        stamp + "/plots/c2c_level_00.png",
        stamp + "/plots/convergence_icp.png",
        stamp + "/plots/convergence_levels.png",
    ]


def test_collect_outputs_handles_a_txt_registered_cloud(tmp_path: Path) -> None:
    native = make_native(tmp_path)
    (native / "registered_ali.las").unlink()
    (native / "registered_ali.txt").write_text("x", encoding="utf-8")

    outputs = adapter.collect_outputs("register", tmp_path)
    assert outputs["registered"] == [native.name + "/registered_ali.txt"]


def test_collect_outputs_coarse_action(tmp_path: Path) -> None:
    native = make_native(tmp_path)
    outputs = adapter.collect_outputs("coarse", tmp_path)
    assert outputs == {"transform": [native.name + "/transform_coarse.txt"]}


def test_collect_outputs_without_a_native_folder(tmp_path: Path) -> None:
    assert adapter.collect_outputs("register", tmp_path) == {}


def test_declared_outputs_match_what_collect_can_produce(engine) -> None:
    assert {s.key for s in engine.action("register").outputs} == {
        "registered",
        "transform",
        "report",
        "plots",
    }
    assert {s.key for s in engine.action("coarse").outputs} == {"transform"}


def test_adapter_error_is_persisted(tmp_path: Path) -> None:
    params_file = tmp_path / "params.json"
    params_file.write_text(json.dumps(defaults_for("register")), encoding="utf-8")

    rc = adapter.main(
        [
            "register",
            "--params", str(params_file),
            "--out", str(tmp_path),
            "--reference=r.las",
            "--align=a.las",
            "--coarse-artifact=",
        ]
    )

    assert rc == 2
    assert "coarse transform artifact is required" in (
        tmp_path / "adapter_error.txt"
    ).read_text(encoding="utf-8")
