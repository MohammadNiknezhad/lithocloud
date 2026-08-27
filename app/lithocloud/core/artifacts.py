"""Artifacts and their provenance sidecar.

Every output file the studio knows about is an **artifact** with recorded
lineage: which engine, which version, which action, which parameters, which
input artifacts (docs/architecture.md section 4). That is what makes any figure
in a paper reproducible.

Layout inside a run folder::

    runs/2026-08-26_1432_ricp_register/
    ├── registered.laz
    ├── transform.json
    ├── manifest.json
    ├── _DONE.json
    └── _artifacts/
        ├── 2026-08-26_1432_ricp_register__registered/provenance.json
        └── 2026-08-26_1432_ricp_register__transform/provenance.json

One folder per artifact, so the sidecar can keep the name ``provenance.json``
even when a run produces several artifacts. ``files`` are stored **relative to
the run folder**, so a project workspace can be moved or copied without
breaking a single link.

Artifact ids are readable and stable: ``<run folder name>__<output key>``. Run
folder names are unique within a workspace, so ids are too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, Union

from ._util import atomic_write_json, read_json, utc_now_iso
from .manifest import ARTIFACT_TYPES
from .runs import RUNS_DIRNAME, is_done

__all__ = [
    "ARTIFACTS_DIRNAME",
    "PROVENANCE_NAME",
    "PROVENANCE_VERSION",
    "Artifact",
    "ArtifactError",
    "ancestors_of",
    "artifact_id_for",
    "index_by_id",
    "parents_of",
    "read_provenance",
    "scan_project",
    "write_provenance",
]

ARTIFACTS_DIRNAME = "_artifacts"
PROVENANCE_NAME = "provenance.json"
PROVENANCE_VERSION = 1

_ID_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

PathLike = Union[str, Path]


class ArtifactError(ValueError):
    """A provenance record is invalid, missing, or could not be written."""


def artifact_id_for(run_dir: PathLike, key: str) -> str:
    """The canonical id of the artifact produced under *key* by *run_dir*."""
    run_name = Path(run_dir).name
    safe_key = _ID_UNSAFE.sub("-", str(key)).strip("-._")
    if not safe_key:
        raise ArtifactError("artifact key {0!r} is empty after sanitising".format(key))
    return "{0}__{1}".format(run_name, safe_key)


@dataclass(frozen=True)
class Artifact:
    """One result, with the lineage that produced it."""

    artifact_id: str
    type: str
    files: tuple[str, ...]
    engine: str = ""
    engine_version: str = ""
    action: str = ""
    params: Mapping[str, Any] = field(default_factory=dict)
    inputs: tuple[str, ...] = ()
    created: str = ""
    #: Run folder that produced it - set when read from disk, never serialised.
    run_dir: Path | None = None
    provenance_path: Path | None = None

    # -- paths ------------------------------------------------------------- #

    @property
    def paths(self) -> tuple[Path, ...]:
        """Absolute paths of the artifact's files (needs :attr:`run_dir`)."""
        if self.run_dir is None:
            raise ArtifactError(
                "{0}: run_dir is unknown, cannot resolve file paths".format(
                    self.artifact_id
                )
            )
        return tuple((self.run_dir / name).resolve() for name in self.files)

    @property
    def exists(self) -> bool:
        """True when every listed file is present on disk."""
        try:
            return bool(self.files) and all(p.is_file() for p in self.paths)
        except ArtifactError:
            return False

    @property
    def missing(self) -> tuple[Path, ...]:
        """Listed files that are not on disk."""
        try:
            return tuple(p for p in self.paths if not p.is_file())
        except ArtifactError:
            return ()

    # -- serialisation ------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        """Exactly the fields the spec names, in a stable order."""
        return {
            "version": PROVENANCE_VERSION,
            "artifact_id": self.artifact_id,
            "type": self.type,
            "files": list(self.files),
            "engine": self.engine,
            "engine_version": self.engine_version,
            "action": self.action,
            "params": dict(self.params),
            "inputs": list(self.inputs),
            "created": self.created,
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        where: str = "provenance",
        run_dir: Path | None = None,
        provenance_path: Path | None = None,
    ) -> "Artifact":
        if not isinstance(data, Mapping):
            raise ArtifactError(
                "{0}: must be an object, got {1}".format(where, type(data).__name__)
            )

        version = data.get("version", PROVENANCE_VERSION)
        if version != PROVENANCE_VERSION:
            raise ArtifactError(
                "{0}: unsupported provenance version {1!r} (this studio speaks "
                "v{2})".format(where, version, PROVENANCE_VERSION)
            )

        for required in ("artifact_id", "type", "files"):
            if required not in data:
                raise ArtifactError("{0}: missing {1!r}".format(where, required))

        artifact_id = data["artifact_id"]
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ArtifactError("{0}: 'artifact_id' must be a non-empty string".format(where))

        atype = data["type"]
        if atype not in ARTIFACT_TYPES:
            raise ArtifactError(
                "{0}: type {1!r} is not one of {2}".format(
                    where, atype, ", ".join(ARTIFACT_TYPES)
                )
            )

        files = data["files"]
        if not isinstance(files, Sequence) or isinstance(files, str):
            raise ArtifactError("{0}: 'files' must be a list".format(where))
        if not files:
            raise ArtifactError("{0}: 'files' must not be empty".format(where))
        for name in files:
            if not isinstance(name, str) or not name:
                raise ArtifactError("{0}: 'files' entries must be non-empty strings".format(where))

        inputs = data.get("inputs", ())
        if isinstance(inputs, str) or not isinstance(inputs, Sequence):
            raise ArtifactError("{0}: 'inputs' must be a list of artifact ids".format(where))

        params = data.get("params", {})
        if not isinstance(params, Mapping):
            raise ArtifactError("{0}: 'params' must be an object".format(where))

        return cls(
            artifact_id=artifact_id,
            type=atype,
            files=tuple(files),
            engine=str(data.get("engine", "")),
            engine_version=str(data.get("engine_version", "")),
            action=str(data.get("action", "")),
            params=dict(params),
            inputs=tuple(str(item) for item in inputs),
            created=str(data.get("created", "")),
            run_dir=run_dir,
            provenance_path=provenance_path,
        )


