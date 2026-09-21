"""The per-action params JSON: what the shell turns into a form.

One file per action, referenced from ``engine.yaml`` by ``actions[].params``.
It lists the engine's parameters **in the order they should appear in the
form**, with the information a widget needs::

    {
      "version": 1,
      "fields": [
        {"key": "voxel_size", "label": "Voxel size (m)", "type": "float",
         "default": 0.05, "min": 0.001, "max": 5.0,
         "help": "Edge length of the subsampling voxel."}
      ]
    }

A bare JSON array of field objects is also accepted, so a hand-written file can
skip the wrapper. :func:`dump_params` always writes the versioned form.

Field types (v1): ``float``, ``int``, ``str``, ``bool``, ``choice``.

Rule 2 of CLAUDE.md applies to these files: a ``default``, ``min`` or ``max``
is part of an engine's numeric behaviour and may not be changed without
Mohammad's explicit confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence, Union

from ._util import atomic_write_json, read_json

__all__ = [
    "FIELD_TYPES",
    "PARAMS_SCHEMA_VERSION",
    "SUPPORTED_PARAMS_VERSIONS",
    "ParamField",
    "ParamSpec",
    "ParamsError",
    "VisibleWhen",
    "dump_params",
    "load_params",
]

#: v1 is the flat schema. v2 (amendment A2, 2026-09-19) adds three optional
#: field keys - ``group``, ``collapsed``, ``visible_when`` - and is what
#: :func:`dump_params` writes. A file must declare version 2 to use them, so an
#: older studio can never silently ignore the grouping.
PARAMS_SCHEMA_VERSION = 2
SUPPORTED_PARAMS_VERSIONS = (1, 2)
_V2_KEYS = ("group", "collapsed", "visible_when")

#: Closed list of widget types. v1: float, int, str, bool, choice.
#: ``edge_list`` (2026-09-21, ricp projects): a list of ``[fixed, moving]``
#: scan-index pairs; the shell draws two spin-boxes + a table. Only the value
#: SHAPE is validated here - graph rules (range, connectivity) belong to the
#: engine adapter that knows how many scans there are.
FIELD_TYPES: tuple[str, ...] = ("float", "int", "str", "bool", "choice", "edge_list")

_NUMERIC = ("float", "int")

PathLike = Union[str, Path]


class ParamsError(ValueError):
    """A params file is invalid, or a value does not satisfy it."""


@dataclass(frozen=True)
class VisibleWhen:
    """``{"field": "<other key>", "in": [...]}`` - show a row only while the
    controlling field's current value is one of *values*."""

    field: str
    values: tuple[Any, ...]

    @classmethod
    def from_dict(cls, data: Any, *, where: str) -> "VisibleWhen":
        if not isinstance(data, Mapping):
            raise ParamsError(
                "{0}: 'visible_when' must be an object {{\"field\": ..., \"in\": [...]}}".format(
                    where
                )
            )
        unknown = set(data) - {"field", "in"}
        if unknown:
            raise ParamsError(
                "{0}: 'visible_when' has unknown key(s) {1}".format(
                    where, ", ".join(sorted(unknown))
                )
            )
        controller = data.get("field")
        if not isinstance(controller, str) or not controller:
            raise ParamsError("{0}: 'visible_when.field' must be a non-empty string".format(where))
        values = data.get("in")
        if not isinstance(values, Sequence) or isinstance(values, str) or not values:
            raise ParamsError("{0}: 'visible_when.in' must be a non-empty list".format(where))
        return cls(field=controller, values=tuple(values))

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "in": list(self.values)}


