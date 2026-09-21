"""The ``edge_list`` form widget: overlap edges as ``[fixed, moving]`` pairs.

Two spin-boxes and Add, a table of the edges, Remove, a message line, and a
hint label carrying the params file's ``help`` text. Rejects a self-edge and
a duplicate connection (either direction counts as the same connection - the
rule the ricp project engine applies) with a visible message at Add. Every
other graph rule - index range, connectivity to scan 0 - belongs to the
engine adapter, which alone knows how many scans there are.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

#: Widest scan index the spin-boxes offer; the adapter checks the real range.
MAX_INDEX = 999


class EdgeListWidget(QWidget):
    changed = Signal()

    def __init__(self, hint: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._fixed = QSpinBox(self)
        self._fixed.setRange(0, MAX_INDEX)
        self._fixed.setToolTip("fixed scan index (0 = REF)")
        self._moving = QSpinBox(self)
        self._moving.setRange(0, MAX_INDEX)
        self._moving.setValue(1)
        self._moving.setToolTip("moving scan index - its transform maps INTO the fixed scan")
        self._add = QPushButton("Add", self)
        self._add.clicked.connect(self._on_add)

        entry = QHBoxLayout()
        entry.addWidget(QLabel("fixed", self))
        entry.addWidget(self._fixed)
        entry.addWidget(QLabel("moving", self))
        entry.addWidget(self._moving)
        entry.addWidget(self._add)
        entry.addStretch(1)

        self._table = QTableWidget(0, 2, self)
        self._table.setHorizontalHeaderLabels(["fixed", "moving"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setMaximumHeight(140)

        self._remove = QPushButton("Remove", self)
        self._remove.clicked.connect(self._on_remove)

        self._message = QLabel("", self)
        self._message.setWordWrap(True)
        self._message.setObjectName("edgeListMessage")

        self._hint = QLabel(hint, self)
        self._hint.setWordWrap(True)
        self._hint.setEnabled(False)  # rendered as secondary text
        self._hint.setVisible(bool(hint))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(entry)
        layout.addWidget(self._table)
        layout.addWidget(self._remove, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._message)
        layout.addWidget(self._hint)

    # -- value ---------------------------------------------------------------- #

    def value(self) -> list[list[int]]:
        return [
            [int(self._table.item(row, 0).text()), int(self._table.item(row, 1).text())]
            for row in range(self._table.rowCount())
        ]

    def set_value(self, edges) -> None:
        self._table.setRowCount(0)
        for fixed, moving in edges:
            self._append_row(int(fixed), int(moving))
        self._message.setText("")
        self.changed.emit()

    @property
    def message(self) -> str:
        """The last rejection message ('' when the last Add succeeded)."""
        return self._message.text()

    # -- editing -------------------------------------------------------------- #

    def add_edge(self, fixed: int, moving: int) -> bool:
        """Append an edge; False (with a visible message) when rejected."""
        if fixed == moving:
            self._message.setText(
                "Rejected: {0} -> {0} is a self-edge - a scan cannot overlap itself.".format(fixed)
            )
            return False
        for existing_fixed, existing_moving in self.value():
            if {existing_fixed, existing_moving} == {fixed, moving}:
                self._message.setText(
                    "Rejected: scans {0} and {1} are already connected "
                    "({2} -> {3}); either direction is the same connection.".format(
                        fixed, moving, existing_fixed, existing_moving
                    )
                )
                return False
        self._append_row(fixed, moving)
        self._message.setText("")
        self.changed.emit()
        return True

    def remove_current(self) -> bool:
        row = self._table.currentRow()
        if row < 0:
            self._message.setText("Select an edge in the table to remove it.")
            return False
        self._table.removeRow(row)
        self._message.setText("")
        self.changed.emit()
        return True

    def _append_row(self, fixed: int, moving: int) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        for column, number in ((0, fixed), (1, moving)):
            item = QTableWidgetItem(str(number))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, column, item)

    def _on_add(self) -> None:
        self.add_edge(self._fixed.value(), self._moving.value())

    def _on_remove(self) -> None:
        self.remove_current()
