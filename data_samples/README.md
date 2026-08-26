# data_samples/

Small, **frozen** real inputs used by the equivalence protocol
(`docs/architecture.md` §11).

## Why this folder exists

Rule 3 of `CLAUDE.md`: *restructuring must prove equivalence*. Before any
existing pipeline is moved or split, it is run **as it is today** on the files
in this folder and its outputs are stored as the golden reference. The
restructured code must then reproduce those outputs — bit-identical, or within
a tolerance that is written down in the engine's spec — before the old entry
point may be retired.

## Rules

- **Mohammad chooses the samples.** They must be real data, but small enough to
  run in seconds and to live in git (guideline: a few MB each).
- Samples are **frozen**: never re-generated, never "cleaned up", never
  re-exported. Changing a sample invalidates every golden output taken from it.
- Point-cloud extensions are in `.gitignore` (`*.laz`, `*.las`, ...). A sample
  that is meant to be committed must be force-added:
  `git add -f data_samples/<file>`.
- Golden outputs live next to the engine that produced them, not here.

## Layout

```
data_samples/
├── README.md          this file
└── <engine>/          one folder per engine that needs samples, added when needed
```

Empty for now — the sample clouds are added by Mohammad.
