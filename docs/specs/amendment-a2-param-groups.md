# Amendment A2 — parameter groups, conditional fields, and the ricp method parameters

**Requested by Mohammad, 2026-09-19.** Two sessions, in this order: **A** is a
shell feature (every engine gets it), **B** is the ricp plug. Do not mix them —
they live in different boxes (see `docs/HOWTO-change-an-engine.md`).

**No R-ICP engine logic changes.** `../ricp` stays read-only in both sessions.

---

## Findings that shape this work (verified 2026-09-19)

1. **The params schema has no grouping or visibility.** `core/params.py`
   accepts exactly `key, label, type, default, min, max, choices, help` and
   rejects anything else; `ui/param_form.py` renders one flat `QFormLayout`
   row per field. So "frequently used / advanced" and "show only for the
   selected method" are **new shell capabilities**, not ricp settings.
2. **`RegistrationConfig` has no typed field for the method parameters.**
   `--plane-radius`, `--m3c2-core-points`, `--m3c2-normal-radius`,
   `--m3c2-projection-radius`, `--m3c2-max-depth`, `--m3c2-scale-mode`,
   `--m3c2-max-scale-factor` and `--m3c2-max-levels` exist only as `ricp.py`
   command-line flags. The supported route is `extra_arguments`, which
   `RegistrationConfig.to_argv()` appends verbatim as separate tokens — exactly
   the "one token per argument, no quotes, no commas" requirement.
3. **Sensor precision is already typed**: `reference_precision_mm`,
   `align_precision_mm` and `registration_uncertainty_mm` map to
   `--m3c2-reference-precision-mm`, `--m3c2-align-precision-mm` and
   `--m3c2-registration-uncertainty-mm`. They are always emitted by `to_argv()`
   with the engine defaults (`0.0`, `0.0`, `auto`), which is identical to not
   passing them. **Do not try to suppress them** for non-M3C2 methods — only
   hide them in the form. Suppressing them would mean changing the engine API.
4. **There is no command preview in the studio** for ricp v2 (it calls the API,
   not a command line), and **input files and the output directory are not
   params** — they are input slots and the run folder. Those parts of the
   request are already satisfied by construction.

---

## Session A — shell: field groups and conditional visibility

**Folder: `app/lithocloud/` only.** Backwards compatible: every existing params
file keeps working unchanged.

### A1. `core/params.py` — params schema v2

Add three optional keys to a field, all validated, all ignorable by old files:

| key | meaning |
|---|---|
| `group` | section title, e.g. `"Frequently used"` / `"Advanced"`. Absent = the first, untitled section. |
| `collapsed` | on the FIRST field of a group: that section renders collapsed. |
| `visible_when` | `{"field": "<other key>", "in": ["value", ...]}` — the row shows only while that field's current value is in the list. |

Rules to enforce at load time, with clear messages:

- `visible_when.field` must name another field **in the same file**, must not
  be the field itself, and must not form a cycle;
- the controlling field must be of type `choice` or `bool`;
- groups keep the order in which they first appear; fields keep file order
  inside their group.

`ParamSpec` gains helpers the UI needs: `groups()` (ordered), `fields_in(group)`,
and `is_visible(key, values)`. `dump_params` round-trips the new keys.
Validation of values is unchanged: **a hidden field is still validated and
still present in `values()`** — hiding is a display concern only.

### A2. `ui/param_form.py` — grouped, collapsible, reactive

- Render one section per group. A section with a title gets a `QGroupBox`;
  `collapsed: true` renders it collapsed (checkable group box, unchecked =
  contents hidden) and the state is remembered per engine+action in QSettings.
- After building, connect every controlling widget's change signal to a
  re-evaluation that shows/hides dependent rows (label **and** widget).
- **Hidden rows keep their values.** Never reset, clear, or re-default a field
  because it became hidden; switching method away and back shows exactly what
  the user typed. `values()` keeps returning every field.
- `set_values()` / `reset_to_defaults()` re-evaluate visibility afterwards.

### A3. Acceptance (Session A)

- `pytest` green, including new tests for: schema validation (good file, unknown
  key, bad `visible_when` target, cycle, non-choice controller); visibility
  evaluation; hidden-value preservation across two toggles; collapsed state;
  and an existing engine's params file rendering unchanged.
