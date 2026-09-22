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
import math
import sys
from pathlib import Path
from typing import Any

OUTPUTS_NAME = "outputs.json"
ERROR_NAME = "adapter_error.txt"
RESULT_NAME = "ricp_result.json"
PROJECT_RESULT_NAME = "ricp_project_result.json"

ACTIONS = ("register", "register_project", "validate_stable_areas")

#: Project API this plug was written against; a test pins the installed one.
PROJECT_API_VERSION_EXPECTED = "0.3.0"
#: Production methods a project may use - the API itself rejects "all".
PROJECT_METHODS = ("paper-c2c", "local-plane", "m3c2")
#: Pinned for projects (spec decision 1): every pair is confirmed by the
#: operator in the engine's own window. Never a form field.
PROJECT_COARSE_REVIEW = "always"

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


def prepare_input(path: str, run_dir: Path, *, what: str, stem_prefix: str = "") -> str:
    """Return a path the engine can read, converting .laz to .las if needed.

    *stem_prefix* keeps converted copies apart when several inputs share a
    file name (a project's scan01_x.las, scan02_x.las, ...).
    """
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
        target = run_dir / (stem_prefix + source.stem + ".las")
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
        # Method flags first, the user's own extra arguments after: argparse
        # keeps the LAST occurrence, so a flag typed by hand wins.
        "extra_arguments": tuple(method_argument_tokens(p))
        + tuple(_text(p, "extra_arguments").split()),
    }

    for key in ("max_registration_points", "max_evaluation_points"):
        text = _text(p, key)
        if text:
            kwargs[key] = _int_or_literal(text, (), what=key)

    return kwargs


# --------------------------------------------------------------------------- #
# Method parameters -> extra_arguments tokens      (pure, unit-tested)
# --------------------------------------------------------------------------- #

#: (params key, CLI flag, which fine_method values it applies to, validator).
#: RegistrationConfig has no typed field for these (amendment A2, finding 2),
#: so they travel through extra_arguments, which to_argv() appends verbatim.
_PLANE_METHODS = ("local-plane", "all")
_M3C2_METHODS = ("m3c2", "all")


def _positive_float(text: str, *, what: str) -> str:
    try:
        value = float(text)
    except ValueError:
        raise AdapterError("{0}: {1!r} is not a number".format(what, text)) from None
    if not math.isfinite(value) or value <= 0:
        raise AdapterError("{0}: must be a finite number > 0, got {1!r}".format(what, text))
    return text


def _float_at_least_one(text: str, *, what: str) -> str:
    try:
        value = float(text)
    except ValueError:
        raise AdapterError("{0}: {1!r} is not a number".format(what, text)) from None
    if not math.isfinite(value) or value < 1.0:
        # ricp's own bound: "--m3c2-max-scale-factor must be finite and >= 1"
        raise AdapterError("{0}: must be a finite number >= 1, got {1!r}".format(what, text))
    return text


def _whole_at_least(minimum: int):
    def check(text: str, *, what: str) -> str:
        try:
            value = int(text)
        except ValueError:
            raise AdapterError("{0}: {1!r} is not a whole number".format(what, text)) from None
        if value < minimum:
            raise AdapterError("{0}: must be a whole number >= {1}, got {2}".format(what, minimum, value))
        return str(value)

    return check


_METHOD_FLAGS = (
    ("plane_radius", "--plane-radius", _PLANE_METHODS, _positive_float),
    ("m3c2_core_points", "--m3c2-core-points", _M3C2_METHODS, _whole_at_least(100)),
    ("m3c2_normal_radius", "--m3c2-normal-radius", _M3C2_METHODS, _positive_float),
    ("m3c2_projection_radius", "--m3c2-projection-radius", _M3C2_METHODS, _positive_float),
    ("m3c2_max_depth", "--m3c2-max-depth", _M3C2_METHODS, _positive_float),
    ("m3c2_scale_mode", "--m3c2-scale-mode", _M3C2_METHODS, None),
    ("m3c2_max_scale_factor", "--m3c2-max-scale-factor", _M3C2_METHODS, _float_at_least_one),
    ("m3c2_max_levels", "--m3c2-max-levels", _M3C2_METHODS, _whole_at_least(1)),
)


