"""Center zone: engine list -> action picker -> auto-form -> input pickers -> Run.

Everything here is generated from manifests and params files - engine screens
are never hand-written (architecture section 5).
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from rockslope_studio.core import (
    Action,
    Artifact,
    Engine,
    IOSpec,
    ParamsError,
    load_params,
)

from .job_runner import JobRequest
from .param_form import ParamForm

_NONE_LABEL = "(none)"


class _InputPicker(QWidget):
    """One input slot: a combo of compatible artifacts (list for `multiple`)."""

    def __init__(self, slot: IOSpec, artifacts: list[Artifact], parent=None) -> None:
        super().__init__(parent)
        self.slot = slot
        self._compatible = [a for a in artifacts if a.type == slot.type]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._combo: QComboBox | None = None
        self._list: QListWidget | None = None

        if slot.multiple:
            box = QListWidget(self)
            box.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            box.setMaximumHeight(96)
            for artifact in self._compatible:
                item = QListWidgetItem(artifact.artifact_id)
                item.setData(Qt.ItemDataRole.UserRole, artifact)
                box.addItem(item)
            self._list = box
            layout.addWidget(box)
        else:
            combo = QComboBox(self)
            if slot.optional:
                combo.addItem(_NONE_LABEL, userData=None)
            for artifact in self._compatible:
                combo.addItem(artifact.artifact_id, userData=artifact)
            self._combo = combo
            layout.addWidget(combo)

    def value(self) -> Any:
        """Artifact | list[Artifact] | None (optional, nothing chosen)."""
        if self._list is not None:
            return [
                item.data(Qt.ItemDataRole.UserRole)
                for item in self._list.selectedItems()
            ]
        assert self._combo is not None
        return self._combo.currentData()

    def is_satisfied(self) -> bool:
        value = self.value()
        if self.slot.optional:
            return True
        if self.slot.multiple:
            return bool(value)
        return value is not None


class EnginePanel(QWidget):
    """Engine list, action picker, generated form, input pickers, Run button."""

    run_requested = Signal(object)  # JobRequest

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._engines: list[Engine] = []
        self._artifacts: list[Artifact] = []
        self._form: ParamForm | None = None
        self._pickers: dict[str, _InputPicker] = {}

        self._engine_list = QListWidget(self)
        self._engine_list.currentRowChanged.connect(self._on_engine_changed)

        self._action_combo = QComboBox(self)
        self._action_combo.currentIndexChanged.connect(self._on_action_changed)

        self._detail_host = QWidget(self)
        self._detail_layout = QVBoxLayout(self._detail_host)
        self._detail_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._detail_host)

        self._status = QLabel("", self)
        self._status.setWordWrap(True)

        self._run_button = QPushButton("Run", self)
        self._run_button.clicked.connect(self._on_run)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Engines"))
        layout.addWidget(self._engine_list, stretch=1)
        layout.addWidget(QLabel("Action"))
        layout.addWidget(self._action_combo)
        layout.addWidget(scroll, stretch=2)
        layout.addWidget(self._status)
        layout.addWidget(self._run_button)

        self._refresh_run_enabled()

    # -- population --------------------------------------------------------- #

    def set_engines(self, engines: list[Engine]) -> None:
        self._engines = list(engines)
        self._engine_list.clear()
        for engine in engines:
            item = QListWidgetItem("{0}  ({1})".format(engine.name, engine.version))
            if engine.description:
                item.setToolTip(engine.description)
            self._engine_list.addItem(item)
        if engines:
            self._engine_list.setCurrentRow(0)
        else:
            self._rebuild_detail()

    def set_artifacts(self, artifacts: list[Artifact]) -> None:
        self._artifacts = list(artifacts)
        self._rebuild_detail()  # pickers must reflect the current project

    # -- current selection --------------------------------------------------- #

    def current_engine(self) -> Engine | None:
        row = self._engine_list.currentRow()
        if 0 <= row < len(self._engines):
            return self._engines[row]
        return None

    def current_action(self) -> Action | None:
        engine = self.current_engine()
        if engine is None:
            return None
        index = self._action_combo.currentIndex()
        if 0 <= index < len(engine.actions):
            return engine.actions[index]
        return None

    @property
    def form(self) -> ParamForm | None:
        return self._form

    def picker(self, key: str) -> _InputPicker | None:
        return self._pickers.get(key)

    # -- internals ----------------------------------------------------------- #

    def _on_engine_changed(self, _row: int) -> None:
        engine = self.current_engine()
        self._action_combo.blockSignals(True)
        self._action_combo.clear()
        if engine is not None:
            for action in engine.actions:
                label = action.label
                if action.interactive:
                    label += "  [console]"
                self._action_combo.addItem(label)
        self._action_combo.blockSignals(False)
        self._action_combo.setCurrentIndex(0 if engine and engine.actions else -1)
        self._rebuild_detail()

    def _on_action_changed(self, _index: int) -> None:
        self._rebuild_detail()

    def _rebuild_detail(self) -> None:
        while self._detail_layout.count():
            item = self._detail_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._form = None
        self._pickers = {}
        self._status.setText("")

        action = self.current_action()
        engine = self.current_engine()
        if action is None or engine is None:
            self._refresh_run_enabled()
            return

        if action.description:
            note = QLabel(action.description, self._detail_host)
            note.setWordWrap(True)
            self._detail_layout.addWidget(note)

        if action.inputs:
            inputs_form = QFormLayout()
            for slot in action.inputs:
                picker = _InputPicker(slot, self._artifacts, self._detail_host)
                self._pickers[slot.key] = picker
                label = "{0} ({1}{2})".format(
                    slot.key,
                    slot.type,
                    ", optional" if slot.optional else "",
                )
                inputs_form.addRow(label, picker)
            host = QWidget(self._detail_host)
            host.setLayout(inputs_form)
            self._detail_layout.addWidget(QLabel("Inputs", self._detail_host))
            self._detail_layout.addWidget(host)

        if action.params:
            params_path = engine.params_path(action)
            try:
                spec = load_params(params_path)
            except ParamsError as exc:
                warn = QLabel("Broken params file:\n{0}".format(exc), self._detail_host)
                warn.setWordWrap(True)
                self._detail_layout.addWidget(warn)
            else:
                self._form = ParamForm(spec, self._detail_host)
                self._detail_layout.addWidget(QLabel("Parameters", self._detail_host))
                self._detail_layout.addWidget(self._form)

        self._detail_layout.addStretch(1)
        self._refresh_run_enabled()

    def _refresh_run_enabled(self) -> None:
        action = self.current_action()
        ready = action is not None
        if action is not None and action.params and self._form is None:
            ready = False  # broken params file - refuse to run blind
        self._run_button.setEnabled(bool(ready))

    def _on_run(self) -> None:
        engine, action = self.current_engine(), self.current_action()
        if engine is None or action is None:
            return

        for key, picker in self._pickers.items():
            if not picker.is_satisfied():
                self._status.setText("Choose an artifact for input {0!r} first.".format(key))
                return

        params: dict[str, Any] = {}
        if self._form is not None:
            try:
                params = self._form.values()
            except ParamsError as exc:
                self._status.setText(str(exc))
                return

        inputs = {
            key: picker.value()
            for key, picker in self._pickers.items()
            if picker.value() not in (None, [])
        }
        self._status.setText("")
        self.run_requested.emit(
            JobRequest(engine=engine, action=action, params=params, inputs=inputs)
        )
