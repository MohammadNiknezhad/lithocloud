# Engine spec — condition (Session 6)

**Source:** `Projects/condition_classification/` — two standalone scripts:

- `Intensity_correction_l1_v6.py` (692 lines) — L1/Livox reflectivity residual
  range + incidence correction; configured by a module-level `CONFIG = {...}`
  dict; non-interactive `main(cfg)`.
- `Gmm_interactive_v8.3.py` (1,146 lines) — two-stage interactive GMM condition
  clustering (geometric → radiometric), neutral cluster vocabulary, boundary
  editor, expert component mapping; fully console-driven (`input()` prompts);
  `RANDOM_STATE = 42`.

**This session builds:** `engines/condition/` as a FULL engine package in the
monorepo — the scripts' new permanent home.

## Step 1 — move, unchanged

Copy both scripts into `engines/condition/` byte-identical (git shows the
import). The originals in `condition_classification/` are retired by Mohammad
himself after acceptance — the session never deletes them.

## Step 2 — manifest

| action | wraps | inputs | outputs | interactive |
|---|---|---|---|---|
| `intensity_correction` | Intensity_correction_l1_v6 | `pointcloud` + trajectory file(s) (sbet.txt) | `pointcloud` (with corrected-intensity fields) + `report` (self-verification stats) | no (config-driven) |
| `gmm_clustering` | Gmm_interactive_v8.3 | `pointcloud` (file path prompt) | labelled `pointcloud` + `report` (run_config) + `figure`s | **yes** — console prompts throughout |

v1 launch strategy (architecture §7): both run attached to a console exactly as
today. For `gmm_clustering` the user answers the prompts (path, columns, K,
boundaries, expert mapping) in that console; the studio contributes the run
folder, log capture, and artifact registration only.

**Known v1 limitation to record in the manifest description:** both scripts
currently choose their own input/output paths (CONFIG dict / prompts), so v1
registration scans the folders they report at exit.

## P1 / P2 — DECLINED by Mohammad (2026-08-27)

Both shims were offered and **not** approved. Wrap the scripts exactly as they
are: no `--config` override for the intensity correction, no pre-answered
prompts for the GMM. Consequences to accept and document in the manifest:

- both actions are `interactive: true` and run in their own console window;
- the intensity correction is configured by editing its in-file `CONFIG` dict
  (the studio does not send parameters); the params file for that action
  therefore stays empty or absent;
- the GMM action is driven entirely by its console prompts, as today;
- reruns are reproducible only through the run record (the scripts' own
  `run_config` output), not by replaying the form.

Do not add argv shims, config overrides, or prompt replay unless Mohammad
asks for them in a later session.

## Open questions for Mohammad (ask at session start)

- The journal paper's Stage-1 **Random Forest** classifier: does that code
  exist somewhere, and should it become a third action later?
- Sample data: which small cloud (+ trajectory) becomes the frozen
  `data_samples/` case for the equivalence check?

## Acceptance

- Package importable; manifest validates; both actions launch from a plain
  Anaconda Prompt via the manifest command and behave exactly as the originals
  (same prompts, same outputs on the sample data — compared against a run of
  the untouched originals).

## Out of scope

Any algorithm/parameter/seed change (P1/P2 included, without approval) ·
deleting the original scripts · UI work.
