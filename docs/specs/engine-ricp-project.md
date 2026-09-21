# Spec — ricp multi-cloud projects (project API 0.3.0) + stable-area validation

**Verified 2026-09-21 against `../ricp/ricp` at main = 7247c30** (ENGINE_GUIDE.md
§5–§7, `ricp_project.py`, `ricp_project_validation.py`). Mohammad's requirement
list (2026-09-21) is the source of intent; this spec pins it to the real API and
to this codebase. Two parts, committed separately: Part 1 is shell
(`app/lithocloud/`), Part 2 is the ricp plug (`engines/ricp/`). `../ricp` stays
read-only; the existing unchanged-against-HEAD test must keep passing. The
single-pair `register` action keeps working exactly as it does today.

## Verified API surface (transcribed, do not guess)

- `ricp_project.PROJECT_API_VERSION == "0.3.0"`;
  `ricp_engine.ENGINE_API_VERSION == "0.4.0"` (additive MethodResult fields:
  `observable_rank`, `required_observable_rank`, `observability_complete`,
  `scaled_information_condition`, `fitting_tolerance_m`,
  `fitting_tolerance_is_registration_uncertainty`).
- `RegistrationProjectConfig(reference, aligns, output_directory, mode,
  fine_method, overlap_edges=(), stability_seeds=(0,1,2), seed=0,
  reference_precision_mm=0.0, align_precision_mm=0.0,
  align_precisions_mm=None, registration_uncertainty_mm=None,
  coarse_mode="auto", coarse_review="always", accept_poor_coarse=False,
  fit_tilt=True, target_points="auto", max_registration_points=…,
  max_evaluation_points=…, dense_report_points="auto", overlap="auto",
  report_thresholds_mm="auto", extra_arguments=(), continue_on_error=True,
  stable_validation_manifest=None)`.
- `fine_method` is `ProductionFineMethod` — **the API itself rejects "all"**.
- `run_registration_project(config, on_progress) -> RegistrationProjectResult`
  — synchronous, sequential, **no cancellation hook parameter**.
- `RegistrationProjectResult`: `status` ∈ completed | partial | cancelled |
  failed, `mode`, `project_directory`, `fine_method`, `pairs` (each wraps a full
  single-pair `RegistrationResult`), `scans`, `artifacts: dict[str, Path]`,
  `stable_validation_status` (default "not-requested"), `error_message`.
- `ProjectScanResult`: `scan_index` (0 = REF), `path`, `status`,
  `global_transform`, `transform_path`, `registered_cloud_path`,
  `uncertainty_status` (a sentence — display it verbatim; multiway deliberately
  withholds a per-scan number).
- `validate_registration_project(project_directory, manifest) -> dict[str, Path]`
  — post-hoc, never reruns registration; repeated runs never overwrite.
  Manifest: `normal_radius_m`, `projection_radius_m`, `max_depth_m` (all
  required positive), `min_valid_cores` (default 30, ≥ 2), `areas[]` with
  `name`, `core_points` (path relative to the JSON, coordinates in the FINAL
  REF frame), `pairs[[i,j],…]`. Per area/pair metrics: `signed_mean_m`,
  `signed_median_m`, `signed_std_m`, `robust_spread_m` (1.4826·MAD),
  `p95_absolute_m`, valid-core coverage; insufficient support is reported as
  unavailable, never zero.
