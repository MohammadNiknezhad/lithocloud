"""Center zone: engine list -> action picker -> auto-form -> input pickers -> Run.

Everything here is generated from manifests and params files - engine screens
are never hand-written (architecture section 5).
"""

from __future__ import annotations

from typing import Any

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
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

from .input_files import ExternalFile, dialog_filter, is_expected_extension
from .job_runner import JobRequest
from .param_form import ParamForm

_NONE_LABEL = "(none)"


class _InputPicker(QWidget):
    """One input slot: compatible artifacts + a Browse button (amendment A1).

    A file chosen from disk becomes an :class:`ExternalFile` entry alongside
    the artifacts, so the two can be mixed freely in a ``multiple`` slot. The
    raw file is never copied or modified - only its absolute path is used.
    """

    #: emitted when the chosen value changes, so the panel can re-check it
    changed = Signal()

    def __init__(
        self,
        slot: IOSpec,
        artifacts: list[Artifact],
        *,
        browse_dir_provider=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.slot = slot
        self._compatible = [a for a in artifacts if a.type == slot.type]
        self._browse_dir_provider = browse_dir_provider

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._combo: QComboBox | None = None
        self._list: QListWidget | None = None

        if slot.multiple:
            box = QListWidget(self)
            box.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            box.setMaximumHeight(96)
            for artifact in self._compatible:
                box.addItem(self._artifact_item(artifact))
            box.itemSelectionChanged.connect(self.changed)
            self._list = box
            layout.addWidget(box, stretch=1)
        else:
            combo = QComboBox(self)
            if slot.optional:
                combo.addItem(_NONE_LABEL, userData=None)
            for artifact in self._compatible:
                combo.addItem(artifact.artifact_id, userData=artifact)
                combo.setItemData(
                    combo.count() - 1, artifact.artifact_id, Qt.ItemDataRole.ToolTipRole
                )
            combo.currentIndexChanged.connect(self.changed)
            self._combo = combo
            layout.addWidget(combo, stretch=1)

        browse = QPushButton("Browse...", self)
        browse.setToolTip(
            "Choose {0} file(s) from disk. The file is used where it is - "
            "never copied or modified.".format(slot.type)
            if slot.multiple
            else "Choose a {0} file from disk. The file is used where it is - "
            "never copied or modified.".format(slot.type)
        )
        browse.clicked.connect(self._browse)
        layout.addWidget(browse)

    # ------------------------------------------------------------------ #

    @staticmethod
    def _artifact_item(artifact: Artifact) -> QListWidgetItem:
        item = QListWidgetItem(artifact.artifact_id)
        item.setData(Qt.ItemDataRole.UserRole, artifact)
        item.setToolTip(artifact.artifact_id)
        return item

    @staticmethod
    def _file_label(external: ExternalFile) -> str:
        return "[file] {0}".format(external.display_name)

    def _start_dir(self) -> str:
        if self._browse_dir_provider is not None:
            folder = self._browse_dir_provider()
            if folder:
                return str(folder)
        return ""

    def _browse(self) -> None:
        caption = "Choose {0} file{1} for '{2}'".format(
            self.slot.type, "s" if self.slot.multiple else "", self.slot.key
        )
        file_filter = dialog_filter(self.slot.type)

        if self.slot.multiple:
            paths, _ = QFileDialog.getOpenFileNames(
                self, caption, self._start_dir(), file_filter
            )
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, caption, self._start_dir(), file_filter
            )
            paths = [path] if path else []

        chosen = [ExternalFile(Path(p)) for p in paths if p]
        if not chosen:
            return

        for external in chosen:
            self._add_external(external)
        self.browsed_dir = chosen[-1].path.parent
        self.changed.emit()

    def _add_external(self, external: ExternalFile) -> None:
        label = self._file_label(external)
        if self._list is not None:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, external)
            item.setToolTip(str(external.path))
            self._list.addItem(item)
            item.setSelected(True)  # newly browsed files are used straight away
        else:
            assert self._combo is not None
            self._combo.addItem(label, userData=external)
            index = self._combo.count() - 1
            self._combo.setItemData(index, str(external.path), Qt.ItemDataRole.ToolTipRole)
            self._combo.setCurrentIndex(index)

    # ------------------------------------------------------------------ #

    def externals(self) -> list[ExternalFile]:
        """Every browsed file currently offered by this row (selected or not)."""
        out: list[ExternalFile] = []
        if self._list is not None:
            for row in range(self._list.count()):
                data = self._list.item(row).data(Qt.ItemDataRole.UserRole)
                if isinstance(data, ExternalFile):
                    out.append(data)
        elif self._combo is not None:
            for index in range(self._combo.count()):
                data = self._combo.itemData(index)
                if isinstance(data, ExternalFile):
                    out.append(data)
        return out

    def restore(self, externals: list[ExternalFile], current: Any) -> None:
        """Re-offer previously browsed files after an artifact refresh.

        Without this, finishing a run would silently drop the file the user
        browsed for the next one.
        """
        for external in externals:
            self._add_external(external)
        self.set_value(current)

    def set_value(self, value: Any) -> None:
        wanted = value if isinstance(value, list) else [value]
        wanted_ids = {_value_id(v) for v in wanted if v is not None}
        if not wanted_ids:
            return

        if self._list is not None:
            for row in range(self._list.count()):
                item = self._list.item(row)
                item.setSelected(
                    _value_id(item.data(Qt.ItemDataRole.UserRole)) in wanted_ids
                )
        elif self._combo is not None:
            for index in range(self._combo.count()):
                if _value_id(self._combo.itemData(index)) in wanted_ids:
                    self._combo.setCurrentIndex(index)
                    return

    def value(self) -> Any:
        """Artifact | ExternalFile | list of either | None."""
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

    def unexpected_extensions(self) -> list[str]:
        """Browsed files whose extension is unusual for this slot's type.

        A warning only: the All-files option exists on purpose (approved
        2026-08-27), so an odd-but-valid extension must never block a run.
        """
        value = self.value()
        chosen = value if isinstance(value, list) else [value]
        return [
            item.path.name
            for item in chosen
            if isinstance(item, ExternalFile)
            and not is_expected_extension(item.path, self.slot.type)
        ]