# --------------------------------------------------------------------------- #
# Writing / reading one sidecar
# --------------------------------------------------------------------------- #


def write_provenance(
    run_dir: PathLike,
    *,
    type: str,
    files: Iterable[PathLike],
    key: str | None = None,
    artifact_id: str | None = None,
    engine: str = "",
    engine_version: str = "",
    action: str = "",
    params: Mapping[str, Any] | None = None,
    inputs: Iterable[str] | None = None,
    created: str | None = None,
) -> Artifact:
    """Register one artifact produced by *run_dir* and write its sidecar.

    Give either *key* (the action's output key - the id is derived from it) or
    an explicit *artifact_id*. *files* may be absolute or relative to the run
    folder; they are stored relative and must exist and lie inside the run
    folder.

    Returns the :class:`Artifact` that was written.
    """
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise ArtifactError("{0}: no such run folder".format(run_dir))

    if artifact_id is None:
        if key is None:
            raise ArtifactError("write_provenance needs either 'key' or 'artifact_id'")
        artifact_id = artifact_id_for(run_dir, key)

    if type not in ARTIFACT_TYPES:
        raise ArtifactError(
            "type {0!r} is not one of {1}".format(type, ", ".join(ARTIFACT_TYPES))
        )

    relative = _relative_files(run_dir, files, artifact_id)

    artifact = Artifact(
        artifact_id=artifact_id,
        type=type,
        files=relative,
        engine=engine,
        engine_version=engine_version,
        action=action,
        params=dict(params or {}),
        inputs=tuple(str(item) for item in (inputs or ())),
        created=created or utc_now_iso(),
        run_dir=run_dir.resolve(),
    )

    target = run_dir / ARTIFACTS_DIRNAME / artifact_id / PROVENANCE_NAME
    try:
        atomic_write_json(target, artifact.to_dict())
    except OSError as exc:
        raise ArtifactError("{0}: cannot write provenance - {1}".format(target, exc)) from exc

    return replace(artifact, provenance_path=target.resolve())


