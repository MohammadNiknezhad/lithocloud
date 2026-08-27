# Engine spec — ricp (Session 5: wrap as-is · Session 9: package split)

**Source:** `../ricp/ricp/ricp.py` (2,916 lines, single file) + `test_ricp.py`
+ `PHASE1_FROZEN_SPEC.md` (the frozen behavioural contract).

## Session 5 — wrap as-is (this repo only, zero changes to ricp.py)

One action `register`:

| inputs | outputs | interactive |
|---|---|---|
| `reference` pointcloud, `align` pointcloud, optional `coarse` transform | `pointcloud` (registered full cloud), `transform` (final 4×4), `report` (level table, validation scores, plots) | when `coarse-mode=gui` (SCENE-style picking) |

- Params JSON transcribed from the argparse block (≈ line 2156+): `--ci`,
  `--max-levels`, `--target-points`, `--icp-max-iter`, `--icp-method`,
  `--coarse-mode {auto,gui,none}`, `--coarse` / `--coarse-matrix`,
  `--overlap`, `--sigma-floor`, `--equivalence-margin`, `--no-polish`,
  `--no-tilt-fit`, `--max-tilt`, `--seed`, … Faithful names/defaults; nothing
  renamed, nothing re-defaulted.
- If the studio supplies a `transform` artifact as `coarse`, the adapter passes
  it via `--coarse-matrix` (non-interactive path). Otherwise `coarse-mode`
  decides, and gui runs attached to a console + its matplotlib windows.
- `run.command`: `{python} ricp.py {reference} {align} -o {run_dir} ...`,
  `cwd = ../ricp/ricp`. Its native `run_YYYYMMDD_HHMMSS` folder is created
  inside the studio run dir; artifacts registered from there.
- Acceptance: manifest validates; command building unit-tested; one smoke run
  with Mohammad (gui mode and matrix mode).

## Session 9 — package split (works INSIDE ../ricp — separate rules)

This later session runs in the **ricp repo**, not LithoCloud. Before it
starts: add a CLAUDE.md to the ricp repo (with Mohammad's permission) carrying
the same hard rules. Plan:

1. Golden run first: Mohammad picks 2 small clouds → run current `ricp.py`
   (fixed `--seed`, `coarse-mode=none` + a saved matrix, `--no-polish` off) →
   store outputs as `tests/golden/`.
2. Split into a package following `PHASE1_FROZEN_SPEC.md` — moves and imports
   ONLY: `io`, `coarse`, `overlap`, `ricp_core`, `validation`, `polish`,
   `report`, `cli` (final names agreed with Mohammad at session start).
   `python ricp.py` keeps working as a thin shim during transition.
3. Equivalence: same inputs/seed → outputs must match golden (bit-identical
   target; any float divergence is documented and approved before acceptance).
4. `test_ricp.py` still passes unchanged.
5. Only after Mohammad's sign-off may the shim be retired (or kept — his call).

**His stated intent:** later he may split `register` into smaller actions
(coarse-align → overlap-crop → recursive-filter → polish) and possibly change
logic. Each such change is proposed in writing and confirmed by him first;
the manifest then grows extra actions without any UI work.

## Out of scope (both sessions)

Algorithm changes of any kind without explicit confirmation · editing the
paper-facing docs in the ricp repo · touching other engines or the shell.