def method_argument_tokens(params: dict) -> list[str]:
    """Method-parameter flags as separate argv tokens, for the selected method.

    * a field left empty emits nothing - the engine's own default applies,
      never a value invented here;
    * ``--plane-radius`` only when ``fine_method`` is local-plane or all;
      ``--m3c2-*`` only for m3c2 or all - so a stale or even invalid value in
      a hidden field never blocks a run of another method;
    * one token per element (``["--plane-radius", "0.35"]``): no quotes, no
      commas, no joined strings;
    * validated before the run, naming the field. Bounds mirror ricp.py's own
      checks (decided 2026-09-19): radii and depth finite and > 0, core points
      a whole number >= 100, max scale factor finite and >= 1, max levels >= 1.

    ``build_config_kwargs`` places these BEFORE the user's ``extra_arguments``;
    argparse takes the last occurrence, so a hand-typed flag still wins.
    """
    method = str(params.get("fine_method", "")).strip()
    tokens: list[str] = []
    for key, flag, methods, validator in _METHOD_FLAGS:
        if method not in methods:
            continue
        text = _text(params, key)
        if not text:
            continue
        if validator is not None:
            text = validator(text, what=key)
        tokens.extend([flag, text])
    return tokens


# --------------------------------------------------------------------------- #
# Projects: graph + config                          (pure, unit-tested)
# --------------------------------------------------------------------------- #


def validate_project_graph(mode: str, align_count: int, edges) -> tuple[list[tuple[int, int]], list[str]]:
    """Check the declared overlap graph before any cloud loads.

    Returns ``(edges, notes)``. Independent mode uses the implied edges
    0->1, 0->2, ... and IGNORES any declared list (decided 2026-09-21: a
    hidden field never blocks another mode; a note says they were not used).
    Multiway rules mirror the engine's own: indices within 0..N, no
    self-edge, no duplicate connection in either direction, every scan
    connected to scan 0. A tree with no redundant loop is allowed but noted:
    loop consistency cannot be checked without a closing edge.
    """
    count = align_count + 1
    declared = [(int(f), int(m)) for f, m in (edges or [])]
    if mode == "independent":
        notes = []
        if declared:
            notes.append(
                "independent mode: the {0} declared overlap edge(s) were not used - "
                "each align scan is registered directly onto REF".format(len(declared))
            )
        return [], notes
    if mode != "multiway":
        raise AdapterError("mode: expected 'independent' or 'multiway', got {0!r}".format(mode))
    if not declared:
        raise AdapterError(
            "multiway mode needs at least one overlap edge (fixed -> moving scan "
            "indices; 0 is REF, 1..{0} are the align rows). A chain without an "
            "extra loop cannot check loop consistency.".format(align_count)
        )
    undirected: set[tuple[int, int]] = set()
    adjacency: dict[int, set[int]] = {i: set() for i in range(count)}
    for fixed, moving in declared:
        if fixed == moving:
            raise AdapterError("overlap_edges: {0} -> {0} is a self-edge".format(fixed))
        if not (0 <= fixed < count and 0 <= moving < count):
            raise AdapterError(
                "overlap_edges: {0} -> {1} references a scan outside 0..{2} "
                "(0 = REF, {3} align row(s))".format(fixed, moving, count - 1, align_count)
            )
        key = (min(fixed, moving), max(fixed, moving))
        if key in undirected:
            raise AdapterError(
                "overlap_edges: scans {0} and {1} are connected twice - either "
                "direction is the same connection".format(*key)
            )
        undirected.add(key)
        adjacency[fixed].add(moving)
        adjacency[moving].add(fixed)
    seen = {0}
    stack = [0]
    while stack:
        node = stack.pop()
        for other in adjacency[node] - seen:
            seen.add(other)
            stack.append(other)
    missing = sorted(set(range(count)) - seen)
    if missing:
        raise AdapterError(
            "overlap_edges: scan(s) {0} have no path to REF (scan 0) - the "
            "graph must be connected".format(", ".join(map(str, missing)))
        )
    notes = []
    if len(undirected) == count - 1:
        notes.append(
            "the declared graph is a chain/tree with no redundant loop: loop "
            "consistency cannot be checked; add a closing edge if those scans "
            "genuinely overlap"
        )
    return declared, notes


def _precision_list(text: str, count: int) -> "list[float] | None":
    raw = str(text).strip()
    if not raw:
        return None
    values: list[float] = []
    for item in raw.replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            value = float(item)
        except ValueError:
            raise AdapterError("align_precisions_mm: {0!r} is not a number".format(item)) from None
        if not math.isfinite(value) or value < 0:
            raise AdapterError("align_precisions_mm: values must be finite and >= 0")
        values.append(value)
    if len(values) != count:
        raise AdapterError(
            "align_precisions_mm: {0} value(s) given for {1} align scan(s) - one per "
            "scan, in list order".format(len(values), count)
        )
    return values


