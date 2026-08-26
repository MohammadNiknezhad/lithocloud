"""`core/` must never import a GUI toolkit.

Session 1 acceptance: "Nothing imports PySide6 inside core/". The engines and
the command-line tools depend on this package; a stray Qt import would drag a
GUI dependency into every subprocess and break headless use.
"""

from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

CORE_DIR = Path(__file__).resolve().parents[1] / "app" / "rockslope_studio" / "core"

FORBIDDEN = ("PySide6", "PyQt5", "PyQt6", "PySide2", "tkinter", "wx")

CORE_MODULES = sorted(p.name for p in CORE_DIR.glob("*.py"))


def test_the_core_package_is_where_we_think_it_is() -> None:
    assert CORE_DIR.is_dir()
    assert "manifest.py" in CORE_MODULES
    assert "params.py" in CORE_MODULES
    assert "runs.py" in CORE_MODULES
    assert "artifacts.py" in CORE_MODULES
    assert "project.py" in CORE_MODULES


@pytest.mark.parametrize("filename", CORE_MODULES)
def test_no_gui_import_in_the_source(filename: str) -> None:
    """Walk the AST rather than grepping, so a comment cannot trip the test."""
    tree = ast.parse((CORE_DIR / filename).read_text(encoding="utf-8"), filename)

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])

    offenders = imported & set(FORBIDDEN)
    assert not offenders, "{0} imports {1}".format(filename, ", ".join(sorted(offenders)))


def test_importing_core_does_not_pull_in_qt() -> None:
    """Belt and braces: a transitive import would not show up in the AST scan."""
    code = (
        "import sys;"
        "sys.path.insert(0, r'{0}');"
        "import rockslope_studio.core;"
        "bad = [m for m in sys.modules if m.split('.')[0] in {1!r}];"
        "print(','.join(bad))"
    ).format(CORE_DIR.parents[1], FORBIDDEN)

    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "", "core pulled in {0}".format(result.stdout.strip())


def test_qt_really_is_installed_so_the_test_above_means_something() -> None:
    """If PySide6 were missing, the check above would pass for the wrong reason."""
    importlib.import_module("PySide6")


def test_the_public_api_is_importable_from_the_package_root() -> None:
    core = importlib.import_module("rockslope_studio.core")

    for name in (
        "load_manifest",
        "find_engines",
        "load_params",
        "create_run_dir",
        "write_provenance",
        "scan_project",
        "create_project",
    ):
        assert hasattr(core, name), name
        assert name in core.__all__
