# How to change an engine (or add one)

The everyday answer to "I want to change something — where do I go?".

## Three boxes

1. **The science** — the algorithms, in their own folders:
   `../tlsphoto`, `../ricp/ricp`, `../geohazard-pipeline` (each its own GitHub
   repo), and `engines/condition`, `engines/preprocess` inside this repo.
2. **The plug** — `engines/<name>/`: `engine.yaml` (actions, inputs, outputs),
   `params_*.json` (what the form shows), `adapter.py` (builds the command,
   writes `outputs.json`). No science here.
3. **The app** — `app/lithocloud/`: window, artifact tree, job runner. No
   science here either.

Changing box 1 leaves boxes 2 and 3 alone, as long as the engine still takes
the same kind of input and produces the same kind of output. That is the whole
point of the design.

## Where does my change belong?

| I want to... | Folder to open Claude Code in | Also needed? |
|---|---|---|
| change how an algorithm works | that engine's own repo | nothing, if inputs/outputs/CLI flags are unchanged |
| add a new option (new CLI flag) | that engine's own repo | then a short session here: add the field to `params_*.json`, pass it in `adapter.py` |
| show/hide/rename a form field | this repo, `engines/<name>/` | no — the science is untouched |
| add a new action (e.g. split one action into four) | usually both repos | one session each, never mixed |
| add a whole new engine | new `engines/<name>/` here (+ its own repo if large) | none — discovery finds it at startup |
| change the app (viewers, tree, buttons) | this repo, `app/` | no engine is touched |

## The recipe

1. **Decide first** — discuss in the Cowork chat; a spec goes in `docs/specs/`.
2. **Open Claude Code in the folder that owns the change** (one folder per
   session — never let a session reach into a sibling repo).
3. **State permission explicitly** for anything that alters behaviour:
   *"I approve this logic change: ... Keep everything else identical. Run the
   current code on sample data first and save the outputs, then show me the
   difference."*
4. **Test in the app** — `lithocloud.bat`, run that engine on a small cloud.
   Old runs stay on disk, so old and new results can be compared.
5. **Commit and push in that repo** — each repo has its own history.
6. **Report back** in the Cowork chat; the decision gets recorded.

## Rules that keep this safe

- No algorithm, default, seed or tolerance changes without the explicit
  permission sentence in that session (CLAUDE.md rule 2).
- Every behaviour change gets a before/after comparison on the same data.
- One folder per session; boxes never reach into each other.
