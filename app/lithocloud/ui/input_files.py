"""External input files (amendment A1, 2026-08-27).

An input slot may be filled from the project's artifacts OR with any file from
disk. A browsed file is represented by :class:`ExternalFile` - a thin wrapper
around an absolute path that the rest of the shell treats exactly like an
artifact's file:

* the adapter receives the absolute path, same as for an artifact;
* the run manifest and the output provenance record that absolute path as the
  input id. It resolves to no artifact, which ``artifacts.parents_of``
  already reports as an unresolved input - lineage still shows the source.

The raw file is never copied or modified.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ALL_FILES_FILTER",
    "ExternalFile",
    "dialog_filter",
    "extensions_for",
    "is_expected_extension",
]

#: Extensions offered per artifact type. Grounded in architecture section 4 and
#: widened to what the wrapped engines actually write (approved 2026-08-27):
#: ricp and geohazard emit .pdf figures and .txt reports, which a strict
#: reading of section 4 would hide behind "All files".
TYPE_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "pointcloud": (".las", ".laz", ".txt", ".xyz", ".csv", ".pts", ".asc"),
    "transform": (".json", ".txt"),
    "table": (".csv",),
    "figure": (".png", ".svg", ".pdf"),
    "map": (".tif", ".tiff", ".png"),
    "report": (".md", ".json", ".txt"),
    "model": (".joblib", ".pkl"),
}

_TYPE_LABELS = {
    "pointcloud": "Point clouds",
    "transform": "Transforms",
    "table": "Tables",
    "figure": "Figures",
    "map": "Maps",
    "report": "Reports",
    "model": "Models",
}

ALL_FILES_FILTER = "All files (*)"


@dataclass(frozen=True)
class ExternalFile:
    """A file chosen from disk rather than picked from the project."""

    path: Path

    def __post_init__(self) -> None:
        # Absolute from the moment it is created: the adapter, the run manifest
        # and the provenance record must all see the same unambiguous path.
        object.__setattr__(self, "path", Path(self.path).resolve())

    @property
    def display_name(self) -> str:
        return self.path.name

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.path)


def extensions_for(artifact_type: str) -> tuple[str, ...]:
    """Extensions considered normal for *artifact_type* (empty if unknown)."""
    return TYPE_EXTENSIONS.get(artifact_type, ())


def dialog_filter(artifact_type: str) -> str:
    """A QFileDialog filter string for *artifact_type*, plus an All-files entry."""
    extensions = extensions_for(artifact_type)
    if not extensions:
        return ALL_FILES_FILTER
    patterns = " ".join("*" + ext for ext in extensions)
    label = _TYPE_LABELS.get(artifact_type, artifact_type)
    return "{0} ({1});;{2}".format(label, patterns, ALL_FILES_FILTER)


def is_expected_extension(path: str | Path, artifact_type: str) -> bool:
    """False when a browsed file's extension is unusual for the slot.

    The All-files fallback is deliberate, so a mismatch only earns a warning
    (approved 2026-08-27) - never a refusal.
    """
    extensions = extensions_for(artifact_type)
    if not extensions:
        return True
    return Path(path).suffix.lower() in extensions
