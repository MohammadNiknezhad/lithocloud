"""Left zone: the project's artifacts, grouped by type, with lineage tooltips."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lithocloud.core import ARTIFACT_TYPES, Artifact

from . import settings

_TYPE_LABELS = {
    "pointcloud": "Point clouds",
    "transform": "Transforms",
    "table": "Tables",
    "figure": "Figures",
    "map": "Maps",
    "report": "Reports",
    "model": "Models",
}


def _params_summary(artifact: Artifact, limit: int = 4) -> str:
    items = list(artifact.params.items())
    shown = ", ".join("{0}={1}".format(k, v) for k, v in items[:limit])
    if len(items) > limit:
        shown += ", ..."
    return shown or "(none)"


def lineage_tooltip(artifact: Artifact) -> str:
    """Engine, action, params summary, inputs - the spec's tooltip content."""
    lines = [
        artifact.artifact_id,
        "type: {0}".format(artifact.type),
        "engine: {0} {1}".format(artifact.engine or "?", artifact.engine_version),
        "action: {0}".format(artifact.action or "?"),
        "params: {0}".format(_params_summary(artifact)),
    ]
    if artifact.inputs:
        lines.append("inputs:")
        lines.extend("  - {0}".format(input_id) for input_id in artifact.inputs)
    else:
        lines.append("inputs: (none)")
    if artifact.created:
        lines.append("created: {0}".format(artifact.created))
    if not artifact.exists:
        lines.append("!! file(s) missing on disk")
    return "\n".join(lines)


class ArtifactTree(QWidget):
    """Tree of artifacts grouped by type + a refresh button."""

    refresh_requested = Signal()
    artifact_activated = Signal(object)  # Artifact (double-click)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._artifacts: list[Artifact] = []

        self._tree = QTreeWidget(self)
        self._tree.setHeaderLabels(["Artifact"])
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._context_menu)
        self._tree.itemDoubleClicked.connect(self._on_double_click)

        refresh = QPushButton("Refresh", self)
        refresh.clicked.connect(self.refresh_requested)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tree)
        layout.addWidget(refresh)

    # ------------------------------------------------------------------ #

    def set_artifacts(self, artifacts: list[Artifact]) -> None:
        self._artifacts = list(artifacts)
        self._tree.clear()
        by_type: dict[str, list[Artifact]] = {}
        for artifact in artifacts:
            by_type.setdefault(artifact.type, []).append(artifact)

        for type_name in ARTIFACT_TYPES:  # stable, spec-defined order
            group = by_type.get(type_name)
            if not group:
                continue
            top = QTreeWidgetItem([
                "{0} ({1})".format(_TYPE_LABELS.get(type_name, type_name), len(group))
            ])
            top.setFlags(top.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self._tree.addTopLevelItem(top)
            for artifact in group:
                item = QTreeWidgetItem([artifact.artifact_id])
                item.setToolTip(0, lineage_tooltip(artifact))
                item.setData(0, Qt.ItemDataRole.UserRole, artifact)
                top.addChild(item)
            top.setExpanded(True)

    def artifacts(self) -> list[Artifact]:
        return list(self._artifacts)

    def selected_artifact(self) -> Artifact | None:
        item = self._tree.currentItem()
        if item is None:
            return None
        data = item.data(0, Qt.ItemDataRole.UserRole)
        return data if isinstance(data, Artifact) else None

    # ------------------------------------------------------------------ #

    def _on_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(data, Artifact):
            self.artifact_activated.emit(data)

    def _context_menu(self, pos) -> None:
        artifact = self.selected_artifact()
        if artifact is None:
            return
        menu = QMenu(self)
        show = menu.addAction("Show in Explorer")
        open_cc = None
        if artifact.type == "pointcloud":
            open_cc = menu.addAction("Open in CloudCompare")
            open_cc.setEnabled(settings.cloudcompare_path() is not None)
            if settings.cloudcompare_path() is None:
                open_cc.setToolTip("Set the CloudCompare path in File > Settings first")
        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen is show:
            self._show_in_explorer(artifact)
        elif open_cc is not None and chosen is open_cc:
            self._open_in_cloudcompare(artifact)

    def _first_path(self, artifact: Artifact) -> Path | None:
        try:
            paths = artifact.paths
        except Exception:  # noqa: BLE001 - a corrupt artifact must not crash the tree
            return None
        return paths[0] if paths else None

    def _show_in_explorer(self, artifact: Artifact) -> None:
        path = self._first_path(artifact)
        if path is None or not path.exists():
            QMessageBox.warning(self, "Missing file", "The artifact's file is not on disk.")
            return
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:  # pragma: no cover
            subprocess.Popen(["xdg-open", str(path.parent)])

    def _open_in_cloudcompare(self, artifact: Artifact) -> None:
        exe = settings.cloudcompare_path()
        path = self._first_path(artifact)
        if exe is None or path is None:
            return
        subprocess.Popen([str(exe), str(path)], cwd=str(path.parent))
