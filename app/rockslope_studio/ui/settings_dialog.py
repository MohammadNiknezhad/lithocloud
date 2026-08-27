"""Settings dialog: currently just the CloudCompare.exe path (spec section 4)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import settings


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")

        self._cc_path = QLineEdit(self)
        current = settings.cloudcompare_path()
        if current is not None:
            self._cc_path.setText(str(current))
        self._cc_path.setPlaceholderText(r"e.g. C:\Program Files\CloudCompare\CloudCompare.exe")

        browse = QPushButton("Browse...", self)
        browse.clicked.connect(self._browse)

        row = QHBoxLayout()
        row.addWidget(self._cc_path, stretch=1)
        row.addWidget(browse)

        form = QFormLayout()
        form.addRow("CloudCompare.exe", row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "Locate CloudCompare", "", "Executables (*.exe)"
        )
        if path:
            self._cc_path.setText(path)

    def _save(self) -> None:
        settings.set_cloudcompare_path(self._cc_path.text().strip() or None)
        self.accept()
