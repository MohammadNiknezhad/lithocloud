"""ricp adapter v2 - a translator around ``ricp_engine`` (ricp-engine 0.2.0).

    python adapter.py register --params <params.json> --out <run_dir>
                      --reference=F --align=F [--coarse-artifact=F]

Studio params in, ``RegistrationConfig`` out, ``outputs.json`` back. No
science lives here: the engine is imported from the editable install of
``../ricp/ricp`` (``pip install -e .``), exactly as ENGINE_GUIDE section 2
describes. Nothing inside ``../ricp`` is touched.

What happens, in order:

1. read params and input paths; a ``.laz`` input is decompressed to ``.las``
   in the run folder (``RegistrationConfig.validate`` rejects LAZ by design);
2. build ``RegistrationConfig(output_directory=<run_dir>, ...)`` - one field
   per params entry, every default the engine's own;
3. ``run_registration(config, on_progress=...)`` streams each line to the
   real stdout so the studio's log panel shows progress live;
4. ``ricp_result.json`` = ``result.as_dict()`` is written whenever the run got
   far enough to create its ``run_...`` folder - success or failure - as the
   complete record a future viewer panel will read (decided 2026-09-09);
5. failure: ``adapter_error.txt`` carries ``error_message`` and, when they
   exist, the coarse overlay paths, so the operator knows what to inspect
   before rerunning with a reviewed matrix; the engine's exit code is
   returned;
6. success: ``outputs.json`` registers the RECOMMENDED method (or the single
   method when only one ran) plus the reports. When several ran and the
   comparison was not decisive, only the reports register - the adapter never
   picks a method the evidence did not (decided 2026-09-09).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

OUTPUTS_NAME = "outputs.json"
ERROR_NAME = "adapter_error.txt"
RESULT_NAME = "ricp_result.json"

ACTIONS = ("register",)

#: What ricp_engine.validate() accepts; a test pins this to
#: ricp_engine.SUPPORTED_INPUT_SUFFIXES. ``.laz`` is converted, never passed.
RICP_READABLE = (".las", ".txt", ".xyz", ".csv", ".pts", ".asc")

#: Keys of result.artifacts that are figures. Anything else there is JSON/CSV.
_ARTIFACT_PLOT_KEYS = ("coarse_overlay_top", "coarse_overlay_side")


class AdapterError(ValueError):
    """Bad parameter combination - reported before the engine is invoked."""


def _write_error_file(run_dir: "str | Path", lines: "str | list[str]") -> None:
    """Persist a failure so it survives the log panel being cleared."""
    text = lines if isinstance(lines, str) else "\n".join(lines)
    try:
        Path(run_dir).mkdir(parents=True, exist_ok=True)
        (Path(run_dir) / ERROR_NAME).write_text(text.rstrip() + "\n", encoding="utf-8")
    except OSError:
        pass


def _engine():
    """The installed ricp_engine module (imported late so tests can stub it)."""
    try:
        import ricp_engine  # noqa: PLC0415
    except ImportError as exc:
        raise AdapterError(
            "ricp_engine is not importable - run 'pip install -e .' in "
            "../ricp/ricp inside the rockslope env (ENGINE_GUIDE section 2): {0}".format(exc)
        ) from None
    return ricp_engine


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #


def prepare_input(path: str, run_dir: Path, *, what: str) -> str:
    """Return a path the engine can read, converting .laz to .las if needed."""
    if not path:
        raise AdapterError("{0}: no cloud chosen".format(what))
    source = Path(path)
    suffix = source.suffix.lower()

    if suffix in RICP_READABLE:
        return str(source)

    if suffix == ".laz":
        try:
            import laspy  # noqa: PLC0415
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
# params -> RegistrationConfig keyword arguments      (pure, unit-tested)
# --------------------------------------------------------------------------- #


def _text(params: dict, key: str) -> str:
    return str(params.get(key, "")).strip()


def _int_or_literal(text: str, literals: tuple[str, ...], *, what: str):
    if text in literals:
        return text
    try:
        return int(text)
    except ValueError:
        raise AdapterError(
            "{0}: expected {1} or a whole number, got {2!r}".format(
                what, " / ".join(repr(x) for x in literals), text
            )
        ) from None


def _float_or_literal(text: str, literals: tuple[str, ...], *, what: str):
    if text in literals:
        return text
    try:
        return float(text)
    except ValueError:
        raise AdapterError(
            "{0}: expected {1} or a number, got {2!r}".format(
                what, " / ".join(repr(x) for x in literals), text
            )
        ) from None


def _seeds(text: str) -> tuple[int, ...]:
    """'0,1,2' -> (0, 1, 2); '' -> () which the engine maps to 'off'."""
    if not text:
        return ()
    out: list[int] = []
    for item in text.replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            out.append(int(item))
        except ValueError:
            raise AdapterError(
                "stability_seeds: {0!r} is not a whole number".format(item)
            ) from None
    return tuple(out)


def _coarse_parameters(text: str) -> "tuple[float, float, float, float] | None":
    if not text:
        return None
    items = text.replace(",", " ").split()
    if len(items) != 4:
        raise AdapterError(
            "coarse_parameters: need four numbers 'tx ty tz yaw_deg', got {0!r}".format(text)
        )
    try:
        values = tuple(float(item) for item in items)
    except ValueError:
        raise AdapterError(
            "coarse_parameters: {0!r} contains a non-number".format(text)
        ) from None
    return values  # type: ignore[return-value]


def build_config_kwargs(
    params: dict,
    reference: str,
    align: str,
    run_dir: "str | Path",
    coarse_matrix: "str | None" = None,
) -> dict[str, Any]:
    """Keyword arguments for ``RegistrationConfig`` - one per params field.

    Every field is passed explicitly EXCEPT ``max_registration_points`` /
    ``max_evaluation_points``: an empty value omits the keyword so the
    installed engine's own default applies and can never drift (decided
    2026-09-09). ``output_directory`` is the studio run folder; ``coarse_matrix``
    comes from the optional transform input, not the form.
    """
    p = dict(params)

    coarse_parameters = _coarse_parameters(_text(p, "coarse_parameters"))
    if coarse_matrix and coarse_parameters is not None:
        raise AdapterError(
            "choose a coarse transform artifact OR 'coarse_parameters', not both"
        )

    registration_uncertainty = _text(p, "registration_uncertainty_mm")

    kwargs: dict[str, Any] = {
        "reference": reference,
        "align": align,
        "output_directory": str(run_dir),
        "fine_method": p["fine_method"],
        "stability_seeds": _seeds(_text(p, "stability_seeds")),
        "seed": int(p["seed"]),
        "reference_precision_mm": float(p["reference_precision_mm"]),
        "align_precision_mm": float(p["align_precision_mm"]),
        "registration_uncertainty_mm": (
            None
            if not registration_uncertainty
            else _float_or_literal(
                registration_uncertainty, (), what="registration_uncertainty_mm"
            )
        ),
        "coarse_mode": p["coarse_mode"],
        "coarse_review": p["coarse_review"],
        "accept_poor_coarse": bool(p.get("accept_poor_coarse", False)),
        "coarse_matrix": coarse_matrix or None,
        "coarse_parameters": coarse_parameters,
        "fit_tilt": bool(p.get("fit_tilt", True)),
        "target_points": _int_or_literal(
            _text(p, "target_points"), ("auto",), what="target_points"
        ),
        "dense_report_points": _int_or_literal(
            _text(p, "dense_report_points"), ("auto", "off"), what="dense_report_points"
        ),
        "overlap": _float_or_literal(_text(p, "overlap"), ("auto", "off"), what="overlap"),
        "report_thresholds_mm": _text(p, "report_thresholds_mm") or "auto",
        "comparison_equivalence_mm": _float_or_literal(
            _text(p, "comparison_equivalence_mm"), ("auto",), what="comparison_equivalence_mm"
        ),
        "extra_arguments": tuple(_text(p, "extra_arguments").split()),
    }

    for key in ("max_registration_points", "max_evaluation_points"):
        text = _text(p, key)
        if text:
            kwargs[key] = _int_or_literal(text, (), what=key)

    return kwargs


# --------------------------------------------------------------------------- #
# RegistrationResult -> outputs.json                (pure, unit-tested)
# --------------------------------------------------------------------------- #


def chosen_method(result) -> "str | None":
    """The method to register: the recommendation, else the only one that ran."""
    methods = dict(result.methods)
    recommended = result.recommended_method
    if recommended and recommended in methods:
        return recommended
    if len(methods) == 1:
        return next(iter(methods))
    return None


def collect_outputs(result, run_dir: "str | Path") -> tuple[dict[str, list[str]], list[str]]:
    """``({output_key: [files relative to run_dir]}, notes)``.

    Every path comes from the result object - the method's own
    ``registered_cloud_path`` / ``transform_path`` / ``directory`` and
    ``result.artifacts`` - never from guessed filenames. ``plots`` is the
    coarse overlays plus every PNG inside the chosen method's directory
    (decided 2026-09-09).
    """
    run_dir = Path(run_dir).resolve()
    notes: list[str] = []
    outputs: dict[str, list[str]] = {}

    def rel(path) -> "str | None":
        if path is None:
            return None
        path = Path(path)
        if not path.is_file():
            return None
        try:
            return path.resolve().relative_to(run_dir).as_posix()
        except ValueError:
            notes.append("{0} lies outside the run folder and was not registered".format(path))
            return None

    def put(key: str, *paths) -> None:
        files = [r for r in (rel(p) for p in paths) if r]
        if files:
            outputs[key] = files

    artifacts = dict(result.artifacts)
    method_name = chosen_method(result)
    method = result.methods.get(method_name) if method_name else None

    if method is not None:
        put("registered", method.registered_cloud_path)
        put("transform", method.transform_path)
        if "registered" not in outputs or "transform" not in outputs:
            notes.append(
                "method {0!r}: registered cloud or transform not found on disk".format(
                    method_name
                )
            )
    elif result.methods:
        notes.append(
            "no recommended method ({0} ran, comparison outcome: {1}) - only the "
            "reports were registered; rerun with 'fine_method' set to the method "
            "you choose after reading method_comparison.json".format(
                ", ".join(sorted(result.methods)), result.comparison_outcome
            )
        )

    put("uncertainty", artifacts.get("registration_uncertainty"))
    put("comparison", artifacts.get("method_comparison"))

    plots: list[Path] = [
        Path(artifacts[key]) for key in _ARTIFACT_PLOT_KEYS if key in artifacts
    ]
    plots += [
        Path(p) for p in artifacts.values()
        if str(p).lower().endswith(".png") and Path(p) not in plots
    ]
    if method is not None and method.directory:
        plots += sorted(Path(method.directory).glob("*.png"))
    seen: set[str] = set()
    unique = [p for p in plots if not (str(p) in seen or seen.add(str(p)))]
    put("plots", *unique)

    return outputs, notes


# --------------------------------------------------------------------------- #
# Running
# --------------------------------------------------------------------------- #


def _dump_result(run_dir: Path, result) -> None:
    try:
        with open(run_dir / RESULT_NAME, "w", encoding="utf-8") as handle:
            json.dump(result.as_dict(), handle, indent=2, default=str)
    except (OSError, TypeError, ValueError) as exc:
        print("adapter: could not write {0} - {1}".format(RESULT_NAME, exc), flush=True)


def _failure_lines(result) -> list[str]:
    lines = [
        "ERROR: ricp {0} (exit code {1})".format(result.status, result.exit_code)
    ]
    if result.error_message:
        lines.append(result.error_message)
    overlays = [
        str(result.artifacts[key])
        for key in _ARTIFACT_PLOT_KEYS
        if key in result.artifacts
    ]
    if overlays:
        lines.append("")
        lines.append(
            "Inspect the coarse overlays before rerunning with a reviewed coarse "
            "transform artifact (or 'accept_poor_coarse'):"
        )
        lines.extend("  " + path for path in overlays)
    if result.run_directory:
        lines.append("")
        lines.append("Run folder: {0}".format(result.run_directory))
        lines.append("Full record: {0}".format(RESULT_NAME))
    return lines


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

    # Captured BEFORE the run: the engine redirects sys.stdout into its own
    # progress stream while it runs, so a callback that printed to sys.stdout
    # would feed its own output back into that stream. The studio reads the
    # process's real stdout.
    real_stdout = sys.stdout

    def on_progress(line: str) -> None:
        real_stdout.write(line + "\n")
        real_stdout.flush()

    try:
        engine = _engine()
    except AdapterError as exc:
        print("ERROR: {0}".format(exc), file=sys.stderr, flush=True)
        _write_error_file(run_dir, "ERROR: {0}".format(exc))
        return 2

    try:
        reference = prepare_input(args.reference, run_dir, what="reference")
        align = prepare_input(args.align, run_dir, what="align")
        kwargs = build_config_kwargs(
            params, reference, align, run_dir, coarse_matrix=args.coarse_artifact or None
        )
        config = engine.RegistrationConfig(**kwargs)
        config.validate()
    except AdapterError as exc:
        print("ERROR: {0}".format(exc), file=sys.stderr, flush=True)
        _write_error_file(run_dir, "ERROR: {0}".format(exc))
        return 2
    except engine.RICPConfigurationError as exc:
        print("ERROR: invalid configuration - {0}".format(exc), file=sys.stderr, flush=True)
        _write_error_file(run_dir, "ERROR: invalid configuration - {0}".format(exc))
        return 2

    print("adapter: RegistrationConfig " + json.dumps(
        {k: (str(v) if isinstance(v, Path) else v) for k, v in kwargs.items()},
        default=str), flush=True)

    result = engine.run_registration(config, on_progress=on_progress)

    if result.run_directory:
        _dump_result(run_dir, result)

    if not result.succeeded:
        lines = _failure_lines(result)
        for line in lines:
            print(line, flush=True)
        _write_error_file(run_dir, lines)
        return int(result.exit_code) or 1

    outputs, notes = collect_outputs(result, run_dir)
    for note in notes:
        print("adapter: WARNING: " + note, flush=True)
    with open(run_dir / OUTPUTS_NAME, "w", encoding="utf-8") as handle:
        json.dump(outputs, handle, indent=2)
    print(
        "adapter: recommended method = {0}; outputs.json -> {1}".format(
            chosen_method(result), sorted(outputs)
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
