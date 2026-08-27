"""Application entry point: ``python -m lithocloud [--dev] [--project P]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from lithocloud.core import ProjectError, load_project

from . import settings
from .main_window import MainWindow
from .start_dialog import StartDialog

#: Bundled artwork. Resolved from the module, never the working directory -
#: lithocloud.bat cds before launching.
RESOURCES = Path(__file__).parent / "resources"
APP_ICON = RESOURCES / "lithocloud.ico"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="lithocloud", description=__doc__)
    parser.add_argument(
        "--dev",
        action="store_true",
        help="also discover engines in '_'-prefixed folders (e.g. the _demo engine)",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="open this workspace or project.json directly, skipping the start dialog",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("LithoCloud")
    app.setOrganizationName("MohammadNiknezhad")
    # One call covers the taskbar, the alt-tab switcher and every window -
    # including StartDialog, since QApplication already exists here.
    app.setWindowIcon(QIcon(str(APP_ICON)))
    # carry the pre-rename recent projects / folders across, once
    settings.migrate_legacy_settings()

    if args.project is not None:
        try:
            project = load_project(args.project)
        except ProjectError as exc:
            QMessageBox.critical(None, "Cannot open project", str(exc))
            return 2
    else:
        dialog = StartDialog()
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.project is None:
            return 0
        project = dialog.project

    window = MainWindow(project, dev=args.dev)
    window.show()
    return app.exec()
