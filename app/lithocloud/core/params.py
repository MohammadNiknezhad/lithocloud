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
    "ParamField",
    "ParamSpec",
    "ParamsError",
    "dump_params",
    "load_params",
]

PARAMS_SCHEMA_VERSION = 1

#: Closed list of widget types for v1.
FIELD_TYPES: tuple[str, ...] = ("float", "int", "str", "bool", "choice")

_NUMERIC = ("float", "int")

PathLike = Union[str, Path]


class ParamsError(ValueError):
    """A params file is invalid, or a value does not satisfy it."""


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
        }
        if unknown:
            raise ParamsError(
                "{0}: unknown key(s) {1}".format(where, ", ".join(sorted(unknown)))
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
        return out

    # -- validation ------------------------------------------------------- #

    def check(self, value: Any) -> Any:
        """Return *value* coerced to this field's type, or raise :class:`ParamsError`.

        The only coercion is int -> float: a form that yields ``2`` for a float
        field is fine. Everything else must already have the right type, so a
        typo can never silently change an engine's numeric behaviour.
        """
        name = self.key

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
        if isinstance(data, Mapping):
            version = data.get("version", PARAMS_SCHEMA_VERSION)
            if version != PARAMS_SCHEMA_VERSION:
                raise ParamsError(
                    "{0}: unsupported params version {1!r} (this studio speaks v{2})".format(
                        where, version, PARAMS_SCHEMA_VERSION
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

        return cls(fields=tuple(fields), path=path)


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


