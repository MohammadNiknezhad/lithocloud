"""ParamForm with schema v2: sections, collapsed state, reactive visibility.

QSettings is bound to a throwaway INI (never the real registry - see
test_ui_identity.py for why setDefaultFormat is not enough).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QGroupBox, QLabel

from lithocloud.core import ParamSpec, load_params
from lithocloud.ui import settings
from lithocloud.ui.param_form import ParamForm

REPO_ROOT = Path(__file__).resolve().parents[1]

GROUPED = {
    "version": 2,
    "fields": [
        {
            "key": "method",
            "label": "Method",
            "type": "choice",
            "default": "all",
            "choices": ["paper-c2c", "local-plane", "m3c2", "all"],
        },
        {
            "key": "plane_radius",
            "label": "Plane radius",
            "type": "str",
            "default": "",
            "visible_when": {"field": "method", "in": ["local-plane", "all"]},
        },
        {
            "key": "core_points",
            "label": "Core points",
            "type": "str",
            "default": "",
            "group": "Advanced",
            "collapsed": True,
            "visible_when": {"field": "method", "in": ["m3c2", "all"]},
        },
        {
            "key": "normal_radius",
            "label": "Normal radius",
            "type": "float",
            "default": 1.5,
            "group": "Advanced",
            "visible_when": {"field": "method", "in": ["m3c2", "all"]},
        },
        {"key": "seed", "label": "Seed", "type": "int", "default": 0, "group": "Advanced"},
        {"key": "extra", "label": "Extra", "type": "str", "default": "", "group": "Advanced"},
    ],
}


@pytest.fixture()
def isolated_settings(monkeypatch, tmp_path: Path):
    ini = str(tmp_path / "lithocloud.ini")
    monkeypatch.setattr(settings, "_store", lambda: QSettings(ini, QSettings.Format.IniFormat))
    return tmp_path


@pytest.fixture()
def form(qtbot, isolated_settings) -> ParamForm:
    widget = ParamForm(ParamSpec.from_dict(GROUPED), state_key="ricp/register")
    qtbot.addWidget(widget)
    widget.show()
    return widget


def shown(form: ParamForm, key: str) -> bool:
    """Qt-level truth: both the widget and its label are visible."""
    label = form.label_widget(key)
    return form.widget(key).isVisibleTo(form) and (label is None or label.isVisibleTo(form))


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #


def test_one_section_per_group_titled_ones_are_group_boxes(form: ParamForm) -> None:
    assert form.spec.groups() == (None, "Advanced")
    assert form.section(None) is None
    box = form.section("Advanced")
    assert isinstance(box, QGroupBox)
    assert box.title() == "Advanced"
    # every field has a widget, whichever section it lives in
    assert set(form.spec.keys) == {
        "method", "plane_radius", "core_points", "normal_radius", "seed", "extra"
    }
    assert all(form.widget(k) is not None for k in form.spec.keys)


def test_a_collapsed_group_starts_collapsed_and_remembers_being_opened(
    qtbot, isolated_settings
) -> None:
    first = ParamForm(ParamSpec.from_dict(GROUPED), state_key="ricp/register")
    qtbot.addWidget(first)
    first.show()
    box = first.section("Advanced")
    assert box.isCheckable()
    assert first.is_section_collapsed("Advanced") is True
    assert not first.widget("seed").isVisibleTo(first)   # contents hidden

    box.setChecked(True)                                  # the user expands it
    assert first.is_section_collapsed("Advanced") is False
    assert first.widget("seed").isVisibleTo(first)
    assert settings.section_collapsed("ricp/register", "Advanced") is False

    # a new form for the SAME engine+action comes back expanded...
    again = ParamForm(ParamSpec.from_dict(GROUPED), state_key="ricp/register")
    qtbot.addWidget(again)
    again.show()
    assert again.is_section_collapsed("Advanced") is False

    # ...while another action keeps the file's default
    other = ParamForm(ParamSpec.from_dict(GROUPED), state_key="ricp/other")
    qtbot.addWidget(other)
    other.show()
    assert other.is_section_collapsed("Advanced") is True


def test_collapsing_again_is_remembered_too(form: ParamForm) -> None:
    box = form.section("Advanced")
    box.setChecked(True)
    box.setChecked(False)
    assert settings.section_collapsed("ricp/register", "Advanced") is True


def test_an_anonymous_form_remembers_nothing(qtbot, isolated_settings) -> None:
    widget = ParamForm(ParamSpec.from_dict(GROUPED))       # no state_key
    qtbot.addWidget(widget)
    widget.section("Advanced").setChecked(True)
    assert settings.section_collapsed(None, "Advanced") is None
    assert QSettings(str(isolated_settings / "lithocloud.ini"),
                     QSettings.Format.IniFormat).allKeys() == []


def test_an_uncollapsed_titled_group_is_a_plain_box(qtbot, isolated_settings) -> None:
    spec = ParamSpec.from_dict({
        "version": 2,
        "fields": [{"key": "a", "type": "int", "default": 0, "group": "Options"}],
    })
    widget = ParamForm(spec)
    qtbot.addWidget(widget)
    box = widget.section("Options")
    assert isinstance(box, QGroupBox) and not box.isCheckable()
    assert widget.is_section_collapsed("Options") is False


# --------------------------------------------------------------------------- #
# Reactive visibility
# --------------------------------------------------------------------------- #


def choose(form: ParamForm, key: str, value: str) -> None:
    combo = form.widget(key)
    combo.setCurrentIndex(form.spec.field(key).choices.index(value))


def test_rows_follow_the_controller(form: ParamForm) -> None:
    form.section("Advanced").setChecked(True)             # so Qt visibility is meaningful

    assert shown(form, "plane_radius") and shown(form, "core_points")
    assert shown(form, "seed")                             # unconditional

    choose(form, "method", "m3c2")
    assert not shown(form, "plane_radius")
    assert shown(form, "core_points") and shown(form, "normal_radius")

    choose(form, "method", "local-plane")
    assert shown(form, "plane_radius")
    assert not shown(form, "core_points") and not shown(form, "normal_radius")

    choose(form, "method", "paper-c2c")
    assert not shown(form, "plane_radius") and not shown(form, "core_points")
    assert shown(form, "seed") and shown(form, "extra")


def test_is_visible_reports_the_spec_rule_even_inside_a_collapsed_section(form: ParamForm) -> None:
    choose(form, "method", "m3c2")
    assert form.is_visible("core_points") is True          # rule says shown...
    assert form.is_section_collapsed("Advanced") is True   # ...its section is just folded
    assert form.is_visible("plane_radius") is False


def test_hidden_values_survive_two_toggles(form: ParamForm) -> None:
    """The spec's hard rule: never reset, clear or re-default a hidden field."""
    form.section("Advanced").setChecked(True)             # unfold, so Qt visibility is meaningful
    form.widget("plane_radius").setText("0.35")
    form.widget("core_points").setText("8000")
    form.widget("normal_radius").setValue(2.25)

    choose(form, "method", "paper-c2c")                    # hides all three
    assert not shown(form, "plane_radius")
    assert form.values()["plane_radius"] == "0.35"         # still returned
    assert form.values()["core_points"] == "8000"
    assert form.values()["normal_radius"] == 2.25

    choose(form, "method", "m3c2")                         # plane stays hidden
    choose(form, "method", "all")                          # everything back
    assert shown(form, "plane_radius") and shown(form, "core_points")
    assert form.widget("plane_radius").text() == "0.35"
    assert form.widget("core_points").text() == "8000"
    assert form.widget("normal_radius").value() == 2.25


