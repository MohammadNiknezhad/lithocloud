# Engine spec — ricp v2 (rebuild the plug for ricp-engine 0.2.0)

**Why:** Mohammad rewrote ricp. The repo now ships `ricp_engine.py` — a typed
UI boundary (`RegistrationConfig`, `run_registration`, `RegistrationResult`) —
plus `ENGINE_GUIDE.md` describing exactly how a UI should call it. The session-5
plug was built for the old command-line script and no longer matches: its
parameters (`--ci`, `--max-levels`, `--polish`, ...) are gone, and its
`_coarse_only()` mirror of ricp internals is obsolete.

**Scope: this repo only.** `../ricp` is read-only, as always. No science is
reimplemented here; the adapter becomes a translator: studio params in,
`RegistrationConfig` out, `outputs.json` back.

## Decisions

- **Actions: ONE action, `register`** (assumed — Mohammad did not pick, and
  this is the simplest reading of ENGINE_GUIDE section 4). The "rerun after
  reviewing a poor coarse result" case is the SAME action with `coarse_matrix`
  supplied or `accept_poor_coarse` ticked — no second action needed. If he
  later wants a separate button, it is a manifest-only change.
- **Outputs: the recommended method plus the reports** (his choice), not all
  three methods.
- **Install: editable** — `pip install -e .` of `../ricp/ricp` into the
  `rockslope` env, per ENGINE_GUIDE section 2. Drop the `sys.path` insertion.

## The API this plug must use (transcribed 2026-09-08, do not guess)

```python
from ricp_engine import RegistrationConfig, run_registration
result = run_registration(config, on_progress=callback)   # synchronous
```

`RegistrationConfig` fields and defaults:

| field | default |
|---|---|
| `reference`, `align`, `output_directory` | required paths |
| `fine_method` | `"all"` — one of `paper-c2c`, `local-plane`, `m3c2`, `all` |
| `stability_seeds` | `(0, 1, 2)` — guide recommends `range(10)` for final runs |
| `seed` | `0` |
| `reference_precision_mm`, `align_precision_mm` | `0.0` (unknown -> LoD warning) |
| `registration_uncertainty_mm` | `None` |
| `coarse_mode` | `"auto"` (`auto` / `gui` / `none`) |
| `coarse_review` | `"never"` (`always` / `if-poor` / `never`) |
| `accept_poor_coarse` | `False` |
| `coarse_matrix` | `None` (path to a 4x4) |
| `coarse_parameters` | `None` (four floats) |
| `fit_tilt` | `True` |
| `target_points` | `"auto"` |
| `max_registration_points`, `max_evaluation_points` | ricp defaults |
| `dense_report_points` | `"auto"` (or `"off"`, or an int) |
| `overlap` | `"auto"` (or `"off"`, or a float) |
| `report_thresholds_mm` | `"auto"` |
| `comparison_equivalence_mm` | `"auto"` |
| `extra_arguments` | `()` |

`RegistrationResult`: `status`, `exit_code`, `succeeded`, `run_directory`,
`methods: dict[str, MethodResult]`, `recommended_method`, `comparison_outcome`,
`artifacts: dict[str, Path]`, `log`, `error_message`, `as_dict()`.

`MethodResult`: `method`, `status`, `directory`, `transform`, `transform_path`,
`registered_cloud_path`, `quality_metrics_path`, `report_path`,
`registration_uncertainty_1sigma_m`, `final_registration_error_95_m`,
`lod95_registration_complete`, `uncertainty_reliability`.

`result.artifacts` keys seen in the engine: `coarse_report`,
`coarse_overlay_top`, `coarse_overlay_side`, `method_comparison`,
`method_transform_differences`, `sampling_stability`,
`registration_uncertainty`. Read them from the result, never by guessing
filenames.

Inputs accepted: `.las .txt .xyz .csv .pts .asc`. **`.laz` is rejected by
`validate()`** — keep the existing adapter step that decompresses a chosen
`.laz` into the run folder and passes the `.las` copy.

## engine.yaml (rewrite)

- `version: 0.2.0` (track `ricp-engine`).
- One action `register`, `interactive: false` (the subprocess the studio
  already uses satisfies the guide's "worker process" rule).
- Inputs: `reference` (pointcloud), `align` (pointcloud),
  `coarse` (transform, optional).
- Outputs: `registered` (pointcloud), `transform` (transform),
  `uncertainty` (report), `comparison` (report), `plots` (figure).
- Delete the `coarse` and `register_gui` actions and `params_coarse.json`.

## params_register.json

One field per `RegistrationConfig` entry above, faithful names/defaults, with
help text. Notes:

- `stability_seeds` as a text field, default `"0,1,2"`, help mentioning
  `0,1,2,3,4,5,6,7,8,9` for a final run.
- the two `*_precision_mm` fields must say in their help: calibrated one-sigma
  sensor/control precision, NOT point spacing, C2C mean, or registration
  error; leave 0 if unknown and the report will say the LoD statement is
  incomplete.
- `output_directory` is not a parameter — the adapter passes the studio run
  folder.

## adapter.py (rewrite, much smaller)

1. read params + input paths; convert a `.laz` input to `.las` in the run
   folder; build `RegistrationConfig(output_directory=<run_dir>, ...)`;
2. `run_registration(config, on_progress=lambda line: print(line, flush=True))`
   so the log panel streams progress;
3. on failure: write `adapter_error.txt` with `result.error_message` and,
   when they exist, the paths of `coarse_overlay_top` / `coarse_overlay_side`
   so the operator knows where to look before rerunning with a reviewed
   matrix; return the exit code;
4. on success: pick `result.recommended_method`, or the single method when
   only one ran; write `outputs.json` with paths **relative to the run folder**:
   `registered` -> that method's `registered_cloud_path`,
   `transform` -> its `transform_path`,
   `uncertainty` -> `artifacts["registration_uncertainty"]`,
   `comparison` -> `artifacts["method_comparison"]`,
   `plots` -> the PNGs the result reports;
5. also dump `result.as_dict()` to `<run_dir>/ricp_result.json` — a complete
   record for later inspection, and what a future viewer panel will read.

Delete `_coarse_only()` and every test that asserted its equivalence with
`transform_coarse.txt`; that contract no longer exists.

## Acceptance

- Unit tests with a stub `ricp_engine` module (no heavy compute): params ->
  `RegistrationConfig` mapping including every default, and
  result -> `outputs.json` mapping for: all-methods run, single-method run,
  failed run, and a run where the recommended method is absent.
- `pytest` green; nothing under `../ricp` modified (assert in a test).
- One real smoke run by Mohammad on a small pair, checking that progress
  streams into the log panel and the five artifacts register.

## Out of scope

Any edit inside `../ricp` · viewers for the new JSON reports (a later polish
item) · exposing all three methods as artifacts (his decision was recommended
method only).
