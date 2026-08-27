"""The single main window: three zones (architecture section 8).

PROJECT (artifact tree) | ENGINE PANEL (form + run) | JOBS (log + history)
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QMessageBox, QSplitter, QWidget

from rockslope_studio.core import Project, discover_engines, scan_project

from . import settings
from .artifact_tree import ArtifactTree
from .engine_panel import EnginePanel
from .job_panel import JobPanel
from .job_runner import JobRequest, JobRunner
from .settings_dialog import SettingsDialog

#: The repo root (…/rockslope-studio), where engines/ lives.
REPO_ROOT = Path(__file__).resolve().parents[3]


class MainWindow(QMainWindow):
    def __init__(
        self,
        project: Project,
        *,
        engines_root: Path | None = None,
        dev: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("rockslope-studio - {0}".format(project.name))
        self.resize(1280, 800)

        self.tree = ArtifactTree(self)
        self.engine_panel = EnginePanel(self)
        self.job_panel = JobPanel(self)
        self.runner = JobRunner(project.workspace_path, self)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self.tree)
        splitter.addWidget(self.engine_panel)
        splitter.addWidget(self.job_panel)
        splitter.setSizes([280, 480, 520])
        self.setCentralWidget(splitter)

        self._build_menu()

        # wiring
        self.tree.refresh_requested.connect(self.refresh_artifacts)
        self.engine_panel.run_requested.connect(self._on_run_requested)
        # amendment A1: the file dialog reopens where it was last used, per project
        self.engine_panel.set_last_browse_dir(
            settings.last_browse_dir(project.workspace_path)
        )
        self.engine_panel.browsed_dir_changed.connect(self._on_browsed_dir_changed)
        self.job_panel.cancel_requested.connect(self.runner.cancel_current)
        self.runner.job_log.connect(self.job_panel.append_log)
        self.runner.job_started.connect(self._on_job_started)
        self.runner.job_finished.connect(self._on_job_finished)

        # initial content
        engines, problems = discover_engines(
            engines_root or REPO_ROOT, include_private=dev
        )
        self.engine_panel.set_engines(engines)
        if problems:
            QMessageBox.warning(
                self,
                "Broken engine manifests",
                "Skipped:\n\n" + "\n\n".join(str(p) for p in problems),
            )
        self.refresh_artifacts()
        self.job_panel.refresh_history(project.workspace_path)

    # ------------------------------------------------------------------ #

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        settings_action = file_menu.addAction("&Settings...")
        settings_action.triggered.connect(lambda: SettingsDialog(self).exec())
        file_menu.addSeparator()
        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

    def refresh_artifacts(self) -> None:
        artifacts = scan_project(self.project.workspace_path)
        self.tree.set_artifacts(artifacts)
        self.engine_panel.set_artifacts(artifacts)

    # ------------------------------------------------------------------ #

    def _on_browsed_dir_changed(self, folder) -> None:
        settings.set_last_browse_dir(self.project.workspace_path, folder)

    def _on_run_requested(self, request: JobRequest) -> None:
        self.runner.submit(request)

    def _on_job_started(self, job) -> None:
        self.job_panel.job_started(job.run_dir.name, self.runner.queued)

    def _on_job_finished(self, _job, _exit_code: int, _ok: bool) -> None:
        self.job_panel.job_finished()
        self.job_panel.refresh_history(self.project.workspace_path)
        self.refresh_artifacts()
