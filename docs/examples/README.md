# docs/examples/ — the engine contract, by example

`engine.yaml` + `params_example.json` are the **reference pair** for sessions
3–7. Copy them into `engines/<name>/` and adapt; every field of schema v1 is
present and commented.

They are not a real engine — nothing here is ever executed. `tests/` load both
files and assert they validate, so they can never drift away from the loader in
`app/rockslope_studio/core/`.

## Checking your own manifest

```bat
conda activate rockslope
python -c "import sys; sys.path.insert(0,'app'); from rockslope_studio.core import load_manifest, load_params; e=load_manifest('engines/preprocess/engine.yaml'); print(e.id, e.action_ids); [load_params(e.params_path(a)) for a in e.actions if a.params]"
```

Anything invalid raises `ManifestError` / `ParamsError` with the file, the
location inside it, and what was wrong.

## The two rules that bite most often

1. **`id` must equal the engine's folder name.** `engines/preprocess/` holds
   `id: preprocess`. (The check runs during discovery, which is why this
   example — living in `docs/examples/` — is allowed to be called `example`.)
2. **A `default`, `min` or `max` in a params file is numeric behaviour.**
   Rule 2 of `CLAUDE.md`: it may not be changed without Mohammad's explicit
   confirmation in that session.
