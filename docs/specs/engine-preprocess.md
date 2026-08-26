# Engine spec — preprocess (Session 7) — DRAFT, needs Mohammad's input

**Status: incomplete by design.** This is the only engine written from scratch,
so its algorithm section must be filled by Mohammad (from his Claude chats and
papers) BEFORE implementation. The session's first step is to finalize this
spec with him and get his written approval of the algorithm descriptions.

**This session builds:** `engines/preprocess/` as a full engine package.

## Planned actions (v1 candidates — Mohammad confirms the list)

| action | purpose | inputs | outputs | interactive |
|---|---|---|---|---|
| `vegetation_filter` | remove face-hugging vegetation | `pointcloud` (RGB and/or intensity) | cleaned `pointcloud` + rejected-points `pointcloud` + `report` | maybe (threshold preview?) |
| `subsample` | voxel / random / spacing-target subsampling | `pointcloud` | `pointcloud` | no |
| `crop` | bounding-box (and later polygon) crop | `pointcloud` | `pointcloud` | maybe |
| `convert` | format conversion (delegates to tlsphoto ingest/export where possible — do not duplicate) | file | file | no |

## To be specified by Mohammad before coding (placeholders)

- **vegetation_filter algorithm:** GLI greenness ratio combined with
  fine-scale roughness (his replacement for failed return-count filtering on
  L1 data). Needed from him: exact GLI formula/thresholds, roughness
  definition (neighborhood radius, metric), combination rule, defaults
  calibrated on Francon L1 data, and what "rejected" output must contain.
- **subsample:** which methods he actually uses (voxel size? minimum spacing?)
  and whether any must preserve extra columns exactly.
- **crop:** is bbox enough for v1?
- Common: chunked processing pattern (follow his existing chunked-KDTree
  conventions), memory ceiling, LAS extra-dims preservation rules.

## Principles (fixed)

- Always writes NEW artifacts; never modifies inputs.
- Chunked/streaming; must handle ~200 M-point clouds on 16 GB RAM.
- Preserves every input column unless the action's spec says otherwise.
- Unit tests with small synthetic clouds; deterministic (fixed seeds).

## Acceptance

Written after the algorithm section is approved — must include: synthetic-data
unit tests per action + one real-sample validation reviewed by Mohammad.

## Out of scope

Anything not listed by Mohammad in the finalized action list · UI work ·
touching other engines.
