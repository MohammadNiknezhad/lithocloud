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
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from rockslope_studio.core import ParamField, ParamSpec

# QDoubleSpinBox needs finite bounds; the spec's min/max win when present.
_FLOAT_MIN, _FLOAT_MAX = -1e12, 1e12
_INT_MIN, _INT_MAX = -2_000_000_000, 2_000_000_000
_FLOAT_DECIMALS = 6


class ParamForm(QWidget):
    """A form widget generated from a :class:`ParamSpec`."""

    def __init__(self, spec: ParamSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._spec = spec
        self._widgets: dict[str, QWidget] = {}

        layout = QFormLayout(self)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for field in spec:
            widget = self._make_widget(field)
            if field.help:
                widget.setToolTip(field.help)
            self._widgets[field.key] = widget
            layout.addRow(field.label, widget)

    # ------------------------------------------------------------------ #

    @property
    def spec(self) -> ParamSpec:
        return self._spec

    def widget(self, key: str) -> QWidget:
        return self._widgets[key]

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

    # ------------------------------------------------------------------ #

    def values(self) -> dict[str, Any]:
        """Current form values, validated and coerced by the spec."""
        raw: dict[str, Any] = {}
        for field in self._spec:
            widget = self._widgets[field.key]
            if field.type == "float":
                raw[field.key] = widget.value()
            elif field.type == "int":
                raw[field.key] = widget.value()
            elif field.type == "bool":
                raw[field.key] = widget.isChecked()
            elif field.type == "choice":
                raw[field.key] = widget.currentData()
            else:
                raw[field.key] = widget.text()
        return self._spec.validate(raw)

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

    def reset_to_defaults(self) -> None:
        self.set_values(self._spec.defaults())
