"""Demo engine - dev only, zero science.

Sleeps, prints progress lines, writes a small CSV, and demonstrates the
outputs.json contract the shell registers artifacts from. Stdlib only: this
file must run under any Python the studio hands it.

Called by the studio as (see engine.yaml):

    python demo_engine.py run --params <params.json> --out <run_dir> --previous=<file|empty>
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def load_params(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_outputs(run_dir: Path, mapping: dict) -> None:
    """The contract (decided 2026-08-27): <run_dir>/outputs.json maps each
    declared output key to the files produced for it, relative to run_dir."""
    with open(run_dir / "outputs.json", "w", encoding="utf-8") as handle:
        json.dump(mapping, handle, indent=2)


def action_run(run_dir: Path, params: dict, previous: str) -> int:
    seconds = float(params.get("seconds", 3.0))
    steps = int(params.get("steps", 6))
    rows = int(params.get("rows", 20))
    mode = params.get("mode", "normal")
    message = params.get("message", "")

    print("demo: {0}".format(message), flush=True)
    if previous:
        print("demo: continuing from {0}".format(previous), flush=True)

    crash_at = steps // 2 if mode == "crash" else -1
    for step in range(1, steps + 1):
        time.sleep(seconds / steps)
        print("progress {0}/{1}".format(step, steps), flush=True)
        if step == crash_at:
            print("demo: injected crash (mode=crash)", file=sys.stderr, flush=True)
            return 3  # no outputs.json, no artifact - the shell must survive

    csv_path = run_dir / "stats.csv"
    with open(csv_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("# {0}\n".format(message))
        handle.write("row,value\n")
        for row in range(rows):
            handle.write("{0},{1}\n".format(row, row * row))

    write_outputs(run_dir, {"stats": ["stats.csv"]})
    print("demo: wrote {0} rows".format(rows), flush=True)
    return 0


def action_ask(run_dir: Path, params: dict, previous: str) -> int:
    """Interactive: a real input() prompt, as the wrapped pipelines have."""
    print("demo (interactive): {0}".format(params.get("message", "")), flush=True)
    try:
        answer = input("Type a short note and press Enter: ")
    except EOFError:
        # No console attached (e.g. launched non-interactively in a test):
        # behave deterministically instead of hanging.
        answer = "(no console attached)"

    note_path = run_dir / "note.txt"
    with open(note_path, "w", encoding="utf-8") as handle:
        handle.write(answer + "\n")

    write_outputs(run_dir, {"note": ["note.txt"]})
    print("demo: note saved", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["run", "ask"])
    parser.add_argument("--params", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--previous", default="")
    args = parser.parse_args(argv)

    run_dir = Path(args.out)
    params = load_params(args.params)

    if args.action == "run":
        return action_run(run_dir, params, args.previous)
    return action_ask(run_dir, params, args.previous)


if __name__ == "__main__":
    sys.exit(main())
