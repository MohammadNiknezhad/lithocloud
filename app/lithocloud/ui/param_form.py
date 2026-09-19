"""Auto-generated parameter form (architecture section 5, "Auto-forms").

One :class:`ParamForm` is built from one ``core.params.ParamSpec``. Engine
screens are never hand-written: this widget IS the engine screen.

Widget per field type:

====== =====================
float  QDoubleSpinBox
int    QSpinBox
str    QLineEdit
bool   QCheckBox
choice QComboBox
====== =====================

Defaults, min/max and help tooltips all come from the params JSON. The values
are validated again by ``spec.validate`` on the way out, so the form can never
hand an engine something the spec rejects.

Schema v2 (amendment A2, 2026-09-19) adds layout on top:

* one section per ``group`` - a titled section is a ``QGroupBox``; one that
  declares ``collapsed`` is checkable, unchecked = contents hidden, and its
  state is remembered per engine+action (``state_key``) in QSettings;
* ``visible_when`` rows are shown or hidden live as their controlling widget
  changes. **A hidden row keeps its value** - nothing is reset or re-defaulted
  because it became hidden, and :meth:`values` keeps returning every field, so
  a saved run configuration stays complete.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from lithocloud.core import ParamField, ParamSpec

from . import settings

# QDoubleSpinBox needs finite bounds; the spec's min/max win when present.
_FLOAT_MIN, _FLOAT_MAX = -1e12, 1e12
_INT_MIN, _INT_MAX = -2_000_000_000, 2_000_000_000
_FLOAT_DECIMALS = 6


class ParamForm(QWidget):
    """A form widget generated from a :class:`ParamSpec`."""

    def __init__(
        self,
        spec: ParamSpec,
        parent: QWidget | None = None,
        *,
        state_key: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._spec = spec
        #: "engine/action" - namespaces the remembered collapsed state.
        self._state_key = state_key
        self._widgets: dict[str, QWidget] = {}
        self._row_layout: dict[str, QFormLayout] = {}
        self._sections: dict[str | None, QGroupBox | None] = {}
        self._contents: dict[str | None, QWidget] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        for group in spec.groups():
            outer.addWidget(self._build_section(group))

        for key in spec.controllers():
            self._change_signal(self._widgets[key]).connect(self._refresh_visibility)
        self._refresh_visibility()

    # ------------------------------------------------------------------ #

    @property
    def spec(self) -> ParamSpec:
        return self._spec

    @property
    def state_key(self) -> str | None:
        return self._state_key

    def widget(self, key: str) -> QWidget:
        return self._widgets[key]

    def label_widget(self, key: str) -> QWidget | None:
        """The QLabel paired with *key*'s widget (None for an unlabelled row)."""
        return self._row_layout[key].labelForField(self._widgets[key])

    def section(self, group: str | None) -> QGroupBox | None:
        """The group box of a titled section; ``None`` for the untitled one."""
        return self._sections[group]

    def is_section_collapsed(self, group: str) -> bool:
        box = self._sections[group]
        return bool(box is not None and box.isCheckable() and not box.isChecked())

    def is_visible(self, key: str) -> bool:
        """Whether *key*'s row is currently shown (spec rule, not Qt state)."""
        return self._spec.is_visible(key, self._raw_values())

    # -- building ---------------------------------------------------------- #

    def _build_section(self, group: str | None) -> QWidget:
        contents = QWidget(self)
        form = QFormLayout(contents)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        if group is not None:
            form.setContentsMargins(0, 0, 0, 0)
        for field in self._spec.fields_in(group):
            widget = self._make_widget(field)
            if field.help:
                widget.setToolTip(field.help)
            self._widgets[field.key] = widget
            self._row_layout[field.key] = form
            form.addRow(field.label, widget)
        self._contents[group] = contents

        if group is None:
            self._sections[group] = None
            return contents

        box = QGroupBox(group, self)
        inner = QVBoxLayout(box)
        inner.addWidget(contents)
        if self._spec.is_collapsed(group):
            # Checkable: the tick is the expand/collapse control. Qt only
            # DISABLES children when unchecked, so hide the contents ourselves.
            box.setCheckable(True)
            remembered = settings.section_collapsed(self._state_key, group)
            collapsed = True if remembered is None else remembered
            box.setChecked(not collapsed)
            contents.setVisible(not collapsed)
            box.toggled.connect(lambda expanded, g=group: self._on_section_toggled(g, expanded))
        self._sections[group] = box
        return box

    def _on_section_toggled(self, group: str, expanded: bool) -> None:
        self._contents[group].setVisible(expanded)
        settings.set_section_collapsed(self._state_key, group, not expanded)

    def _make_widget(self, field: ParamField) -> QWidget:
        if field.type == "float":
            box = QDoubleSpinBox(self)
            box.setDecimals(_FLOAT_DECIMALS)
            box.setRange(
                field.min if field.min is not None else _FLOAT_MIN,
                field.max if field.max is not None else _FLOAT_MAX,
            )
            box.setValue(float(field.default))
            return box

        if field.type == "int":
            box = QSpinBox(self)
            box.setRange(
                int(field.min) if field.min is not None else _INT_MIN,
                int(field.max) if field.max is not None else _INT_MAX,
            )
            box.setValue(int(field.default))
            return box

        if field.type == "bool":
            check = QCheckBox(self)
            check.setChecked(bool(field.default))
            return check

        if field.type == "choice":
            combo = QComboBox(self)
            assert field.choices is not None
            for choice in field.choices:
                combo.addItem(str(choice), userData=choice)
            combo.setCurrentIndex(field.choices.index(field.default))
            return combo

        # str
        edit = QLineEdit(self)
        edit.setText(str(field.default))
        return edit

    @staticmethod
    def _change_signal(widget: QWidget):
        """The signal that fires when a controller's value changes."""
        if isinstance(widget, QComboBox):
            return widget.currentIndexChanged
        if isinstance(widget, QCheckBox):
            return widget.toggled
        raise TypeError("only choice and bool fields can control visibility")

    # -- visibility --------------------------------------------------------- #

    def _raw_values(self) -> dict[str, Any]:
        raw: dict[str, Any] = {}
        for field in self._spec:
            widget = self._widgets[field.key]
            if field.type in ("float", "int"):
                raw[field.key] = widget.value()
            elif field.type == "bool":
                raw[field.key] = widget.isChecked()
            elif field.type == "choice":
                raw[field.key] = widget.currentData()
            else:
                raw[field.key] = widget.text()
        return raw

    def _refresh_visibility(self) -> None:
        """Show/hide every conditional row for the current controller values.

        Only the label and widget are toggled - values are never touched.
        """
        raw = self._raw_values()
        for field in self._spec:
            if field.visible_when is None:
                continue
            shown = self._spec.is_visible(field.key, raw)
            widget = self._widgets[field.key]
            widget.setVisible(shown)
            label = self._row_layout[field.key].labelForField(widget)
            if label is not None:
                label.setVisible(shown)

    # -- values -------------------------------------------------------------- #

    def values(self) -> dict[str, Any]:
        """Current form values - EVERY field, hidden ones included - validated
        and coerced by the spec."""
        return self._spec.validate(self._raw_values())

    def set_values(self, values: dict[str, Any]) -> None:
        """Programmatically fill the form (used by tests; later: presets)."""
        checked = self._spec.validate(values)
        for field in self._spec:
            widget = self._widgets[field.key]
            value = checked[field.key]
            if field.type in ("float", "int"):
                widget.setValue(value)
            elif field.type == "bool":
                widget.setChecked(value)
            elif field.type == "choice":
                assert field.choices is not None
                widget.setCurrentIndex(field.choices.index(value))
            else:
                widget.setText(value)
        self._refresh_visibility()

    def reset_to_defaults(self) -> None:
        self.set_values(self._spec.defaults())