@dataclass(frozen=True)
class ParamField:
    """One parameter: one row in the generated form."""

    key: str
    label: str
    type: str
    default: Any
    min: float | int | None = None
    max: float | int | None = None
    choices: tuple[Any, ...] | None = None
    help: str = ""
    #: schema v2 - section title; None = the first, untitled section.
    group: str | None = None
    #: schema v2 - on the first field of a titled group: render it collapsed.
    collapsed: bool = False
    #: schema v2 - conditional visibility; a display concern only.
    visible_when: VisibleWhen | None = None

    @property
    def uses_v2(self) -> bool:
        return self.group is not None or self.collapsed or self.visible_when is not None

    # -- construction ----------------------------------------------------- #

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, where: str = "field") -> "ParamField":
        if not isinstance(data, Mapping):
            raise ParamsError(
                "{0}: must be an object, got {1}".format(where, type(data).__name__)
            )

        unknown = set(data) - {
            "key",
            "label",
            "type",
            "default",
            "min",
            "max",
            "choices",
            "help",
            "group",
            "collapsed",
            "visible_when",
        }
        if unknown:
            raise ParamsError(
                "{0}: unknown key(s) {1}".format(where, ", ".join(sorted(unknown)))
            )

        group = data.get("group")
        if group is not None and (not isinstance(group, str) or not group.strip()):
            raise ParamsError("{0}: 'group' must be a non-empty string".format(where))
        collapsed = data.get("collapsed", False)
        if not isinstance(collapsed, bool):
            raise ParamsError("{0}: 'collapsed' must be true or false".format(where))
        visible_when = (
            VisibleWhen.from_dict(data["visible_when"], where=where)
            if data.get("visible_when") is not None
            else None
        )

        for required in ("key", "type", "default"):
            if required not in data:
                raise ParamsError("{0}: missing {1!r}".format(where, required))

        key = data["key"]
        if not isinstance(key, str) or not key:
            raise ParamsError("{0}: 'key' must be a non-empty string".format(where))

        ftype = data["type"]
        if ftype not in FIELD_TYPES:
            raise ParamsError(
                "{0}: type {1!r} is not one of {2}".format(
                    where, ftype, ", ".join(FIELD_TYPES)
                )
            )

        choices = data.get("choices")
        if ftype == "choice":
            if not isinstance(choices, Sequence) or isinstance(choices, str) or not choices:
                raise ParamsError(
                    "{0}: type 'choice' needs a non-empty 'choices' list".format(where)
                )
            choices = tuple(choices)
            if len(set(map(repr, choices))) != len(choices):
                raise ParamsError("{0}: 'choices' contains duplicates".format(where))
        elif choices is not None:
            raise ParamsError(
                "{0}: 'choices' is only allowed for type 'choice'".format(where)
            )

        low, high = data.get("min"), data.get("max")
        if ftype not in _NUMERIC and (low is not None or high is not None):
            raise ParamsError(
                "{0}: 'min'/'max' are only allowed for 'float' and 'int'".format(where)
            )
        for name, bound in (("min", low), ("max", high)):
            if bound is not None and not isinstance(bound, (int, float)):
                raise ParamsError("{0}: {1!r} must be a number".format(where, name))
            if isinstance(bound, bool):
                raise ParamsError("{0}: {1!r} must be a number".format(where, name))
        if low is not None and high is not None and low > high:
            raise ParamsError("{0}: min ({1}) is greater than max ({2})".format(where, low, high))

        help_text = data.get("help", "")
        if not isinstance(help_text, str):
            raise ParamsError("{0}: 'help' must be a string".format(where))

        label = data.get("label", key)
        if not isinstance(label, str) or not label:
            raise ParamsError("{0}: 'label' must be a non-empty string".format(where))

        field = cls(
            key=key,
            label=label,
            type=ftype,
            default=data["default"],
            min=low,
            max=high,
            choices=choices,
            help=help_text,
            group=group.strip() if group is not None else None,
            collapsed=collapsed,
            visible_when=visible_when,
        )
        # A default that its own field would reject is always a bug.
        try:
            field.check(field.default)
        except ParamsError as exc:
            raise ParamsError("{0}: invalid default - {1}".format(where, exc)) from None
        return field

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "default": self.default,
        }
        if self.min is not None:
            out["min"] = self.min
        if self.max is not None:
            out["max"] = self.max
        if self.choices is not None:
            out["choices"] = list(self.choices)
        if self.help:
            out["help"] = self.help
        if self.group is not None:
            out["group"] = self.group
        if self.collapsed:
            out["collapsed"] = True
        if self.visible_when is not None:
            out["visible_when"] = self.visible_when.to_dict()
        return out

    # -- validation ------------------------------------------------------- #

    def check(self, value: Any) -> Any:
        """Return *value* coerced to this field's type, or raise :class:`ParamsError`.

        The only coercion is int -> float: a form that yields ``2`` for a float
        field is fine. Everything else must already have the right type, so a
        typo can never silently change an engine's numeric behaviour.
        """
        name = self.key

        if self.type == "edge_list":
            return _check_edge_list(name, value)

        if self.type == "bool":
            if not isinstance(value, bool):
                raise ParamsError(
                    "{0}: expected true/false, got {1!r}".format(name, value)
                )
            return value

        if self.type == "str":
            if not isinstance(value, str):
                raise ParamsError("{0}: expected a string, got {1!r}".format(name, value))
            return value

        if self.type == "choice":
            assert self.choices is not None  # guaranteed by from_dict
            if value not in self.choices:
                raise ParamsError(
                    "{0}: {1!r} is not one of {2}".format(
                        name, value, ", ".join(repr(c) for c in self.choices)
                    )
                )
            return value

        # float / int
        if isinstance(value, bool):
            raise ParamsError("{0}: expected a number, got {1!r}".format(name, value))
        if self.type == "int":
            if not isinstance(value, int):
                raise ParamsError(
                    "{0}: expected a whole number, got {1!r}".format(name, value)
                )
            number: float | int = value
        else:
            if not isinstance(value, (int, float)):
                raise ParamsError("{0}: expected a number, got {1!r}".format(name, value))
            number = float(value)

        if self.min is not None and number < self.min:
            raise ParamsError("{0}: {1} is below the minimum {2}".format(name, number, self.min))
        if self.max is not None and number > self.max:
            raise ParamsError("{0}: {1} is above the maximum {2}".format(name, number, self.max))
        return number


