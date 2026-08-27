"""Engine panel: discovery listing, action switching, pickers, run requests."""

from __future__ import annotations

from pathlib import Path

import pytest

from rockslope_studio.core import Artifact, find_engines
from rockslope_studio.ui.engine_panel import EnginePanel
from rockslope_studio.ui.job_runner import JobRequest


def fake_artifact(artifact_id: str, type_: str) -> Artifact:
    return Artifact(artifact_id=artifact_id, type=type_, files=("f",))


@pytest.fixture()
def panel(qtbot, repo_root: Path) -> EnginePanel:
    widget = EnginePanel()
    qtbot.addWidget(widget)
    engines = [e for e in find_engines(repo_root, include_private=True) if e.id == "demo"]
    assert [e.id for e in engines] == ["demo"], "the _demo engine must exist"
    widget.set_engines(engines)
    return widget


def test_selecting_the_engine_offers_its_actions(panel: EnginePanel) -> None:
    engine = panel.current_engine()
    assert engine is not None and engine.id == "demo"

    action = panel.current_action()
    assert action is not None and action.id == "run"

    panel._action_combo.setCurrentIndex(1)
    assert panel.current_action().id == "ask"


def test_the_form_is_generated_from_the_params_json(panel: EnginePanel) -> None:
    form = panel.form
    assert form is not None
    assert set(form.spec.keys) == {"seconds", "steps", "rows", "mode", "message"}
    assert form.values() == form.spec.defaults()


def test_pickers_offer_only_type_compatible_artifacts(panel: EnginePanel) -> None:
    panel.set_artifacts(
        [
            fake_artifact("a__stats", "table"),
            fake_artifact("b__cloud", "pointcloud"),
            fake_artifact("c__older_stats", "table"),
        ]
    )

    picker = panel.picker("previous")
    assert picker is not None
    combo = picker._combo
    # "(none)" for the optional slot + the two tables; the pointcloud is absent
    labels = [combo.itemText(i) for i in range(combo.count())]
    assert labels == ["(none)", "a__stats", "c__older_stats"]


def test_run_emits_a_complete_job_request(qtbot, panel: EnginePanel) -> None:
    stats = fake_artifact("a__stats", "table")
    panel.set_artifacts([stats])
    panel.picker("previous")._combo.setCurrentIndex(1)  # choose the artifact
    panel.form.widget("steps").setValue(3)

    captured: list[JobRequest] = []
    panel.run_requested.connect(captured.append)
    panel._run_button.click()

    assert len(captured) == 1
    request = captured[0]
    assert request.engine.id == "demo"
    assert request.action.id == "run"
    assert request.params["steps"] == 3
    assert request.inputs == {"previous": stats}
    assert request.input_ids() == {"previous": "a__stats"}


def test_optional_input_may_stay_none(qtbot, panel: EnginePanel) -> None:
    panel.set_artifacts([])

    captured: list[JobRequest] = []
    panel.run_requested.connect(captured.append)
    panel._run_button.click()

    assert len(captured) == 1
    assert captured[0].inputs == {}


def test_no_engines_disables_run(qtbot) -> None:
    widget = EnginePanel()
    qtbot.addWidget(widget)
    widget.set_engines([])
    assert widget._run_button.isEnabled() is False


def test_refreshing_artifacts_rebuilds_pickers(panel: EnginePanel) -> None:
    panel.set_artifacts([])
    assert panel.picker("previous")._combo.count() == 1  # just "(none)"

    panel.set_artifacts([fake_artifact("new__stats", "table")])
    assert panel.picker("previous")._combo.count() == 2
