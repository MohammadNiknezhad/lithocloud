"""Application entry point: ``python -m rockslope_studio [--dev] [--project P]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from rockslope_studio.core import ProjectError, load_project

from .main_window import MainWindow
from .start_dialog import StartDialog


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="rockslope_studio", description=__doc__)
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
    app.setApplicationName("rockslope-studio")
    app.setOrganizationName("MohammadNiknezhad")

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
