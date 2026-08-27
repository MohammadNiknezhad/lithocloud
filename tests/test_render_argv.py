"""render_argv: the argument-list form of the command template.

The point of this function (session-2 requirement): a Windows path containing
spaces must arrive at the engine as ONE argument, so execution never round-trips
through a single command string.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rockslope_studio.core.manifest import (
    ManifestError,
    load_manifest,
    render_argv,
    render_command,
)

from conftest import write_manifest


@pytest.fixture()
def engine(engine_dir: Path):
    return load_manifest(engine_dir)


def test_basic_rendering(engine) -> None:
    argv = render_argv(
        engine,
        "run",
        python="python.exe",
        run_dir="rundir",
        params_file="params.json",
        inputs={"cloud": "site.laz"},
    )
    assert argv == [
        "python.exe",
        "-m",
        "demo",
        "run",
        "--params",
        "params.json",
        "--out",
        "rundir",
        "--in",
        "site.laz",
    ]


def test_a_path_with_spaces_stays_one_argument(engine) -> None:
    """The whole reason this function exists."""
    python = r"C:\Program Files\Anaconda\python.exe"
    run_dir = r"D:\My Projects\Francon site\runs\2026-08-27_0900_demo_run"
    cloud = r"D:\My Projects\Francon site\raw\south face scan.laz"

    argv = render_argv(
        engine,
        "run",
        python=python,
        run_dir=run_dir,
        params_file=r"D:\My Projects\params file.json",
        inputs={"cloud": cloud},
    )

    assert argv[0] == python
    assert run_dir in argv
    assert cloud in argv
    # nothing got split on the spaces
    assert "Files\\Anaconda\\python.exe" not in argv
    assert r"D:\My" not in argv
    assert len(argv) == 10


def test_multi_valued_input_expands_to_one_argument_per_file(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "e",
        'id: d\nname: N\nversion: "1.0"\n'
        "actions: [{id: a, label: A, inputs: [{key: c, type: pointcloud, "
        "multiple: true}]}]\n"
        'run: {command: "run {input:c} --end"}\n',
    )
    engine = load_manifest(path)

    argv = render_argv(
        engine,
        "a",
        python="py",
        run_dir="r",
        inputs={"c": [r"C:\a dir\one.laz", r"C:\a dir\two.laz"]},
    )

    assert argv == ["run", r"C:\a dir\one.laz", r"C:\a dir\two.laz", "--end"]


def test_omitted_optional_input_drops_its_token(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "e",
        'id: d\nname: N\nversion: "1.0"\n'
        "actions: [{id: a, label: A, inputs: [{key: m, type: table, optional: true}]}]\n"
        'run: {command: "run {input:m} --end"}\n',
    )
    engine = load_manifest(path)

    assert render_argv(engine, "a", python="py", run_dir="r") == ["run", "--end"]
    assert render_argv(
        engine, "a", python="py", run_dir="r", inputs={"m": "t.csv"}
    ) == ["run", "t.csv", "--end"]


def test_embedded_placeholder_substitutes_in_place(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "e",
        'id: d\nname: N\nversion: "1.0"\n'
        "actions: [{id: a, label: A, inputs: [{key: c, type: pointcloud}]}]\n"
        'run: {command: "run --in={input:c} --out={run_dir}"}\n',
    )
    engine = load_manifest(path)

    argv = render_argv(
        engine, "a", python="py", run_dir=r"C:\out dir", inputs={"c": r"C:\in dir\a.laz"}
    )
    assert argv == ["run", r"--in=C:\in dir\a.laz", r"--out=C:\out dir"]


def test_embedded_optional_missing_becomes_empty(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "e",
        'id: d\nname: N\nversion: "1.0"\n'
        "actions: [{id: a, label: A, inputs: [{key: m, type: table, optional: true}]}]\n"
        'run: {command: "run --mask={input:m}"}\n',
    )
    engine = load_manifest(path)

    assert render_argv(engine, "a", python="py", run_dir="r") == ["run", "--mask="]


def test_embedded_multi_valued_input_is_rejected(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "e",
        'id: d\nname: N\nversion: "1.0"\n'
        "actions: [{id: a, label: A, inputs: [{key: c, type: pointcloud, "
        "multiple: true}]}]\n"
        'run: {command: "run --in={input:c}"}\n',
    )
    engine = load_manifest(path)

    with pytest.raises(ManifestError, match="cannot be embedded"):
        render_argv(
            engine, "a", python="py", run_dir="r", inputs={"c": ["a.laz", "b.laz"]}
        )


def test_embedded_multi_input_with_a_single_value_is_fine(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "e",
        'id: d\nname: N\nversion: "1.0"\n'
        "actions: [{id: a, label: A, inputs: [{key: c, type: pointcloud, "
        "multiple: true}]}]\n"
        'run: {command: "run --in={input:c}"}\n',
    )
    engine = load_manifest(path)

    argv = render_argv(engine, "a", python="py", run_dir="r", inputs={"c": ["a.laz"]})
    assert argv == ["run", "--in=a.laz"]


def test_missing_required_input_is_an_error(engine) -> None:
    with pytest.raises(ManifestError, match="missing input 'cloud'"):
        render_argv(engine, "run", python="py", run_dir="r", params_file="p.json")


def test_missing_params_file_is_an_error(engine) -> None:
    with pytest.raises(ManifestError, match="no params file"):
        render_argv(engine, "run", python="py", run_dir="r", inputs={"cloud": "a.laz"})


def test_input_key_the_action_does_not_declare(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "e",
        'id: d\nname: N\nversion: "1.0"\n'
        "actions:\n"
        "  - {id: one, label: One, inputs: [{key: cloud, type: pointcloud}]}\n"
        "  - {id: two, label: Two, inputs: [{key: table, type: table}]}\n"
        'run: {command: "run {input:cloud}"}\n',
    )
    engine = load_manifest(path)

    with pytest.raises(ManifestError, match="no such input"):
        render_argv(engine, "two", python="py", run_dir="r", inputs={})


def test_agrees_with_render_command_when_there_are_no_spaces(engine) -> None:
    kwargs = dict(
        python="python.exe",
        run_dir="rundir",
        params_file="params.json",
        inputs={"cloud": "site.laz"},
    )
    assert render_argv(engine, "run", **kwargs) == (
        render_command(engine, "run", **kwargs).split()
    )


def test_accepts_path_objects(engine, tmp_path: Path) -> None:
    argv = render_argv(
        engine,
        "run",
        python=Path("python.exe"),
        run_dir=tmp_path / "with space",
        params_file=tmp_path / "p.json",
        inputs={"cloud": Path("a.laz")},
    )
    assert str(tmp_path / "with space") in argv


def test_the_example_manifest_renders_to_argv(examples_dir: Path, tmp_path: Path) -> None:
    engine = load_manifest(examples_dir / "engine.yaml")

    argv = render_argv(
        engine,
        "subsample",
        python="python.exe",
        run_dir=tmp_path / "run dir",
        params_file=tmp_path / "params.json",
        inputs={"cloud": tmp_path / "my cloud.laz"},
    )

    assert str(tmp_path / "run dir") in argv
    assert str(tmp_path / "my cloud.laz") in argv
    assert all("{" not in arg for arg in argv)
