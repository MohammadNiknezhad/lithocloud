"""Job history rendering: one status word per run outcome."""

from __future__ import annotations

from pathlib import Path

import pytest

from rockslope_studio.core import RunRecord
from rockslope_studio.core.runs import create_run_dir, finish_run, write_run_manifest
from rockslope_studio.ui.job_panel import JobPanel


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        (RunRecord(path=Path("x"), name="r", exit_code=0, done=True), "OK"),
        (RunRecord(path=Path("x"), name="r", exit_code=3, done=False), "FAILED"),
        (RunRecord(path=Path("x"), name="r"), "running / interrupted"),
        (
            RunRecord(path=Path("x"), name="r", exit_code=1, cancelled=True),
            "CANCELLED",
        ),
        # cancelled wins even if the kill happened to report exit 0
        (
            RunRecord(path=Path("x"), name="r", exit_code=0, cancelled=True),
            "CANCELLED",
        ),
    ],
)
def test_status_column(record: RunRecord, expected: str) -> None:
    assert JobPanel._history_item(record).text(3) == expected


def test_history_shows_a_cancelled_run_as_cancelled(qtbot, tmp_path: Path) -> None:
    """End to end through list_runs, as the panel reads it after a cancel."""
    run_dir = create_run_dir(tmp_path, "demo", "run")
    write_run_manifest(run_dir, engine="demo", engine_version="1", action="run")
    finish_run(run_dir, 1, cancelled=True)

    panel = JobPanel()
    qtbot.addWidget(panel)
    panel.refresh_history(tmp_path)

    assert panel._history.topLevelItemCount() == 1
    assert panel._history.topLevelItem(0).text(3) == "CANCELLED"
