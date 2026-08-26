"""Shared fixtures for the core-library tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
EXAMPLES_DIR = REPO_ROOT / "docs" / "examples"

# pyproject sets pythonpath, but keep this so a bare `python tests/...` and
# Spyder's run-file button work too.
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


GOOD_MANIFEST = """
id: demo
name: Demo Engine
version: 2.1.0
actions:
  - id: run
    label: Run it
    inputs:
      - {key: cloud, type: pointcloud}
      - {key: extra, type: table, optional: true}
      - {key: many, type: pointcloud, multiple: true}
    outputs:
      - {key: result, type: pointcloud}
    params: params_run.json
  - id: pick
    label: Pick points
    interactive: true
    outputs:
      - {key: transform, type: transform}
run:
  command: "{python} -m demo {action} --params {params_file} --out {run_dir} --in {input:cloud}"
  cwd: .
"""


@pytest.fixture()
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture()
def examples_dir() -> Path:
    return EXAMPLES_DIR


@pytest.fixture()
def engine_dir(tmp_path: Path) -> Path:
    """An ``engines/demo/`` folder holding a valid manifest and params file."""
    folder = tmp_path / "engines" / "demo"
    folder.mkdir(parents=True)
    (folder / "engine.yaml").write_text(GOOD_MANIFEST, encoding="utf-8")
    (folder / "params_run.json").write_text(
        json.dumps(
            {
                "version": 1,
                "fields": [
                    {
                        "key": "voxel",
                        "label": "Voxel size",
                        "type": "float",
                        "default": 0.05,
                        "min": 0.0,
                        "max": 1.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return folder


@pytest.fixture()
def engines_root(engine_dir: Path) -> Path:
    """The repo-root-like folder that contains ``engines/``."""
    return engine_dir.parent.parent


def write_manifest(folder: Path, text: str) -> Path:
    """Helper: drop *text* into ``<folder>/engine.yaml``, creating the folder."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "engine.yaml"
    path.write_text(text, encoding="utf-8")
    return path