def _value_id(value: Any) -> str | None:
    if isinstance(value, Artifact):
        return value.artifact_id
    if isinstance(value, ExternalFile):
        return str(value.path)
    return None


class EnginePanel(QWidget):
    """Engine list, action picker, generated form, input pickers, Run button."""

    run_requested = Signal(object)  # JobRequest

    #: emitted with the folder of the most recently browsed file, so the
    #: window can remember it per project (amendment A1).
    browsed_dir_changed = Signal(object)  # Path

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._engines: list[Engine] = []
        self._artifacts: list[Artifact] = []
        self._form: ParamForm | None = None
        self._pickers: dict[str, _InputPicker] = {}
        #: last folder a file dialog was used in; seeded by the main window
        self._last_browse_dir: Path | None = None

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
        """Refresh the pickers after the project's artifacts changed.

        Files browsed from disk survive the rebuild: a run finishing must not
        silently discard the input the user just chose for the next one.
        """
        self._artifacts = list(artifacts)
        carried = {
            key: (picker.externals(), picker.value())
            for key, picker in self._pickers.items()
        }
        self._rebuild_detail()
        for key, (externals, current) in carried.items():
            picker = self._pickers.get(key)
            if picker is not None and (externals or current):
                picker.restore(externals, current)

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

    # -- browsed-folder memory ----------------------------------------------- #

    def set_last_browse_dir(self, folder: "Path | str | None") -> None:
        self._last_browse_dir = Path(folder) if folder else None

    def _browse_dir(self) -> "Path | None":
        return self._last_browse_dir

    def _on_picker_changed(self) -> None:
        """A picker's value changed - remember any new folder, re-check Run."""
        for picker in self._pickers.values():
            folder = getattr(picker, "browsed_dir", None)
            if folder is not None and folder != self._last_browse_dir:
                self._last_browse_dir = folder
                self.browsed_dir_changed.emit(folder)
        self._status.setText("")
        self._refresh_run_enabled()

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
                picker = _InputPicker(
                    slot,
                    self._artifacts,
                    browse_dir_provider=self._browse_dir,
                    parent=self._detail_host,
                )
                picker.changed.connect(self._on_picker_changed)
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
                self._status.setText(
                    "Choose an artifact or a file for input {0!r} first.".format(key)
                )
                return

        # Unusual extensions are a warning, never a block: the All-files option
        # in the dialog exists on purpose (approved 2026-08-27).
        notes: list[str] = []
        for key, picker in self._pickers.items():
            for name in picker.unexpected_extensions():
                notes.append(
                    "{0} is unusual for the {1} input {2!r}".format(
                        name, picker.slot.type, key
                    )
                )

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
        self._status.setText("Note: " + "; ".join(notes) if notes else "")
        self.run_requested.emit(
            JobRequest(engine=engine, action=action, params=params, inputs=inputs)
        )
