"""Run folders: ``<workspace>/runs/<YYYY-MM-DD_HHMM>_<engine>_<action>/``.

This generalises the convention geohazard-pipeline and ricp already use
(docs/architecture.md section 4):

* one folder per engine run, **never** overwritten - a name that is already
  taken gets a ``_2``, ``_3``, ... suffix;
* ``manifest.json`` records engine id and version, action, params, input
  artifact ids, timestamps and the exit code;
* ``_DONE.json`` is written **only** when the run succeeded, so a folder
  without it is a failed or interrupted run and its outputs must not be
  registered as artifacts.

The timestamp in the folder name is **local time** - it is what Mohammad reads
in Explorer. The timestamps inside ``manifest.json`` are UTC and unambiguous.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, Union

from ._util import atomic_write_json, read_json, safe_token, utc_now_iso

__all__ = [
    "DONE_NAME",
    "MANIFEST_NAME",
    "RUNS_DIRNAME",
    "RUN_MANIFEST_VERSION",
    "RunError",
    "RunRecord",
    "create_run_dir",
    "finish_run",
    "is_done",
    "list_runs",
    "read_run_manifest",
    "run_dir_name",
    "write_run_manifest",
]

RUNS_DIRNAME = "runs"
MANIFEST_NAME = "manifest.json"
DONE_NAME = "_DONE.json"
RUN_MANIFEST_VERSION = 1

_STAMP_FMT = "%Y-%m-%d_%H%M"

PathLike = Union[str, Path]


class RunError(RuntimeError):
    """A run folder could not be created, written or read."""


# --------------------------------------------------------------------------- #
# Creating the folder
# --------------------------------------------------------------------------- #


def run_dir_name(
    engine: str, action: str, when: _dt.datetime | None = None, *, suffix: int = 1
) -> str:
    """Build the folder name ``2026-08-26_1432_ricp_register``.

    *when* defaults to now, in local time. *suffix* > 1 appends ``_<suffix>``,
    which is how collisions inside the same minute are resolved.
    """
    stamp = (when or _dt.datetime.now()).strftime(_STAMP_FMT)
    name = "{0}_{1}_{2}".format(stamp, safe_token(engine), safe_token(action))
    if suffix > 1:
        name = "{0}_{1}".format(name, suffix)
    return name


def create_run_dir(
    workspace: PathLike,
    engine: str,
    action: str,
    *,
    when: _dt.datetime | None = None,
    max_attempts: int = 999,
) -> Path:
    """Create and return a fresh run folder. Never returns an existing folder.

    The folder is created with ``os.mkdir``, which fails if the name is taken,
    so two studios writing into the same workspace cannot collide.
    """
    runs_root = Path(workspace) / RUNS_DIRNAME
    try:
        runs_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RunError("cannot create {0} - {1}".format(runs_root, exc)) from exc

    when = when or _dt.datetime.now()
    for suffix in range(1, max_attempts + 1):
        candidate = runs_root / run_dir_name(engine, action, when, suffix=suffix)
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        except OSError as exc:
            raise RunError("cannot create {0} - {1}".format(candidate, exc)) from exc
        return candidate

    raise RunError(
        "could not find a free run folder name under {0} after {1} attempts".format(
            runs_root, max_attempts
        )
    )


# --------------------------------------------------------------------------- #
# manifest.json / _DONE.json
# --------------------------------------------------------------------------- #


def write_run_manifest(
    run_dir: PathLike,
    *,
    engine: str,
    engine_version: str,
    action: str,
    params: Mapping[str, Any] | None = None,
    inputs: Mapping[str, Any] | Sequence[str] | None = None,
    command: str | None = None,
    cwd: PathLike | None = None,
    started: str | None = None,
    finished: str | None = None,
    exit_code: int | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Path:
    """Write (or rewrite) ``manifest.json`` in *run_dir*.

    *inputs* may be a mapping ``{input_key: artifact_id | [artifact_id, ...]}``
    or a plain list of artifact ids; both are stored as given so the shell can
    show which artifact filled which slot.

    ``exit_code`` is ``None`` while the run is in flight and is filled in by
    :func:`finish_run`.
    """
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise RunError("{0}: no such run folder".format(run_dir))

    payload: dict[str, Any] = {
        "version": RUN_MANIFEST_VERSION,
        "engine": engine,
        "engine_version": engine_version,
        "action": action,
        "params": dict(params or {}),
        "inputs": _normalise_inputs(inputs),
        "started": started or utc_now_iso(),
        "finished": finished,
        "exit_code": exit_code,
    }
    if command is not None:
        payload["command"] = command
    if cwd is not None:
        payload["cwd"] = str(cwd)
    if extra:
        overlap = set(extra) & set(payload)
        if overlap:
            raise RunError(
                "extra may not override {0}".format(", ".join(sorted(overlap)))
            )
        payload.update(extra)

    try:
        return atomic_write_json(run_dir / MANIFEST_NAME, payload)
    except OSError as exc:
        raise RunError("{0}: cannot write manifest - {1}".format(run_dir, exc)) from exc


def _normalise_inputs(inputs: Any) -> Any:
    if inputs is None:
        return {}
    if isinstance(inputs, Mapping):
        return {str(key): value for key, value in inputs.items()}
    if isinstance(inputs, (list, tuple)):
        return [str(item) for item in inputs]
    raise RunError("inputs must be a mapping or a list, got {0}".format(type(inputs).__name__))


def read_run_manifest(run_dir: PathLike) -> dict[str, Any]:
    """Read ``manifest.json`` from a run folder."""
    path = Path(run_dir)
    if path.name != MANIFEST_NAME:
        path = path / MANIFEST_NAME
    try:
        data = read_json(path)
    except FileNotFoundError as exc:
        raise RunError("{0}: no run manifest".format(path)) from exc
    except ValueError as exc:
        raise RunError(str(exc)) from exc
    if not isinstance(data, dict):
        raise RunError("{0}: run manifest must be an object".format(path))
    return data


def finish_run(
    run_dir: PathLike,
    exit_code: int,
    *,
    finished: str | None = None,
    outputs: Iterable[str] | None = None,
    message: str = "",
) -> Path | None:
    """Record the end of a run.

    Updates ``exit_code`` and ``finished`` in ``manifest.json`` and, **only for
    ``exit_code == 0``**, writes ``_DONE.json``. Returns the path of the
    ``_DONE.json`` that was written, or ``None`` for a failed run.
    """
    run_dir = Path(run_dir)
    stamp = finished or utc_now_iso()

    try:
        manifest = read_run_manifest(run_dir)
    except RunError:
        manifest = {}
    manifest["exit_code"] = int(exit_code)
    manifest["finished"] = stamp
    if outputs is not None:
        manifest["outputs"] = [str(item) for item in outputs]
    atomic_write_json(run_dir / MANIFEST_NAME, manifest)

    if exit_code != 0:
        return None

    done: dict[str, Any] = {
        "version": RUN_MANIFEST_VERSION,
        "finished": stamp,
        "exit_code": 0,
    }
    if outputs is not None:
        done["outputs"] = [str(item) for item in outputs]
    if message:
        done["message"] = message
    return atomic_write_json(run_dir / DONE_NAME, done)


def is_done(run_dir: PathLike) -> bool:
    """True when the run completed successfully (``_DONE.json`` exists)."""
    return (Path(run_dir) / DONE_NAME).is_file()


# --------------------------------------------------------------------------- #
# Listing
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RunRecord:
    """One run folder, as the job-history panel needs it."""

    path: Path
    name: str
    engine: str = ""
    engine_version: str = ""
    action: str = ""
    params: Mapping[str, Any] = field(default_factory=dict)
    inputs: Any = field(default_factory=dict)
    started: str = ""
    finished: str | None = None
    exit_code: int | None = None
    done: bool = False
    problem: str = ""

    @property
    def succeeded(self) -> bool:
        return self.done and self.exit_code == 0

    @property
    def running(self) -> bool:
        """No exit code yet and no ``_DONE.json`` - in flight, or interrupted."""
        return self.exit_code is None and not self.done


def list_runs(workspace: PathLike) -> list[RunRecord]:
    """Every run folder in ``<workspace>/runs``, sorted by name.

    The folder name starts with the timestamp, so name order is time order.

    A folder with a missing or unreadable ``manifest.json`` is still returned,
    with ``problem`` set - the job history must show interrupted runs too.
    """
    runs_root = Path(workspace) / RUNS_DIRNAME
    records: list[RunRecord] = []
    if not runs_root.is_dir():
        return records

    for folder in sorted(p for p in runs_root.iterdir() if p.is_dir()):
        done = is_done(folder)
        try:
            data = read_run_manifest(folder)
        except RunError as exc:
            records.append(
                RunRecord(path=folder, name=folder.name, done=done, problem=str(exc))
            )
            continue
        records.append(
            RunRecord(
                path=folder,
                name=folder.name,
                engine=str(data.get("engine", "")),
                engine_version=str(data.get("engine_version", "")),
                action=str(data.get("action", "")),
                params=data.get("params") or {},
                inputs=data.get("inputs") or {},
                started=str(data.get("started", "")),
                finished=data.get("finished"),
                exit_code=data.get("exit_code"),
                done=done,
            )
        )
    return records


