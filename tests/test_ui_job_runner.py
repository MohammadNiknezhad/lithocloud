"""JobRunner: execution, queueing, failure handling, cancel, spaces in paths.

These run the REAL _demo engine as a subprocess, exactly as the shell does.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from rockslope_studio.core import (
    is_done,
    list_runs,
    load_manifest,
    load_params,
    scan_project,
)
from rockslope_studio.ui.job_runner import JobRequest, JobRunner

TIMEOUT_MS = 30_000


@pytest.fixture()
def demo_engine(repo_root: Path):
    return load_manifest(repo_root / "engines" / "_demo")


@pytest.fixture()
def demo_defaults(repo_root: Path) -> dict:
    return load_params(repo_root / "engines" / "_demo" / "params_run.json").defaults()


def make_request(engine, defaults: dict, **overrides) -> JobRequest:
    params = {**defaults, "seconds": 0.2, "steps": 2, **overrides.pop("params", {})}
    return JobRequest(
        engine=engine, action=engine.action("run"), params=params, **overrides
    )


def wait_finished(qtbot, runner: JobRunner, count: int = 1) -> list[tuple]:
    """Run the event loop until `count` job_finished signals arrived."""
    results: list[tuple] = []
    runner.job_finished.connect(lambda job, code, ok: results.append((job, code, ok)))
    qtbot.waitUntil(lambda: len(results) >= count, timeout=TIMEOUT_MS)
    return results


# --------------------------------------------------------------------------- #
# The happy path
# --------------------------------------------------------------------------- #


def test_a_run_completes_and_registers_its_artifact(
    qtbot, tmp_path: Path, demo_engine, demo_defaults
) -> None:
    runner = JobRunner(tmp_path)
    runner.submit(make_request(demo_engine, demo_defaults))
    ((job, code, ok),) = wait_finished(qtbot, runner)

    assert ok and code == 0
    assert is_done(job.run_dir)
    assert (job.run_dir / "stats.csv").is_file()

    artifacts = scan_project(tmp_path)
    assert len(artifacts) == 1
    assert artifacts[0].type == "table"
    assert artifacts[0].engine == "demo"
    assert artifacts[0].action == "run"
    assert artifacts[0].artifact_id.endswith("__stats")
    assert artifacts[0].exists


def test_the_run_manifest_records_the_job(
    qtbot, tmp_path: Path, demo_engine, demo_defaults
) -> None:
    runner = JobRunner(tmp_path)
    runner.submit(make_request(demo_engine, demo_defaults))
    ((job, _code, _ok),) = wait_finished(qtbot, runner)

    manifest = json.loads((job.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["engine"] == "demo"
    assert manifest["engine_version"] == "0.1.0"
    assert manifest["action"] == "run"
    assert manifest["params"]["steps"] == 2
    assert manifest["exit_code"] == 0
    assert manifest["finished"] is not None
    assert isinstance(manifest["argv"], list)
    # the validated params were also written for the engine itself
    assert (job.run_dir / "params.json").is_file()


def test_progress_lines_reach_the_log(
    qtbot, tmp_path: Path, demo_engine, demo_defaults
) -> None:
    runner = JobRunner(tmp_path)
    lines: list[str] = []
    runner.job_log.connect(lines.append)

    runner.submit(make_request(demo_engine, demo_defaults))
    wait_finished(qtbot, runner)

    joined = "\n".join(lines)
    assert "progress 1/2" in joined
    assert "progress 2/2" in joined
    assert "finished OK" in joined


# --------------------------------------------------------------------------- #
# Spaces in paths (the session-2 extra requirement)
# --------------------------------------------------------------------------- #


def test_a_workspace_path_with_spaces_works_end_to_end(
    qtbot, tmp_path: Path, demo_engine, demo_defaults
) -> None:
    workspace = tmp_path / "My Site With Spaces" / "field campaign 2026"
    workspace.mkdir(parents=True)

    runner = JobRunner(workspace)
    runner.submit(make_request(demo_engine, demo_defaults))
    ((job, code, ok),) = wait_finished(qtbot, runner)

    assert ok and code == 0, "engine failed - the spaced path was mangled"
    assert " " in str(job.run_dir)
    assert (job.run_dir / "stats.csv").is_file()
    assert scan_project(workspace)[0].exists


def test_an_input_path_with_spaces_survives(
    qtbot, tmp_path: Path, demo_engine, demo_defaults
) -> None:
    workspace = tmp_path / "spaced out workspace"
    workspace.mkdir()
    runner = JobRunner(workspace)

    # first run produces the artifact (its path contains spaces)
    runner.submit(make_request(demo_engine, demo_defaults))
    wait_finished(qtbot, runner)
    first = scan_project(workspace)[0]
    assert " " in str(first.paths[0])

    # second run consumes it through {input:previous}
    lines: list[str] = []
    runner.job_log.connect(lines.append)
    runner.submit(
        make_request(demo_engine, demo_defaults, inputs={"previous": first})
    )
    results = wait_finished(qtbot, runner)
    _job, code, ok = results[-1]

    assert ok and code == 0
    # the engine echoed the full, unsplit path
    assert any(str(first.paths[0]) in line for line in lines)

    # and lineage points at the first artifact
    second = [a for a in scan_project(workspace) if a.artifact_id != first.artifact_id]
    assert second[0].inputs == (first.artifact_id,)


# --------------------------------------------------------------------------- #
# Queueing
# --------------------------------------------------------------------------- #


def test_jobs_queue_one_at_a_time(
    qtbot, tmp_path: Path, demo_engine, demo_defaults
) -> None:
    runner = JobRunner(tmp_path)
    started: list[str] = []
    runner.job_started.connect(lambda job: started.append(job.run_dir.name))

    runner.submit(make_request(demo_engine, demo_defaults))
    runner.submit(make_request(demo_engine, demo_defaults))
    runner.submit(make_request(demo_engine, demo_defaults))

    # nothing runs synchronously inside submit(); the event loop starts job 1
    assert started == []
    assert runner.queued == 3
    qtbot.waitUntil(lambda: len(started) == 1, timeout=TIMEOUT_MS)
    assert runner.queued == 2  # exactly one running, two waiting

    results = wait_finished(qtbot, runner, count=3)

    assert [ok for _job, _code, ok in results] == [True, True, True]
    assert runner.queued == 0
    assert runner.current is None
    # three distinct run folders, started in submission order
    names = [job.run_dir.name for job, _code, _ok in results]
    assert len(set(names)) == 3
    assert names == started


def test_a_failed_job_does_not_block_the_queue(
    qtbot, tmp_path: Path, demo_engine, demo_defaults
) -> None:
    runner = JobRunner(tmp_path)
    runner.submit(make_request(demo_engine, demo_defaults, params={"mode": "crash"}))
    runner.submit(make_request(demo_engine, demo_defaults))

    results = wait_finished(qtbot, runner, count=2)

    (_j1, code1, ok1), (_j2, code2, ok2) = results
    assert not ok1 and code1 == 3
    assert ok2 and code2 == 0


# --------------------------------------------------------------------------- #
# Failure handling (session-2 acceptance: crash must not crash the shell)
# --------------------------------------------------------------------------- #


def test_a_crash_is_a_failed_run_with_no_done_and_no_artifacts(
    qtbot, tmp_path: Path, demo_engine, demo_defaults
) -> None:
    runner = JobRunner(tmp_path)
    runner.submit(make_request(demo_engine, demo_defaults, params={"mode": "crash"}))
    ((job, code, ok),) = wait_finished(qtbot, runner)

    assert not ok and code == 3
    assert not is_done(job.run_dir)
    assert not (job.run_dir / "_DONE.json").exists()
    assert scan_project(tmp_path) == []  # nothing registered

    manifest = json.loads((job.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["exit_code"] == 3

    record = list_runs(tmp_path)[0]
    assert record.succeeded is False
    assert record.exit_code == 3


def test_a_missing_outputs_json_is_a_warning_not_a_failure(
    qtbot, tmp_path: Path
) -> None:
    """Contract: run succeeds, declared outputs unregistered, warning logged.

    Uses a stub engine that exits 0 but never writes outputs.json.
    """
    runner = JobRunner(tmp_path)
    lines: list[str] = []
    runner.job_log.connect(lines.append)

    stub_dir = tmp_path / "engines" / "stub"
    stub_dir.mkdir(parents=True)
    (stub_dir / "engine.yaml").write_text(
        'id: stub\nname: Stub\nversion: "0.0"\n'
        "actions: [{id: a, label: A, outputs: [{key: out, type: table}]}]\n"
        'run: {command: "{python} -c pass", cwd: .}\n',
        encoding="utf-8",
    )
    from rockslope_studio.core import load_manifest as load

    stub = load(stub_dir)
    runner.submit(JobRequest(engine=stub, action=stub.action("a")))
    ((job, code, ok),) = wait_finished(qtbot, runner)

    assert ok and code == 0
    assert is_done(job.run_dir)
    assert scan_project(tmp_path) == []
    assert any("wrote no outputs.json" in line for line in lines)


def test_an_unlaunchable_command_fails_cleanly(qtbot, tmp_path: Path) -> None:
    from rockslope_studio.core import load_manifest as load

    bad_dir = tmp_path / "engines" / "bad"
    bad_dir.mkdir(parents=True)
    (bad_dir / "engine.yaml").write_text(
        'id: bad\nname: Bad\nversion: "0.0"\n'
        "actions: [{id: a, label: A}]\n"
        'run: {command: "definitely-not-a-program-xyz --flag", cwd: .}\n',
        encoding="utf-8",
    )
    runner = JobRunner(tmp_path)
    lines: list[str] = []
    runner.job_log.connect(lines.append)

    bad = load(bad_dir)
    runner.submit(JobRequest(engine=bad, action=bad.action("a")))
    ((job, code, ok),) = wait_finished(qtbot, runner)

    assert not ok and code != 0
    assert not is_done(job.run_dir)
    assert any("failed to start" in line for line in lines)


def test_a_missing_working_directory_fails_before_launch(
    qtbot, tmp_path: Path, demo_defaults, repo_root: Path
) -> None:
    engine = load_manifest(repo_root / "engines" / "_demo")
    broken = dataclasses.replace(engine, run=dataclasses.replace(engine.run, cwd="nope"))

    runner = JobRunner(tmp_path)
    lines: list[str] = []
    runner.job_log.connect(lines.append)
    runner.submit(make_request(broken, demo_defaults))

    qtbot.waitUntil(
        lambda: any("could not start job" in line for line in lines), timeout=TIMEOUT_MS
    )
    assert runner.current is None


# --------------------------------------------------------------------------- #
# Cancel
# --------------------------------------------------------------------------- #


def test_cancel_kills_the_run_and_leaves_a_failed_record(
    qtbot, tmp_path: Path, demo_engine, demo_defaults
) -> None:
    runner = JobRunner(tmp_path)
    started: list[object] = []
    runner.job_started.connect(started.append)

    runner.submit(
        make_request(demo_engine, demo_defaults, params={"seconds": 60.0, "steps": 60})
    )
    qtbot.waitUntil(lambda: len(started) == 1, timeout=TIMEOUT_MS)
    qtbot.waitUntil(lambda: runner.current is not None and bool(runner.current.pid()), timeout=TIMEOUT_MS)

    runner.cancel_current()
    ((job, code, ok),) = wait_finished(qtbot, runner)

    assert not ok and code != 0
    assert job.cancelled
    assert not is_done(job.run_dir)
    assert scan_project(tmp_path) == []

    # the run record says CANCELLED, not failed
    manifest = json.loads((job.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cancelled"] is True
    record = list_runs(tmp_path)[0]
    assert record.cancelled is True
    assert record.succeeded is False


def test_cancel_lets_the_next_queued_job_run(
    qtbot, tmp_path: Path, demo_engine, demo_defaults
) -> None:
    runner = JobRunner(tmp_path)
    started: list[object] = []
    runner.job_started.connect(started.append)

    runner.submit(
        make_request(demo_engine, demo_defaults, params={"seconds": 60.0, "steps": 60})
    )
    runner.submit(make_request(demo_engine, demo_defaults))

    qtbot.waitUntil(lambda: runner.current is not None and bool(runner.current.pid()), timeout=TIMEOUT_MS)
    runner.cancel_current()

    results = wait_finished(qtbot, runner, count=2)
    (_j1, _code1, ok1), (_j2, code2, ok2) = results

    assert not ok1
    assert ok2 and code2 == 0
    assert len(scan_project(tmp_path)) == 1  # only the second registered


# --------------------------------------------------------------------------- #
# The interactive (console) path
# --------------------------------------------------------------------------- #


def test_an_interactive_action_runs_via_popen_and_registers(
    qtbot, tmp_path: Path, demo_engine, demo_defaults
) -> None:
    """Force the non-blocking 'run' action down the interactive code path.

    (The real 'ask' action would wait for keyboard input in its own console;
    'run' exercises the same Popen + poll + registration machinery without
    blocking. A console window may flash briefly - that is expected.)
    """
    interactive_action = dataclasses.replace(demo_engine.action("run"), interactive=True)

    runner = JobRunner(tmp_path)
    lines: list[str] = []
    runner.job_log.connect(lines.append)
    runner.submit(
        JobRequest(
            engine=demo_engine,
            action=interactive_action,
            params={**demo_defaults, "seconds": 0.2, "steps": 2},
        )
    )
    ((job, code, ok),) = wait_finished(qtbot, runner)

    assert ok and code == 0
    assert is_done(job.run_dir)
    assert any("interactive" in line for line in lines)
    assert len(scan_project(tmp_path)) == 1


def test_a_failed_jobs_adapter_error_file_is_echoed_to_the_log(
    qtbot, tmp_path: Path
) -> None:
    """Adapters persist early errors to adapter_error.txt (approved
    2026-08-27); the shell echoes it so console-window errors stay readable."""
    from rockslope_studio.core import load_manifest as load

    stub_dir = tmp_path / "engines" / "stub"
    stub_dir.mkdir(parents=True)
    # a stand-in adapter: writes adapter_error.txt into the run dir, exits 2
    (stub_dir / "fail.py").write_text(
        "import pathlib, sys\n"
        "run_dir = pathlib.Path(sys.argv[1])\n"
        "run_dir.joinpath('adapter_error.txt').write_text(\n"
        "    'ERROR: ingest: in_files is required', encoding='utf-8')\n"
        "sys.exit(2)\n",
        encoding="utf-8",
    )
    (stub_dir / "engine.yaml").write_text(
        'id: stub\nname: Stub\nversion: "0.0"\n'
        "actions: [{id: a, label: A}]\n"
        'run: {command: "{python} fail.py {run_dir}", cwd: .}\n',
        encoding="utf-8",
    )

    runner = JobRunner(tmp_path)
    lines: list[str] = []
    runner.job_log.connect(lines.append)

    stub = load(stub_dir)
    runner.submit(JobRequest(engine=stub, action=stub.action("a")))
    ((job, code, ok),) = wait_finished(qtbot, runner)

    assert not ok and code == 2
    assert any("adapter_error.txt" in line for line in lines)
    assert any("in_files is required" in line for line in lines)


def test_a_successful_job_does_not_look_for_an_error_file(
    qtbot, tmp_path: Path, demo_engine, demo_defaults
) -> None:
    runner = JobRunner(tmp_path)
    lines: list[str] = []
    runner.job_log.connect(lines.append)

    runner.submit(make_request(demo_engine, demo_defaults))
    wait_finished(qtbot, runner)

    assert not any("adapter_error.txt" in line for line in lines)