- No engine folder touched.

---

## Session B — ricp plug: the method parameters

**Folder: `engines/ricp/` only.** `../ricp` read-only (keep the existing test
that asserts it is unchanged).

### B1. `params_register.json` — regroup and extend

Group 1 — **Frequently used** (no `group` key, or `"Frequently used"`):
`fine_method`, `stability_seeds`, `seed`, plus the two new fields:

| key | label | type | default | visible_when `fine_method` in | tooltip |
|---|---|---|---|---|---|
| `plane_radius` | Plane radius (m) | str (empty = engine default) | `""` | `local-plane`, `all` | "Neighborhood radius used to fit local planes." |
| `m3c2_core_points` | M3C2 core points | str (empty = engine default) | `""` | `m3c2`, `all` | "Number of representative locations used by the M3C2-guided registration. More points increase coverage and processing time." |

Group 2 — **Advanced**, `collapsed: true` on its first field. Everything else,
in this order: the M3C2 block (`m3c2_normal_radius`, `m3c2_projection_radius`,
`m3c2_max_depth`, `m3c2_scale_mode`, `m3c2_max_scale_factor`,
`m3c2_max_levels`, then the three precision/uncertainty fields), all with
`visible_when: fine_method in [m3c2, all]`; then the method-independent
settings already present (`coarse_*`, `fit_tilt`, `target_points`,
`max_registration_points`, `max_evaluation_points`, `dense_report_points`,
`overlap`, `report_thresholds_mm`, `comparison_equivalence_mm`); and
`extra_arguments` **last**, always visible, as the expert fallback.

New Advanced field defaults — empty means "engine default", and the help text
must state what that default is (from `ricp.py --help`, transcribed, not
invented): plane radius 4× measured spacing; normal radius 6×; projection
radius 4×; max depth 10×; scale mode `adaptive`; max scale factor 4; max
levels 5; core points 5000.

`m3c2_scale_mode` is a `choice` with `["", "adaptive", "fixed"]` where `""`
means "engine default".

### B2. `adapter.py` — map the method fields to `extra_arguments` tokens

A new pure function, unit-tested:

```
method_argument_tokens(params) -> list[str]
```

- emits nothing for a field left empty (engine default applies — never invent
  a value);
- emits `--plane-radius <value>` only when `fine_method` is `local-plane` or
  `all`; `--m3c2-*` flags only when `fine_method` is `m3c2` or `all`;
- one token per element: `["--plane-radius", "0.35"]`. No quotes, no commas,
  no joined strings;
- **validation before the run**, with an `AdapterError` naming the field.
  Bounds mirror `ricp.py`'s own checks (corrected 2026-09-19, decided by
  Mohammad in-session — the spec's original `> 0` / `≥ 1` bounds were wrong
  versus the engine): radii and depth finite and > 0; core points a whole
  number **≥ 100**; max scale factor finite and **≥ 1**; `m3c2_max_levels` ≥ 1.
- The generated tokens go **before** the user's `extra_arguments` in the final
  sequence, so an expert flag typed by hand wins (argparse takes the last
  occurrence). Say so in the docstring.

`build_config_kwargs` then passes
`extra_arguments = tuple(method_tokens) + tuple(user_tokens)`. Nothing else in
the mapping changes; the precision fields stay typed as they are (finding 3).

### B3. Acceptance (Session B) — the report Mohammad asked for

A test that builds the config from the form defaults for each of the four
methods and asserts the **exact** `to_argv()` token list, then the session
reports those four lists in its summary: what `paper-c2c`, `local-plane`,
`m3c2` and `all` each send, at defaults and with every new field filled in.

Plus: hidden-field values present in the saved `params.json` but absent from
the engine arguments; a wrong value in a hidden field does not block a run of
another method; `pytest` green; `../ricp` unchanged.

---

## Out of scope

Typed fields for these parameters inside `ricp_engine.RegistrationConfig`
(that is a change in Mohammad's own repo — worth asking for later, after which
the adapter would switch from `extra_arguments` to typed fields) · any other
engine's params file · viewers.
