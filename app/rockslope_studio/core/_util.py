"""Small shared helpers for the core library. Private — no public API."""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

__all__ = [
    "atomic_write_json",
    "read_json",
    "safe_token",
    "utc_now_iso",
]

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def utc_now_iso() -> str:
    """Current UTC time as ``2026-08-26T14:32:07Z`` — sortable, unambiguous."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_token(text: str, *, fallback: str = "unknown") -> str:
    """Reduce *text* to characters that are safe in a Windows folder name."""
    token = _UNSAFE.sub("-", str(text)).strip("-._")
    return token or fallback


def read_json(path: Path) -> Any:
    """Read UTF-8 JSON. Raises ``FileNotFoundError`` / ``ValueError``."""
    with open(path, "r", encoding="utf-8") as handle:
        try:
            return json.load(handle)
        except json.JSONDecodeError as exc:  # noqa: PERF203 - context matters
            raise ValueError(f"{path}: invalid JSON — {exc}") from exc


def atomic_write_json(path: Path, payload: Any) -> Path:
    """Write JSON via a temp file + replace, so a crash never truncates *path*.

    Run manifests are written repeatedly while a job is alive; a half-written
    ``manifest.json`` would make the run unreadable forever.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False, sort_keys=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path