def build_project_kwargs(params: dict, reference: str, aligns, run_dir: "str | Path") -> tuple[dict[str, Any], list[str]]:
    """Keyword arguments for ``RegistrationProjectConfig`` plus adapter notes.

    Every shared field follows the single-pair mapping; the method flags
    reuse ``method_argument_tokens`` unchanged (generated tokens first, the
    user's extras after). ``coarse_review`` is never read from the form: it
    is pinned to "always" (spec decision 1). ``fine_method`` must be one
    production method - "all" is refused before the engine sees it.
    """
    p = dict(params)
    aligns = [str(a) for a in aligns]
    if not aligns:
        raise AdapterError("register_project: add at least one ALIGN scan")

    method = str(p.get("fine_method", "")).strip()
    if method not in PROJECT_METHODS:
        raise AdapterError(
            "fine_method: a project needs ONE production method ({0}); {1!r} is not "
            "allowed ('all' is diagnostic-only)".format(", ".join(PROJECT_METHODS), method)
        )
    mode = str(p.get("mode", "")).strip()
    edges, notes = validate_project_graph(mode, len(aligns), p.get("overlap_edges", []))

    registration_uncertainty = _text(p, "registration_uncertainty_mm")
    kwargs: dict[str, Any] = {
        "reference": reference,
        "aligns": aligns,
        "output_directory": str(run_dir),
        "mode": mode,
        "fine_method": method,
        "overlap_edges": [tuple(e) for e in edges],
        "stability_seeds": _seeds(_text(p, "stability_seeds")),
        "seed": int(p["seed"]),
        "reference_precision_mm": float(p["reference_precision_mm"]),
        "align_precision_mm": float(p["align_precision_mm"]),
        "align_precisions_mm": _precision_list(_text(p, "align_precisions_mm"), len(aligns)),
        "registration_uncertainty_mm": (
            None
            if not registration_uncertainty
            else _float_or_literal(registration_uncertainty, (), what="registration_uncertainty_mm")
        ),
        "coarse_mode": p["coarse_mode"],
        "coarse_review": PROJECT_COARSE_REVIEW,
        "accept_poor_coarse": bool(p.get("accept_poor_coarse", False)),
        "fit_tilt": bool(p.get("fit_tilt", True)),
        "target_points": _int_or_literal(_text(p, "target_points"), ("auto",), what="target_points"),
        "dense_report_points": _int_or_literal(
            _text(p, "dense_report_points"), ("auto", "off"), what="dense_report_points"
        ),
        "overlap": _float_or_literal(_text(p, "overlap"), ("auto", "off"), what="overlap"),
        "report_thresholds_mm": _text(p, "report_thresholds_mm") or "auto",
        "extra_arguments": tuple(method_argument_tokens(p))
        + tuple(_text(p, "extra_arguments").split()),
        "continue_on_error": bool(p.get("continue_on_error", True)),
    }
    for key in ("max_registration_points", "max_evaluation_points"):
        text = _text(p, key)
        if text:
            kwargs[key] = _int_or_literal(text, (), what=key)
    return kwargs, notes


# --------------------------------------------------------------------------- #
# Projects: result -> outputs.json + log summary
# --------------------------------------------------------------------------- #


def _rel_in(run_dir: Path, path) -> "str | None":
    if path is None:
        return None
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return path.resolve().relative_to(Path(run_dir).resolve()).as_posix()
    except ValueError:
        return None


