# CLAUDE.md — rules for every Claude Code session in LithoCloud

This repo is the **shell (studio)** that hosts Mohammad's rock-slope point-cloud
pipelines as independent engines. Read `docs/architecture.md` (v1.0, approved)
before doing anything. Your session's scope is defined by ONE spec file in
`docs/specs/` — Mohammad will tell you which one.

## Hard rules — non-negotiable

1. **One module per session.** Work only inside the package/folder your spec
   names. Do not edit any file outside it (docs updates for your module are OK).
2. **Never change algorithm logic, parameter defaults, seeds, tolerances,
   output columns, or numeric behaviour without Mohammad's explicit
   confirmation in this session.** This includes "small improvements" and
   "obvious fixes". Propose in writing → wait for his yes → then implement.
3. **Restructuring must prove equivalence** (architecture §11): run the old
   code on `data_samples/`, store golden outputs, run the new code, outputs
   must match (bit-identical, or a documented numeric tolerance). Only then may
   the old entry point be retired. The old file remains in git history.
4. **Boundaries:** engines never import the shell or other engines; the shell
   never imports engine internals. Communication is ONLY
   manifest → subprocess → artifacts.
5. **Sibling repos are other projects.** `../tlsphoto`, `../ricp`,
   `../geohazard-pipeline` are read-only from a LithoCloud session.
   Adapter code lives HERE, under `engines/<name>/`. Never write into the
   siblings; never modify `launcher_settings.py` anywhere.
6. **Unclear spec? Stop and ask.** If the spec conflicts with what you find in
   the code, report the conflict to Mohammad — do not guess, do not "fix" it.
7. **Dependencies:** ask before adding any. `environment.yml` is the single
   source of the shared `rockslope` env.
8. **Git:** small commits, clear messages, never force-push, never create or
   push to GitHub repos unless Mohammad asks in this session.
9. **End of session:** list what changed, what was tested, and what remains.
   Mohammad reviews before the next session starts.

## Project shape

```
lithocloud/
├── app/lithocloud/     shell: core lib (session 1), UI (session 2), viewers (session 8)
├── engines/
│   ├── tlsphoto/             adapter + engine.yaml only  (code in ../../tlsphoto)
│   ├── ricp/                 adapter + engine.yaml only  (code in ../../ricp/ricp)
│   ├── geohazard/            adapter + engine.yaml only  (code in ../../geohazard-pipeline)
│   ├── condition/            full engine package (scripts moved from condition_classification)
│   └── preprocess/           full engine package (new)
├── docs/architecture.md      the approved design — the authority for this repo
├── docs/specs/               one spec per session
└── data_samples/             small frozen clouds for equivalence checks
```

## Environment facts

Windows 11 · 16 GB RAM · conda env `rockslope` (Python 3.11) · Spyder user.
Point clouds reach ~200 M points: never load a full cloud into the UI process;
engines stream/chunk as they already do. UI = PySide6. All subprocess calls
must work from a plain Anaconda Prompt.
