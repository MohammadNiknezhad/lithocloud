"""ricp adapter - the thin wrapper the studio actually runs.

    python adapter.py <action> --params <params.json> --out <run_dir>
                      --reference=F --align=F [--coarse-artifact=F]

Actions
-------
register / register_gui
    Build a ricp.py argument list and call ``ricp.main()`` in-process. This is
    the wrap-as-is path: ricp decides everything, exactly as today.

coarse
    Standalone coarse alignment. ricp.py has NO --coarse-only flag, so this
    action RE-COMPOSES the code path main() runs up to the point where it
    writes transform_coarse.txt - see _coarse_only() below. Approved by
    Mohammad on 2026-08-27 after the risk was put to him in writing.

    The rule for that function: call ricp's OWN functions, with ricp's OWN
    arguments, in ricp's OWN order. Nothing is reimplemented, re-tuned or
    reordered - in particular the RNG is drawn in the same sequence, so the
    subsampling is identical. tests/test_ricp_adapter.py contains an
    EQUIVALENCE test (architecture section 11) that runs the real ricp.py on a
    generated cloud and asserts this function reproduces its
    transform_coarse.txt exactly.

LAZ inputs are auto-converted to uncompressed .las inside the run folder
(decided 2026-08-27): ricp cannot read .laz by design. The converted copy is
what ricp sees, and it stays in the run folder as part of the record.

Stdlib + laspy (already an engine dependency) only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

#: engines/ricp/adapter.py -> Projects/ricp/ricp  (sibling repo, read-only)
RICP_REPO = Path(__file__).resolve().parents[3] / "ricp" / "ricp"

OUTPUTS_NAME = "outputs.json"
ERROR_NAME = "adapter_error.txt"

ACTIONS = ("coarse", "register", "register_gui")

#: ricp reads these; .laz is explicitly unsupported and gets converted.
RICP_READABLE = (".las", ".txt", ".xyz", ".csv", ".pts", ".asc")


class AdapterError(ValueError):
    """Bad parameter combination - reported before ricp is invoked."""


def _write_error_file(run_dir: "str | Path", error: Exception) -> None:
    """Persist an early failure so it survives a closed console window."""
    try:
        Path(run_dir).mkdir(parents=True, exist_ok=True)
        (Path(run_dir) / ERROR_NAME).write_text(
            "ERROR: {0}\n".format(error), encoding="utf-8"
        )
    except OSError:
        pass


def _import_ricp():
    """Import ricp.py from the sibling repo (no pip install, no edits)."""
    if not (RICP_REPO / "ricp.py").is_file():
        raise AdapterError("ricp repo not found at {0}".format(RICP_REPO))
    if str(RICP_REPO) not in sys.path:
        sys.path.insert(0, str(RICP_REPO))
    import ricp  # noqa: PLC0415 - deliberately late, after sys.path is set

    return ricp


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #


def prepare_input(path: str, run_dir: Path, *, what: str) -> str:
    """Return a path ricp can read, converting .laz to .las if needed."""
    if not path:
        raise AdapterError("{0}: no cloud chosen".format(what))
    source = Path(path)
    suffix = source.suffix.lower()

    if suffix in RICP_READABLE:
        return str(source)

    if suffix == ".laz":
        try:
            import laspy
        except ImportError:
            raise AdapterError(
                "{0}: {1} is LAZ, which ricp cannot read, and laspy is not "
                "available to convert it - export uncompressed .las first".format(
                    what, source.name
                )
            ) from None
        target = run_dir / (source.stem + ".las")
        print(
            "adapter: {0} is LAZ (ricp cannot read it) - writing an "
            "uncompressed copy to {1}".format(source.name, target.name),
            flush=True,
        )
        try:
            laspy.read(str(source)).write(str(target))
        except Exception as exc:  # noqa: BLE001 - any laspy failure is ours to report
            raise AdapterError(
                "{0}: could not convert {1} to .las - {2}".format(what, source, exc)
            ) from None
        return str(target)

    raise AdapterError(
        "{0}: unsupported extension {1!r} - ricp reads {2} (.laz is converted "
        "automatically)".format(what, suffix, ", ".join(RICP_READABLE))
    )


# --------------------------------------------------------------------------- #
# ricp.py argv  (pure - unit-tested with no data)
# --------------------------------------------------------------------------- #


def build_cli_argv(
    action: str,
    params: dict,
    reference: str,
    align: str,
    run_dir: "str | Path",
    coarse_matrix: "str | None" = None,
) -> list[str]:
    """The ricp.py argv for one full-registration run."""
    run_dir = Path(run_dir)
    p = dict(params)
    argv = [reference, align, "-o", str(run_dir)]

    def always(flag: str, value) -> None:
        argv.extend([flag, str(value)])

    def flag(name: str, on: bool) -> None:
        if on:
            argv.append(name)

    always("--ci", p["ci"])
    always("--max-levels", p["max_levels"])
    always("--target-points", _target_points(p["target_points"]))
    always("--icp-max-iter", p["icp_max_iter"])
    always("--icp-method", p["icp_method"])

    if action == "register":
        # The coarse artifact is mandatory for this action; supplying the
        # matrix also removes every interactive fallback inside ricp.
        if not coarse_matrix:
            raise AdapterError(
                "register: a coarse transform artifact is required "
                "(use the 'coarse' action first, or run register_gui)"
            )
        always("--coarse-matrix", coarse_matrix)
    else:
        always("--coarse-mode", p["coarse_mode"])
        if str(p.get("coarse", "")).strip():
            always("--coarse", _coarse_quad(p["coarse"]))
        if str(p.get("coarse_cell", "")).strip():
            always("--coarse-cell", _number(p["coarse_cell"], what="coarse_cell"))

    flag("--no-tilt-fit", p.get("no_tilt_fit", False))
    always("--max-tilt", p["max_tilt"])
    always("--overlap", _overlap(p["overlap"]))
    always("--equivalence-margin", _equivalence_margin(p["equivalence_margin"]))
    always("--sigma-floor", _positive(p["sigma_floor"], what="sigma_floor"))
    flag("--no-polish", p.get("no_polish", False))
    flag("--validate-swap", p.get("validate_swap", False))
    if str(p.get("swap_max_levels", "")).strip():
        always("--swap-max-levels", _positive_int(p["swap_max_levels"], what="swap_max_levels"))
    if str(p.get("cycle_tolerance", "")).strip():
        always("--cycle-tolerance", _positive(p["cycle_tolerance"], what="cycle_tolerance"))
    flag("--cycle-experiment", p.get("cycle_experiment", False))
    always("--seed", p["seed"])
    return argv


# -- small validators (mirror ricp's own p.error() checks) ------------------ #

MIN_POINTS_AFTER_FILTER = 2_000  # ricp constant, checked here for a clear message


def _number(text, *, what: str) -> str:
    try:
        float(text)
    except (TypeError, ValueError):
        raise AdapterError("{0}: {1!r} is not a number".format(what, text)) from None
    return str(text)


def _positive(text, *, what: str) -> str:
    value = _number(text, what=what)
    if float(value) <= 0:
        raise AdapterError("{0}: must be > 0, got {1}".format(what, value))
    return value


def _positive_int(text, *, what: str) -> str:
    try:
        value = int(str(text).strip())
    except ValueError:
        raise AdapterError("{0}: {1!r} is not a whole number".format(what, text)) from None
    if value < 1:
        raise AdapterError("{0}: must be >= 1, got {1}".format(what, value))
    return str(value)


def _target_points(text) -> str:
    raw = str(text).strip()
    if raw == "auto":
        return raw
    try:
        value = int(raw)
    except ValueError:
        raise AdapterError(
            "target_points: must be a whole number or 'auto', got {0!r}".format(text)
        ) from None
    if value < MIN_POINTS_AFTER_FILTER:
        raise AdapterError(
            "target_points: must be >= {0}, got {1}".format(MIN_POINTS_AFTER_FILTER, value)
        )
    return str(value)


def _overlap(text) -> str:
    raw = str(text).strip()
    if raw in ("auto", "off"):
        return raw
    return _number(raw, what="overlap")


def _equivalence_margin(text) -> str:
    raw = str(text).strip()
    if raw == "auto":
        return raw
    value = _number(raw, what="equivalence_margin")
    if float(value) < 0:
        raise AdapterError("equivalence_margin: must be >= 0 or 'auto'")
    return value


def _coarse_quad(text) -> str:
    items = str(text).split()
    if len(items) != 4:
        raise AdapterError(
            "coarse: need four numbers 'tx ty tz yaw_deg', got {0!r}".format(text)
        )
    for item in items:
        _number(item, what="coarse")
    return " ".join(items)


# --------------------------------------------------------------------------- #
# The re-composed coarse-only path
# --------------------------------------------------------------------------- #


def _coarse_only(ricp, params: dict, reference: str, align: str, run_dir: Path) -> Path:
    """Mirror of ricp.main() from its start to transform_coarse.txt.

    Line-for-line correspondence with ricp.py (v as of 2026-08-27):
      main() 2306-2318  rng, load_cloud x2, make_run_dir
      main() 2324-2325  native_spacing x2      <- same RNG order, so the
      main() 2329-2398  the target_points branch   subsampling is identical
      main() 2411-2444  the coarse branch
      main() 2446-2458  tilt fit + savetxt

    NOTHING here is reimplemented: every computation is a call into ricp.
    Returns the path of the written transform_coarse.txt.
    """
    import numpy as np

    p = dict(params)
    seed = int(p["seed"])
    target_points = _target_points(p["target_points"])

    rng = np.random.default_rng(seed)

    print("Loading reference: {0}".format(reference), flush=True)
    ref = ricp.load_cloud(reference)
    print("  {0:,} points".format(ref.n), flush=True)
    print("Loading align:     {0}".format(align), flush=True)
    ali = ricp.load_cloud(align)
    print("  {0:,} points".format(ali.n), flush=True)

    out = Path(ricp.make_run_dir(str(run_dir)))
    print("Run folder: {0}".format(out), flush=True)

    s_nat_ref = ricp.native_spacing(ref.xyz, rng)
    s_nat_ali = ricp.native_spacing(ali.xyz, rng)
    print(
        "Data profile: approx. native spacing ref ~{0:.3f} m, align ~{1:.3f} m".format(
            s_nat_ref, s_nat_ali
        ),
        flush=True,
    )

    if target_points == "auto":
        target_s = 2.0 * max(s_nat_ref, s_nat_ali)
        ref_sub, s_ref_act = ricp.subsample_to_spacing(ref.xyz, target_s)
        ali_sub, s_ali_act = ricp.subsample_to_spacing(ali.xyz, target_s)
        ref_sub, ali_sub, s_ref_act, s_ali_act, _parity_ok, _tries = ricp.density_parity(
            ref.xyz, ali.xyz, ref_sub, ali_sub, s_ref_act, s_ali_act
        )
        ref_sub_spacing = s_ref_act
    else:
        count = int(target_points)
        ref_sub = ricp.voxel_downsample(ref.xyz, count, rng)
        ali_sub = ricp.voxel_downsample(ali.xyz, count, rng)
        ref_sub_spacing = ricp.estimate_spacing(ref_sub)
    print(
        "  reference: {0:,} pts   align: {1:,} pts".format(len(ref_sub), len(ali_sub)),
        flush=True,
    )

    # ---- coarse (mirrors main() 2411-2444) --------------------------------
    mode = p["coarse_mode"]
    if str(p.get("coarse", "")).strip():
        T_coarse = ricp.parse_coarse_arg(_coarse_quad(p["coarse"]))
        print("Coarse transform from --coarse parameters.", flush=True)
    elif mode == "none":
        T_coarse = np.eye(4)
        print("Coarse step skipped.", flush=True)
    elif mode == "auto":
        cell = p.get("coarse_cell", "")
        cell_value = float(_number(cell, what="coarse_cell")) if str(cell).strip() else None
        print("Automatic coarse registration (SCENE top-view logic):", flush=True)
        T_coarse, quality = ricp.auto_coarse_topview(ref_sub, ali_sub, cell=cell_value)
        if quality > ricp.AUTO_COARSE_QUALITY_LIMIT:
            print(
                "  WARNING: placement quality is poor ({0:.1f} x point spacing).\n"
                "  Falling back to the manual GUI so you can check/fix it "
                "(close with Enter to accept, Esc to abort).".format(quality),
                flush=True,
            )
            T_gui = ricp.coarse_gui(ref_sub, ali_sub, initial_T=T_coarse)
            if T_gui is None:
                raise AdapterError("coarse registration cancelled - aborting")
            T_coarse = T_gui
        else:
            print("  Auto coarse placement accepted.", flush=True)
    else:  # gui
        print("Opening coarse registration GUI (SCENE-style top view)...", flush=True)
        T_coarse = ricp.coarse_gui(ref_sub, ali_sub)
        if T_coarse is None:
            raise AdapterError("coarse registration cancelled - aborting")
        print("Coarse transform accepted.", flush=True)

    # ---- tilt fit + write (mirrors main() 2446-2458) -----------------------
    if not p.get("no_tilt_fit", False):
        print("Tilt estimation from DEM differences:", flush=True)
        placed = ricp.apply_transform(T_coarse, ali_sub)
        T_tilt, tinfo = ricp.dem_tilt_fit(
            ref_sub, placed, max_tilt_deg=float(p["max_tilt"]), spacing=ref_sub_spacing
        )
        if tinfo["ok"]:
            T_coarse = T_tilt @ T_coarse

    target = out / "transform_coarse.txt"
    np.savetxt(
        str(target),
        T_coarse,
        fmt="%.10f",
        header="coarse 4x4 (align -> reference), tilt fit included",
    )
    print("Coarse transform -> {0}".format(target), flush=True)
    return target


# --------------------------------------------------------------------------- #
# outputs.json
# --------------------------------------------------------------------------- #


def find_native_run_dir(run_dir: Path) -> "Path | None":
    """The run_YYYYMMDD_HHMMSS folder ricp created inside the studio run."""
    candidates = [
        child
        for child in sorted(Path(run_dir).iterdir())
        if child.is_dir() and child.name.startswith("run_")
    ]
    return candidates[-1] if candidates else None


def collect_outputs(action: str, run_dir: Path) -> dict:
    """``{output_key: [files relative to run_dir]}``."""
    run_dir = Path(run_dir)
    native = find_native_run_dir(run_dir)
    if native is None:
        return {}

    def rel(path: Path) -> str:
        return path.relative_to(run_dir).as_posix()

    def existing(*names: str) -> list[str]:
        return [rel(native / n) for n in names if (native / n).is_file()]

    if action == "coarse":
        files = existing("transform_coarse.txt")
        return {"transform": files} if files else {}

    outputs: dict[str, list[str]] = {}

    registered = sorted(
        rel(p)
        for p in native.iterdir()
        if p.is_file() and p.name.startswith("registered_")
    )
    if registered:
        outputs["registered"] = registered

    transforms = existing(
        "transform_final.txt", "transform_coarse.txt", "transform_icp.txt"
    )
    if transforms and transforms[0].endswith("transform_final.txt"):
        outputs["transform"] = transforms

    report = existing("report.txt", "stats.csv", "c2c_check.txt")
    if report and report[0].endswith("report.txt"):
        outputs["report"] = report

    plots = sorted(rel(p) for p in (native / "plots").glob("*.png") if p.is_file())
    if plots:
        outputs["plots"] = plots
    return outputs


# --------------------------------------------------------------------------- #
# Running
# --------------------------------------------------------------------------- #


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=ACTIONS)
    parser.add_argument("--params", required=True)
    parser.add_argument("--out", required=True, help="the studio run folder")
    parser.add_argument("--reference", default="")
    parser.add_argument("--align", default="")
    parser.add_argument("--coarse-artifact", dest="coarse_artifact", default="")
    args = parser.parse_args(argv)

    run_dir = Path(args.out)
    with open(args.params, "r", encoding="utf-8") as handle:
        params = json.load(handle)

    try:
        ricp = _import_ricp()
        reference = prepare_input(args.reference, run_dir, what="reference")
        align = prepare_input(args.align, run_dir, what="align")

        if args.action == "coarse":
            _coarse_only(ricp, params, reference, align, run_dir)
            code = 0
        else:
            cli_argv = build_cli_argv(
                args.action,
                params,
                reference,
                align,
                run_dir,
                coarse_matrix=args.coarse_artifact or None,
            )
            print("ricp.py " + " ".join(cli_argv), flush=True)
            code = int(ricp.main(cli_argv) or 0)
    except AdapterError as exc:
        print("ERROR: {0}".format(exc), file=sys.stderr)
        _write_error_file(run_dir, exc)
        return 2
    except SystemExit as exc:  # argparse inside ricp
        return int(exc.code or 0)

    if code != 0:
        return code

    outputs = collect_outputs(args.action, run_dir)
    with open(run_dir / OUTPUTS_NAME, "w", encoding="utf-8") as handle:
        json.dump(outputs, handle, indent=2)
    print("adapter: outputs.json -> {0}".format(sorted(outputs)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
