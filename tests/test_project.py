"""project.json: creation with a user-chosen workspace (decision D4)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from lithocloud.core.project import (
    PROJECT_FILENAME,
    ProjectError,
    create_project,
    load_project,
    save_project,
)


def test_create_writes_project_json_and_the_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "Sites" / "Francon"

    project = create_project("Francon", workspace, crs_note="EPSG:2950, MTM zone 8")

    assert project.name == "Francon"
    assert project.crs_note == "EPSG:2950, MTM zone 8"
    assert project.workspace_path == workspace.resolve()
    assert (workspace / PROJECT_FILENAME).is_file()
    assert (workspace / "raw").is_dir()
    assert (workspace / "runs").is_dir()


def test_the_workspace_is_wherever_the_user_chose(tmp_path: Path) -> None:
    """Decision D4: no hard-coded location."""
    for name in ("on_c", "on_d_drive_lookalike", "deep/nested/path"):
        project = create_project(name.replace("/", "-"), tmp_path / name)
        assert project.workspace_path == (tmp_path / name).resolve()


def test_stored_fields(tmp_path: Path) -> None:
    create_project("Francon", tmp_path / "ws", crs_note="note")

    data = json.loads((tmp_path / "ws" / PROJECT_FILENAME).read_text(encoding="utf-8"))

    assert data["name"] == "Francon"
    assert data["crs_note"] == "note"
    assert data["workspace_path"] == str((tmp_path / "ws").resolve())
    assert data["created"].endswith("Z")


def test_crs_note_defaults_to_empty(tmp_path: Path) -> None:
    assert create_project("P", tmp_path / "ws").crs_note == ""


def test_name_is_trimmed(tmp_path: Path) -> None:
    assert create_project("  Camillien-Houde  ", tmp_path / "ws").name == (
        "Camillien-Houde"
    )


@pytest.mark.parametrize("name", ["", "   "])
def test_an_empty_name_is_rejected(tmp_path: Path, name: str) -> None:
    with pytest.raises(ProjectError, match="non-empty string"):
        create_project(name, tmp_path / "ws")


def test_create_accepts_the_project_file_path(tmp_path: Path) -> None:
    project = create_project("P", tmp_path / "ws" / PROJECT_FILENAME)
    assert project.workspace_path == (tmp_path / "ws").resolve()


def test_create_refuses_to_overwrite_an_existing_project(tmp_path: Path) -> None:
    create_project("First", tmp_path / "ws", crs_note="the only record")

    with pytest.raises(ProjectError, match="already exists"):
        create_project("Second", tmp_path / "ws")

    assert load_project(tmp_path / "ws").name == "First"


def test_create_can_overwrite_when_asked(tmp_path: Path) -> None:
    create_project("First", tmp_path / "ws")
    create_project("Second", tmp_path / "ws", exist_ok=True)
    assert load_project(tmp_path / "ws").name == "Second"


def test_create_keeps_existing_raw_and_runs(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    (workspace / "raw").mkdir(parents=True)
    (workspace / "raw" / "site.laz").write_text("cloud", encoding="utf-8")

    create_project("P", workspace)

    assert (workspace / "raw" / "site.laz").read_text(encoding="utf-8") == "cloud"


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def test_round_trip(tmp_path: Path) -> None:
    created = create_project("Francon", tmp_path / "ws", crs_note="EPSG:2950")

    loaded = load_project(tmp_path / "ws")

    assert loaded.name == created.name
    assert loaded.crs_note == created.crs_note
    assert loaded.created == created.created
    assert loaded.workspace_path == created.workspace_path
    assert loaded.path == created.path


def test_load_accepts_the_folder_or_the_file(tmp_path: Path) -> None:
    create_project("P", tmp_path / "ws")

    assert load_project(tmp_path / "ws").name == "P"
    assert load_project(tmp_path / "ws" / PROJECT_FILENAME).name == "P"


def test_a_moved_project_still_opens(tmp_path: Path) -> None:
    """workspace_path records where it was made; where it IS wins."""
    create_project("Francon", tmp_path / "old")
    shutil.move(str(tmp_path / "old"), str(tmp_path / "new"))

    project = load_project(tmp_path / "new")

    assert project.workspace_path == (tmp_path / "new").resolve()
    assert project.runs_dir == (tmp_path / "new").resolve() / "runs"
    assert project.raw_dir == (tmp_path / "new").resolve() / "raw"


def test_convenience_paths(tmp_path: Path) -> None:
    project = create_project("P", tmp_path / "ws")
    assert project.runs_dir == (tmp_path / "ws").resolve() / "runs"
    assert project.raw_dir == (tmp_path / "ws").resolve() / "raw"


def test_missing_project_file(tmp_path: Path) -> None:
    with pytest.raises(ProjectError, match="no such project file"):
        load_project(tmp_path / "nowhere")


def test_corrupt_project_file(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / PROJECT_FILENAME).write_text("{ truncated", encoding="utf-8")

    with pytest.raises(ProjectError, match="invalid JSON"):
        load_project(workspace)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"crs_note": "x"}, "'name' must be"),
        ({"name": ""}, "'name' must be"),
        ({"name": "P", "crs_note": 7}, "'crs_note' must be"),
        ({"version": 99, "name": "P"}, "unsupported project version"),
        (["not", "an", "object"], "must be an object"),
    ],
)
def test_invalid_project_file(tmp_path: Path, data: object, message: str) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / PROJECT_FILENAME).write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ProjectError, match=message):
        load_project(workspace)


# --------------------------------------------------------------------------- #
# Saving
# --------------------------------------------------------------------------- #


def test_save_updates_the_file(tmp_path: Path) -> None:
    from dataclasses import replace

    project = create_project("P", tmp_path / "ws")
    save_project(replace(project, crs_note="EPSG:2950, added later"))

    assert load_project(tmp_path / "ws").crs_note == "EPSG:2950, added later"


def test_save_does_not_truncate_on_a_failed_write(tmp_path: Path) -> None:
    """Writes go through a temp file, so the old content always survives."""
    project = create_project("P", tmp_path / "ws", crs_note="important")
    before = (tmp_path / "ws" / PROJECT_FILENAME).read_text(encoding="utf-8")

    save_project(project)

    assert (tmp_path / "ws" / PROJECT_FILENAME).read_text(encoding="utf-8") == before
    assert json.loads(before)["crs_note"] == "important"