def test_values_returns_every_field_whatever_is_hidden(form: ParamForm) -> None:
    choose(form, "method", "paper-c2c")
    assert set(form.values()) == set(form.spec.keys)


def test_set_values_and_reset_reevaluate_visibility(form: ParamForm) -> None:
    form.set_values({"method": "m3c2", "core_points": "123"})
    assert not shown(form, "plane_radius")
    assert form.is_visible("core_points") is True
    assert form.widget("core_points").text() == "123"

    form.reset_to_defaults()                                # method back to 'all'
    assert shown(form, "plane_radius")
    assert form.widget("core_points").text() == ""


def test_a_bool_controller_toggles_its_dependents(qtbot, isolated_settings) -> None:
    spec = ParamSpec.from_dict({
        "version": 2,
        "fields": [
            {"key": "fit", "label": "Fit", "type": "bool", "default": True},
            {"key": "max_tilt", "label": "Max tilt", "type": "float", "default": 10.0,
             "visible_when": {"field": "fit", "in": [True]}},
        ],
    })
    widget = ParamForm(spec)
    qtbot.addWidget(widget)
    widget.show()
    assert shown(widget, "max_tilt")
    widget.widget("fit").setChecked(False)
    assert not shown(widget, "max_tilt")
    assert widget.values()["max_tilt"] == 10.0
    widget.widget("fit").setChecked(True)
    assert shown(widget, "max_tilt")


def test_chained_visibility_in_the_form(qtbot, isolated_settings) -> None:
    spec = ParamSpec.from_dict({
        "version": 2,
        "fields": [
            {"key": "a", "label": "A", "type": "bool", "default": True},
            {"key": "b", "label": "B", "type": "bool", "default": True,
             "visible_when": {"field": "a", "in": [True]}},
            {"key": "c", "label": "C", "type": "str", "default": "x",
             "visible_when": {"field": "b", "in": [True]}},
        ],
    })
    widget = ParamForm(spec)
    qtbot.addWidget(widget)
    widget.show()
    assert shown(widget, "c")
    widget.widget("a").setChecked(False)                    # hides b, hence c
    assert not shown(widget, "b") and not shown(widget, "c")
    assert widget.widget("b").isChecked() is True           # b's value untouched


# --------------------------------------------------------------------------- #
# An existing engine's file renders exactly as before
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "relative",
    [
        "engines/tlsphoto/params_fuse.json",
        "engines/geohazard/params_run.json",
        # engines/ricp/params_register.json is schema v2 since A2 session B
        # (grouped, collapsed Advanced) - covered by test_ricp_method_params.py
        "engines/_demo/params_run.json",
        "docs/examples/params_example.json",
    ],
)
def test_a_v1_engine_file_renders_as_one_flat_untitled_section(
    qtbot, isolated_settings, relative: str
) -> None:
    spec = load_params(REPO_ROOT / relative)
    widget = ParamForm(spec, state_key="x/y")
    qtbot.addWidget(widget)
    widget.show()

    assert spec.groups() == (None,)
    assert widget.findChildren(QGroupBox) == []            # no sections at all
    labels = [l.text() for l in widget.findChildren(QLabel)]
    assert labels == [f.label for f in spec]                # every row, file order
    assert all(shown(widget, k) for k in spec.keys)         # nothing conditional
    assert widget.values() == spec.defaults()
    assert settings.section_collapsed("x/y", "anything") is None
