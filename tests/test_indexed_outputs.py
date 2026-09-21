"""Indexed outputs (2026-09-21): an output declared 'indexed: true' registers
every outputs.json key '<key><n>' as its own artifact - a project's per-scan
clouds and transforms, whose count is only known at run time."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lithocloud.core import IOSpec, ManifestError, load_manifest, scan_project
from lithocloud.ui.job_runner import JobRequest, JobRunner

from conftest import write_manifest

TIMEOUT_MS = 30_000


def test_matches() -> None:
    plain = IOSpec(key="report", type="report")
    assert plain.matches("report") and not plain.matches("report1")
    indexed = IOSpec(key="registered_scan", type="pointcloud", indexed=True)
    assert indexed.matches("registered_scan1") and indexed.matches("registered_scan12")
    assert not indexed.matches("registered_scan")        # the bare key is not an index
    assert not indexed.matches("registered_scanA")
    assert not indexed.matches("other1")


def test_manifest_loads_indexed_outputs_and_round_trips(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "e",
        'id: d\nname: N\nversion: "1.0"\n'
        "actions: [{id: a, label: A, outputs: [{key: registered_scan, type: pointcloud, indexed: true}, "
        "{key: report, type: report}]}]\n"
        'run: {command: "x"}\n',
    )
    engine = load_manifest(path)
    slot = engine.action("a").output("registered_scan")
    assert slot.indexed is True
    assert slot.to_dict() == {"key": "registered_scan", "type": "pointcloud", "indexed": True}
    assert engine.action("a").output("report").indexed is False


def test_indexed_is_rejected_on_an_input(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "e",
        'id: d\nname: N\nversion: "1.0"\n'
        "actions: [{id: a, label: A, inputs: [{key: c, type: pointcloud, indexed: true}]}]\n"
        'run: {command: "x"}\n',
    )
    with pytest.raises(ManifestError, match="'indexed' applies to outputs only"):
        load_manifest(path)


@pytest.fixture()
def stub_engine(tmp_path: Path):
    """An engine that writes three per-scan clouds, two transforms, one report."""
    stub_dir = tmp_path / "engines" / "stub"
    stub_dir.mkdir(parents=True)
    (stub_dir / "go.py").write_text(
        "import json, pathlib, sys\n"
        "run = pathlib.Path(sys.argv[1])\n"
        "out = {}\n"
        "for i in (1, 2, 3):\n"
        "    (run / f'scan{i}.las').write_bytes(b'x'); out[f'registered_scan{i}'] = [f'scan{i}.las']\n"
        "for i in (1, 3):\n"
        "    (run / f't{i}.txt').write_text('1'); out[f'transform_scan{i}'] = [f't{i}.txt']\n"
        "(run / 'summary.json').write_text('{}'); out['project_summary'] = ['summary.json']\n"
        "(run / 'outputs.json').write_text(json.dumps(out))\n",
        encoding="utf-8",
    )
    (stub_dir / "engine.yaml").write_text(
        'id: stub\nname: Stub\nversion: "0.0"\n'
        "actions: [{id: a, label: A, outputs: ["
        "{key: registered_scan, type: pointcloud, indexed: true}, "
        "{key: transform_scan, type: transform, indexed: true}, "
        "{key: project_summary, type: report}]}]\n"
        'run: {command: "{python} go.py {run_dir}", cwd: .}\n',
        encoding="utf-8",
    )
    return load_manifest(stub_dir)


def test_every_index_registers_as_its_own_artifact(qtbot, tmp_path: Path, stub_engine) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    runner = JobRunner(workspace)
    lines: list[str] = []
    runner.job_log.connect(lines.append)
    results: list = []
    runner.job_finished.connect(lambda j, c, ok: results.append((j, c, ok)))
    runner.submit(JobRequest(engine=stub_engine, action=stub_engine.action("a")))
    qtbot.waitUntil(lambda: len(results) == 1, timeout=TIMEOUT_MS)

    job, code, ok = results[0]
    assert ok and code == 0
    ids = sorted(a.artifact_id.split("__")[-1] for a in scan_project(workspace))
    assert ids == [
        "project_summary",
        "registered_scan1", "registered_scan2", "registered_scan3",
        "transform_scan1", "transform_scan3",
    ]
    types = {a.artifact_id.split("__")[-1]: a.type for a in scan_project(workspace)}
    assert types["registered_scan2"] == "pointcloud"
    assert types["transform_scan3"] == "transform"
    assert not any("does not declare" in line for line in lines)
    assert "6 artifact(s) registered" in "\n".join(lines)


def test_an_indexed_output_with_no_entries_is_a_warning(qtbot, tmp_path: Path) -> None:
    stub_dir = tmp_path / "engines" / "stub2"
    stub_dir.mkdir(parents=True)
    (stub_dir / "go.py").write_text(
        "import json, pathlib, sys\n"
        "run = pathlib.Path(sys.argv[1])\n"
        "(run / 'outputs.json').write_text(json.dumps({'stray5': []}))\n",
        encoding="utf-8",
    )
    (stub_dir / "engine.yaml").write_text(
        'id: stub2\nname: S\nversion: "0.0"\n'
        "actions: [{id: a, label: A, outputs: [{key: registered_scan, type: pointcloud, indexed: true}]}]\n"
        'run: {command: "{python} go.py {run_dir}", cwd: .}\n',
        encoding="utf-8",
    )
    engine = load_manifest(stub_dir)
    runner = JobRunner(tmp_path / "ws")
    lines: list[str] = []
    runner.job_log.connect(lines.append)
    results: list = []
    runner.job_finished.connect(lambda j, c, ok: results.append((j, c, ok)))
    runner.submit(JobRequest(engine=engine, action=engine.action("a")))
    qtbot.waitUntil(lambda: len(results) == 1, timeout=TIMEOUT_MS)

    _job, code, ok = results[0]
    assert ok and code == 0                                   # a warning, not a failure
    joined = "\n".join(lines)
    assert "registered_scan<n>" in joined
    assert "'stray5', which the manifest does not declare" in joined
    assert scan_project(tmp_path / "ws") == []


def test_existing_manifests_are_unaffected() -> None:
    """Every engine on disk still loads; none of them uses 'indexed' yet."""
    root = Path(__file__).resolve().parents[1]
    for path in sorted((root / "engines").glob("*/engine.yaml")):
        engine = load_manifest(path)
        for action in engine.actions:
            assert all(not s.indexed for s in action.inputs + action.outputs), path
    data = json.loads((root / "docs" / "examples" / "params_example.json").read_text(encoding="utf-8"))
    assert data["fields"]
