"""``project.json`` - one site (Francon, Camillien-Houde, ...).

Decision D4: the studio **asks the user** where a project workspace lives. The
chosen folder is written into ``project.json`` and remembered per project;
nothing is hard-coded.

The file sits at the top of the workspace::

    <workspace>/
    ├── raw/            original files - the studio never modifies them
    ├── runs/           one folder per engine run
    └── project.json    {"name", "crs_note", "workspace_path"}

``workspace_path`` records where the project was created. If the folder is
later moved or copied, :func:`load_project` trusts **the location of
``project.json`` on disk** instead, so a moved project still opens.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Union

from ._util import atomic_write_json, read_json, utc_now_iso

__all__ = [
    "PROJECT_FILENAME",
    "PROJECT_VERSION",
    "RAW_DIRNAME",
    "Project",
    "ProjectError",
    "create_project",
    "load_project",
    "save_project",
]

PROJECT_FILENAME = "project.json"
PROJECT_VERSION = 1
RAW_DIRNAME = "raw"
RUNS_DIRNAME = "runs"

PathLike = Union[str, Path]


class ProjectError(ValueError):
    """A project could not be created, read or written."""


@dataclass(frozen=True)
class Project:
    """An open project."""

    name: str
    workspace_path: Path
    crs_note: str = ""
    created: str = ""
    #: Where ``project.json`` actually is. Set on load/create.
    path: Path | None = None

    @property
    def runs_dir(self) -> Path:
        return self.workspace_path / RUNS_DIRNAME

    @property
    def raw_dir(self) -> Path:
        return self.workspace_path / RAW_DIRNAME

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": PROJECT_VERSION,
            "name": self.name,
            "crs_note": self.crs_note,
            "workspace_path": str(self.workspace_path),
            "created": self.created,
        }

    @classmethod
    def from_dict(
        cls, data: Any, *, where: str = "project.json", workspace: Path | None = None
    ) -> "Project":
        if not isinstance(data, dict):
            raise ProjectError(
                "{0}: must be an object, got {1}".format(where, type(data).__name__)
            )

        version = data.get("version", PROJECT_VERSION)
        if version != PROJECT_VERSION:
            raise ProjectError(
                "{0}: unsupported project version {1!r} (this studio speaks v{2})".format(
                    where, version, PROJECT_VERSION
                )
            )

        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ProjectError("{0}: 'name' must be a non-empty string".format(where))

        crs_note = data.get("crs_note", "")
        if not isinstance(crs_note, str):
            raise ProjectError("{0}: 'crs_note' must be a string".format(where))

        recorded = data.get("workspace_path")
        if recorded is not None and not isinstance(recorded, str):
            raise ProjectError("{0}: 'workspace_path' must be a string".format(where))
        if workspace is None:
            if not recorded:
                raise ProjectError("{0}: missing 'workspace_path'".format(where))
            workspace = Path(recorded)

        return cls(
            name=name,
            workspace_path=workspace,
            crs_note=crs_note,
            created=str(data.get("created", "")),
        )


def _project_file(path: PathLike) -> Path:
    path = Path(path)
    return path if path.name == PROJECT_FILENAME else path / PROJECT_FILENAME


def create_project(
    name: str,
    workspace_path: PathLike,
    *,
    crs_note: str = "",
    exist_ok: bool = False,
) -> Project:
    """Create a workspace and write its ``project.json``.

    Creates ``raw/`` and ``runs/`` too. Refuses to overwrite an existing
    ``project.json`` unless *exist_ok* is true: a project file holds the only
    record of a site's CRS note, and re-creating it must be deliberate.
    """
    if not isinstance(name, str) or not name.strip():
        raise ProjectError("project name must be a non-empty string")

    workspace = Path(workspace_path).expanduser()
    target = _project_file(workspace)
    workspace = target.parent

    if target.exists() and not exist_ok:
        raise ProjectError(
            "{0} already exists - open the project instead, or pass "
            "exist_ok=True".format(target)
        )

    try:
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / RAW_DIRNAME).mkdir(exist_ok=True)
        (workspace / RUNS_DIRNAME).mkdir(exist_ok=True)
    except OSError as exc:
        raise ProjectError("cannot create workspace {0} - {1}".format(workspace, exc)) from exc

    project = Project(
        name=name.strip(),
        workspace_path=workspace.resolve(),
        crs_note=crs_note,
        created=utc_now_iso(),
        path=target.resolve(),
    )
    save_project(project)
    return project


def load_project(path: PathLike) -> Project:
    """Open a project. *path* may be the workspace folder or ``project.json``."""
    target = _project_file(path)
    try:
        data = read_json(target)
    except FileNotFoundError as exc:
        raise ProjectError("{0}: no such project file".format(target)) from exc
    except ValueError as exc:
        raise ProjectError(str(exc)) from exc

    # The folder that actually holds project.json wins over the recorded path,
    # so a project that was moved or copied still opens.
    project = Project.from_dict(
        data, where=str(target), workspace=target.parent.resolve()
    )
    return replace(project, path=target.resolve())


def save_project(project: Project) -> Path:
    """Write *project* to ``<workspace>/project.json``."""
    target = project.path or _project_file(project.workspace_path)
    try:
        return atomic_write_json(Path(target), project.to_dict())
    except OSError as exc:
        raise ProjectError("cannot write {0} - {1}".format(target, exc)) from exc
