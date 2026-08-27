"""Params files: validation, value checking, and round-tripping."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lithocloud.core.params import (
    ParamField,
    ParamSpec,
    ParamsError,
    dump_params,
    load_params,
)

FULL_SPEC: dict[str, Any] = {
    "version": 1,
    "fields": [
        {
            "key": "voxel",
            "label": "Voxel size (m)",
            "type": "float",
            "default": 0.05,
            "min": 0.001,
            "max": 5.0,
            "help": "Edge length.",
        },
        {"key": "iters", "label": "Iterations", "type": "int", "default": 30, "min": 1},
        {"key": "tag", "label": "Tag", "type": "str", "default": "run"},
        {"key": "keep", "label": "Keep intensity", "type": "bool", "default": True},
        {
            "key": "method",
            "label": "Method",
            "type": "choice",
            "default": "centroid",
            "choices": ["centroid", "nearest"],
        },
    ],
}


def write_spec(tmp_path: Path, data: Any, name: str = "params.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def test_loads_every_field_type(tmp_path: Path) -> None:
    spec = load_params(write_spec(tmp_path, FULL_SPEC))

    assert spec.keys == ("voxel", "iters", "tag", "keep", "method")
    assert len(spec) == 5
    assert "voxel" in spec
    assert "nope" not in spec


def test_field_order_is_the_file_order(tmp_path: Path) -> None:
    """The form is generated in this order, so it must never be re-sorted."""
    reversed_fields = {"version": 1, "fields": list(reversed(FULL_SPEC["fields"]))}
    spec = load_params(write_spec(tmp_path, reversed_fields))

    assert spec.keys == ("method", "keep", "tag", "iters", "voxel")


def test_field_attributes(tmp_path: Path) -> None:
    spec = load_params(write_spec(tmp_path, FULL_SPEC))
    voxel = spec.field("voxel")

    assert voxel.label == "Voxel size (m)"
    assert voxel.type == "float"
    assert voxel.default == 0.05
    assert (voxel.min, voxel.max) == (0.001, 5.0)
    assert voxel.help == "Edge length."

    assert spec.field("method").choices == ("centroid", "nearest")
    assert spec.field("iters").max is None


def test_label_defaults_to_the_key(tmp_path: Path) -> None:
    path = write_spec(tmp_path, [{"key": "eps", "type": "float", "default": 0.1}])
    assert load_params(path).field("eps").label == "eps"


def test_a_bare_list_of_fields_is_accepted(tmp_path: Path) -> None:
    path = write_spec(tmp_path, FULL_SPEC["fields"])
    assert load_params(path).keys == ("voxel", "iters", "tag", "keep", "method")


def test_defaults(tmp_path: Path) -> None:
    spec = load_params(write_spec(tmp_path, FULL_SPEC))

    assert spec.defaults() == {
        "voxel": 0.05,
        "iters": 30,
        "tag": "run",
        "keep": True,
        "method": "centroid",
    }


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ParamsError, match="no such params file"):
        load_params(tmp_path / "nope.json")


def test_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "params.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ParamsError, match="invalid JSON"):
        load_params(path)


# --------------------------------------------------------------------------- #
# Rejecting bad specs
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ({"label": "L", "type": "float", "default": 1.0}, "missing 'key'"),
        ({"key": "k", "default": 1.0}, "missing 'type'"),
        ({"key": "k", "type": "float"}, "missing 'default'"),
        ({"key": "k", "type": "colour", "default": "red"}, "not one of"),
        ({"key": "k", "type": "float", "default": 1.0, "step": 2}, "unknown key"),
        ({"key": "", "type": "float", "default": 1.0}, "non-empty string"),
        ({"key": "k", "type": "choice", "default": "a"}, "needs a non-empty 'choices'"),
        (
            {"key": "k", "type": "choice", "default": "a", "choices": ["a", "a"]},
            "duplicates",
        ),
        (
            {"key": "k", "type": "str", "default": "x", "choices": ["x"]},
            "only allowed for type 'choice'",
        ),
        ({"key": "k", "type": "str", "default": "x", "min": 1}, "only allowed for"),
        ({"key": "k", "type": "bool", "default": True, "max": 1}, "only allowed for"),
        (
            {"key": "k", "type": "float", "default": 1.0, "min": 5, "max": 1},
            "greater than max",
        ),
        ({"key": "k", "type": "float", "default": 1.0, "min": "low"}, "must be a number"),
        ({"key": "k", "type": "float", "default": 1.0, "help": 7}, "'help' must be"),
    ],
)
def test_bad_field_definition(tmp_path: Path, field: dict, message: str) -> None:
    with pytest.raises(ParamsError, match=message):
        load_params(write_spec(tmp_path, [field]))


@pytest.mark.parametrize(
    "field",
    [
        {"key": "k", "type": "float", "default": 10.0, "max": 5.0},
        {"key": "k", "type": "int", "default": 0, "min": 1},
        {"key": "k", "type": "choice", "default": "z", "choices": ["a", "b"]},
        {"key": "k", "type": "int", "default": 1.5},
        {"key": "k", "type": "bool", "default": "yes"},
        {"key": "k", "type": "str", "default": 3},
    ],
)
def test_a_default_that_violates_its_own_field_is_rejected(
    tmp_path: Path, field: dict
) -> None:
    with pytest.raises(ParamsError, match="invalid default"):
        load_params(write_spec(tmp_path, [field]))


def test_duplicate_keys(tmp_path: Path) -> None:
    fields = [
        {"key": "k", "type": "int", "default": 1},
        {"key": "k", "type": "int", "default": 2},
    ]
    with pytest.raises(ParamsError, match="duplicate parameter key"):
        load_params(write_spec(tmp_path, fields))


def test_unsupported_version(tmp_path: Path) -> None:
    with pytest.raises(ParamsError, match="unsupported params version"):
        load_params(write_spec(tmp_path, {"version": 99, "fields": []}))


def test_unknown_top_level_key(tmp_path: Path) -> None:
    with pytest.raises(ParamsError, match="unknown key"):
        load_params(write_spec(tmp_path, {"version": 1, "fields": [], "titel": "x"}))


def test_missing_fields_key(tmp_path: Path) -> None:
    with pytest.raises(ParamsError, match="missing 'fields'"):
        load_params(write_spec(tmp_path, {"version": 1}))


def test_wrong_top_level_shape(tmp_path: Path) -> None:
    with pytest.raises(ParamsError, match="expected an object"):
        load_params(write_spec(tmp_path, "not a spec"))


def test_the_error_names_the_file_and_the_field_index(tmp_path: Path) -> None:
    path = write_spec(
        tmp_path,
        [
            {"key": "ok", "type": "int", "default": 1},
            {"key": "bad", "type": "nope", "default": 1},
        ],
    )
    with pytest.raises(ParamsError) as caught:
        load_params(path)

    assert "params.json" in str(caught.value)
    assert "fields[1]" in str(caught.value)


# --------------------------------------------------------------------------- #
# Validating values
# --------------------------------------------------------------------------- #


@pytest.fixture()
def spec(tmp_path: Path) -> ParamSpec:
    return load_params(write_spec(tmp_path, FULL_SPEC))


def test_validate_accepts_good_values(spec: ParamSpec) -> None:
    values = {
        "voxel": 0.1,
        "iters": 5,
        "tag": "site-a",
        "keep": False,
        "method": "nearest",
    }
    assert spec.validate(values) == values


def test_validate_fills_missing_values_from_defaults(spec: ParamSpec) -> None:
    assert spec.validate({"voxel": 0.2}) == {
        "voxel": 0.2,
        "iters": 30,
        "tag": "run",
        "keep": True,
        "method": "centroid",
    }


def test_validate_returns_values_in_field_order(spec: ParamSpec) -> None:
    out = spec.validate({"method": "nearest", "voxel": 0.2})
    assert list(out) == ["voxel", "iters", "tag", "keep", "method"]


def test_validate_can_demand_every_value(spec: ParamSpec) -> None:
    with pytest.raises(ParamsError, match="missing parameter"):
        spec.validate({"voxel": 0.2}, allow_missing=False)


def test_validate_rejects_unknown_keys(spec: ParamSpec) -> None:
    """Silently dropping a parameter the user set would be the worst outcome."""
    with pytest.raises(ParamsError, match="unknown parameter"):
        spec.validate({"voxel": 0.2, "voxelsize": 0.3})


def test_int_is_widened_to_float(spec: ParamSpec) -> None:
    out = spec.validate({"voxel": 2})
    assert out["voxel"] == 2.0
    assert isinstance(out["voxel"], float)


def test_float_is_not_narrowed_to_int(spec: ParamSpec) -> None:
    with pytest.raises(ParamsError, match="whole number"):
        spec.validate({"iters": 2.5})


def test_bool_is_not_a_number(spec: ParamSpec) -> None:
    with pytest.raises(ParamsError, match="expected a number"):
        spec.validate({"iters": True})


def test_number_is_not_a_bool(spec: ParamSpec) -> None:
    with pytest.raises(ParamsError, match="true/false"):
        spec.validate({"keep": 1})


def test_strings_are_not_coerced(spec: ParamSpec) -> None:
    with pytest.raises(ParamsError, match="expected a number"):
        spec.validate({"voxel": "0.1"})


@pytest.mark.parametrize("value", [0.0, 6.0])
def test_bounds_are_enforced(spec: ParamSpec, value: float) -> None:
    with pytest.raises(ParamsError, match="minimum|maximum"):
        spec.validate({"voxel": value})


def test_bounds_are_inclusive(spec: ParamSpec) -> None:
    assert spec.validate({"voxel": 0.001})["voxel"] == 0.001
    assert spec.validate({"voxel": 5.0})["voxel"] == 5.0


def test_choice_must_be_one_of_the_choices(spec: ParamSpec) -> None:
    with pytest.raises(ParamsError, match="not one of"):
        spec.validate({"method": "median"})


def test_validate_rejects_a_non_mapping(spec: ParamSpec) -> None:
    with pytest.raises(ParamsError, match="must be a mapping"):
        spec.validate([("voxel", 0.1)])  # type: ignore[arg-type]


def test_error_message_names_the_parameter(spec: ParamSpec) -> None:
    with pytest.raises(ParamsError, match="voxel"):
        spec.validate({"voxel": 99.0})


def test_unknown_field_lookup(spec: ParamSpec) -> None:
    with pytest.raises(KeyError):
        spec.field("nope")


# --------------------------------------------------------------------------- #
# Round-trip
# --------------------------------------------------------------------------- #


def test_round_trip_preserves_every_field(tmp_path: Path) -> None:
    original = load_params(write_spec(tmp_path, FULL_SPEC))

    out = tmp_path / "again.json"
    dump_params(original, out)
    reloaded = load_params(out)

    assert reloaded.fields == original.fields
    assert reloaded.defaults() == original.defaults()


def test_round_trip_is_stable_on_a_second_pass(tmp_path: Path) -> None:
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"

    spec = load_params(write_spec(tmp_path, FULL_SPEC))
    dump_params(spec, first)
    dump_params(load_params(first), second)

    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")


def test_dump_writes_the_versioned_form_even_from_a_bare_list(tmp_path: Path) -> None:
    spec = load_params(write_spec(tmp_path, FULL_SPEC["fields"]))
    out = tmp_path / "again.json"
    dump_params(spec, out)

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert [f["key"] for f in data["fields"]] == list(spec.keys)


def test_optional_keys_are_omitted_when_absent(tmp_path: Path) -> None:
    spec = load_params(write_spec(tmp_path, [{"key": "k", "type": "int", "default": 1}]))
    out = tmp_path / "again.json"
    dump_params(spec, out)

    field = json.loads(out.read_text(encoding="utf-8"))["fields"][0]
    assert set(field) == {"key", "label", "type", "default"}


def test_round_trip_through_dicts_without_touching_disk() -> None:
    spec = ParamSpec.from_dict(FULL_SPEC)
    assert ParamSpec.from_dict(spec.to_dict()).fields == spec.fields


def test_param_field_is_immutable() -> None:
    field = ParamField(key="k", label="K", type="int", default=1)
    with pytest.raises(Exception):
        field.default = 2  # type: ignore[misc]