def _check_edge_list(name: str, value: Any) -> list[list[int]]:
    """Shape check for an ``edge_list`` value: ``[[fixed, moving], ...]`` of
    non-negative whole numbers. Returns a normalised list of 2-lists."""
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ParamsError(
            "{0}: expected a list of [fixed, moving] pairs, got {1!r}".format(name, value)
        )
    out: list[list[int]] = []
    for index, item in enumerate(value):
        if isinstance(item, str) or not isinstance(item, Sequence) or len(item) != 2:
            raise ParamsError(
                "{0}: edge {1} must be a [fixed, moving] pair, got {2!r}".format(
                    name, index, item
                )
            )
        pair: list[int] = []
        for end in item:
            if isinstance(end, bool) or not isinstance(end, int) or end < 0:
                raise ParamsError(
                    "{0}: edge {1} must hold non-negative whole numbers, got {2!r}".format(
                        name, index, item
                    )
                )
            pair.append(end)
        out.append(pair)
    return out


@dataclass(frozen=True)
class ParamSpec:
    """The ordered fields of one action's params file."""

    fields: tuple[ParamField, ...]
    path: Path | None = None

    # -- container behaviour ---------------------------------------------- #

    def __iter__(self) -> Iterator[ParamField]:
        return iter(self.fields)

    def __len__(self) -> int:
        return len(self.fields)

    def __contains__(self, key: object) -> bool:
        return any(f.key == key for f in self.fields)

    def field(self, key: str) -> ParamField:
        for item in self.fields:
            if item.key == key:
                return item
        raise KeyError("no parameter {0!r}".format(key))

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(f.key for f in self.fields)

    # -- groups and visibility (schema v2) ---------------------------------- #

    def groups(self) -> tuple[str | None, ...]:
        """Section titles in the order they first appear; ``None`` is the
        untitled section (fields with no ``group``)."""
        seen: list[str | None] = []
        for item in self.fields:
            if item.group not in seen:
                seen.append(item.group)
        return tuple(seen)

    def fields_in(self, group: str | None) -> tuple[ParamField, ...]:
        """The fields of one section, in file order."""
        return tuple(f for f in self.fields if f.group == group)

    def is_collapsed(self, group: str | None) -> bool:
        """Whether a titled section declares ``collapsed`` (on its first field)."""
        members = self.fields_in(group)
        return bool(members) and members[0].collapsed

    def controllers(self) -> tuple[str, ...]:
        """Keys that some other field's visibility depends on."""
        out: list[str] = []
        for item in self.fields:
            if item.visible_when is not None and item.visible_when.field not in out:
                out.append(item.visible_when.field)
        return tuple(out)

    def is_visible(self, key: str, values: Mapping[str, Any]) -> bool:
        """Whether *key*'s row should show for the given (raw) values.

        Transitive (decided 2026-09-19): a row is visible only if its
        controller's value is in the list AND the controller itself is
        visible, so nothing depends on a value the user cannot see. A
        controller missing from *values* is judged on its default. Hidden or
        not, the field's value is untouched - hiding is display only.
        """
        field = self.field(key)
        rule = field.visible_when
        if rule is None:
            return True
        controller = self.field(rule.field)
        current = values.get(rule.field, controller.default)
        return current in rule.values and self.is_visible(rule.field, values)

    # -- values ------------------------------------------------------------ #

    def defaults(self) -> dict[str, Any]:
        """The default value of every field, in file order."""
        return {f.key: f.default for f in self.fields}

    def validate(self, values: Mapping[str, Any], *, allow_missing: bool = True) -> dict[str, Any]:
        """Check *values* against the spec and return them coerced and ordered.

        Missing keys fall back to their default unless *allow_missing* is false.
        Unknown keys are always an error: silently dropping a parameter the user
        set is exactly the kind of surprise this library must not produce.
        """
        if not isinstance(values, Mapping):
            raise ParamsError(
                "values must be a mapping, got {0}".format(type(values).__name__)
            )

        unknown = [key for key in values if key not in self]
        if unknown:
            raise ParamsError(
                "unknown parameter(s): {0}".format(", ".join(sorted(unknown)))
            )

        out: dict[str, Any] = {}
        missing: list[str] = []
        for item in self.fields:
            if item.key in values:
                out[item.key] = item.check(values[item.key])
            elif allow_missing:
                out[item.key] = item.default
            else:
                missing.append(item.key)
        if missing:
            raise ParamsError("missing parameter(s): {0}".format(", ".join(missing)))
        return out

    # -- serialisation ----------------------------------------------------- #

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": PARAMS_SCHEMA_VERSION,
            "fields": [f.to_dict() for f in self.fields],
        }

    @classmethod
    def from_dict(cls, data: Any, *, where: str = "params", path: Path | None = None) -> "ParamSpec":
        version: Any = PARAMS_SCHEMA_VERSION
        if isinstance(data, Mapping):
            version = data.get("version", PARAMS_SCHEMA_VERSION)
            if version not in SUPPORTED_PARAMS_VERSIONS:
                raise ParamsError(
                    "{0}: unsupported params version {1!r} (this studio speaks v{2})".format(
                        where, version, " and v".join(str(v) for v in SUPPORTED_PARAMS_VERSIONS)
                    )
                )
            unknown = set(data) - {"version", "fields"}
            if unknown:
                raise ParamsError(
                    "{0}: unknown key(s) {1}".format(where, ", ".join(sorted(unknown)))
                )
            if "fields" not in data:
                raise ParamsError("{0}: missing 'fields'".format(where))
            raw_fields = data["fields"]
        elif isinstance(data, list):
            raw_fields = data
        else:
            raise ParamsError(
                "{0}: expected an object with 'fields', or a list of fields, got "
                "{1}".format(where, type(data).__name__)
            )

        if not isinstance(raw_fields, list):
            raise ParamsError("{0}: 'fields' must be a list".format(where))

        fields: list[ParamField] = []
        seen: set[str] = set()
        for index, raw in enumerate(raw_fields):
            item = ParamField.from_dict(raw, where="{0}: fields[{1}]".format(where, index))
            if item.key in seen:
                raise ParamsError(
                    "{0}: duplicate parameter key {1!r}".format(where, item.key)
                )
            seen.add(item.key)
            fields.append(item)

        if version == 1:
            v2_users = [f.key for f in fields if f.uses_v2]
            if v2_users:
                raise ParamsError(
                    "{0}: field(s) {1} use {2}, which need \"version\": 2 - declare it "
                    "so an older studio cannot silently ignore them".format(
                        where, ", ".join(repr(k) for k in v2_users), " / ".join(_V2_KEYS)
                    )
                )

        _check_layout_rules(fields, where)
        return cls(fields=tuple(fields), path=path)