def collect_project_outputs(result, run_dir: "str | Path") -> tuple[dict[str, list[str]], list[str]]:
    """``({output_key: [files relative to run_dir]}, notes)`` for a project.

    Per scan: ``registered_scan<i>`` when its cloud is on disk and
    ``transform_scan<i>`` when its transform is (a transform-only scan
    registers the transform alone - decided 2026-09-21). Then the summary,
    the pose-graph table (multiway), the engine's own outputs.json, and our
    ricp_project_result.json. Every path comes from the result object.
    """
    run_dir = Path(run_dir)
    outputs: dict[str, list[str]] = {}
    notes: list[str] = []

    def put(key: str, *paths) -> None:
        files = [r for r in (_rel_in(run_dir, p) for p in paths) if r]
        if files:
            outputs[key] = files

    for scan in result.scans:
        if scan.scan_index == 0:
            continue
        put("registered_scan{0}".format(scan.scan_index), scan.registered_cloud_path)
        put("transform_scan{0}".format(scan.scan_index), scan.transform_path)
        if scan.transform_path and not scan.registered_cloud_path:
            notes.append(
                "scan {0} ({1}) is transform-only: its global transform registers, "
                "no registered cloud exists".format(scan.scan_index, Path(scan.path).name)
            )

    artifacts = dict(result.artifacts)
    put(
        "project_summary",
        artifacts.get("project_summary"),
        artifacts.get("project_summary_text"),
        artifacts.get("project_summary_csv"),
    )
    put("pose_graph_edges", artifacts.get("pose_graph_edges_csv"), artifacts.get("pose_graph_edges"))
    put("engine_outputs", artifacts.get("outputs"))
    put("project_result", run_dir / PROJECT_RESULT_NAME)
    return outputs, notes


def _graph_rows(result) -> list[dict]:
    path = dict(result.artifacts).get("pose_graph_edges")
    if not path or not Path(path).is_file():
        return []
    try:
        rows = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return rows if isinstance(rows, list) else []


def _observability_warnings(result) -> list[dict]:
    """Pairs whose method reports observability_complete is False (API 0.4.0)."""
    findings: list[dict] = []
    for pair in result.pairs:
        for name, method in dict(pair.registration.methods).items():
            complete = getattr(method, "observability_complete", None)
            entry = {
                "edge_number": pair.edge_number,
                "fixed_index": pair.fixed_index,
                "moving_index": pair.moving_index,
                "method": name,
                "observable_rank": getattr(method, "observable_rank", None),
                "required_observable_rank": getattr(method, "required_observable_rank", None),
                "observability_complete": complete,
                "scaled_information_condition": getattr(method, "scaled_information_condition", None),
                "fitting_diagnostics": {
                    "fitting_tolerance_m": getattr(method, "fitting_tolerance_m", None),
                    "fitting_tolerance_is_registration_uncertainty": getattr(
                        method, "fitting_tolerance_is_registration_uncertainty", None
                    ),
                },
            }
            findings.append(entry)
    return findings


def project_summary_lines(result, kwargs: dict, notes: list[str]) -> list[str]:
    """The log summary, worded the way the engine guide requires."""
    ok_pairs = sum(1 for p in result.pairs if p.transform is not None)
    n_pairs = len(result.pairs)
    lines: list[str] = ["", "=" * 72]
    if result.status == "partial":
        lines.append("=== PROJECT PARTIAL - {0} of {1} pairs succeeded ===".format(ok_pairs, n_pairs))
    else:
        lines.append("=== PROJECT {0} - {1} of {2} pairs succeeded ===".format(
            result.status.upper(), ok_pairs, n_pairs))
    lines.append("mode: {0}   fine method: {1}   coarse review: {2}".format(
        result.mode, result.fine_method, kwargs.get("coarse_review")))
    if result.error_message:
        lines.append("engine message: {0}".format(result.error_message))
    for note in notes:
        lines.append("note: " + note)

    lines.append("")
    lines.append("SCANS (uncertainty is the engine's own status sentence)")
    for scan in result.scans:
        if scan.scan_index == 0:
            lines.append("  [0] {0}: fixed reference".format(Path(scan.path).name))
            continue
        line = "  [{0}] {1}: {2}; uncertainty: {3}".format(
            scan.scan_index, Path(scan.path).name, scan.status, scan.uncertainty_status)
        sigma = getattr(scan, "registration_uncertainty_1sigma_m", None)
        if result.mode == "independent" and sigma is not None and sigma > 0:
            line += " ({0:.3f} mm, direct pair, 1-sigma)".format(1000.0 * sigma)
        lines.append(line)

    for finding in _observability_warnings(result):
        if finding["observability_complete"] is False:
            lines.append(
                "WARNING: pair {0} [{1} <- {2}] method {3}: observability incomplete "
                "(rank {4} of {5}) - the transform is not fully constrained".format(
                    finding["edge_number"], finding["fixed_index"], finding["moving_index"],
                    finding["method"], finding["observable_rank"],
                    finding["required_observable_rank"]))

    rows = _graph_rows(result)
    if rows:
        lines.append("")
        lines.append("POSE-GRAPH EDGES (95th-percentile transform disagreement is NOT surface error)")
        for row in rows:
            metric = row.get("consistency_metric")
            p95 = row.get("postfit_p95_point_displacement_m")
            if metric == "p95-transform-displacement" and p95 is not None:
                measure = "95th-percentile transform disagreement {0:.3f} mm".format(1000.0 * p95)
            else:
                measure = "legacy extent heuristic (fallback: {0}) - not the headline number".format(metric)
            lines.append("  edge {0} [{1} <- {2}]: {3}; {4}".format(
                row.get("edge_number"), row.get("fixed_index"), row.get("moving_index"),
                measure, row.get("consistency")))
        if any(row.get("consistency") == "SUSPECT" for row in rows):
            lines.append(
                "  SUSPECT = unresolved loop disagreement, not proven pairwise failure. "
                "Decide with independent stable surfaces or controls.")
    lines.append("=" * 72)
    return lines


