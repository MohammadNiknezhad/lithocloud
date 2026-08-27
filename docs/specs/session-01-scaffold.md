# Session 1 — Scaffold: repo, environment, core library

**Scope:** create the repository skeleton and the small core library that every
later session builds on. **No UI, no engine wrapping, no science code.**

## 1. Repository skeleton

Create in `Projects/lithocloud/` (this folder already contains CLAUDE.md
and docs/ — keep them):

- `git init`, first commit; `.gitignore` for Python (+ `runs/`, `*.laz`, `.spyproject`).
- `README.md` — short: what the studio is, link to docs/architecture.md.
- `LICENSE` — ask Mohammad which license (his other repos have one; match it unless he says otherwise).
- Folders per CLAUDE.md "Project shape": `app/lithocloud/`, `engines/<5 names>/` (empty except `.gitkeep`), `data_samples/` (with a README explaining its purpose; actual sample clouds are added by Mohammad later).
- GitHub remote `MohammadNiknezhad/LithoCloud`: create/push **only if Mohammad confirms in the session**.

## 2. environment.yml

Env name `rockslope`, Python 3.11. Conda deps: numpy, scipy, pandas,
matplotlib, scikit-learn, pyyaml, jsonschema. Pip deps: `laspy[lazrs]`,
`PySide6`. Nothing else without asking. Verify: `conda env create` works on
Windows/Anaconda and `python -c "import laspy, PySide6"` succeeds.

## 3. Core library — `app/lithocloud/core/`

Pure-Python, no Qt imports, fully unit-tested. Four small modules:

**a) `manifest.py`** — load + validate `engine.yaml`. Schema (v1):

```yaml
id: str            # unique, folder name
name: str
version: str
actions:           # list
  - id: str
    label: str
    interactive: bool        # true → runs attached to a console window
    inputs:  [{key, type, multiple?: bool, optional?: bool}]
    outputs: [{key, type}]
    params: str              # relative path to params JSON (may be absent)
run:
  command: str     # template; placeholders {python} {action} {params_file} {run_dir} {input:<key>}
  cwd: str         # relative to the engine folder (adapters point at sibling repos)
```

Artifact types (closed list v1): `pointcloud, transform, table, figure, map, report, model`.
Discovery: `find_engines(root) -> list[Engine]` scans `engines/*/engine.yaml`;
a broken manifest is reported, never crashes discovery.

**b) `params.py`** — load a params JSON (per action): ordered fields with
`{key, label, type: float|int|str|bool|choice, default, min?, max?, choices?, help}`.
This file is what the future UI turns into a form. Validate values against it.

**c) `runs.py`** — create run folders `<workspace>/runs/<YYYY-MM-DD_HHMM>_<engine>_<action>/`
(collision-safe suffix), never overwrite; write `manifest.json` (engine id,
version, action, params, input artifact ids, timestamps, exit code) and
`_DONE.json` on success — the same convention geohazard-pipeline and ricp use.

**d) `artifacts.py`** — provenance sidecar `provenance.json` per artifact:
`{artifact_id, type, files[], engine, engine_version, action, params, inputs[], created}`.
`scan_project(workspace) -> list[Artifact]` walks `runs/` and returns everything
with lineage links. Round-trip tested.

Also `project.py`: `project.json` = `{name, crs_note, workspace_path}` — created
by "new project", workspace path **chosen by the user** (decision D4).

## 4. Acceptance (all must pass)

- `pytest` green on Windows; tests cover: manifest validation (good + broken),
  params round-trip, run-folder naming under collisions, provenance scan on a
  fabricated fake workspace.
- A `docs/examples/engine.yaml` + `params_example.json` pair that validates —
  used as the reference by sessions 3–7.
- Nothing imports PySide6 inside `core/`.

## Out of scope

UI (session 2) · any engine.yaml for real engines (sessions 3–7) · viewers
(session 8) · touching sibling repos (never).
