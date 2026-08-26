"""Run folders: naming, collisions, manifest.json and _DONE.json."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from rockslope_studio.core.runs import (
    DONE_NAME,
    MANIFEST_NAME,
    RunError,
    create_run_dir,
    finish_run,
    is_done,
    list_runs,
    read_run_manifest,
    run_dir_name,
    write_run_manifest,
)

WHEN = dt.datetime(2026, 8, 26, 14, 32, 7)


# --------------------------------------------------------------------------- #
# Naming
# --------------------------------------------------------------------------- #


def test_run_dir_name_format() -> None:
    assert run_dir_name("ricp", "register", WHEN) == "2026-08-26_1432_ricp_register"


def test_run_dir_name_suffix() -> None:
    assert run_dir_name("ricp", "register", WHEN, suffix=3) == (
        "2026-08-26_1432_ricp_register_3"
    )


def test_run_dir_name_sanitises_unsafe_characters() -> None:
    name = run_dir_name("my engine!", "do/it", WHEN)
    assert name == "2026-08-26_1432_my-engine_do-it"
    assert not set(name) & set(r'<>:"/\|?*')


def test_run_dir_names_sort_chronologically() -> None:
    early = run_dir_name("e", "a", dt.datetime(2026, 1, 9, 9, 5))
    late = run_dir_name("e", "a", dt.datetime(2026, 11, 20, 16, 40))
    assert early < late


# --------------------------------------------------------------------------- #
# Creating the folder
# --------------------------------------------------------------------------- #


def test_create_run_dir_makes_the_folder(tmp_path: Path) -> None:
    run_dir = create_run_dir(tmp_path, "ricp", "register", when=WHEN)

    assert run_dir.is_dir()
    assert run_dir.name == "2026-08-26_1432_ricp_register"
    assert run_dir.parent == tmp_path / "runs"


def test_create_run_dir_creates_the_runs_root(tmp_path: Path) -> None:
    workspace = tmp_path / "brand" / "new"
    create_run_dir(workspace, "e", "a", when=WHEN)
    assert (workspace / "runs").is_dir()


def test_collisions_get_numbered_suffixes(tmp_path: Path) -> None:
    """Two runs of the same action in the same minute must not collide."""
    names = [create_run_dir(tmp_path, "ricp", "register", when=WHEN).name for _ in range(4)]

    assert names == [
        "2026-08-26_1432_ricp_register",
        "2026-08-26_1432_ricp_register_2",
        "2026-08-26_1432_ricp_register_3",
        "2026-08-26_1432_ricp_register_4",
    ]
    assert len(set(names)) == 4


def test_an_existing_run_folder_is_never_reused(tmp_path: Path) -> None:
    first = create_run_dir(tmp_path, "e", "a", when=WHEN)
    (first / "result.laz").write_text("precious", encoding="utf-8")

    second = create_run_dir(tmp_path, "e", "a", when=WHEN)

    assert second != first
    assert (first / "result.laz").read_text(encoding="utf-8") == "precious"
    assert list(second.iterdir()) == []


def test_a_folder_created_behind_our_back_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / run_dir_name("e", "a", WHEN)).mkdir()

    run_dir = create_run_dir(tmp_path, "e", "a", when=WHEN)
    assert run_dir.name.endswith("_2")


def test_create_run_dir_gives_up_cleanly(tmp_path: Path) -> None:
    (tmp_path / "runs").mkdir()
    for suffix in range(1, 4):
        (tmp_path / "runs" / run_dir_name("e", "a", WHEN, suffix=suffix)).mkdir()

    with pytest.raises(RunError, match="could not find a free run folder name"):
        create_run_dir(tmp_path, "e", "a", when=WHEN, max_attempts=3)


def test_different_actions_do_not_collide(tmp_path: Path) -> None:
    one = create_run_dir(tmp_path, "geohazard", "stage1", when=WHEN)
    two = create_run_dir(tmp_path, "geohazard", "stage2", when=WHEN)
    assert one.name != two.name


# --------------------------------------------------------------------------- #
# manifest.json
# --------------------------------------------------------------------------- #


def test_write_and_read_run_manifest(tmp_path: Path) -> None:
    run_dir = create_run_dir(tmp_path, "ricp", "register", when=WHEN)

    write_run_manifest(
        run_dir,
        engine="ricp",
        engine_version="1.0.0",
        action="register",
        params={"voxel": 0.05},
        inputs={"reference": "run_a__cloud", "align": "run_b__cloud"},
        command="python -m ricp register",
        cwd=r"C:\Projects\ricp",
        started="2026-08-26T18:32:07Z",
    )
    data = read_run_manifest(run_dir)

    assert data["engine"] == "ricp"
    assert data["engine_version"] == "1.0.0"
    assert data["action"] == "register"
    assert data["params"] == {"voxel": 0.05}
    assert data["inputs"] == {"reference": "run_a__cloud", "align": "run_b__cloud"}
    assert data["started"] == "2026-08-26T18:32:07Z"
    assert data["finished"] is None
    assert data["exit_code"] is None
    assert data["command"] == "python -m ricp register"


def test_manifest_records_every_field_the_spec_names(tmp_path: Path) -> None:
    run_dir = create_run_dir(tmp_path, "e", "a", when=WHEN)
    write_run_manifest(run_dir, engine="e", engine_version="1", action="a")

    data = read_run_manifest(run_dir)
    for key in (
        "engine",
        "engine_version",
        "action",
        "params",
        "inputs",
        "started",
        "finished",
        "exit_code",
    ):
        assert key in data


def test_started_defaults_to_now_in_utc(tmp_path: Path) -> None:
    run_dir = create_run_dir(tmp_path, "e", "a", when=WHEN)
    write_run_manifest(run_dir, engine="e", engine_version="1", action="a")

    started = read_run_manifest(run_dir)["started"]
    assert started.endswith("Z")
    dt.datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ")  # parses


def test_inputs_may_be_a_plain_list(tmp_path: Path) -> None:
    run_dir = create_run_dir(tmp_path, "e", "a", when=WHEN)
    write_run_manifest(
        run_dir, engine="e", engine_version="1", action="a", inputs=["id1", "id2"]
    )
    assert read_run_manifest(run_dir)["inputs"] == ["id1", "id2"]


def test_inputs_of_a_wrong_shape_are_rejected(tmp_path: Path) -> None:
    run_dir = create_run_dir(tmp_path, "e", "a", when=WHEN)
    with pytest.raises(RunError, match="mapping or a list"):
        write_run_manifest(
            run_dir, engine="e", engine_version="1", action="a", inputs="id1"
        )


def test_extra_cannot_overwrite_a_recorded_field(tmp_path: Path) -> None:
    run_dir = create_run_dir(tmp_path, "e", "a", when=WHEN)
    with pytest.raises(RunError, match="may not override"):
        write_run_manifest(
            run_dir,
            engine="e",
            engine_version="1",
            action="a",
            extra={"engine": "somethingelse"},
        )


def test_extra_fields_are_stored(tmp_path: Path) -> None:
    run_dir = create_run_dir(tmp_path, "e", "a", when=WHEN)
    write_run_manifest(
        run_dir, engine="e", engine_version="1", action="a", extra={"seed": 42}
    )
    assert read_run_manifest(run_dir)["seed"] == 42


def test_write_manifest_needs_an_existing_folder(tmp_path: Path) -> None:
    with pytest.raises(RunError, match="no such run folder"):
        write_run_manifest(tmp_path / "nope", engine="e", engine_version="1", action="a")


def test_read_manifest_of_a_folder_without_one(tmp_path: Path) -> None:
    run_dir = create_run_dir(tmp_path, "e", "a", when=WHEN)
    with pytest.raises(RunError, match="no run manifest"):
        read_run_manifest(run_dir)


def test_read_manifest_accepts_the_file_path(tmp_path: Path) -> None:
    run_dir = create_run_dir(tmp_path, "e", "a", when=WHEN)
    write_run_manifest(run_dir, engine="e", engine_version="1", action="a")
    assert read_run_manifest(run_dir / MANIFEST_NAME)["engine"] == "e"


def test_a_corrupt_manifest_is_reported(tmp_path: Path) -> None:
    run_dir = create_run_dir(tmp_path, "e", "a", when=WHEN)
    (run_dir / MANIFEST_NAME).write_text("{ truncated", encoding="utf-8")

    with pytest.raises(RunError, match="invalid JSON"):
        read_run_manifest(run_dir)


# --------------------------------------------------------------------------- #
# _DONE.json
# --------------------------------------------------------------------------- #


def test_success_writes_done_and_records_the_exit_code(tmp_path: Path) -> None:
    run_dir = create_run_dir(tmp_path, "e", "a", when=WHEN)
    write_run_manifest(run_dir, engine="e", engine_version="1", action="a")

    done = finish_run(run_dir, 0, outputs=["result.laz"])

    assert done is not None and done.name == DONE_NAME
    assert is_done(run_dir)

    data = read_run_manifest(run_dir)
    assert data["exit_code"] == 0
    assert data["finished"] is not None
    assert data["outputs"] == ["result.laz"]

    marker = json.loads((run_dir / DONE_NAME).read_text(encoding="utf-8"))
    assert marker["exit_code"] == 0
    assert marker["outputs"] == ["result.laz"]


def test_failure_records_the_exit_code_but_writes_no_done(tmp_path: Path) -> None:
    """A crashed engine must never look like a completed run."""
    run_dir = create_run_dir(tmp_path, "e", "a", when=WHEN)
    write_run_manifest(run_dir, engine="e", engine_version="1", action="a")

    assert finish_run(run_dir, 1) is None
    assert not is_done(run_dir)
    assert not (run_dir / DONE_NAME).exists()
    assert read_run_manifest(run_dir)["exit_code"] == 1


def test_finish_run_keeps_the_rest_of_the_manifest(tmp_path: Path) -> None:
    run_dir = create_run_dir(tmp_path, "ricp", "register", when=WHEN)
    write_run_manifest(
        run_dir,
        engine="ricp",
        engine_version="1.0.0",
        action="register",
        params={"voxel": 0.05},
    )

    finish_run(run_dir, 0)

    data = read_run_manifest(run_dir)
    assert data["engine"] == "ricp"
    assert data["params"] == {"voxel": 0.05}


def test_finish_run_survives_a_missing_manifest(tmp_path: Path) -> None:
    """An engine killed before the manifest was written must still be recorded."""
    run_dir = create_run_dir(tmp_path, "e", "a", when=WHEN)

    finish_run(run_dir, 137)

    assert read_run_manifest(run_dir)["exit_code"] == 137
    assert not is_done(run_dir)


def test_is_done_on_a_missing_folder(tmp_path: Path) -> None:
    assert is_done(tmp_path / "nope") is False


def test_finish_run_message(tmp_path: Path) -> None:
    run_dir = create_run_dir(tmp_path, "e", "a", when=WHEN)
    finish_run(run_dir, 0, message="all good")

    marker = json.loads((run_dir / DONE_NAME).read_text(encoding="utf-8"))
    assert marker["message"] == "all good"


# --------------------------------------------------------------------------- #
# Listing
# --------------------------------------------------------------------------- #


def test_list_runs_on_an_empty_workspace(tmp_path: Path) -> None:
    assert list_runs(tmp_path) == []


def test_list_runs_reports_status(tmp_path: Path) -> None:
    ok = create_run_dir(tmp_path, "e", "good", when=WHEN)
    write_run_manifest(ok, engine="e", engine_version="1", action="good")
    finish_run(ok, 0)

    bad = create_run_dir(tmp_path, "e", "bad", when=WHEN)
    write_run_manifest(bad, engine="e", engine_version="1", action="bad")
    finish_run(bad, 2)

    live = create_run_dir(tmp_path, "e", "live", when=WHEN)
    write_run_manifest(live, engine="e", engine_version="1", action="live")

    records = {r.action: r for r in list_runs(tmp_path)}

    assert records["good"].succeeded is True
    assert records["good"].exit_code == 0

    assert records["bad"].succeeded is False
    assert records["bad"].exit_code == 2
    assert records["bad"].running is False

    assert records["live"].running is True
    assert records["live"].succeeded is False


def test_list_runs_still_reports_a_folder_with_no_manifest(tmp_path: Path) -> None:
    """An interrupted run must stay visible in the job history."""
    orphan = create_run_dir(tmp_path, "e", "a", when=WHEN)

    records = list_runs(tmp_path)

    assert len(records) == 1
    assert records[0].path == orphan
    assert records[0].problem
    assert records[0].engine == ""


def test_list_runs_is_in_time_order(tmp_path: Path) -> None:
    for hour in (16, 9, 11):
        run = create_run_dir(tmp_path, "e", "a", when=dt.datetime(2026, 8, 26, hour, 0))
        write_run_manifest(run, engine="e", engine_version="1", action="a")

    names = [r.name for r in list_runs(tmp_path)]
    assert names == sorted(names)
    assert names[0].startswith("2026-08-26_0900")
    assert names[-1].startswith("2026-08-26_1600")


def test_list_runs_ignores_stray_files(tmp_path: Path) -> None:
    run = create_run_dir(tmp_path, "e", "a", when=WHEN)
    write_run_manifest(run, engine="e", engine_version="1", action="a")
    (tmp_path / "runs" / "notes.txt").write_text("hi", encoding="utf-8")

    assert len(list_runs(tmp_path)) == 1