def _project_record(result, kwargs: dict, notes: list[str]) -> dict:
    return {
        "project_status": result.status,
        "project_api_version_expected": PROJECT_API_VERSION_EXPECTED,
        "mode": result.mode,
        "fine_method": result.fine_method,
        "config": {k: (list(v) if isinstance(v, tuple) else v) for k, v in kwargs.items()},
        "adapter_notes": notes,
        "observability": _observability_warnings(result),
        "pose_graph_edges": _graph_rows(result),
        "engine": result.as_dict(),
    }


def _stamp_run_manifest(run_dir: Path, status: str) -> None:
    """Best-effort: add project_status to the shell's run manifest (decision 4)."""
    path = run_dir / "manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["project_status"] = status
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError):
        pass


def run_project(args, params: dict, run_dir: Path, on_progress) -> int:
    try:
        import ricp_project  # noqa: PLC0415
    except ImportError as exc:
        raise AdapterError(
            "ricp_project is not importable - 'pip install -e .' in ../ricp/ricp "
            "(project API 0.3.0 ships with ricp-engine 0.2.0): {0}".format(exc)
        ) from None

    reference = prepare_input(args.reference, run_dir, what="reference", stem_prefix="scan00_")
    aligns = [
        prepare_input(path, run_dir, what="align {0}".format(i), stem_prefix="scan{0:02d}_".format(i))
        for i, path in enumerate(args.aligns, 1)
    ]
    kwargs, notes = build_project_kwargs(params, reference, aligns, run_dir)
    config = ricp_project.RegistrationProjectConfig(**kwargs)
    try:
        config.validate()
    except ricp_project.RICPConfigurationError as exc:
        raise AdapterError("invalid project configuration - {0}".format(exc)) from None

    for note in notes:
        print("adapter: note: " + note, flush=True)
    print("adapter: RegistrationProjectConfig " + json.dumps(
        {k: (list(v) if isinstance(v, tuple) else v) for k, v in kwargs.items()}, default=str),
        flush=True)

    result = ricp_project.run_registration_project(config, on_progress=on_progress)

    record = _project_record(result, kwargs, notes)
    with open(run_dir / PROJECT_RESULT_NAME, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, default=str)
    _stamp_run_manifest(run_dir, result.status)

    for line in project_summary_lines(result, kwargs, notes):
        print(line, flush=True)

    if result.status in ("failed", "cancelled"):
        lines = ["ERROR: project {0}".format(result.status)]
        if result.error_message:
            lines.append(result.error_message)
        lines.append("Project folder (finished pairs remain for inspection): {0}".format(
            result.project_directory))
        lines.append("Full record: {0}".format(PROJECT_RESULT_NAME))
        _write_error_file(run_dir, lines)
        return 1

    outputs, out_notes = collect_project_outputs(result, run_dir)
    for note in out_notes:
        print("adapter: " + note, flush=True)
    with open(run_dir / OUTPUTS_NAME, "w", encoding="utf-8") as handle:
        json.dump(outputs, handle, indent=2)
    print("adapter: outputs.json -> {0}".format(sorted(outputs)), flush=True)
    return 0


# --------------------------------------------------------------------------- #
# Stable-area validation (post-hoc)
# --------------------------------------------------------------------------- #


