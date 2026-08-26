# Session 2 — Shell core (first working window)

**Scope:** the PySide6 shell over the session-1 core library. No engine
manifests yet (session 3+); development uses `docs/examples/engine.yaml` and a
`demo` engine (a harmless script that sleeps, prints progress, writes a small
CSV — lives in `engines/_demo/`, excluded from real discovery by its `_` prefix
unless a dev flag is on).

## Windows & flow

1. **Start / project dialog** — create project: name + workspace folder chosen
   by the user via folder picker (decision D4), written to `project.json`;
   open project: pick an existing `project.json`; recent-projects list.
2. **Main window, three zones** (architecture §8):
   - left: artifact tree from `core.artifacts.scan_project()` — grouped by
     type, tooltip shows lineage (engine, action, params summary, inputs);
     refresh button; "show in Explorer" context action.
   - center: engine list (from discovery) → action picker → **auto-generated
     form** from the action's params JSON (float/int/str/bool/choice widgets,
     defaults, min/max, help tooltips) + input-artifact pickers filtered by
     type → Run button.
   - bottom/right: job panel — live log view (subprocess stdout/stderr),
     status, elapsed time, Cancel (terminate process tree), job history for
     this project (read from `runs/`).
3. **Execution** — `QProcess`/subprocess per architecture §5: build the command
   from the manifest template, run with the engine's `cwd`, one job at a time
   (queue further requests), write run `manifest.json` + `_DONE.json` via the
   core lib, register output artifacts on success.
   Interactive engines (`interactive: true`): launch in a **new console
   window** (Windows `CREATE_NEW_CONSOLE`) so `input()` prompts and matplotlib
   windows behave exactly as today; the studio still owns the run folder and
   registers artifacts on exit.
4. **"Open in CloudCompare"** — context action on pointcloud artifacts; path to
   CloudCompare.exe found via settings dialog (stored in a per-user settings
   file, not in the repo).

## Non-goals / boundaries

- No science logic; no plotting; no 3D (session 8 = figures/tables viewers,
  v2 = embedded 3D).
- Shell imports `rockslope_studio.core` only — never engine internals.
- Keep it light: standard widgets, no styling framework, cold start < 2 s.

## Acceptance

- On Windows: create project → run `_demo` engine twice (one normal, one
  cancelled) → artifacts + lineage appear correctly; job history correct;
  crash injected into `_demo` does NOT crash the shell (failed run shown, no
  `_DONE.json`, no artifact registration).
- `pytest` (with `pytest-qt`) covering: form generation from params JSON,
  command building, queueing, failure handling.
- Mohammad clicks through it and signs off before session 3.
