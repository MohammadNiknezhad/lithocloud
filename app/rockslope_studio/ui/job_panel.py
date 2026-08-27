"""Third zone: live log, status + elapsed time, Cancel, and the job history."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rockslope_studio.core import RunRecord, list_runs

_MAX_LOG_BLOCKS = 20_000  # keep memory bounded on chatty engines


class JobPanel(QWidget):
    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._elapsed = QElapsedTimer()
        self._ticker = QTimer(self)
        self._ticker.setInterval(1000)
        self._ticker.timeout.connect(self._tick)

        # --- live tab ---
        self._log = QPlainTextEdit(self)
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(_MAX_LOG_BLOCKS)

        self._status = QLabel("idle", self)
        self._cancel = QPushButton("Cancel", self)
        self._cancel.setEnabled(False)
        self._cancel.clicked.connect(self.cancel_requested)

        status_row = QHBoxLayout()
        status_row.addWidget(self._status, stretch=1)
        status_row.addWidget(self._cancel)

        live = QWidget(self)
        live_layout = QVBoxLayout(live)
        live_layout.setContentsMargins(0, 0, 0, 0)
        live_layout.addLayout(status_row)
        live_layout.addWidget(self._log)

        # --- history tab ---
        self._history = QTreeWidget(self)
        self._history.setHeaderLabels(
            ["Run", "Engine", "Action", "Status", "Exit", "Started"]
        )
        self._history.setRootIsDecorated(False)

        tabs = QTabWidget(self)
        tabs.addTab(live, "Current job")
        tabs.addTab(self._history, "History")
        self._tabs = tabs

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(tabs)

    # -- live job ------------------------------------------------------------ #

    def job_started(self, name: str, queued: int) -> None:
        self._elapsed.restart()
        self._ticker.start()
        self._cancel.setEnabled(True)
        self._set_status(name, queued)
        self._tabs.setCurrentIndex(0)

    def job_finished(self) -> None:
        self._ticker.stop()
        self._cancel.setEnabled(False)
        self._status.setText("idle")

    def append_log(self, line: str) -> None:
        self._log.appendPlainText(line)

    def clear_log(self) -> None:
        self._log.clear()

    def _tick(self) -> None:
        # re-render the elapsed time; the rest of the status text is kept
        text = self._status.text()
        base = text.split("  |  ")[0]
        self._status.setText("{0}  |  {1}".format(base, self._format_elapsed()))

    def _set_status(self, name: str, queued: int) -> None:
        base = "running: {0}".format(name)
        if queued:
            base += "  (+{0} queued)".format(queued)
        self._status.setText("{0}  |  {1}".format(base, self._format_elapsed()))

    def _format_elapsed(self) -> str:
        seconds = self._elapsed.elapsed() // 1000
        return "{0:d}:{1:02d}".format(int(seconds // 60), int(seconds % 60))

    # -- history ------------------------------------------------------------- #

    def refresh_history(self, workspace: Path) -> None:
        self._history.clear()
        for record in reversed(list_runs(workspace)):  # newest first
            self._history.addTopLevelItem(self._history_item(record))
        for column in range(self._history.columnCount()):
            self._history.resizeColumnToContents(column)

    @staticmethod
    def _history_item(record: RunRecord) -> QTreeWidgetItem:
        if record.succeeded:
            status = "OK"
        elif record.cancelled:
            status = "CANCELLED"
        elif record.running:
            status = "running / interrupted"
        else:
            status = "FAILED"
        item = QTreeWidgetItem(
            [
                record.name,
                record.engine,
                record.action,
                status,
                "" if record.exit_code is None else str(record.exit_code),
                record.started,
            ]
        )
        if record.problem:
            item.setToolTip(0, record.problem)
        return item
