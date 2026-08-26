# Engine spec — geohazard (Session 4)

**Source (read-only):** `../geohazard-pipeline` — staged package
(`01_ingest → 02_orientation → 03_facets → 04_edges → 05_stereonet → 06_hazard`)
with run manager, checkpoints, `--resume`/`--redo`.
**This session builds:** `engines/geohazard/engine.yaml` + params JSONs +
thin adapter. **Zero changes inside ../geohazard-pipeline.**

## Actions

Model each run as ONE action `run` with stage control, mirroring the real CLI
(`python -m geohazard_pipeline.main INPUT [--config J] [--to STAGE] [--resume RUN]
[--redo STAGE] [--runs-dir D] [--tag T] [--yes]`):

| action | inputs | key params | outputs | interactive |
|---|---|---|---|---|
| `run` | `pointcloud` (.txt/.csv/.las/.laz) | `to_stage` (choice of 6), `tag`, `batch(--yes)` + config overrides | per-stage artifacts (see below) | **yes** — column mapping + north confirm |
| `redo_stage` | previous run (pick from job history) | `redo` stage choice + config overrides | updated stage artifacts | possibly |

- `--runs-dir` is pointed at the studio project's `runs/` so geohazard's native
  run folders ARE the studio's run folders (same convention — no duplication).
- Config overrides: the params JSON mirrors `PipelineConfig` fields
  (`config.py`, read-only transcription of names/defaults/help); the adapter
  writes them to a temp JSON passed as `--config`. Expose only fields Mohammad
  confirms at session start; the rest stay at pipeline defaults.
- Interactivity: launch attached to a console window (architecture §7) so the
  column-mapping and north confirm-or-stop prompts work exactly as today.
  `--yes` exposed as a "batch mode" checkbox.

## Output artifact registration (after the subprocess exits)

Scan the run folder's stage subfolders and register: facet/joint-set `table`s,
stereonet `figure`s (.png), hazard `map` layers, plus the run `manifest.json`
as `report`. Registration is read-only bookkeeping — files are not moved.

## Acceptance

- Manifest validates; command building unit-tested (string-compare against
  hand-written correct commands for: fresh run to 03; resume+redo 05).
- One real tiny-cloud smoke run with Mohammad present, confirming prompts
  appear and artifacts register with correct lineage.

## Out of scope

Any edit under `../geohazard-pipeline` · converting its readers to canonical
LAZ (future, optional, needs Mohammad's approval) · UI work.
