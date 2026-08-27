<p align="center">
  <img src="branding/png/lithocloud-lockup-800.png" alt="LithoCloud" width="420">
</p>

# LithoCloud

**See into the rock — LiDAR, photogrammetry, machine learning**

Mohammad Niknezhad · ÉTS Montréal

---

A light desktop studio that turns raw LiDAR and photogrammetric scans of rock
slopes into registered, fused, classified and hazard-mapped results — each
pipeline an independent **engine**, every result carrying its full provenance.

The studio itself contains **zero science logic**. Each pipeline is wrapped
behind a small `engine.yaml` manifest, runs as a **subprocess**, and writes its
results into the project workspace as **artifacts** with full provenance. That
is why any engine can be changed, split, or rewritten without touching the UI
or the other engines.

```
Shell (PySide6)  ──manifest──▶  Engine (subprocess)  ──▶  Artifacts (+ provenance)
```

## Engines

| Engine | Source | Role |
|---|---|---|
| `tlsphoto` | `../tlsphoto` (own repo) | ingest, register, fuse, compare, topview |
| `ricp` | `../ricp/ricp` (own repo) | R-ICP registration |
| `geohazard` | `../geohazard-pipeline` (own repo) | structure & hazard stages |
| `condition` | here | intensity correction, GMM clustering |
| `preprocess` | here | vegetation filter, subsample, crop, convert |

The first three keep their own GitHub repositories and live beside this one in
`Projects/`; this repo holds only their manifest + adapter.

## Project workspace

```
<project>/
├── raw/                       original files — the studio never modifies them
├── runs/
│   └── 2026-08-26_1432_ricp_register/
│       ├── ...output files
│       ├── _artifacts/<artifact_id>/provenance.json
│       ├── manifest.json      engine, version, action, params, inputs, exit code
│       └── _DONE.json         completion marker (successful runs only)
└── project.json               name, CRS note, workspace path
```

## Install

```bat
conda env create -f environment.yml
conda activate rockslope
```

## Launch the studio

From an Anaconda Prompt with the `rockslope` env active:

```bat
lithocloud.bat
```

The conda environment is still named `rockslope` — it predates the rename and
was deliberately left alone so a working environment did not have to be
rebuilt. `run_studio.bat` still works as a shim for one release.

(or `set PYTHONPATH=app` then `python -m lithocloud`). Add `--dev` to
also see `_`-prefixed development engines such as `engines/_demo/`; add
`--project <folder>` to skip the start dialog. The CloudCompare path for the
"Open in CloudCompare" context action is set in File ▸ Settings.

## Run the tests

```bat
conda activate rockslope
pytest
```

**Activate the environment — do not call `python.exe` by its full path.** The
`rockslope` env's `Library\bin` holds the BLAS DLLs; without activation any
numpy matrix multiply dies with a Windows DLL error (`0xC06D007F`), which takes
the ricp engine down with it.

## Documentation

- **[docs/architecture.md](docs/architecture.md)** — the approved design (v1.0). The authority for this repo.
- **[docs/specs/](docs/specs/)** — one spec per implementation session.
- **[docs/examples/](docs/examples/)** — reference `engine.yaml` + params JSON that every engine must validate against.
- **[CLAUDE.md](CLAUDE.md)** — the non-negotiable rules for every Claude Code session here.

## Status

Sessions 1 (scaffold + core library) and 2 (shell: first working window,
subprocess job runner, auto-forms) complete. Real engine manifests arrive in
sessions 3–7; results viewers in session 8.

Engine contract note (decided 2026-08-27): on success an engine writes
`<run_dir>/outputs.json` = `{"<output_key>": ["file", ...]}` (paths relative to
the run folder); the shell registers artifacts from it. A declared key missing
from the file is a warning, not a failure.

## How to cite

If LithoCloud contributes to work you publish, please cite it. Machine-readable
metadata is in [CITATION.cff](CITATION.cff); GitHub renders a ready-made
citation from it under **Cite this repository**.

> Niknezhad, M. (2026). *LithoCloud* (version 0.1.0) [Computer software].
> École de technologie supérieure (ÉTS), Montréal, Canada.
> https://github.com/MohammadNiknezhad/lithocloud

The wrapped pipelines have their own repositories and their own citations —
cite those as well when a result depends on them.

## License

MIT — see [LICENSE](LICENSE). ÉTS Montréal appears as the author's affiliation
only; it is not an endorsement.
