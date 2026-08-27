"""geohazard adapter - the thin wrapper the studio actually runs.

    python adapter.py <action> --params <params.json> --out <run_dir>
                      [--cloud=F] [--previous=F]

What it does, in order:

1. translate the studio's validated params JSON into a geohazard CLI argument
   list (pure function, unit-tested):
   - the curated config fields are nested back into PipelineConfig sections
     and written to ``<run_dir>/config_overrides.json``, passed via --config;
   - ``--runs-dir`` is THE STUDIO RUN FOLDER (decided 2026-08-27), so
     geohazard's native ``<stamp>/`` folder - its own manifest.json, stage
     subfolders, _DONE.json checkpoints - is created nested inside it;
   - for ``redo_stage`` the picked report artifact leads to the previous
     native folder (--resume) and the original cloud path is re-read from
     that run's manifest ``input_file`` entry;
2. invoke the pipeline **in-process** (``geohazard_pipeline.main.main``) with
   the sibling repo on sys.path - no pip install, zero changes inside
   ../geohazard-pipeline. Interactive prompts (column mapping, north
   confirmation) work because the studio launches this adapter in its own
   console window;
3. on success, find the native run folder and write ``<run_dir>/outputs.json``
   = ``{output_key: [files relative to run_dir]}`` by scanning the stage
   subfolders - registration is read-only bookkeeping, files are not moved.

Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

#: engines/geohazard/adapter.py -> Projects/geohazard-pipeline (read-only)
GEOHAZARD_REPO = Path(__file__).resolve().parents[3] / "geohazard-pipeline"

OUTPUTS_NAME = "outputs.json"
CONFIG_NAME = "config_overrides.json"
ERROR_NAME = "adapter_error.txt"

STAGES = (
    "01_ingest",
    "02_orientation",
    "03_facets",
    "04_edges",
    "05_stereonet",
    "06_hazard",
)

ACTIONS = ("run", "redo_stage")


class AdapterError(ValueError):
    """Bad parameter combination - reported before the pipeline is invoked."""


def _write_error_file(run_dir: "str | Path", error: Exception) -> None:
    """Persist an early failure so it stays readable after a console closes.

    Best-effort: writing must never mask the original error.
    """
    try:
        Path(run_dir).mkdir(parents=True, exist_ok=True)
        (Path(run_dir) / ERROR_NAME).write_text(
            "ERROR: {0}\n".format(error), encoding="utf-8"
        )
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Config overrides
# --------------------------------------------------------------------------- #

#: params key -> (config section, field). Values pass through unchanged unless
#: a parser is named in _CONFIG_PARSERS.
_CONFIG_MAP = {
    "facets_normal_radius_mult": ("facets", "normal_radius_mult"),
    "facets_rg_angle_deg": ("facets", "rg_angle_deg"),
    "facets_rg_knn": ("facets", "rg_knn"),
    "facets_rg_min_facet_points": ("facets", "rg_min_facet_points"),
    "facets_joint_set_max_k": ("facets", "joint_set_max_k"),
    "facets_joint_set_fixed_k": ("facets", "joint_set_fixed_k"),
    "facets_use_input_normals": ("facets", "use_input_normals"),
    "facets_flip_normals": ("facets", "flip_normals"),
    "edges_adjacency_tol_mult": ("edges", "adjacency_tol_mult"),
    "edges_min_internormal_angle_deg": ("edges", "min_internormal_angle_deg"),
    "edges_min_edge_length_mult": ("edges", "min_edge_length_mult"),
    "sectors_mode": ("sectors", "mode"),
    "sectors_max_drift_deg": ("sectors", "max_drift_deg"),
    "stereonet_display_friction_deg": ("stereonet", "display_friction_deg"),
    "stereonet_min_chain_length_m": ("stereonet", "min_chain_length_m"),
    "stereonet_exclude_sets": ("stereonet", "exclude_sets"),
    "stereonet_length_weighted": ("stereonet", "length_weighted"),
    "stereonet_dpi": ("stereonet", "dpi"),
    "hazard_grid_cell_m": ("hazard", "grid_cell_m"),
    "hazard_friction_sweep_deg": ("hazard", "friction_sweep_deg"),
    "hazard_toppling_phi_deg": ("hazard", "toppling_phi_deg"),
    "point_density_enabled": ("point_density", "enabled"),
    "point_density_radius_m": ("point_density", "radius_m"),
}


def _int_or_none(text, *, what: str):
    if str(text).strip() == "":
        return None
    try:
        return int(str(text).strip())
    except ValueError:
        raise AdapterError(
            "{0}: {1!r} is not a whole number (or empty)".format(what, text)
        ) from None


def _float_or_none(text, *, what: str):
    if str(text).strip() == "":
        return None
    try:
        return float(str(text).strip())
    except ValueError:
        raise AdapterError("{0}: {1!r} is not a number (or empty)".format(what, text)) from None


def _int_list(text, *, what: str):
    out = []
    for item in str(text).split():
        try:
            out.append(int(item))
        except ValueError:
            raise AdapterError(
                "{0}: {1!r} is not a whole number".format(what, item)
            ) from None
    return out


def _float_list(text, *, what: str):
    out = []
    for item in str(text).split():
        try:
            out.append(float(item))
        except ValueError:
            raise AdapterError("{0}: {1!r} is not a number".format(what, item)) from None
    return out


#: fields whose text form needs parsing before it enters the config JSON.
_CONFIG_PARSERS = {
    "facets_joint_set_fixed_k": lambda v: _int_or_none(v, what="joint_set_fixed_k"),
    "stereonet_exclude_sets": lambda v: _int_list(v, what="exclude_sets"),
    "hazard_friction_sweep_deg": lambda v: _float_list(v, what="friction_sweep_deg"),
    "point_density_radius_m": lambda v: _float_or_none(v, what="point_density radius_m"),
}


def build_config_overrides(params: dict) -> dict:
    """Nest the curated flat params back into PipelineConfig sections.

    Every exposed field is written explicitly (defaults included) so a run's
    config_overrides.json is a complete record of what the form sent; unexposed
    fields stay at pipeline defaults (PipelineConfig.from_json merges over
    them). One exception: an empty 'exclude_sets' is left out of the JSON -
    empty means 'ask at run time' and the omission keeps that intent visible
    in the file.
    """
    config: dict = {"random_seed": params.get("random_seed", 42)}
    for key, (section, field) in _CONFIG_MAP.items():
        if key not in params:
            continue
        value = params[key]
        if key in _CONFIG_PARSERS:
            value = _CONFIG_PARSERS[key](value)
        if key == "stereonet_exclude_sets" and value == []:
            continue  # empty = ask at run time (the config default)
        config.setdefault(section, {})[field] = value
    return config


# --------------------------------------------------------------------------- #
# CLI argv
# --------------------------------------------------------------------------- #


def _native_run_dir_of(artifact_file: str) -> Path:
    """Walk up from a picked artifact file to geohazard's native run folder
    (the directory holding manifest.json next to stage subfolders)."""
    if not artifact_file:
        raise AdapterError("redo_stage: pick the previous run's report artifact")
    node = Path(artifact_file).resolve()
    for parent in [node] + list(node.parents):
        if parent.is_dir() and (parent / "manifest.json").is_file():
            if any((parent / stage).is_dir() for stage in STAGES):
                return parent
            # the studio run folder also has a manifest.json - keep walking
    raise AdapterError(
        "redo_stage: {0} is not inside a geohazard run folder "
        "(no manifest.json with stage subfolders found above it)".format(artifact_file)
    )


def _input_file_from(native_dir: Path) -> str:
    try:
        with open(native_dir / "manifest.json", "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError) as exc:
        raise AdapterError(
            "redo_stage: cannot read {0}/manifest.json - {1}".format(native_dir, exc)
        ) from None
    input_file = manifest.get("input_file")
    if not input_file:
        raise AdapterError(
            "redo_stage: {0}/manifest.json records no input_file".format(native_dir)
        )
    return str(input_file)


def build_cli_argv(action: str, params: dict, inputs: dict, run_dir: "str | Path") -> list[str]:
    """The geohazard_pipeline.main argv for one run (positional input first)."""
    run_dir = Path(run_dir)
    p = dict(params)

    if action == "run":
        cloud = inputs.get("cloud", "")
        in_file = str(p.get("in_file", "")).strip()
        if bool(cloud) == bool(in_file):
            raise AdapterError(
                "run: give exactly ONE input - pick a pointcloud artifact or "
                "fill the 'in_file' parameter"
            )
        input_path = cloud or in_file
        resume: str | None = None
        redo: str | None = None

    elif action == "redo_stage":
        native = _native_run_dir_of(inputs.get("previous", ""))
        input_path = _input_file_from(native)
        resume = str(native)
        redo = p["redo"]

    else:
        raise AdapterError("unknown action {0!r}".format(action))

    argv = [input_path, "--config", str(run_dir / CONFIG_NAME)]
    argv.extend(["--to", p["to_stage"]])
    if resume:
        argv.extend(["--resume", resume])
    if redo:
        argv.extend(["--redo", redo])
    argv.extend(["--runs-dir", str(run_dir)])
    if str(p.get("tag", "")).strip():
        argv.extend(["--tag", str(p["tag"]).strip()])
    if p.get("batch_yes", False):
        argv.append("--yes")
    return argv


# --------------------------------------------------------------------------- #
# outputs.json
# --------------------------------------------------------------------------- #


def find_native_run_dir(run_dir: Path) -> "Path | None":
    """The geohazard folder the pipeline just created inside the studio run."""
    candidates = [
        child
        for child in sorted(run_dir.iterdir())
        if child.is_dir() and (child / "manifest.json").is_file()
    ]
    return candidates[-1] if candidates else None


def collect_outputs(run_dir: Path) -> dict:
    """``{output_key: [files relative to run_dir]}`` from the stage folders.

    Keys for stages that were not run are simply absent - the shell logs its
    'declared output missing' warning for them, which is accurate.
    """
    native = find_native_run_dir(Path(run_dir))
    if native is None:
        return {}

    def rel(path: Path) -> str:
        return path.relative_to(run_dir).as_posix()

    def existing(*names: str) -> list[str]:
        return [rel(p) for name in names for p in [native / name] if p.is_file()]

    def globbed(pattern: str) -> list[str]:
        return sorted(rel(p) for p in native.glob(pattern) if p.is_file())

    outputs: dict[str, list[str]] = {}

    def put(key: str, files: list[str], primary: "str | None" = None) -> None:
        if files and (primary is None or any(f.endswith(primary) for f in files)):
            outputs[key] = files

    put("facets", existing("03_facets/facets.csv"))
    put("joint_sets", existing("03_facets/joint_sets.csv"))
    put(
        "edges",
        existing("04_edges/edges.csv", "04_edges/chains.csv"),
        primary="edges.csv",
    )
    put("stereonet_figures", globbed("05_stereonet/*.png"))
    put(
        "kinematics",
        existing(
            "05_stereonet/kinematic_summary.json",
            "05_stereonet/sector_kinematics.csv",
            "05_stereonet/edge_lengths.csv",
        ),
        primary="kinematic_summary.json",
    )
    put("hazard_maps", globbed("06_hazard/map_*.png"))
    put("hazard_tables", globbed("06_hazard/grid_cells_*.csv"))
    put("report", existing("manifest.json"))
    return outputs


# --------------------------------------------------------------------------- #
# Running
# --------------------------------------------------------------------------- #


def run_geohazard(cli_argv: list[str]) -> int:
    """Invoke the pipeline in-process. Its prompts use this console."""
    if not (GEOHAZARD_REPO / "geohazard_pipeline" / "main.py").is_file():
        print(
            "ERROR: geohazard-pipeline repo not found at {0}".format(GEOHAZARD_REPO),
            file=sys.stderr,
        )
        return 2
    if str(GEOHAZARD_REPO) not in sys.path:
        sys.path.insert(0, str(GEOHAZARD_REPO))

    from geohazard_pipeline.main import main as geohazard_main

    # main() returns None on success; SystemExit propagates its code.
    try:
        geohazard_main(cli_argv)
    except SystemExit as exc:  # argparse errors, explicit exits
        return int(exc.code or 0)
    return 0


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=ACTIONS)
    parser.add_argument("--params", required=True)
    parser.add_argument("--out", required=True, help="the studio run folder")
    parser.add_argument("--cloud", default="")
    parser.add_argument("--previous", default="")
    args = parser.parse_args(argv)

    run_dir = Path(args.out)
    with open(args.params, "r", encoding="utf-8") as handle:
        params = json.load(handle)
    inputs = {"cloud": args.cloud, "previous": args.previous}

    try:
        config = build_config_overrides(params)
        cli_argv = build_cli_argv(args.action, params, inputs, run_dir)
    except AdapterError as exc:
        print("ERROR: {0}".format(exc), file=sys.stderr)
        _write_error_file(run_dir, exc)
        return 2

    with open(run_dir / CONFIG_NAME, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)

    print("geohazard_pipeline.main " + " ".join(cli_argv), flush=True)
    code = run_geohazard(cli_argv)
    if code != 0:
        return code

    outputs = collect_outputs(run_dir)
    with open(run_dir / OUTPUTS_NAME, "w", encoding="utf-8") as handle:
        json.dump(outputs, handle, indent=2)
    print("adapter: outputs.json -> {0}".format(sorted(outputs)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
