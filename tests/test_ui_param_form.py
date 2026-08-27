"""Form generation from a params JSON (session-2 acceptance criterion)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QSpinBox,
)

from lithocloud.core import ParamsError, ParamSpec, load_params
from lithocloud.ui.param_form import ParamForm

FULL_SPEC = {
    "version": 1,
    "fields": [
        {
            "key": "voxel",
            "label": "Voxel size (m)",
            "type": "float",
            "default": 0.05,
            "min": 0.001,
            "max": 5.0,
            "help": "Edge length.",
        },
        {"key": "iters", "label": "Iterations", "type": "int", "default": 30, "min": 1, "max": 500},
        {"key": "tag", "label": "Tag", "type": "str", "default": "run"},
        {"key": "keep", "label": "Keep intensity", "type": "bool", "default": True},
        {
            "key": "method",
            "label": "Method",
            "type": "choice",
            "default": "centroid",
            "choices": ["centroid", "nearest"],
            "help": "Which point represents a voxel.",
        },
    ],
}


@pytest.fixture()
def form(qtbot) -> ParamForm:
    widget = ParamForm(ParamSpec.from_dict(FULL_SPEC))
    qtbot.addWidget(widget)
    return widget


def test_widget_types(form: ParamForm) -> None:
    assert isinstance(form.widget("voxel"), QDoubleSpinBox)
    assert isinstance(form.widget("iters"), QSpinBox)
    assert isinstance(form.widget("tag"), QLineEdit)
    assert isinstance(form.widget("keep"), QCheckBox)
    assert isinstance(form.widget("method"), QComboBox)


def test_defaults_appear_in_the_widgets(form: ParamForm) -> None:
    assert form.widget("voxel").value() == 0.05
    assert form.widget("iters").value() == 30
    assert form.widget("tag").text() == "run"
    assert form.widget("keep").isChecked() is True
    assert form.widget("method").currentText() == "centroid"


def test_min_max_reach_the_spinboxes(form: ParamForm) -> None:
    voxel = form.widget("voxel")
    assert voxel.minimum() == 0.001
    assert voxel.maximum() == 5.0

    iters = form.widget("iters")
    assert iters.minimum() == 1
    assert iters.maximum() == 500


def test_unbounded_numbers_get_wide_ranges(qtbot) -> None:
    spec = ParamSpec.from_dict(
        [{"key": "x", "type": "float", "default": 0.0}, {"key": "n", "type": "int", "default": 0}]
    )
    form = ParamForm(spec)
    qtbot.addWidget(form)

    assert form.widget("x").minimum() < -1e9
    assert form.widget("x").maximum() > 1e9
    assert form.widget("n").minimum() < -1e6


def test_help_becomes_a_tooltip(form: ParamForm) -> None:
    assert form.widget("voxel").toolTip() == "Edge length."
    assert form.widget("method").toolTip() == "Which point represents a voxel."
    assert form.widget("tag").toolTip() == ""  # no help given


def test_choice_offers_exactly_the_choices(form: ParamForm) -> None:
    combo = form.widget("method")
    assert [combo.itemText(i) for i in range(combo.count())] == ["centroid", "nearest"]


def test_values_returns_the_defaults_initially(form: ParamForm) -> None:
    assert form.values() == {
        "voxel": 0.05,
        "iters": 30,
        "tag": "run",
        "keep": True,
        "method": "centroid",
    }


def test_edited_widgets_round_trip(form: ParamForm) -> None:
    form.widget("voxel").setValue(0.25)
    form.widget("iters").setValue(99)
    form.widget("tag").setText("site-b")
    form.widget("keep").setChecked(False)
    form.widget("method").setCurrentIndex(1)

    assert form.values() == {
        "voxel": 0.25,
        "iters": 99,
        "tag": "site-b",
        "keep": False,
        "method": "nearest",
    }


def test_spinboxes_clamp_to_the_spec_bounds(form: ParamForm) -> None:
    """A user cannot type a value outside min/max - Qt clamps, spec agrees."""
    form.widget("voxel").setValue(999.0)
    assert form.widget("voxel").value() == 5.0
    form.values()  # validates without raising


def test_set_values_and_reset(form: ParamForm) -> None:
    form.set_values({"voxel": 1.5, "method": "nearest"})
    assert form.widget("voxel").value() == 1.5
    assert form.widget("method").currentText() == "nearest"

    form.reset_to_defaults()
    assert form.values() == form.spec.defaults()


def test_set_values_rejects_bad_input(form: ParamForm) -> None:
    with pytest.raises(ParamsError):
        form.set_values({"method": "bogus"})


def test_form_from_the_demo_engine_params(qtbot, repo_root: Path) -> None:
    """The real _demo params file produces a working form."""
    spec = load_params(repo_root / "engines" / "_demo" / "params_run.json")
    form = ParamForm(spec)
    qtbot.addWidget(form)

    values = form.values()
    assert values == spec.defaults()
    assert values["mode"] == "normal"


def test_form_from_the_reference_example(qtbot, examples_dir: Path) -> None:
    spec = load_params(examples_dir / "params_example.json")
    form = ParamForm(spec)
    qtbot.addWidget(form)
    assert form.values() == spec.defaults()