def _check_layout_rules(fields: list[ParamField], where: str) -> None:
    """Schema v2 rules that span fields: visibility targets and 'collapsed'."""
    by_key = {f.key: f for f in fields}

    # 'collapsed' belongs on the FIRST field of a TITLED group, nowhere else.
    first_of_group: dict[str | None, str] = {}
    for f in fields:
        first_of_group.setdefault(f.group, f.key)
    for f in fields:
        if not f.collapsed:
            continue
        if f.group is None:
            raise ParamsError(
                "{0}: field {1!r}: 'collapsed' needs a 'group' - the untitled "
                "section has no box to collapse".format(where, f.key)
            )
        if first_of_group[f.group] != f.key:
            raise ParamsError(
                "{0}: field {1!r}: 'collapsed' must be on the first field of group "
                "{2!r} (that is {3!r})".format(where, f.key, f.group, first_of_group[f.group])
            )

    for f in fields:
        rule = f.visible_when
        if rule is None:
            continue
        prefix = "{0}: field {1!r}: visible_when".format(where, f.key)
        if rule.field == f.key:
            raise ParamsError(prefix + " cannot reference the field itself")
        controller = by_key.get(rule.field)
        if controller is None:
            raise ParamsError(
                prefix + " names {0!r}, which is not a field in this file".format(rule.field)
            )
        if controller.type not in ("choice", "bool"):
            raise ParamsError(
                prefix + " controller {0!r} must be a choice or bool field, "
                "not {1}".format(rule.field, controller.type)
            )
        if controller.type == "choice":
            assert controller.choices is not None
            impossible = [v for v in rule.values if v not in controller.choices]
        else:
            impossible = [v for v in rule.values if not isinstance(v, bool)]
        if impossible:
            raise ParamsError(
                prefix + " lists {0}, which {1!r} can never equal".format(
                    ", ".join(repr(v) for v in impossible), rule.field
                )
            )

    # No cycles: follow controller -> controller; a repeat means a loop.
    for f in fields:
        trail: list[str] = [f.key]
        node = f
        while node.visible_when is not None:
            nxt = node.visible_when.field
            if nxt in trail:
                trail.append(nxt)
                raise ParamsError(
                    "{0}: visible_when forms a cycle: {1}".format(where, " -> ".join(trail))
                )
            trail.append(nxt)
            node = by_key[nxt]


def load_params(path: PathLike) -> ParamSpec:
    """Load and validate one params JSON file."""
    path = Path(path)
    try:
        data = read_json(path)
    except FileNotFoundError as exc:
        raise ParamsError("{0}: no such params file".format(path)) from exc
    except ValueError as exc:
        raise ParamsError(str(exc)) from exc
    return ParamSpec.from_dict(data, where=str(path), path=path.resolve())


def dump_params(spec: ParamSpec, path: PathLike) -> Path:
    """Write *spec* back out in the canonical versioned form."""
    return atomic_write_json(Path(path), spec.to_dict())


