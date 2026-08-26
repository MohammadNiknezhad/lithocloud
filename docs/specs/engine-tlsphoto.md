# Engine spec — tlsphoto (Session 3)

**Source (read-only):** `../tlsphoto` — mature package with CLI, tests, SPEC v0.5.
**This session builds:** `engines/tlsphoto/engine.yaml` + `params_*.json` files
+ (only if needed) a thin `adapter.py`. **Zero changes inside ../tlsphoto.**

## Actions (from `tlsphoto/cli.py` — verify against `--help` during the session)

| action | CLI subcommand | inputs (artifacts) | outputs | interactive |
|---|---|---|---|---|
| `ingest` | `ingest --role tls\|photo` | raw file(s) (user-picked path or `pointcloud`) | `pointcloud` (canonical .laz) + manifest | no |
| `register` | `register` | tls `pointcloud`, photo `pointcloud` | `pointcloud` (registered) + `transform` + `report` | possibly (verify) |
| `fuse` | `fuse` | registered tls + photo `pointcloud` | `pointcloud` (fused, layered) + `report` | no |
| `compare` | `compare --old --new` | two fuse-run folders | `table` + `report` | no |
| `export` | `export` | `pointcloud` | text file (`table`) | no |
| `split` | `split --fuse-dir` | legacy fuse run | layered `pointcloud`s | no |
| `info` | `info` | `pointcloud` | `report` (stdout capture) | no |

- Params JSONs: enumerate each subcommand's arguments from `cli.py` argparse
  (names, defaults, choices, help) — transcribe faithfully, do not invent or
  "improve" defaults. Expose the memory knob `--chunk-size` as an advanced param.
- `run.command`: `{python} -m tlsphoto {action} ...` with `cwd` = `../tlsphoto`
  (module import from the sibling repo; no pip install).
- The launcher (`launcher.py` + `launcher_settings.py`) stays untouched and
  remains Mohammad's manual workflow; the studio calls the CLI only.
  **Never read, write, or copy `launcher_settings.py`.**

## Open question for Mohammad (ask at session start)

- Which register/fuse parameters does he want visible in the form vs. fixed at
  his calibrated values (FUSE_MODE="max_tls", FUSE_TOLERANCE=0.05, FUSE_QMAX=0.20,
  FUSE_AXIAL_MAX_DEG=50.0) as defaults?

## Acceptance

- Engine appears via core discovery; every action validates against the
  session-1 manifest schema.
- Dry proof on a tiny sample: `ingest` runs end-to-end from a generated command
  line identical (string-compare) to a hand-written correct command.
- `pytest` for the adapter's command-building (no cloud data needed in CI).

## Out of scope

Any edit under `../tlsphoto` · UI work · fusing real site data (Mohammad's job,
through the app, later).
