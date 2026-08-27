"""Core library — pure Python, no Qt.

Nothing in this package may import PySide6 (or any other GUI toolkit): the
engines and the command-line tools depend on it too. `tests/test_no_qt.py`
enforces this.

Modules
-------
manifest   load + validate ``engine.yaml``; discover engines
params     load + validate the per-action params JSON the UI turns into a form
runs       create run folders, write ``manifest.json`` / ``_DONE.json``
artifacts  write + read ``provenance.json``; scan a workspace for lineage
project    create / load ``project.json``
"""

from .artifacts import (
    Artifact,
    ArtifactError,
    read_provenance,
    scan_project,
    write_provenance,
)
from .manifest import (
    ARTIFACT_TYPES,
    Action,
    Engine,
    IOSpec,
    ManifestError,
    ManifestProblem,
    RunSpec,
    discover_engines,
    find_engines,
    load_manifest,
    render_argv,
    render_command,
)
from .params import (
    FIELD_TYPES,
    ParamField,
    ParamsError,
    ParamSpec,
    dump_params,
    load_params,
)
from .project import Project, ProjectError, create_project, load_project, save_project
from .runs import (
    DONE_NAME,
    MANIFEST_NAME,
    RunError,
    RunRecord,
    create_run_dir,
    finish_run,
    is_done,
    list_runs,
    read_run_manifest,
    run_dir_name,
    write_run_manifest,
)

__all__ = [
    # manifest
    "ARTIFACT_TYPES",
    "Action",
    "Engine",
    "IOSpec",
    "ManifestError",
    "ManifestProblem",
    "RunSpec",
    "discover_engines",
    "find_engines",
    "load_manifest",
    "render_argv",
    "render_command",
    # params
    "FIELD_TYPES",
    "ParamField",
    "ParamSpec",
    "ParamsError",
    "dump_params",
    "load_params",
    # runs
    "DONE_NAME",
    "MANIFEST_NAME",
    "RunError",
    "RunRecord",
    "create_run_dir",
    "finish_run",
    "is_done",
    "list_runs",
    "read_run_manifest",
    "run_dir_name",
    "write_run_manifest",
    # artifacts
    "Artifact",
    "ArtifactError",
    "read_provenance",
    "scan_project",
    "write_provenance",
    # project
    "Project",
    "ProjectError",
    "create_project",
    "load_project",
    "save_project",
]