- Graph reporting: `pose_graph_edges.csv` with
  `postfit_p95_point_displacement_m` (label: "95th-percentile transform
  disagreement" — NOT surface error), `consistency_metric`, SUSPECT flag
  (= unresolved loop disagreement, not proven edge failure), legacy
  `postfit_site_error_m` / truthful `postfit_extent_heuristic_m` (never the
  headline number).

## Integration decisions

1. **Coarse review**: `coarse_review="always"` opens the pair application's own
   Tk checkpoint per pair; the guide requires the host to run the worker where
   that window can show. Our interactive-action path (adapter subprocess in its
   own console; Tk/matplotlib windows work) is exactly that context — so the
   project action is `interactive: true` and there is **no blocker**. Never
   pass `coarse_review="never"` or `accept_poor_coarse=True` by default; the
   operator gate stays.
2. **Responsiveness**: the adapter subprocess IS the worker; the engine runs
   pairs sequentially inside it. No new threading in the shell.
3. **Cancellation**: the API has no graceful-cancel hook. Cancel stays the
   existing tree-kill. Consequence, stated in the action description: a killed
   project registers no artifacts, but every finished pair's folder remains on
   disk inside the run folder for inspection; the engine's own
   `status="cancelled"` only arises when a pair is cancelled at its checkpoint.
4. **Exit policy / partial**: adapter exit 0 for `completed` AND `partial`
   (usable clouds must register), nonzero for `failed`/`cancelled`. A partial
   run must be unmistakable: log banner `=== PROJECT PARTIAL — n of m pairs
   succeeded ===`, `project_status` in the run-manifest `extra`, and the same
   status at the top of `ricp_project_result.json`. Never word partial as
   success.
5. **Two `outputs.json` files exist and must not be confused**: the engine
   writes its own inside `project_directory` (a timestamped subfolder the
   engine creates under our run folder, like geohazard's nested native run);
   the shell contract file stays at the run-folder root, written by the
   adapter.
6. **Artifacts registered** (project action): per-scan registered cloud
   (`registered_scan<i>`, pointcloud) and global transform
   (`transform_scan<i>`, transform) for scans with both on disk;
   `project_summary` (report), `pose_graph_edges` (table, multiway),
   engine `outputs.json` (report), `project_result` = our
   `ricp_project_result.json` (report). Validation action: the
   `stable_validation` JSON/TXT as report + CSV as table; the signed-distance
   PLY maps are named by path inside the report, not forced into the artifact
   type system.
7. **Fine-method params**: reuse Amendment A2 exactly — `fine_method` choice
   (paper-c2c / local-plane / m3c2, NO "all"), `plane_radius` and
   `m3c2_core_points` frequently-used with the same tooltips and
   `visible_when`, other M3C2 fields in Advanced, same bounds (core ≥ 100,
   scale ≥ 1), same token mapping through `extra_arguments`, generated tokens
   before user extras.
8. **Observability (ENGINE_API 0.4.0)**: when any pair's method reports
   `observability_complete is False`, print a warning line naming the pair and
   include the fields in `ricp_project_result.json`. `fitting_tolerance_m` may
   appear only under a "Fitting diagnostics" heading, never as uncertainty.

## Part 1 — shell (`app/lithocloud/` only)

- **Ordered multi-file inputs**: the multiple-input picker becomes an ordered
  list — numbered rows, Up/Down reorder, remove; the row number is shown. The
  ricp plug labels REF as index 0 and the align rows as 1…N in its input help
  text; the shell renders the numbers.
- **New field type `edge_list`**: value = list of `[fixed, moving]` integer
  pairs; widget = two spin-boxes + Add, a table of edges, Remove; rejects
  self-edges and duplicates at Add with a visible message; a hint label under
  the table (text supplied by the params file `help`) — full graph rules stay
  in the adapter. Serializes to JSON; hidden-value preservation and
  `visible_when` work as for every other field.
- Schema/params: `edge_list` joins `FIELD_TYPES`; validation of the stored
  value shape at load; `dump_params` round-trips.
- Tests: reorder round-trip and ordering preserved into `values()`;
  edge-widget add/remove/reject; `edge_list` under `visible_when`.

## Part 2 — ricp plug (`engines/ricp/` only)

Two NEW actions beside the untouched `register`:

**`register_project`** — `interactive: true` (decision 1). Inputs:
`reference` (pointcloud, help: "REF — index 0"), `aligns` (pointcloud,
`multiple: true`, help: "ALIGN scans — indices 1, 2, … in list order").
Params (A2 groups): Frequently used = `mode` (choice independent/multiway),
`fine_method` (three choices, no "all"), `plane_radius`, `m3c2_core_points`,
`stability_seeds`, `seed`, `overlap_edges` (`edge_list`, visible_when mode =
multiway; help carries the connectivity hint including "a chain without an
extra loop cannot check loop consistency"). Advanced = the A2 M3C2 set,
precision fields (labelled user-supplied 1-sigma mm; plus
`align_precisions_mm` as an optional comma list, one value per align, length
validated), `continue_on_error` (default true), the shared engine settings
(`coarse_mode`, `fit_tilt`, `target_points`, `max_*`, `dense_report_points`,
`overlap`, `report_thresholds_mm`), `extra_arguments` last. `coarse_review`
is NOT a form field for this action: pinned to "always" in the adapter
(decision 1); `accept_poor_coarse` stays available but defaults false and its
help says "only after inspecting the coarse overlays".

Adapter: validate the graph before running — indices in range, no self-edges,
no duplicates (either direction counts as the same connection — flag if the
engine disagrees), connected to scan 0; friendly `AdapterError` messages.
Build `RegistrationProjectConfig`, call `run_registration_project` with the
same captured-stdout progress callback pattern as v2; LAZ conversion applies
to every input cloud. Then decisions 4–6: statuses, `ricp_project_result.json`
(config echo, per-pair and per-scan summaries incl. `uncertainty_status` and
observability fields, artifact paths), outputs mapping, log summary that
labels `postfit_p95_point_displacement_m` correctly, prints
`consistency_metric` and any SUSPECT edges with the "unresolved loop
disagreement, not proven pairwise failure" wording, and never headlines
`postfit_site_error_m`.

**`validate_stable_areas`** — `interactive: false`. Inputs: `project`
(report — pick the previous project run's `project_summary` or
`project_result` artifact; walk up to `project_directory` like the geohazard
redo action) and `manifest` (report — Browse to `stable_areas.json`). No
params file needed (the manifest carries the settings). Adapter calls
`validate_registration_project(project_directory, manifest)`, registers the
returned reports (decision 6), and its description states: areas are
user-declared; residuals include noise, roughness and real change — never
absolute registration accuracy; the engine never invents stable areas.

Tests (stub `ricp_project` module; no clouds): config build for both modes
incl. per-scan precisions and edge pass-through; graph validation matrix
(self, duplicate, disconnected, out-of-range, chain-vs-loop hint);
method-token reuse for the three production methods; statuses → exit code +
registration behaviour (completed, partial, cancelled, failed); outputs
mapping incl. nested-vs-root `outputs.json`; coarse-review safety (config
always built with `coarse_review="always"`; no code path can emit "never");
validation action end-to-end against a stub; plus the real-module import
test asserting `PROJECT_API_VERSION == "0.3.0"` so a future engine bump
fails loudly. `../ricp` unchanged. Report exactly which config every mode
sends and any remaining limitations.
