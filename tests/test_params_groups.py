"""Params schema v2 (amendment A2): group / collapsed / visible_when.

Load-time validation, the ordering helpers, visibility evaluation, and
backwards compatibility with every v1 file already in the repo.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lithocloud.core import (
    PARAMS_SCHEMA_VERSION,
    SUPPORTED_PARAMS_VERSIONS,
    ParamsError,
    ParamSpec,
    VisibleWhen,
    dump_params,
    load_params,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def spec_of(*fields: dict, version: int = 2) -> ParamSpec:
    return ParamSpec.from_dict({"version": version, "fields": list(fields)})


METHOD = {
    "key": "method",
    "type": "choice",
    "default": "all",
    "choices": ["paper-c2c", "local-plane", "m3c2", "all"],
}
PLANE = {
    "key": "plane_radius",
    "type": "str",
    "default": "",
    "visible_when": {"field": "method", "in": ["local-plane", "all"]},
}
CORE = {
    "key": "core_points",
    "type": "str",
    "default": "",
    "group": "Advanced",
    "collapsed": True,
    "visible_when": {"field": "method", "in": ["m3c2", "all"]},
}
SEED = {"key": "seed", "type": "int", "default": 0, "group": "Advanced"}


# --------------------------------------------------------------------------- #
# The good file
# --------------------------------------------------------------------------- #


def test_a_v2_file_loads_with_groups_collapsed_and_rules() -> None:
    spec = spec_of(METHOD, PLANE, CORE, SEED)

    assert spec.keys == ("method", "plane_radius", "core_points", "seed")
    assert spec.field("plane_radius").visible_when == VisibleWhen(
        "method", ("local-plane", "all")
    )
    assert spec.field("core_points").group == "Advanced"
    assert spec.field("core_points").collapsed is True
    assert spec.field("method").group is None
    assert spec.field("method").visible_when is None


def test_groups_keep_first_appearance_order_and_fields_keep_file_order() -> None:
    spec = spec_of(
        {"key": "a", "type": "int", "default": 0, "group": "Frequently used"},
        {"key": "b", "type": "int", "default": 0},
        {"key": "c", "type": "int", "default": 0, "group": "Advanced"},
        {"key": "d", "type": "int", "default": 0, "group": "Frequently used"},
    )
    assert spec.groups() == ("Frequently used", None, "Advanced")
    assert [f.key for f in spec.fields_in("Frequently used")] == ["a", "d"]
    assert [f.key for f in spec.fields_in(None)] == ["b"]
    assert spec.is_collapsed("Advanced") is False


def test_collapsed_is_read_from_the_first_field_of_the_group() -> None:
    spec = spec_of(METHOD, CORE, SEED)
    assert spec.is_collapsed("Advanced") is True
    assert spec.is_collapsed(None) is False


def test_controllers_lists_each_once_in_order() -> None:
    spec = spec_of(METHOD, PLANE, CORE, SEED)
    assert spec.controllers() == ("method",)


def test_versions() -> None:
    assert PARAMS_SCHEMA_VERSION == 2
    assert SUPPORTED_PARAMS_VERSIONS == (1, 2)


# --------------------------------------------------------------------------- #
# Rejections, each with a message naming the problem
# --------------------------------------------------------------------------- #


def test_unknown_key_is_still_rejected() -> None:
    with pytest.raises(ParamsError, match="unknown key"):
        spec_of({**METHOD, "hidden": True})


def test_visible_when_must_name_a_field_in_the_same_file() -> None:
    with pytest.raises(ParamsError, match="'nope', which is not a field in this file"):
        spec_of(METHOD, {**PLANE, "visible_when": {"field": "nope", "in": ["x"]}})


def test_visible_when_cannot_reference_itself() -> None:
    with pytest.raises(ParamsError, match="cannot reference the field itself"):
        spec_of(
            {**METHOD, "visible_when": {"field": "method", "in": ["all"]}},
        )


def test_visible_when_controller_must_be_choice_or_bool() -> None:
    with pytest.raises(ParamsError, match="must be a choice or bool field, not int"):
        spec_of(
            {"key": "n", "type": "int", "default": 1},
            {"key": "x", "type": "str", "default": "", "visible_when": {"field": "n", "in": [1]}},
        )


def test_visible_when_rejects_a_cycle() -> None:
    with pytest.raises(ParamsError, match="cycle: a -> b -> a"):
        spec_of(
            {"key": "a", "type": "bool", "default": True,
             "visible_when": {"field": "b", "in": [True]}},
            {"key": "b", "type": "bool", "default": True,
             "visible_when": {"field": "a", "in": [True]}},
        )


def test_visible_when_rejects_a_longer_cycle() -> None:
    with pytest.raises(ParamsError, match="cycle"):
        spec_of(
            {"key": "a", "type": "bool", "default": True,
             "visible_when": {"field": "c", "in": [True]}},
            {"key": "b", "type": "bool", "default": True,
             "visible_when": {"field": "a", "in": [True]}},
            {"key": "c", "type": "bool", "default": True,
             "visible_when": {"field": "b", "in": [True]}},
        )


def test_visible_when_rejects_values_the_controller_can_never_take() -> None:
    """Decided 2026-09-19: a typo like 'm3c2 ' fails at load, never silently."""
    with pytest.raises(ParamsError, match="lists 'm3c2 ', which 'method' can never equal"):
        spec_of(METHOD, {**PLANE, "visible_when": {"field": "method", "in": ["m3c2 "]}})
    with pytest.raises(ParamsError, match="can never equal"):
        spec_of(
            {"key": "flag", "type": "bool", "default": True},
            {"key": "x", "type": "str", "default": "",
             "visible_when": {"field": "flag", "in": ["yes"]}},
        )


@pytest.mark.parametrize(
    ("rule", "message"),
    [
        ("method", "must be an object"),
        ({"field": "method"}, "'visible_when.in' must be a non-empty list"),
        ({"field": "method", "in": []}, "non-empty list"),
        ({"in": ["all"]}, "'visible_when.field' must be a non-empty string"),
        ({"field": "method", "in": ["all"], "unless": 1}, "unknown key"),
    ],
)
def test_visible_when_shape_is_validated(rule, message: str) -> None:
    with pytest.raises(ParamsError, match=message):
        spec_of(METHOD, {**PLANE, "visible_when": rule})


def test_collapsed_needs_a_titled_group() -> None:
    with pytest.raises(ParamsError, match="'collapsed' needs a 'group'"):
        spec_of({**METHOD, "collapsed": True})


def test_collapsed_must_be_on_the_first_field_of_its_group() -> None:
    with pytest.raises(ParamsError, match="must be on the first field of group 'Advanced'"):
        spec_of(METHOD, SEED, {**CORE})  # SEED opens 'Advanced'; CORE carries collapsed


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ({**METHOD, "group": ""}, "'group' must be a non-empty string"),
        ({**METHOD, "group": 3}, "'group' must be a non-empty string"),
        ({**METHOD, "collapsed": "yes"}, "'collapsed' must be true or false"),
    ],
)
def test_group_and_collapsed_types(field: dict, message: str) -> None:
    with pytest.raises(ParamsError, match=message):
        spec_of(field)


# --------------------------------------------------------------------------- #
# Versioning and backwards compatibility
# --------------------------------------------------------------------------- #


def test_a_v1_file_using_v2_keys_must_declare_version_2() -> None:
    with pytest.raises(ParamsError, match="need \"version\": 2"):
        spec_of(METHOD, PLANE, version=1)


def test_a_plain_v1_file_still_loads() -> None:
    spec = spec_of(METHOD, {"key": "seed", "type": "int", "default": 0}, version=1)
    assert spec.groups() == (None,)
    assert spec.controllers() == ()
    assert all(f.visible_when is None and f.group is None for f in spec)


def test_a_bare_list_may_use_v2_keys() -> None:
    spec = ParamSpec.from_dict([METHOD, PLANE])
    assert spec.field("plane_radius").visible_when is not None


def test_unsupported_version_message_names_both_versions() -> None:
    with pytest.raises(ParamsError, match="speaks v1 and v2"):
        spec_of(METHOD, version=3)


def test_every_engine_params_file_in_the_repo_still_loads() -> None:
    """Backwards compatibility with what is actually on disk."""
    files = sorted((REPO_ROOT / "engines").glob("*/params_*.json")) + [
        REPO_ROOT / "docs" / "examples" / "params_example.json"
    ]
    assert files
    for path in files:
        spec = load_params(path)
        assert spec.validate(spec.defaults()) == spec.defaults(), path


def test_dump_round_trips_the_new_keys(tmp_path: Path) -> None:
    original = spec_of(METHOD, PLANE, CORE, SEED)
    out = tmp_path / "p.json"
    dump_params(original, out)

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["version"] == 2
    by_key = {f["key"]: f for f in data["fields"]}
    assert by_key["plane_radius"]["visible_when"] == {
        "field": "method", "in": ["local-plane", "all"]
    }
    assert by_key["core_points"]["group"] == "Advanced"
    assert by_key["core_points"]["collapsed"] is True
    assert "group" not in by_key["method"]
    assert "collapsed" not in by_key["seed"]
    assert "visible_when" not in by_key["seed"]

    assert load_params(out).fields == original.fields


# --------------------------------------------------------------------------- #
# Visibility evaluation
# --------------------------------------------------------------------------- #


def test_is_visible_follows_the_controllers_value() -> None:
    spec = spec_of(METHOD, PLANE, CORE, SEED)

    assert spec.is_visible("plane_radius", {"method": "all"}) is True
    assert spec.is_visible("plane_radius", {"method": "local-plane"}) is True
    assert spec.is_visible("plane_radius", {"method": "m3c2"}) is False
    assert spec.is_visible("core_points", {"method": "m3c2"}) is True
    assert spec.is_visible("core_points", {"method": "paper-c2c"}) is False
    assert spec.is_visible("seed", {"method": "paper-c2c"}) is True     # no rule


def test_is_visible_uses_the_controllers_default_when_absent() -> None:
    spec = spec_of(METHOD, PLANE)
    assert spec.is_visible("plane_radius", {}) is True        # default 'all'


def test_visibility_is_transitive_through_a_hidden_controller() -> None:
    """Decided 2026-09-19: a hidden controller hides its dependents."""
    spec = spec_of(
        {"key": "a", "type": "bool", "default": True},
        {"key": "b", "type": "bool", "default": True,
         "visible_when": {"field": "a", "in": [True]}},
        {"key": "c", "type": "str", "default": "",
         "visible_when": {"field": "b", "in": [True]}},
    )
    assert spec.is_visible("c", {"a": True, "b": True}) is True
    assert spec.is_visible("c", {"a": True, "b": False}) is False
    # b is still True, but b itself is hidden by a -> c hides too
    assert spec.is_visible("c", {"a": False, "b": True}) is False


def test_hidden_fields_are_still_validated_and_returned() -> None:
    """Hiding is display only: values() must stay complete for the run record."""
    spec = spec_of(METHOD, PLANE, CORE, SEED)
    out = spec.validate({"method": "paper-c2c", "plane_radius": "0.35", "core_points": "5000"})
    assert out == {
        "method": "paper-c2c", "plane_radius": "0.35", "core_points": "5000", "seed": 0
    }
    with pytest.raises(ParamsError, match="seed"):
        spec.validate({"method": "paper-c2c", "seed": "not a number"})
