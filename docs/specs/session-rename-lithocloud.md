# Session R — Rename to LithoCloud

**Scope:** rename the product and the Python package, add the identity block
(About dialog, README header, CITATION.cff), keep git history and every
existing project working. **No behaviour changes to any engine or to the
job/artifact logic.**

## The name (decided by Mohammad, 2026-08-27)

```
LithoCloud
See into the rock — LiDAR, photogrammetry, machine learning
Mohammad Niknezhad · ÉTS Montréal
```

- Product name (display): **LithoCloud**, one word, capital L and C.
- Python package: `lithocloud` (lower case).
- Repository: `MohammadNiknezhad/lithocloud`.
- ÉTS appears **only as plain-text attribution** ("ÉTS Montréal"), never in a
  logo or in the product name — it is an affiliation, not an endorsement.
  Never use ÉTS colours, wordmark or logo files.

## 1. In-repo changes (this session)

1. **Package**: `git mv app/rockslope_studio app/lithocloud`; update every
   `rockslope_studio` import in `app/` and `tests/` (engine adapters import
   nothing from the shell — verify that stays true).
2. **Launcher**: `run_studio.bat` → `lithocloud.bat`, PYTHONPATH line updated.
   Keep the old file for one release as a two-line shim calling the new one.
3. **Titles**: `main_window.py` and `start_dialog.py` window titles →
   `LithoCloud`; `app.py` `setApplicationName("LithoCloud")`.
4. **QSettings** (`ui/settings.py`): `_ORG` stays `MohammadNiknezhad`;
   `_APP` changes `rockslope-studio` → `LithoCloud`. **Migrate on first run**:
   if the new store is empty and the old one exists, copy recent projects and
   remembered folders across, so Mohammad does not lose his recent-project
   list. One small function, unit-tested.
5. **Version**: add `__version__` to `app/lithocloud/__init__.py` (start at
   `0.1.0`) — the About box and run manifests read it.
6. **About dialog**: new `Help ▸ About LithoCloud` showing the three identity
   lines above plus version, license (MIT), the GitHub URL, and a "Copy
   diagnostics" button (versions of Python, PySide6, numpy, laspy — useful
   when something breaks). Plain Qt, no images yet; the logo comes later and
   will slot into this dialog.
7. **CITATION.cff** (new, repo root): `cff-version: 1.2.0`, title
   `LithoCloud`, authors → family-names `Niknezhad`, given-names `Mohammad`,
   affiliation `École de technologie supérieure (ÉTS), Montréal, Canada`,
   ORCID **left as a TODO comment — ask Mohammad for it**, license `MIT`,
   repository-code URL, `type: software`.
8. **LICENSE**: copyright line → `Copyright (c) 2026 Mohammad Niknezhad`
   (spaced, as a person's name).
9. **pyproject.toml**: add a `[project]` table — name `lithocloud`, version,
   description (the tagline), authors, license, `requires-python = ">=3.11"`.
   Keep the existing pytest config.
10. **README**: new header with the identity block, the tagline, one sentence
    on what the studio is, and an "How to cite" section pointing at
    CITATION.cff. Update every `rockslope-studio` mention.
11. **Docs**: `CLAUDE.md`, `docs/architecture.md`, `docs/examples/*`,
    `docs/specs/*` — replace `rockslope-studio` with `LithoCloud` (repo name
    `lithocloud`) and `rockslope_studio` with `lithocloud`. Keep the history
    honest: add one line at the top of architecture.md noting the project was
    called rockslope-studio until 2026-08-27.
12. **environment.yml**: env name stays `rockslope`? **Ask Mohammad** — my
    recommendation is to rename it to `lithocloud` for consistency and tell
    him the one-time command to recreate it; if he prefers not to rebuild the
    env now, leave it and note it in the README.

## 2. Outside the repo (Mohammad does these, this session tells him when)

- **GitHub**: repo Settings → Rename to `lithocloud` (GitHub keeps redirects
  from the old URL). Then in the repo: `git remote set-url origin
  https://github.com/MohammadNiknezhad/lithocloud.git`.
- **Local folder**: close Claude Code and the studio, rename
  `Projects\rockslope-studio` → `Projects\lithocloud` in Explorer, reopen.
  (Windows cannot rename a folder that a running process is inside.)
  Engine adapters locate sibling repos by folder *position*, not by this
  repo's name, so nothing breaks.

## 3. Acceptance

- `pytest` fully green after the rename (no `rockslope_studio` left anywhere
  except the historical note and the compatibility shim).
- The studio launches from `lithocloud.bat`, the title bar says LithoCloud,
  About shows the identity block and the right version.
- The existing `studio-test` project opens with its artifacts and history
  intact, and the recent-projects list survived the QSettings migration.
- One engine run still works end to end (geohazard to 03_facets, or demo).

## Out of scope

The logo (a later, separate task — the About dialog and README are written so
a mark can be dropped in without rework) · any engine behaviour · any change
to run folders, provenance, or manifests already written on disk.
