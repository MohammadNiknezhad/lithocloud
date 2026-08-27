"""Per-user settings - QSettings, never a file in the repo.

On Windows this lands in the registry under
``HKCU\\Software\\MohammadNiknezhad\\rockslope-studio``.
Stored here: the recent-projects list and the CloudCompare.exe path.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

_ORG = "MohammadNiknezhad"
_APP = "rockslope-studio"

_RECENT_KEY = "projects/recent"
_CLOUDCOMPARE_KEY = "tools/cloudcompare_path"

MAX_RECENT = 8


def _store() -> QSettings:
    return QSettings(_ORG, _APP)


# --------------------------------------------------------------------------- #
# Recent projects
# --------------------------------------------------------------------------- #


def recent_projects() -> list[Path]:
    """Most recent first. Entries whose project.json vanished are dropped."""
    raw = _store().value(_RECENT_KEY, [])
    if isinstance(raw, str):  # QSettings collapses a 1-item list to a string
        raw = [raw]
    paths = []
    for item in raw or []:
        path = Path(str(item))
        if path.is_file():
            paths.append(path)
    return paths


def remember_project(project_file: Path) -> None:
    project_file = Path(project_file).resolve()
    entries = [str(project_file)]
    for existing in recent_projects():
        if existing != project_file and len(entries) < MAX_RECENT:
            entries.append(str(existing))
    _store().setValue(_RECENT_KEY, entries)


# --------------------------------------------------------------------------- #
# CloudCompare
# --------------------------------------------------------------------------- #


def cloudcompare_path() -> Path | None:
    raw = _store().value(_CLOUDCOMPARE_KEY, "")
    if raw and Path(str(raw)).is_file():
        return Path(str(raw))
    return None


def set_cloudcompare_path(path: str | Path | None) -> None:
    if path:
        _store().setValue(_CLOUDCOMPARE_KEY, str(path))
    else:
        _store().remove(_CLOUDCOMPARE_KEY)
