"""Start dialog: create a project, open one, or pick a recent one.

Decision D4: the workspace folder is CHOSEN BY THE USER via a folder picker,
written to project.json, remembered per project. Nothing is hard-coded.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rockslope_studio.core import Project, ProjectError, create_project, load_project

from . import settings


class StartDialog(QDialog):
    """Modal. On accept, :attr:`project` holds the opened/created project."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("rockslope-studio")
        self.project: Project | None = None

        # --- create ---
        self._name = QLineEdit(self)
        self._name.setPlaceholderText("e.g. Francon")
        self._crs = QLineEdit(self)
        self._crs.setPlaceholderText("free text, e.g. EPSG:2950 (MTM zone 8)")
        self._folder = QLineEdit(self)
        self._folder.setReadOnly(True)
        browse = QPushButton("Choose folder...", self)
        browse.clicked.connect(self._browse_folder)

        folder_row = QHBoxLayout()
        folder_row.addWidget(self._folder, stretch=1)
        folder_row.addWidget(browse)

        create_form = QFormLayout()
        create_form.addRow("Site name", self._name)
        create_form.addRow("CRS note", self._crs)
        create_form.addRow("Workspace", folder_row)

        create_button = QPushButton("Create project", self)
        create_button.clicked.connect(self._create)

        create_box = QGroupBox("New project", self)
        create_layout = QVBoxLayout(create_box)
        create_layout.addLayout(create_form)
        create_layout.addWidget(create_button)

        # --- open ---
        open_button = QPushButton("Open project.json...", self)
        open_button.clicked.connect(self._open_existing)

        self._recent = QListWidget(self)
        for path in settings.recent_projects():
            item = QListWidgetItem(str(path.parent))
            item.setToolTip(str(path))
            self._recent.addItem(item)
        self._recent.itemDoubleClicked.connect(self._open_recent)

        open_box = QGroupBox("Open", self)
        open_layout = QVBoxLayout(open_box)
        open_layout.addWidget(open_button)
        open_layout.addWidget(QLabel("Recent projects (double-click):"))
        open_layout.addWidget(self._recent)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(create_box)
        layout.addWidget(open_box)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------ #

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose the workspace folder")
        if folder:
            self._folder.setText(folder)

    def _create(self) -> None:
        name = self._name.text().strip()
        folder = self._folder.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing name", "Give the site a name.")
            return
        if not folder:
            QMessageBox.warning(self, "Missing folder", "Choose a workspace folder.")
            return
        try:
            self.project = create_project(name, folder, crs_note=self._crs.text().strip())
        except ProjectError as exc:
            QMessageBox.critical(self, "Cannot create project", str(exc))
            return
        self._finish()

    def _open_existing(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "Open project", "", "Project files (project.json)"
        )
        if path:
            self._open_path(Path(path))

    def _open_recent(self, item: QListWidgetItem) -> None:
        self._open_path(Path(item.toolTip()))

    def _open_path(self, path: Path) -> None:
        try:
            self.project = load_project(path)
        except ProjectError as exc:
            QMessageBox.critical(self, "Cannot open project", str(exc))
            return
        self._finish()

    def _finish(self) -> None:
        assert self.project is not None and self.project.path is not None
        settings.remember_project(self.project.path)
        self.accept()
