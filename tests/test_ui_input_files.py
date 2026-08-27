"""Amendment A1: input slots accept files from disk, not just artifacts."""

from __future__ import annotations

from pathlib import Path

import pytest

from lithocloud.core import ARTIFACT_TYPES, Artifact, IOSpec
from lithocloud.ui.engine_panel import EnginePanel, _InputPicker
from lithocloud.ui.input_files import (
    ALL_FILES_FILTER,
    ExternalFile,
    dialog_filter,
    extensions_for,
    is_expected_extension,
)
from lithocloud.ui.job_runner import JobRequest


def fake_artifact(artifact_id: str, type_: str) -> Artifact:
    return Artifact(artifact_id=artifact_id, type=type_, files=("f",))


def slot(key: str, type_: str, **kwargs) -> IOSpec:
    return IOSpec(key=key, type=type_, **kwargs)


# --------------------------------------------------------------------------- #
# ExternalFile
# --------------------------------------------------------------------------- #


def test_external_file_is_always_absolute(tmp_path: Path, monkeypatch) -> None:
    """The adapter, the run manifest and provenance must all see one path."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cloud.las").write_text("x", encoding="utf-8")

    external = ExternalFile(Path("cloud.las"))

    assert external.path.is_absolute()
    assert external.path == (tmp_path / "cloud.las").resolve()
    assert external.display_name == "cloud.las"


def test_external_file_is_hashable_and_comparable(tmp_path: Path) -> None:
    a = ExternalFile(tmp_path / "a.las")
    b = ExternalFile(tmp_path / "a.las")
    assert a == b
    assert len({a, b}) == 1


# --------------------------------------------------------------------------- #
# Dialog filters
# --------------------------------------------------------------------------- #


def test_the_amendments_three_filters_are_exact() -> None:
    assert extensions_for("pointcloud") == (
        ".las", ".laz", ".txt", ".xyz", ".csv", ".pts", ".asc",
    )
    assert extensions_for("transform") == (".json", ".txt")
    assert extensions_for("table") == (".csv",)


def test_the_remaining_types_have_filters() -> None:
    """Approved 2026-08-27: architecture section 4 widened to what the wrapped
    engines actually write (.pdf figures, .txt reports)."""
    assert extensions_for("figure") == (".png", ".svg", ".pdf")
    assert extensions_for("map") == (".tif", ".tiff", ".png")
    assert extensions_for("report") == (".md", ".json", ".txt")
    assert extensions_for("model") == (".joblib", ".pkl")


def test_every_artifact_type_has_a_filter() -> None:
    for type_name in ARTIFACT_TYPES:
        assert extensions_for(type_name), type_name


def test_dialog_filter_offers_the_type_then_all_files() -> None:
    text = dialog_filter("pointcloud")
    assert text.startswith("Point clouds (*.las *.laz *.txt *.xyz *.csv *.pts *.asc)")
    assert text.endswith(ALL_FILES_FILTER)
    assert ";;" in text


def test_dialog_filter_for_an_unknown_type_is_all_files() -> None:
    assert dialog_filter("nonesuch") == ALL_FILES_FILTER


@pytest.mark.parametrize(
    ("name", "type_", "expected"),
    [
        ("a.las", "pointcloud", True),
        ("a.LAZ", "pointcloud", True),   # case-insensitive
        ("a.docx", "pointcloud", False),
        ("t.json", "transform", True),
        ("t.csv", "transform", False),
        ("x.csv", "table", True),
    ],
)
def test_is_expected_extension(name: str, type_: str, expected: bool) -> None:
    assert is_expected_extension(name, type_) is expected


# --------------------------------------------------------------------------- #
# The picker
# --------------------------------------------------------------------------- #


def test_a_single_slot_offers_artifacts_and_takes_a_browsed_file(
    qtbot, tmp_path: Path
) -> None:
    picker = _InputPicker(slot("cloud", "pointcloud"), [fake_artifact("a__c", "pointcloud")])
    qtbot.addWidget(picker)

    assert picker._combo.count() == 1
    assert isinstance(picker.value(), Artifact)

    external = ExternalFile(tmp_path / "site.las")
    picker._add_external(external)

    assert picker._combo.count() == 2
    assert picker.value() == external            # newly browsed becomes current
    assert picker._combo.currentText() == "[file] site.las"
    assert picker._combo.itemData(1, 3) == str(external.path)  # ToolTipRole


def test_an_empty_project_can_still_be_run_from_a_browsed_file(
    qtbot, tmp_path: Path
) -> None:
    """The problem amendment A1 exists to fix."""
    picker = _InputPicker(slot("cloud", "pointcloud"), [])
    qtbot.addWidget(picker)

    assert picker.is_satisfied() is False        # nothing to pick - Run blocked
    picker._add_external(ExternalFile(tmp_path / "raw.las"))
    assert picker.is_satisfied() is True


def test_a_multiple_slot_mixes_artifacts_and_files(qtbot, tmp_path: Path) -> None:
    artifact = fake_artifact("a__c", "pointcloud")
    picker = _InputPicker(slot("cloud", "pointcloud", multiple=True), [artifact])
    qtbot.addWidget(picker)

    picker._list.item(0).setSelected(True)
    one = ExternalFile(tmp_path / "one.las")
    two = ExternalFile(tmp_path / "two.las")
    picker._add_external(one)
    picker._add_external(two)

    value = picker.value()
    assert value == [artifact, one, two]         # browsed files auto-selected
    assert picker._list.count() == 3


def test_optional_slot_keeps_its_none_entry(qtbot, tmp_path: Path) -> None:
    picker = _InputPicker(slot("mask", "table", optional=True), [])
    qtbot.addWidget(picker)

    assert picker.value() is None
    assert picker.is_satisfied() is True

    picker._add_external(ExternalFile(tmp_path / "m.csv"))
    assert isinstance(picker.value(), ExternalFile)


def test_the_dialog_starts_in_the_remembered_folder(qtbot, tmp_path: Path) -> None:
    picker = _InputPicker(
        slot("cloud", "pointcloud"), [], browse_dir_provider=lambda: tmp_path
    )
    qtbot.addWidget(picker)
    assert picker._start_dir() == str(tmp_path)


def test_no_remembered_folder_means_the_dialogs_default(qtbot) -> None:
    picker = _InputPicker(slot("cloud", "pointcloud"), [])
    qtbot.addWidget(picker)
    assert picker._start_dir() == ""


def test_unexpected_extensions_are_reported_but_not_blocking(
    qtbot, tmp_path: Path
) -> None:
    picker = _InputPicker(slot("cloud", "pointcloud"), [])
    qtbot.addWidget(picker)
    picker._add_external(ExternalFile(tmp_path / "notes.docx"))

    assert picker.unexpected_extensions() == ["notes.docx"]
    assert picker.is_satisfied() is True         # still runnable


def test_expected_extensions_produce_no_warning(qtbot, tmp_path: Path) -> None:
    picker = _InputPicker(slot("cloud", "pointcloud"), [])
    qtbot.addWidget(picker)
    picker._add_external(ExternalFile(tmp_path / "site.laz"))
    assert picker.unexpected_extensions() == []


# --------------------------------------------------------------------------- #
# Surviving an artifact refresh
# --------------------------------------------------------------------------- #


@pytest.fixture()
def panel(qtbot, repo_root: Path) -> EnginePanel:
    from lithocloud.core import find_engines

    widget = EnginePanel()
    qtbot.addWidget(widget)
    engines = [e for e in find_engines(repo_root, include_private=True) if e.id == "demo"]
    widget.set_engines(engines)
    return widget


def test_a_browsed_file_survives_the_post_run_refresh(
    panel: EnginePanel, tmp_path: Path
) -> None:
    """A finishing run refreshes the artifact list; the file the user browsed
    for the NEXT run must not vanish."""
    external = ExternalFile(tmp_path / "previous.csv")
    panel.picker("previous")._add_external(external)
    assert panel.picker("previous").value() == external

    panel.set_artifacts([fake_artifact("new__stats", "table")])

    picker = panel.picker("previous")
    assert external in picker.externals()
    assert picker.value() == external            # and it is still the choice


def test_a_selected_artifact_survives_the_refresh(
    panel: EnginePanel, tmp_path: Path
) -> None:
    stats = fake_artifact("a__stats", "table")
    panel.set_artifacts([stats])
    panel.picker("previous")._combo.setCurrentIndex(1)
    assert panel.picker("previous").value() == stats

    panel.set_artifacts([stats, fake_artifact("b__stats", "table")])
    assert panel.picker("previous").value() == stats


def test_browsing_reports_the_folder_for_the_project_memory(
    panel: EnginePanel, tmp_path: Path
) -> None:
    seen: list[Path] = []
    panel.browsed_dir_changed.connect(seen.append)

    picker = panel.picker("previous")
    picker._add_external(ExternalFile(tmp_path / "sub" / "x.csv"))
    picker.browsed_dir = (tmp_path / "sub")
    picker.changed.emit()

    assert seen == [tmp_path / "sub"]


def test_the_panel_seeds_the_pickers_start_folder(panel: EnginePanel, tmp_path: Path) -> None:
    panel.set_last_browse_dir(tmp_path)
    assert panel.picker("previous")._start_dir() == str(tmp_path)


# --------------------------------------------------------------------------- #
# Lineage: an external input reaches the manifest and the provenance
# --------------------------------------------------------------------------- #


def test_job_request_uses_the_absolute_path_for_an_external_file(
    tmp_path: Path, repo_root: Path
) -> None:
    from lithocloud.core import load_manifest

    engine = load_manifest(repo_root / "engines" / "_demo")
    external = ExternalFile(tmp_path / "raw cloud.csv")

    request = JobRequest(
        engine=engine, action=engine.action("run"), inputs={"previous": external}
    )

    assert request.input_paths() == {"previous": str(external.path)}
    # the id IS the path, so lineage records where the result came from
    assert request.input_ids() == {"previous": str(external.path)}


def test_job_request_mixes_artifacts_and_files_in_one_slot(
    tmp_path: Path, repo_root: Path
) -> None:
    from lithocloud.core import load_manifest

    engine = load_manifest(repo_root / "engines" / "_demo")
    artifact = Artifact(
        artifact_id="run__stats",
        type="table",
        files=("stats.csv",),
        run_dir=tmp_path,
    )
    (tmp_path / "stats.csv").write_text("x", encoding="utf-8")
    external = ExternalFile(tmp_path / "extra.csv")

    request = JobRequest(
        engine=engine,
        action=engine.action("run"),
        inputs={"previous": [artifact, external]},
    )

    assert request.input_ids() == {
        "previous": ["run__stats", str(external.path)]
    }
    assert request.input_paths() == {
        "previous": [str((tmp_path / "stats.csv").resolve()), str(external.path)]
    }


def test_an_external_input_shows_as_an_unresolved_lineage_source(
    tmp_path: Path
) -> None:
    """architecture section 16: the path resolves to no artifact, and
    parents_of returns such ids as unresolved - by design."""
    from lithocloud.core.artifacts import index_by_id, parents_of

    raw = str((tmp_path / "raw.las").resolve())
    product = Artifact(
        artifact_id="run__out", type="pointcloud", files=("out.las",), inputs=(raw,)
    )

    resolved, unresolved = parents_of(product, index_by_id([product]))

    assert resolved == []
    assert unresolved == [raw]


def test_end_to_end_an_external_file_reaches_provenance_untouched(
    qtbot, tmp_path: Path, repo_root: Path
) -> None:
    """The amendment's core guarantee, through a real subprocess run."""
    from lithocloud.core import load_manifest, load_params, scan_project
    from lithocloud.ui.job_runner import JobRunner
    import json

    raw = tmp_path / "raw inputs" / "previous stats.csv"
    raw.parent.mkdir(parents=True)
    raw.write_text("row,value\n0,0\n", encoding="utf-8")
    original_bytes = raw.read_bytes()
    original_mtime = raw.stat().st_mtime_ns

    workspace = tmp_path / "project"
    workspace.mkdir()
    engine = load_manifest(repo_root / "engines" / "_demo")
    defaults = load_params(repo_root / "engines" / "_demo" / "params_run.json").defaults()

    runner = JobRunner(workspace)
    results: list = []
    runner.job_finished.connect(lambda job, code, ok: results.append((job, code, ok)))
    runner.submit(
        JobRequest(
            engine=engine,
            action=engine.action("run"),
            params={**defaults, "seconds": 0.2, "steps": 2},
            inputs={"previous": ExternalFile(raw)},
        )
    )
    qtbot.waitUntil(lambda: len(results) == 1, timeout=60_000)

    job, code, ok = results[0]
    assert ok and code == 0

    # the raw file was neither copied into the run nor modified
    assert raw.read_bytes() == original_bytes
    assert raw.stat().st_mtime_ns == original_mtime
    assert not (job.run_dir / raw.name).exists()

    # the run manifest records the absolute path
    manifest = json.loads((job.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["inputs"] == {"previous": str(raw.resolve())}

    # and so does the output artifact's provenance
    artifacts = scan_project(workspace)
    assert len(artifacts) == 1
    assert artifacts[0].inputs == (str(raw.resolve()),)
