"""The reference pair in docs/examples/ must always validate.

Sessions 3-7 copy those two files. If the loader and the reference ever drift
apart, this is where it shows up.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rockslope_studio.core import ARTIFACT_TYPES, FIELD_TYPES, load_manifest, load_params


@pytest.fixture()
def engine(examples_dir: Path):
    return load_manifest(examples_dir / "engine.yaml")


def test_the_example_manifest_validates(engine) -> None:
    assert engine.id == "example"
    assert engine.version == "1.0.0"
    assert engine.action_ids == ("subsample", "compare", "pick_points")


def test_the_example_params_file_validates(examples_dir: Path) -> None:
    spec = load_params(examples_dir / "params_example.json")
    assert spec.keys == (
        "voxel_size",
        "min_points_per_voxel",
        "method",
        "keep_intensity",
        "output_name",
    )


def test_every_params_file_the_example_references_loads(engine) -> None:
    referenced = [a for a in engine.actions if a.params]
    assert referenced, "the example should demonstrate at least one params file"

    for action in referenced:
        path = engine.params_path(action)
        assert path is not None and path.is_file()
        load_params(path)


def test_the_example_defaults_validate_against_the_example_spec(
    examples_dir: Path,
) -> None:
    spec = load_params(examples_dir / "params_example.json")
    assert spec.validate(spec.defaults()) == spec.defaults()


def test_the_example_demonstrates_every_field_type(examples_dir: Path) -> None:
    """A reference the later sessions copy has to show all of them."""
    spec = load_params(examples_dir / "params_example.json")
    assert {f.type for f in spec} == set(FIELD_TYPES)


def test_the_example_demonstrates_optional_multiple_and_interactive(engine) -> None:
    compare = engine.action("compare")
    assert compare.input("cloud").multiple is True
    assert compare.input("mask").optional is True
    assert engine.action("pick_points").interactive is True
    assert engine.action("subsample").interactive is False


def test_every_type_used_by_the_example_is_a_declared_artifact_type(engine) -> None:
    used = {
        slot.type
        for action in engine.actions
        for slot in action.inputs + action.outputs
    }
    assert used <= set(ARTIFACT_TYPES)


def test_the_example_command_renders(engine, tmp_path: Path) -> None:
    from rockslope_studio.core import render_command

    rendered = render_command(
        engine,
        "subsample",
        python="python.exe",
        run_dir=str(tmp_path),
        params_file="params.json",
        inputs={"cloud": "cloud.laz"},
    )

    assert "subsample" in rendered
    assert "params.json" in rendered
    assert "cloud.laz" in rendered
    assert "{" not in rendered  # every placeholder was filled


def test_the_examples_readme_exists(examples_dir: Path) -> None:
    assert (examples_dir / "README.md").is_file()
