"""Per-user settings - QSettings, never a file in the repo.

On Windows this lands in the registry under
``HKCU\\Software\\MohammadNiknezhad\\rockslope-studio``.
Stored here: the recent-projects list, the last browsed folder per project
(amendment A1), and the CloudCompare.exe path.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from PySide6.QtCore import QSettings

_ORG = "MohammadNiknezhad"
_APP = "rockslope-studio"

_RECENT_KEY = "projects/recent"
_CLOUDCOMPARE_KEY = "tools/cloudcompare_path"
_BROWSE_DIR_KEY = "projects/browse_dir"

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
# Last browsed folder, per project (amendment A1)
# --------------------------------------------------------------------------- #


def _project_key(workspace: str | Path) -> str:
    """A QSettings-safe key for one project's workspace path.

    '/' would create nested groups and a bare Windows path contains both
    separators and a colon, so the path is hashed. Collisions are irrelevant
    here - the worst case is that a file dialog opens in the wrong folder.
    """
    resolved = str(Path(workspace).resolve()).lower()
    return hashlib.sha1(resolved.encode("utf-8")).hexdigest()[:16]


def last_browse_dir(workspace: str | Path) -> Path | None:
    """The folder this project's last file dialog was used in, if it still exists."""
    raw = _store().value("{0}/{1}".format(_BROWSE_DIR_KEY, _project_key(workspace)), "")
    if raw and Path(str(raw)).is_dir():
        return Path(str(raw))
    return None


def set_last_browse_dir(workspace: str | Path, folder: str | Path) -> None:
    _store().setValue(
        "{0}/{1}".format(_BROWSE_DIR_KEY, _project_key(workspace)), str(folder)
    )


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