def project_directory_from(picked: str) -> Path:
    """The engine's project folder, from any artifact of a previous project run.

    Accepts the folder itself, a file inside it (project_summary.json ...),
    or our ricp_project_result.json at the run-folder root, which records the
    project directory it belongs to.
    """
    if not picked:
        raise AdapterError("project: pick the previous project run's project_summary or project_result artifact")
    node = Path(picked).resolve()
    if node.is_file() and node.name == PROJECT_RESULT_NAME:
        try:
            data = json.loads(node.read_text(encoding="utf-8"))
            candidate = Path(data["engine"]["project_directory"])
        except (OSError, ValueError, KeyError, TypeError):
            raise AdapterError("project: {0} does not name its project directory".format(node)) from None
        if (candidate / "project_summary.json").is_file():
            return candidate
        raise AdapterError("project: project directory {0} is not readable".format(candidate))
    for folder in ([node] if node.is_dir() else []) + list(node.parents):
        if (folder / "project_summary.json").is_file() and (folder / "project_metadata.json").is_file():
            return folder
    raise AdapterError(
        "project: {0} is not inside an R-ICP project folder (no project_summary.json + "
        "project_metadata.json found above it)".format(picked)
    )


def run_validation(args, run_dir: Path) -> int:
    import shutil  # noqa: PLC0415

    try:
        import ricp_project_validation  # noqa: PLC0415
    except ImportError as exc:
        raise AdapterError("ricp_project_validation is not importable: {0}".format(exc)) from None

    project_dir = project_directory_from(args.project)
    manifest = Path(args.manifest) if args.manifest else None
    if manifest is None or not manifest.is_file():
        raise AdapterError("manifest: Browse to your stable_areas.json (user-declared stable cores)")

    print("adapter: validating {0} on user-declared stable areas from {1}".format(project_dir, manifest), flush=True)
    print("adapter: residuals include scanner noise, roughness and real change - NOT absolute "
          "registration accuracy, NOT a complete LoD95", flush=True)
    try:
        artifacts = ricp_project_validation.validate_registration_project(project_dir, manifest)
    except ricp_project_validation.RICPConfigurationError as exc:
        raise AdapterError("stable-area validation refused - {0}".format(exc)) from None

    # The engine writes into a new timestamped folder INSIDE the old project
    # directory. Small reports are copied into this run so they can register
    # (decided 2026-09-21); the engine's folder and the PLY maps stay in place.
    copied: dict[str, str] = {}
    for key in ("stable_validation", "stable_validation_text", "stable_validation_csv"):
        source = artifacts.get(key)
        if source and Path(source).is_file():
            target = run_dir / Path(source).name
            shutil.copy2(source, target)
            copied[key] = target.name
    source_note = run_dir / "stable_validation_source.txt"
    source_note.write_text(
        "Copies of the engine's stable-area validation reports.\n"
        "Engine validation folder (also holds the signed-distance PLY maps):\n"
        "  {0}\n"
        "Project directory:\n  {1}\nManifest:\n  {2}\n"
        "Residuals include scanner noise, surface roughness and any real surface change;\n"
        "they are not absolute registration accuracy and not a complete LoD95.\n".format(
            Path(artifacts["stable_validation"]).parent if "stable_validation" in artifacts else "?",
            project_dir, manifest),
        encoding="utf-8",
    )
    outputs: dict[str, list[str]] = {}
    report = [copied[k] for k in ("stable_validation", "stable_validation_text") if k in copied]
    if report:
        outputs["stable_validation"] = report + [source_note.name]
    if "stable_validation_csv" in copied:
        outputs["stable_validation_table"] = [copied["stable_validation_csv"]]
    with open(run_dir / OUTPUTS_NAME, "w", encoding="utf-8") as handle:
        json.dump(outputs, handle, indent=2)
    try:
        status = json.loads(Path(artifacts["stable_validation"]).read_text(encoding="utf-8")).get("status")
    except (OSError, ValueError, KeyError):
        status = None
    print("adapter: stable-area validation status: {0}; engine folder: {1}".format(
        status, Path(artifacts["stable_validation"]).parent), flush=True)
    return 0


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
    parser.add_argument("--project", default="")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--aligns", nargs="*", default=[])
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

    if args.action in ("register_project", "validate_stable_areas"):
        try:
            if args.action == "register_project":
                return run_project(args, params, run_dir, on_progress)
            return run_validation(args, run_dir)
        except AdapterError as exc:
            print("ERROR: {0}".format(exc), file=sys.stderr, flush=True)
            _write_error_file(run_dir, "ERROR: {0}".format(exc))
            return 2

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
