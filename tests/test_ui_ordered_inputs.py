"""Ordered multiple inputs and the edge_list field (ricp projects, Part 1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from lithocloud.core import Artifact, IOSpec, ParamsError, ParamSpec, dump_params, load_params
from lithocloud.ui import settings
from lithocloud.ui.edge_list_widget import EdgeListWidget
from lithocloud.ui.engine_panel import _InputPicker
from lithocloud.ui.input_files import ExternalFile
from lithocloud.ui.param_form import ParamForm


def fake_artifact(artifact_id: str) -> Artifact:
    return Artifact(artifact_id=artifact_id, type="pointcloud", files=("f",))


@pytest.fixture()
def isolated_settings(monkeypatch, tmp_path: Path):
    ini = str(tmp_path / "lithocloud.ini")
    monkeypatch.setattr(settings, "_store", lambda: QSettings(ini, QSettings.Format.IniFormat))
    return tmp_path


# --------------------------------------------------------------------------- #
# Ordered multi-input rows
# --------------------------------------------------------------------------- #


@pytest.fixture()
def picker(qtbot):
    arts = [fake_artifact("s1"), fake_artifact("s2"), fake_artifact("s3")]
    widget = _InputPicker(IOSpec(key="aligns", type="pointcloud", multiple=True), arts)
    qtbot.addWidget(widget)
    for index in range(3):                         # add s1, s2, s3 in order
        widget._available.setCurrentIndex(index)
        widget._add_available()
    return widget


def test_rows_are_numbered_in_order(picker) -> None:
    assert picker.row_labels() == ["1.  s1", "2.  s2", "3.  s3"]
    assert [a.artifact_id for a in picker.value()] == ["s1", "s2", "s3"]


def test_reorder_round_trips_into_values(picker) -> None:
    picker.move_row(2, -1)                         # s3 up -> s1, s3, s2
    assert [a.artifact_id for a in picker.value()] == ["s1", "s3", "s2"]
    assert picker.row_labels() == ["1.  s1", "2.  s3", "3.  s2"]

    picker.move_row(0, +1)                         # s1 down -> s3, s1, s2
    assert [a.artifact_id for a in picker.value()] == ["s3", "s1", "s2"]

    picker.move_row(0, -1)                         # already first: no-op
    assert [a.artifact_id for a in picker.value()] == ["s3", "s1", "s2"]
    picker.move_row(2, +1)                         # already last: no-op
    assert [a.artifact_id for a in picker.value()] == ["s3", "s1", "s2"]


def test_remove_renumbers(picker) -> None:
    picker._list.setCurrentRow(1)
    picker._remove_current()
    assert picker.row_labels() == ["1.  s1", "2.  s3"]
    assert picker.is_satisfied() is True
    picker._list.setCurrentRow(0)
    picker._remove_current()
    picker._list.setCurrentRow(0)
    picker._remove_current()
    assert picker.value() == []
    assert picker.is_satisfied() is False


def test_the_same_artifact_may_appear_twice_and_files_interleave(picker, tmp_path: Path) -> None:
    raw = ExternalFile(tmp_path / "raw scan.las")
    picker._add_external(raw)
    picker._available.setCurrentIndex(0)
    picker._add_available()
    assert [getattr(v, "artifact_id", None) or v.display_name for v in picker.value()] == [
        "s1", "s2", "s3", "raw scan.las", "s1"
    ]
    assert picker.row_labels()[3] == "4.  [file] raw scan.las"


def test_set_value_rebuilds_rows_in_the_given_order(picker, tmp_path: Path) -> None:
    raw = ExternalFile(tmp_path / "x.las")
    picker.set_value([fake_artifact("s2"), raw, fake_artifact("s1")])
    assert [getattr(v, "artifact_id", None) or v.display_name for v in picker.value()] == [
        "s2", "x.las", "s1"
    ]
    assert picker.row_labels() == ["1.  s2", "2.  [file] x.las", "3.  s1"]


def test_order_survives_an_artifact_refresh(qtbot, isolated_settings, tmp_path: Path) -> None:
    """The panel carries (externals, value) across set_artifacts; restore must
    keep the ORDER, not just the membership."""
    from lithocloud.core import load_manifest
    from lithocloud.ui.engine_panel import EnginePanel

    # a throwaway manifest with one multiple input
    engine_dir = tmp_path / "engines" / "multi"
    engine_dir.mkdir(parents=True)
    (engine_dir / "engine.yaml").write_text(
        'id: multi\nname: M\nversion: "1"\n'
        "actions: [{id: go, label: Go, inputs: [{key: aligns, type: pointcloud, multiple: true}]}]\n"
        'run: {command: "x {input:aligns}", cwd: .}\n',
        encoding="utf-8",
    )
    panel = EnginePanel()
    qtbot.addWidget(panel)
    panel.set_engines([load_manifest(engine_dir)])
    arts = [fake_artifact("s1"), fake_artifact("s2")]
    panel.set_artifacts(arts)

    pk = panel.picker("aligns")
    pk._available.setCurrentIndex(1)
    pk._add_available()                            # s2 first
    pk._add_external(ExternalFile(tmp_path / "f.las"))
    pk._available.setCurrentIndex(0)
    pk._add_available()                            # then s1

    panel.set_artifacts(arts + [fake_artifact("s3")])   # a run finished
    pk = panel.picker("aligns")
    assert [getattr(v, "artifact_id", None) or v.display_name for v in pk.value()] == [
        "s2", "f.las", "s1"
    ]


# --------------------------------------------------------------------------- #
# edge_list: schema
# --------------------------------------------------------------------------- #


EDGES = {
    "key": "overlap_edges",
    "label": "Overlap edges",
    "type": "edge_list",
    "default": [],
    "help": "a chain without an extra loop cannot check loop consistency",
}
MODE = {
    "key": "mode",
    "type": "choice",
    "default": "independent",
    "choices": ["independent", "multiway"],
}


def test_edge_list_loads_and_validates_shape() -> None:
    spec = ParamSpec.from_dict({"version": 2, "fields": [EDGES]})
    assert spec.field("overlap_edges").type == "edge_list"
    assert spec.validate({"overlap_edges": [[0, 1], (1, 2)]}) == {
        "overlap_edges": [[0, 1], [1, 2]]
    }
    assert spec.validate({}) == {"overlap_edges": []}


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("0,1", "expected a list"),
        ([[0]], "must be a \\[fixed, moving\\] pair"),
        ([[0, 1, 2]], "must be a \\[fixed, moving\\] pair"),
        ([[0, -1]], "non-negative whole numbers"),
        ([[0, 1.5]], "non-negative whole numbers"),
        ([[True, 1]], "non-negative whole numbers"),
        ([["0", "1"]], "non-negative whole numbers"),
    ],
)
def test_edge_list_rejects_bad_shapes(value, message: str) -> None:
    spec = ParamSpec.from_dict({"version": 2, "fields": [EDGES]})
    with pytest.raises(ParamsError, match=message):
        spec.validate({"overlap_edges": value})


def test_edge_list_default_is_shape_checked_too() -> None:
    with pytest.raises(ParamsError, match="invalid default"):
        ParamSpec.from_dict({"version": 2, "fields": [{**EDGES, "default": [[1]]}]})


def test_edge_list_takes_no_min_max_or_choices() -> None:
    with pytest.raises(ParamsError, match="only allowed for 'float' and 'int'"):
        ParamSpec.from_dict({"version": 2, "fields": [{**EDGES, "min": 0}]})
    with pytest.raises(ParamsError, match="only allowed for type 'choice'"):
        ParamSpec.from_dict({"version": 2, "fields": [{**EDGES, "choices": [1]}]})


def test_edge_list_round_trips_through_dump(tmp_path: Path) -> None:
    spec = ParamSpec.from_dict(
        {"version": 2, "fields": [MODE, {**EDGES, "default": [[0, 1], [1, 2]],
                                        "visible_when": {"field": "mode", "in": ["multiway"]}}]}
    )
    out = tmp_path / "p.json"
    dump_params(spec, out)
    again = load_params(out)
    assert again.fields == spec.fields
    assert again.field("overlap_edges").default == [[0, 1], [1, 2]]


def test_edge_list_cannot_control_visibility() -> None:
    with pytest.raises(ParamsError, match="must be a choice or bool field, not edge_list"):
        ParamSpec.from_dict({"version": 2, "fields": [
            EDGES,
            {"key": "x", "type": "str", "default": "",
             "visible_when": {"field": "overlap_edges", "in": [[0, 1]]}},
        ]})


# --------------------------------------------------------------------------- #
# edge_list: the widget
# --------------------------------------------------------------------------- #


def test_widget_add_and_remove(qtbot) -> None:
    w = EdgeListWidget(hint="the hint")
    qtbot.addWidget(w)
    assert w.value() == []
    assert w._hint.text() == "the hint"

    w._fixed.setValue(0)
    w._moving.setValue(1)
    w._add.click()
    w._fixed.setValue(1)
    w._moving.setValue(2)
    w._add.click()
    assert w.value() == [[0, 1], [1, 2]]
    assert w.message == ""

    w._table.setCurrentCell(0, 0)
    w._remove.click()
    assert w.value() == [[1, 2]]


def test_widget_rejects_self_edge_and_duplicates_with_a_message(qtbot) -> None:
    w = EdgeListWidget()
    qtbot.addWidget(w)
    assert w.add_edge(2, 2) is False
    assert "self-edge" in w.message
    assert w.value() == []

    assert w.add_edge(0, 1) is True
    assert w.add_edge(0, 1) is False
    assert "already connected" in w.message
    assert w.add_edge(1, 0) is False               # either direction is the same connection
    assert "either direction" in w.message
    assert w.value() == [[0, 1]]

    assert w.add_edge(1, 2) is True                # a fresh connection clears the message
    assert w.message == ""


def test_remove_with_nothing_selected_explains(qtbot) -> None:
    w = EdgeListWidget()
    qtbot.addWidget(w)
    assert w.remove_current() is False
    assert "Select an edge" in w.message


def test_widget_emits_changed(qtbot) -> None:
    w = EdgeListWidget()
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.changed, timeout=1000):
        w.add_edge(0, 1)


# --------------------------------------------------------------------------- #
# edge_list inside the form: visible_when and hidden-value preservation
# --------------------------------------------------------------------------- #


def test_edge_list_under_visible_when_keeps_its_value(qtbot, isolated_settings) -> None:
    spec = ParamSpec.from_dict({"version": 2, "fields": [
        MODE, {**EDGES, "visible_when": {"field": "mode", "in": ["multiway"]}},
    ]})
    form = ParamForm(spec)
    qtbot.addWidget(form)
    form.show()
    edges = form.widget("overlap_edges")
    assert isinstance(edges, EdgeListWidget)
    assert not edges.isVisibleTo(form)                     # independent: hidden

    form.widget("mode").setCurrentIndex(1)                 # multiway
    assert edges.isVisibleTo(form)
    edges.add_edge(0, 1)
    edges.add_edge(1, 2)
    assert form.values()["overlap_edges"] == [[0, 1], [1, 2]]

    form.widget("mode").setCurrentIndex(0)                 # hide again
    assert not edges.isVisibleTo(form)
    assert form.values()["overlap_edges"] == [[0, 1], [1, 2]]   # untouched

    form.widget("mode").setCurrentIndex(1)
    assert edges.value() == [[0, 1], [1, 2]]


def test_set_values_and_reset_drive_the_edge_widget(qtbot, isolated_settings) -> None:
    spec = ParamSpec.from_dict({"version": 2, "fields": [MODE, EDGES]})
    form = ParamForm(spec)
    qtbot.addWidget(form)
    form.set_values({"mode": "multiway", "overlap_edges": [[0, 2], [2, 1]]})
    assert form.widget("overlap_edges").value() == [[0, 2], [2, 1]]
    form.reset_to_defaults()
    assert form.widget("overlap_edges").value() == []
    assert form.values() == {"mode": "independent", "overlap_edges": []}
