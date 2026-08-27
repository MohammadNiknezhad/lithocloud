"""Manifest loading, validation (good + broken) and discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from lithocloud.core import manifest as M
from lithocloud.core.manifest import (
    ManifestError,
    discover_engines,
    find_engines,
    load_manifest,
    render_command,
)

from conftest import GOOD_MANIFEST, write_manifest

# --------------------------------------------------------------------------- #
# The good case
# --------------------------------------------------------------------------- #


def test_loads_a_valid_manifest(engine_dir: Path) -> None:
    engine = load_manifest(engine_dir / "engine.yaml")

    assert engine.id == "demo"
    assert engine.name == "Demo Engine"
    assert engine.version == "2.1.0"
    assert engine.action_ids == ("run", "pick")
    assert engine.path == engine_dir.resolve()
    assert engine.run.cwd == "."


def test_accepts_the_engine_folder_instead_of_the_file(engine_dir: Path) -> None:
    assert load_manifest(engine_dir).id == "demo"


def test_action_fields_and_defaults(engine_dir: Path) -> None:
    action = load_manifest(engine_dir).action("run")

    assert action.label == "Run it"
    assert action.interactive is False  # defaults to false
    assert [slot.key for slot in action.inputs] == ["cloud", "extra", "many"]
    assert action.input("extra").optional is True
    assert action.input("many").multiple is True
    assert action.input("cloud").optional is False
    assert action.output("result").type == "pointcloud"
    assert action.params == "params_run.json"

    interactive = load_manifest(engine_dir).action("pick")
    assert interactive.interactive is True
    assert interactive.inputs == ()
    assert interactive.params is None


def test_params_path_resolves_against_the_engine_folder(engine_dir: Path) -> None:
    engine = load_manifest(engine_dir)

    assert engine.params_path("run") == (engine_dir / "params_run.json").resolve()
    assert engine.params_path("pick") is None


def test_working_dir_can_point_at_a_sibling_repo(tmp_path: Path) -> None:
    folder = tmp_path / "engines" / "tlsphoto"
    write_manifest(
        folder,
        "id: tlsphoto\nname: T\nversion: \"1.0\"\n"
        "actions: [{id: ingest, label: Ingest}]\n"
        'run: {command: "{python} -m tlsphoto {action} --out {run_dir}", '
        'cwd: "../../../tlsphoto"}\n',
    )
    engine = load_manifest(folder)
    assert engine.working_dir() == (tmp_path / "engines" / "tlsphoto" / "../../../tlsphoto").resolve()


def test_unknown_action_lists_the_known_ones(engine_dir: Path) -> None:
    with pytest.raises(KeyError, match="run, pick"):
        load_manifest(engine_dir).action("nope")


# --------------------------------------------------------------------------- #
# The broken cases
# --------------------------------------------------------------------------- #


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="no such manifest file"):
        load_manifest(tmp_path / "engine.yaml")


def test_empty_file(tmp_path: Path) -> None:
    path = write_manifest(tmp_path / "e", "")
    with pytest.raises(ManifestError, match="empty"):
        load_manifest(path)


def test_not_a_mapping(tmp_path: Path) -> None:
    path = write_manifest(tmp_path / "e", "- just\n- a list\n")
    with pytest.raises(ManifestError, match="must be a mapping"):
        load_manifest(path)


def test_broken_yaml(tmp_path: Path) -> None:
    path = write_manifest(tmp_path / "e", "id: demo\n  bad indent: [\n")
    with pytest.raises(ManifestError, match="cannot read YAML"):
        load_manifest(path)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("name: N\nversion: \"1.0\"\nactions: [{id: a, label: A}]\nrun: {command: x}\n", "id"),
        ("id: d\nversion: \"1.0\"\nactions: [{id: a, label: A}]\nrun: {command: x}\n", "name"),
        ("id: d\nname: N\nactions: [{id: a, label: A}]\nrun: {command: x}\n", "version"),
        ("id: d\nname: N\nversion: \"1.0\"\nrun: {command: x}\n", "actions"),
        ("id: d\nname: N\nversion: \"1.0\"\nactions: [{id: a, label: A}]\n", "run"),
    ],
)
def test_missing_required_top_level_key(tmp_path: Path, text: str, message: str) -> None:
    path = write_manifest(tmp_path / "e", text)
    with pytest.raises(ManifestError, match=message):
        load_manifest(path)


def test_empty_actions_list(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "e", "id: d\nname: N\nversion: \"1.0\"\nactions: []\nrun: {command: x}\n"
    )
    with pytest.raises(ManifestError):
        load_manifest(path)


def test_unknown_top_level_key_is_rejected(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "e",
        "id: d\nname: N\nversion: \"1.0\"\nauthr: typo\n"
        "actions: [{id: a, label: A}]\nrun: {command: x}\n",
    )
    with pytest.raises(ManifestError, match="authr"):
        load_manifest(path)


def test_unknown_artifact_type_is_rejected(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "e",
        "id: d\nname: N\nversion: \"1.0\"\n"
        "actions: [{id: a, label: A, inputs: [{key: c, type: mesh}]}]\n"
        "run: {command: x}\n",
    )
    with pytest.raises(ManifestError, match="mesh"):
        load_manifest(path)


def test_all_declared_artifact_types_are_accepted(tmp_path: Path) -> None:
    inputs = ", ".join(
        "{{key: k{0}, type: {1}}}".format(i, t) for i, t in enumerate(M.ARTIFACT_TYPES)
    )
    path = write_manifest(
        tmp_path / "e",
        "id: d\nname: N\nversion: \"1.0\"\n"
        "actions: [{{id: a, label: A, inputs: [{0}]}}]\n"
        "run: {{command: x}}\n".format(inputs),
    )
    assert len(load_manifest(path).action("a").inputs) == len(M.ARTIFACT_TYPES)


def test_duplicate_action_id(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "e",
        "id: d\nname: N\nversion: \"1.0\"\n"
        "actions: [{id: a, label: A}, {id: a, label: B}]\nrun: {command: x}\n",
    )
    with pytest.raises(ManifestError, match="duplicate action id"):
        load_manifest(path)


def test_duplicate_input_key(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "e",
        "id: d\nname: N\nversion: \"1.0\"\n"
        "actions: [{id: a, label: A, inputs: [{key: c, type: table}, "
        "{key: c, type: table}]}]\nrun: {command: x}\n",
    )
    with pytest.raises(ManifestError, match="duplicate input key"):
        load_manifest(path)


def test_bad_engine_id_characters(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "e",
        "id: My Engine\nname: N\nversion: \"1.0\"\n"
        "actions: [{id: a, label: A}]\nrun: {command: x}\n",
    )
    with pytest.raises(ManifestError, match="lower-case"):
        load_manifest(path)


def test_output_may_not_be_optional(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "e",
        "id: d\nname: N\nversion: \"1.0\"\n"
        "actions: [{id: a, label: A, outputs: [{key: r, type: table, optional: true}]}]\n"
        "run: {command: x}\n",
    )
    with pytest.raises(ManifestError, match="may not be"):
        load_manifest(path)


def test_unknown_placeholder_in_command(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "e",
        "id: d\nname: N\nversion: \"1.0\"\nactions: [{id: a, label: A}]\n"
        'run: {command: "{python} --where {workspace}"}\n',
    )
    with pytest.raises(ManifestError, match="unknown placeholder"):
        load_manifest(path)


def test_input_placeholder_no_action_declares(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "e",
        "id: d\nname: N\nversion: \"1.0\"\nactions: [{id: a, label: A}]\n"
        'run: {command: "{python} {input:cloud}"}\n',
    )
    with pytest.raises(ManifestError, match="no action declares"):
        load_manifest(path)


def test_bare_input_placeholder_needs_a_key(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "e",
        "id: d\nname: N\nversion: \"1.0\"\nactions: [{id: a, label: A}]\n"
        'run: {command: "{python} {input}"}\n',
    )
    with pytest.raises(ManifestError, match="needs a key"):
        load_manifest(path)


def test_params_declared_but_never_passed(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "e",
        "id: d\nname: N\nversion: \"1.0\"\n"
        "actions: [{id: a, label: A, params: p.json}]\n"
        'run: {command: "{python} {action}"}\n',
    )
    with pytest.raises(ManifestError, match="params_file"):
        load_manifest(path)


def test_one_template_serves_actions_with_different_inputs(tmp_path: Path) -> None:
    """Shared template, heterogeneous actions (approved 2026-08-27): a key the
    current action does not declare renders as empty instead of erroring."""
    path = write_manifest(
        tmp_path / "e",
        "id: d\nname: N\nversion: \"1.0\"\n"
        "actions:\n"
        "  - {id: stage1, label: One, inputs: [{key: cloud, type: pointcloud}]}\n"
        "  - {id: stage2, label: Two, inputs: [{key: table, type: table}]}\n"
        'run: {command: "{python} {action} {input:cloud}"}\n',
    )
    engine = load_manifest(path)  # loads fine: stage1 declares 'cloud'

    assert render_command(engine, "stage2", python="py", run_dir="r", inputs={}) == (
        "py stage2"
    )
    assert render_command(
        engine, "stage1", python="py", run_dir="r", inputs={"cloud": "a.laz"}
    ) == "py stage1 a.laz"


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #


def test_discovery_finds_engines(engines_root: Path) -> None:
    engines, problems = discover_engines(engines_root)

    assert [e.id for e in engines] == ["demo"]
    assert problems == []


def test_discovery_accepts_the_engines_folder_itself(engines_root: Path) -> None:
    assert [e.id for e in discover_engines(engines_root / "engines")[0]] == ["demo"]


def test_discovery_reports_a_broken_manifest_without_crashing(engines_root: Path) -> None:
    write_manifest(engines_root / "engines" / "broken", "id: broken\nname: [\n")

    engines, problems = discover_engines(engines_root)

    assert [e.id for e in engines] == ["demo"]  # the good one still loads
    assert len(problems) == 1
    assert "broken" in str(problems[0])


def test_find_engines_skips_broken_ones_silently(engines_root: Path, caplog) -> None:
    write_manifest(engines_root / "engines" / "broken", "id: broken\nname: [\n")

    assert [e.id for e in find_engines(engines_root)] == ["demo"]
    assert "broken" in caplog.text


def test_id_must_match_the_folder_name(engines_root: Path) -> None:
    write_manifest(
        engines_root / "engines" / "wrongname",
        "id: notthefolder\nname: N\nversion: \"1.0\"\n"
        "actions: [{id: a, label: A}]\nrun: {command: x}\n",
    )

    engines, problems = discover_engines(engines_root)

    assert [e.id for e in engines] == ["demo"]
    assert "must match the engine folder name" in str(problems[0])


def test_private_folders_are_skipped_unless_asked_for(engines_root: Path) -> None:
    write_manifest(
        engines_root / "engines" / "_demo2",
        "id: demo2\nname: N\nversion: \"1.0\"\n"
        "actions: [{id: a, label: A}]\nrun: {command: x}\n",
    )

    assert [e.id for e in discover_engines(engines_root)[0]] == ["demo"]
    assert [
        e.id for e in discover_engines(engines_root, include_private=True)[0]
    ] == ["demo", "demo2"]


def test_scaffold_folder_without_a_manifest_is_not_an_error(engines_root: Path) -> None:
    (engines_root / "engines" / "preprocess").mkdir()
    (engines_root / "engines" / "preprocess" / ".gitkeep").touch()

    engines, problems = discover_engines(engines_root)

    assert [e.id for e in engines] == ["demo"]
    assert problems == []


def test_missing_engines_folder_returns_nothing(tmp_path: Path) -> None:
    assert discover_engines(tmp_path) == ([], [])


def test_engines_are_sorted_by_id(engines_root: Path) -> None:
    for name in ("alpha", "zulu"):
        write_manifest(
            engines_root / "engines" / name,
            "id: {0}\nname: N\nversion: \"1.0\"\n"
            "actions: [{{id: a, label: A}}]\nrun: {{command: x}}\n".format(name),
        )

    assert [e.id for e in discover_engines(engines_root)[0]] == ["alpha", "demo", "zulu"]


# --------------------------------------------------------------------------- #
# Command rendering
# --------------------------------------------------------------------------- #


def test_render_command_fills_every_placeholder(engine_dir: Path) -> None:
    engine = load_manifest(engine_dir)

    rendered = render_command(
        engine,
        "run",
        python=r"C:\envs\rockslope\python.exe",
        run_dir=r"D:\proj\runs\2026-08-26_1432_demo_run",
        params_file="params.json",
        inputs={"cloud": "raw/site.laz"},
    )

    assert rendered == (
        r"C:\envs\rockslope\python.exe -m demo run --params params.json "
        r"--out D:\proj\runs\2026-08-26_1432_demo_run --in raw/site.laz"
    )


def test_render_command_joins_multi_valued_inputs(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "e",
        "id: d\nname: N\nversion: \"1.0\"\n"
        "actions: [{id: a, label: A, inputs: [{key: c, type: pointcloud, "
        "multiple: true}]}]\n"
        'run: {command: "run {input:c}"}\n',
    )
    engine = load_manifest(path)

    rendered = render_command(
        engine, "a", python="py", run_dir="r", inputs={"c": ["one.laz", "two.laz"]}
    )
    assert rendered == "run one.laz two.laz"


def test_render_command_drops_an_omitted_optional_input(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "e",
        "id: d\nname: N\nversion: \"1.0\"\n"
        "actions: [{id: a, label: A, inputs: [{key: m, type: table, optional: true}]}]\n"
        'run: {command: "run --mask {input:m}"}\n',
    )
    engine = load_manifest(path)

    assert render_command(engine, "a", python="py", run_dir="r") == "run --mask"


def test_render_command_refuses_a_missing_required_input(engine_dir: Path) -> None:
    engine = load_manifest(engine_dir)

    with pytest.raises(ManifestError, match="missing input 'cloud'"):
        render_command(engine, "run", python="py", run_dir="r", params_file="p.json")


def test_render_command_refuses_a_missing_params_file(engine_dir: Path) -> None:
    engine = load_manifest(engine_dir)

    with pytest.raises(ManifestError, match="no params file"):
        render_command(engine, "run", python="py", run_dir="r", inputs={"cloud": "a.laz"})


def test_render_command_accepts_an_action_object(engine_dir: Path) -> None:
    engine = load_manifest(engine_dir)
    action = engine.action("run")

    assert "demo run" in render_command(
        engine,
        action,
        python="py",
        run_dir="r",
        params_file="p.json",
        inputs={"cloud": "a.laz"},
    )