def _relative_files(
    run_dir: Path, files: Iterable[PathLike], artifact_id: str
) -> tuple[str, ...]:
    run_root = run_dir.resolve()
    out: list[str] = []
    for item in files:
        path = Path(item)
        absolute = path if path.is_absolute() else run_dir / path
        absolute = absolute.resolve()
        if not absolute.is_file():
            raise ArtifactError(
                "{0}: file {1} does not exist".format(artifact_id, absolute)
            )
        try:
            rel = absolute.relative_to(run_root)
        except ValueError:
            raise ArtifactError(
                "{0}: file {1} is outside its run folder {2} - an artifact must live "
                "in the run that produced it".format(artifact_id, absolute, run_root)
            ) from None
        out.append(rel.as_posix())
    if not out:
        raise ArtifactError("{0}: no files given".format(artifact_id))
    return tuple(out)


def read_provenance(path: PathLike) -> Artifact:
    """Read one ``provenance.json``.

    *path* may be the sidecar itself or the artifact folder containing it.
    """
    path = Path(path)
    if path.is_dir():
        path = path / PROVENANCE_NAME
    try:
        data = read_json(path)
    except FileNotFoundError as exc:
        raise ArtifactError("{0}: no such provenance file".format(path)) from exc
    except ValueError as exc:
        raise ArtifactError(str(exc)) from exc

    # <run_dir>/_artifacts/<artifact_id>/provenance.json  ->  <run_dir>
    run_dir = path.parent.parent.parent.resolve()
    return Artifact.from_dict(
        data, where=str(path), run_dir=run_dir, provenance_path=path.resolve()
    )


# --------------------------------------------------------------------------- #
# Scanning a workspace
# --------------------------------------------------------------------------- #


def scan_project(
    workspace: PathLike, *, include_unfinished: bool = False
) -> list[Artifact]:
    """Every artifact in ``<workspace>/runs``, with its lineage.

    Runs without ``_DONE.json`` are skipped unless *include_unfinished* is true:
    a failed or interrupted run must not contribute artifacts to the project
    (that is the point of the completion marker).

    Sorted by ``created`` then ``artifact_id``, so the order is stable. A
    sidecar that cannot be read is skipped rather than breaking the scan - the
    project tree must always open.
    """
    runs_root = Path(workspace) / RUNS_DIRNAME
    artifacts: list[Artifact] = []
    if not runs_root.is_dir():
        return artifacts

    for run_dir in sorted(p for p in runs_root.iterdir() if p.is_dir()):
        if not include_unfinished and not is_done(run_dir):
            continue
        artifacts_dir = run_dir / ARTIFACTS_DIRNAME
        if not artifacts_dir.is_dir():
            continue
        for folder in sorted(p for p in artifacts_dir.iterdir() if p.is_dir()):
            sidecar = folder / PROVENANCE_NAME
            if not sidecar.is_file():
                continue
            try:
                artifacts.append(read_provenance(sidecar))
            except ArtifactError:
                continue

    artifacts.sort(key=lambda a: (a.created, a.artifact_id))
    return artifacts


# --------------------------------------------------------------------------- #
# Lineage
# --------------------------------------------------------------------------- #


def index_by_id(artifacts: Iterable[Artifact]) -> dict[str, Artifact]:
    """``{artifact_id: artifact}`` for lineage lookups."""
    return {a.artifact_id: a for a in artifacts}


def parents_of(
    artifact: Artifact, index: Mapping[str, Artifact]
) -> tuple[list[Artifact], list[str]]:
    """Direct inputs of *artifact*, split into ``(resolved, unresolved_ids)``.

    An id can be unresolved for a good reason - a file the user picked from
    ``raw/`` was never produced by a run - so it is returned, not dropped.
    """
    resolved: list[Artifact] = []
    unresolved: list[str] = []
    for input_id in artifact.inputs:
        parent = index.get(input_id)
        if parent is None:
            unresolved.append(input_id)
        else:
            resolved.append(parent)
    return resolved, unresolved


def ancestors_of(
    artifact: Artifact, index: Mapping[str, Artifact]
) -> list[Artifact]:
    """Every artifact *artifact* descends from, nearest first, each once.

    Cycles cannot happen in a real workspace (a run's inputs always predate it)
    but the walk guards against them anyway - a corrupted sidecar must not hang
    the shell.
    """
    seen: set[str] = {artifact.artifact_id}
    out: list[Artifact] = []
    queue: list[Artifact] = [artifact]
    while queue:
        current = queue.pop(0)
        for parent in parents_of(current, index)[0]:
            if parent.artifact_id in seen:
                continue
            seen.add(parent.artifact_id)
            out.append(parent)
            queue.append(parent)
    return out
