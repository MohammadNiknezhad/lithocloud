"""tlsphoto adapter - the thin wrapper the studio actually runs.

    python adapter.py <action> --params <params.json> --out <run_dir>
                      [--tls=F] [--photo=F] [--cloud=F] [--old=F] [--new=F] [--fuse-src=F]

What it does, in order:

1. translate the studio's validated params JSON + picked artifact files into a
   tlsphoto CLI argument list (pure function, unit-tested);
2. invoke the tlsphoto CLI **in-process** (``tlsphoto.cli.main``) with the
   sibling repo on sys.path - no pip install, zero changes inside ../tlsphoto;
3. on success, write ``<run_dir>/outputs.json`` = ``{output_key: [files]}``
   (paths relative to the run folder) - the contract the shell registers
   artifacts from. tlsphoto itself knows nothing about this file.

Conventions:

* every scalar parameter is passed to the CLI explicitly (defaults included),
  so a run is reproducible even if tlsphoto's own defaults ever change;
* an empty-string parameter, or an 'auto' choice, means "flag not passed" -
  the CLI behaves exactly as if the flag were omitted on a hand-written
  command line;
* a false boolean means "flag not passed"; true adds the flag;
* ``compare``/``split`` receive a pointcloud artifact FILE from the picker and
  pass that file's FOLDER to the CLI (decided 2026-08-27).

Stdlib only. Never touches launcher.py / launcher_settings.py.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

#: engines/tlsphoto/adapter.py -> Projects/tlsphoto  (sibling repo, read-only)
TLSPHOTO_REPO = Path(__file__).resolve().parents[3] / "tlsphoto"

OUTPUTS_NAME = "outputs.json"
ERROR_NAME = "adapter_error.txt"

ACTIONS = ("ingest", "register", "fuse", "compare", "split", "export", "info")


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


class AdapterError(ValueError):
    """Bad parameter combination - reported before tlsphoto is even invoked."""


# --------------------------------------------------------------------------- #
# Small builders
# --------------------------------------------------------------------------- #


def _split(text: str) -> list[str]:
    """Space-separated list parameter -> argv items ('' -> [])."""
    return [item for item in str(text).split() if item]


def _split_paths(text: str) -> list[str]:
    """';'-separated path list -> items, trimmed, empties dropped."""
    return [item.strip() for item in str(text).split(";") if item.strip()]


def _number(text: str, *, what: str) -> str:
    """Validate a numeric string parameter (kept as text for the CLI)."""
    try:
        float(text)
    except ValueError:
        raise AdapterError("{0}: {1!r} is not a number".format(what, text)) from None
    return str(text)


def _triple(text: str, *, what: str) -> list[str]:
    items = _split(text)
    if len(items) != 3:
        raise AdapterError("{0}: need three numbers 'X Y Z', got {1!r}".format(what, text))
    return [_number(item, what=what) for item in items]


def _pair_of_files(a: str, b: str, *, what: str) -> list[str] | None:
    if bool(a) != bool(b):
        raise AdapterError("{0}: give both files or neither".format(what))
    return [a, b] if a else None


def _folder_of(artifact_file: str, *, what: str) -> str:
    """compare/split take run FOLDERS; the picker hands us a file inside one."""
    if not artifact_file:
        raise AdapterError("{0}: no artifact chosen".format(what))
    return str(Path(artifact_file).parent)


# --------------------------------------------------------------------------- #
# params + inputs -> tlsphoto CLI argv     (pure - unit-tested with no data)
# --------------------------------------------------------------------------- #


def build_cli_argv(
    action: str, params: dict, inputs: dict, run_dir: "str | Path"
) -> list[str]:
    """The tlsphoto argv for one run, starting at the subcommand name."""
    run_dir = Path(run_dir)
    p = dict(params)
    argv: list[str] = [action]

    def flag(name: str, on: bool) -> None:
        if on:
            argv.append(name)

    def opt(name: str, value: str) -> None:
        if str(value):
            argv.extend([name, str(value)])

    def always(name: str, value) -> None:
        argv.extend([name, str(value)])

    if action == "ingest":
        files = _split_paths(p.get("in_files", ""))
        if not files:
            raise AdapterError(
                "ingest: 'in_files' is required - full path(s) separated by ;"
            )
        always("--role", p["role"])
        argv.append("--in")
        argv.extend(files)
        always("--out", run_dir / p["out_name"])
        if _split(p.get("columns", "")):
            argv.append("--columns")
            argv.extend(_split(p["columns"]))
        if _split(p.get("map", "")):
            argv.append("--map")
            argv.extend(_split(p["map"]))
        opt("--scanners", p.get("scanners", ""))
        if _split(p.get("scan_ids", "")):
            argv.append("--scan-ids")
            argv.extend(_split(p["scan_ids"]))
        always("--scanid-offset", p["scanid_offset"])
        always("--chunk-size", p["chunk_size"])
        always("--scale", p["scale"])
        opt("--crs", p.get("crs", ""))
        opt("--units", p.get("units", ""))
        always("--extra-dtype", p["extra_dtype"])
        flag("--drop-unknown", p.get("drop_unknown", False))
        flag("--no-raw-intensity", p.get("no_raw_intensity", False))
        if p.get("rgb_encoding", "auto") != "auto":
            always("--rgb-encoding", p["rgb_encoding"])
        if p.get("intensity_encoding", "auto") != "auto":
            always("--intensity-encoding", p["intensity_encoding"])
        flag("--dry-run", p.get("dry_run", False))

    elif action == "register":
        _require(inputs, "tls", "register")
        _require(inputs, "photo", "register")
        always("--tls", inputs["tls"])
        always("--photo", inputs["photo"])
        always("--out-dir", run_dir)
        pairs = _pair_of_files(
            p.get("pairs_tls", ""), p.get("pairs_photo", ""), what="register: pairs"
        )
        if pairs:
            argv.append("--pairs")
            argv.extend(pairs)
        always("--holdout", p["holdout"])
        check = _pair_of_files(
            p.get("check_tls", ""), p.get("check_photo", ""), what="register: check"
        )
        if check:
            argv.append("--check")
            argv.extend(check)
        opt("--init", p.get("init", ""))
        if p.get("shift_tls", ""):
            argv.append("--shift-tls")
            argv.extend(_triple(p["shift_tls"], what="register: shift_tls"))
        if p.get("shift_photo", ""):
            argv.append("--shift-photo")
            argv.extend(_triple(p["shift_photo"], what="register: shift_photo"))
        flag("--auto", p.get("auto", False))
        flag("--topview", p.get("topview", False))
        always("--auto-voxel", p["auto_voxel"])
        always("--topview-cell", p["topview_cell"])
        if p.get("yaw_hint", ""):
            items = _split(p["yaw_hint"])
            if len(items) != 2:
                raise AdapterError(
                    "register: yaw_hint needs two numbers 'DEG HALFWIN', got {0!r}".format(
                        p["yaw_hint"]
                    )
                )
            argv.append("--yaw-hint")
            argv.extend(_number(i, what="register: yaw_hint") for i in items)
        always("--sample-voxel", p["sample_voxel"])
        always("--max-sample", p["max_sample"])
        always("--max-points", p["max_points"])
        always("--coarse-voxel", p["coarse_voxel"])
        if _split(p.get("levels", "")):
            argv.append("--levels")
            argv.extend(
                _number(i, what="register: levels") for i in _split(p["levels"])
            )
        always("--corr-factor", p["corr_factor"])
        always("--qa-threshold", p["qa_threshold"])
        flag("--no-icp", p.get("no_icp", False))
        flag("--no-apply", p.get("no_apply", False))
        always("--chunk-size", p["chunk_size"])
        always("--workers", p["workers"])

    elif action == "fuse":
        _require(inputs, "tls", "fuse")
        _require(inputs, "photo", "fuse")
        always("--tls", inputs["tls"])
        always("--photo", inputs["photo"])
        always("--out-dir", run_dir)
        always("--cell", p["cell"])
        always("--mode", p["mode"])
        if p.get("tolerance", ""):
            always("--tolerance", _number(p["tolerance"], what="fuse: tolerance"))
        always("--support-radius", p["support_radius"])
        always("--surface-radius", p["surface_radius"])
        always("--rep-nmin", p["rep_nmin"])
        always("--q-max", p["q_max"])
        always("--products", p["products"])
        always("--axial-max-deg", p["axial_max_deg"])
        always("--rgb-dist", p["rgb_dist"])
        flag("--no-clean-photo", p.get("no_clean_photo", False))
        opt("--confidence-field", p.get("confidence_field", ""))
        if p.get("confidence_min", ""):
            always(
                "--confidence-min", _number(p["confidence_min"], what="fuse: confidence_min")
            )
        flag("--include-ambiguous", p.get("include_ambiguous", False))
        always("--chunk-size", p["chunk_size"])
        always("--workers", p["workers"])

    elif action == "compare":
        always("--old", _folder_of(inputs.get("old", ""), what="compare: old"))
        always("--new", _folder_of(inputs.get("new", ""), what="compare: new"))
        always("--out-dir", run_dir)
        always("--chunk-size", p["chunk_size"])

    elif action == "split":
        always(
            "--fuse-dir", _folder_of(inputs.get("fusedir", ""), what="split: fusedir")
        )
        always("--out-dir", run_dir)
        always("--support-radius", p["support_radius"])

    elif action == "export":
        _require(inputs, "cloud", "export")
        always("--in", inputs["cloud"])
        always("--out", run_dir / p["out_name"])
        always("--delimiter", p["delimiter"])
        always("--precision", p["precision"])
        if _split(p.get("columns", "")):
            argv.append("--columns")
            argv.extend(_split(p["columns"]))
        always("--header", p["header"])
        always("--rgb", p["rgb"])
        flag("--decode-intensity", p.get("decode_intensity", False))
        flag("--keep-zero-fields", p.get("keep_zero_fields", False))
        always("--chunk-size", p["chunk_size"])

    elif action == "info":
        _require(inputs, "cloud", "info")
        always("--in", inputs["cloud"])

    else:
        raise AdapterError("unknown action {0!r}".format(action))

    return argv


def _require(inputs: dict, key: str, action: str) -> None:
    if not inputs.get(key):
        raise AdapterError("{0}: input {1!r} is required".format(action, key))


# --------------------------------------------------------------------------- #
# outputs.json
# --------------------------------------------------------------------------- #


def collect_outputs(action: str, params: dict, inputs: dict, run_dir: Path) -> dict:
    """``{output_key: [existing files, relative to run_dir]}`` after a run.

    A key whose primary file is absent is dropped entirely - the shell then
    logs its 'declared output missing' warning (e.g. register --no-apply,
    ingest --dry-run, a compare with no transitions).
    """
    candidates: dict[str, list[str]] = {}

    if action == "ingest":
        out = params["out_name"]
        candidates["canonical"] = [out, out + ".json"]

    elif action == "register":
        stem = Path(inputs["tls"]).stem
        reg = stem + "_registered.laz"
        candidates["registered"] = [reg, reg + ".json"]
        candidates["transform"] = ["transform.json", "transform_tls_to_photo.txt"]
        candidates["report"] = ["registration_report.txt"]

    elif action in ("fuse", "split"):
        candidates["tls_colored"] = ["tls_colored.laz", "tls_colored.laz.json"]
        candidates["photo_surface_consistent"] = ["photo_surface_consistent.laz"]
        candidates["photo_outside_tls_support"] = ["photo_outside_tls_support.laz"]
        candidates["photo_ambiguous"] = ["photo_ambiguous.laz"]
        if action == "fuse":
            candidates["report"] = ["fusion_report.txt", "fusion.json"]
        else:
            candidates["report"] = ["split_report.txt"]

    elif action == "compare":
        candidates["report"] = ["compare_report.txt"]
        transitions = sorted(p.name for p in run_dir.glob("*.laz"))
        if transitions:
            candidates["transitions"] = transitions

    elif action == "export":
        candidates["table"] = [params["out_name"]]

    elif action == "info":
        candidates["report"] = ["info.txt"]

    outputs: dict[str, list[str]] = {}
    for key, files in candidates.items():
        existing = [name for name in files if (run_dir / name).is_file()]
        if not existing or files[0] not in existing:
            continue  # primary file missing -> skip the key, shell warns
        outputs[key] = existing
    return outputs


# --------------------------------------------------------------------------- #
# Running
# --------------------------------------------------------------------------- #


class _Tee(io.TextIOBase):
    """Write to the real stream AND remember everything (for info.txt)."""

    def __init__(self, real) -> None:
        self._real = real
        self.buffer = io.StringIO()

    def write(self, text: str) -> int:
        self.buffer.write(text)
        return self._real.write(text)

    def flush(self) -> None:  # pragma: no cover - passthrough
        self._real.flush()


def run_tlsphoto(cli_argv: list[str]) -> tuple[int, str]:
    """Invoke tlsphoto's CLI in-process. Returns (exit_code, captured output)."""
    if not (TLSPHOTO_REPO / "tlsphoto" / "cli.py").is_file():
        print(
            "ERROR: tlsphoto repo not found at {0}".format(TLSPHOTO_REPO),
            file=sys.stderr,
        )
        return 2, ""
    if str(TLSPHOTO_REPO) not in sys.path:
        sys.path.insert(0, str(TLSPHOTO_REPO))

    from tlsphoto.cli import main as tlsphoto_main

    out_tee, err_tee = _Tee(sys.stdout), _Tee(sys.stderr)
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out_tee, err_tee
    try:
        code = int(tlsphoto_main(cli_argv))
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return code, out_tee.buffer.getvalue() + err_tee.buffer.getvalue()


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=ACTIONS)
    parser.add_argument("--params", required=True)
    parser.add_argument("--out", required=True, help="the run folder")
    parser.add_argument("--tls", default="")
    parser.add_argument("--photo", default="")
    parser.add_argument("--cloud", default="")
    parser.add_argument("--old", default="")
    parser.add_argument("--new", default="")
    parser.add_argument("--fuse-src", dest="fuse_src", default="")
    args = parser.parse_args(argv)

    run_dir = Path(args.out)
    with open(args.params, "r", encoding="utf-8") as handle:
        params = json.load(handle)
    inputs = {
        "tls": args.tls,
        "photo": args.photo,
        "cloud": args.cloud,
        "old": args.old,
        "new": args.new,
        "fusedir": args.fuse_src,
    }

    try:
        cli_argv = build_cli_argv(args.action, params, inputs, run_dir)
    except AdapterError as exc:
        print("ERROR: {0}".format(exc), file=sys.stderr)
        _write_error_file(run_dir, exc)
        return 2

    print("tlsphoto " + " ".join(cli_argv), flush=True)
    code, captured = run_tlsphoto(cli_argv)
    if code != 0:
        return code

    if args.action == "info":
        (run_dir / "info.txt").write_text(captured, encoding="utf-8")

    outputs = collect_outputs(args.action, params, inputs, run_dir)
    with open(run_dir / OUTPUTS_NAME, "w", encoding="utf-8") as handle:
        json.dump(outputs, handle, indent=2)
    print("adapter: outputs.json -> {0}".format(sorted(outputs)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
