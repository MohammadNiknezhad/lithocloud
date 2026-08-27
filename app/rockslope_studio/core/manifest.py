"""Load, validate and discover engine manifests (``engine.yaml``).

The manifest is the **only** thing the shell knows about an engine
(docs/architecture.md section 5). Schema v1 is documented by the reference pair
in ``docs/examples/``::

    id: str                 # unique; must equal the engine folder name
    name: str
    version: str
    actions:
      - id: str
        label: str
        interactive: bool             # true -> runs attached to a console window
        inputs:  [{key, type, multiple?: bool, optional?: bool}]
        outputs: [{key, type}]
        params: str                   # relative path to a params JSON (optional)
    run:
      command: str          # template; see FIXED_PLACEHOLDERS
      cwd: str              # relative to the engine folder
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence, Union

import jsonschema
import yaml

__all__ = [
    "ARTIFACT_TYPES",
    "MANIFEST_NAME",
    "MANIFEST_SCHEMA_VERSION",
    "PLACEHOLDER_RE",
    "Action",
    "Engine",
    "IOSpec",
    "ManifestError",
    "ManifestProblem",
    "RunSpec",
    "discover_engines",
    "find_engines",
    "load_manifest",
    "render_argv",
    "render_command",
]

_log = logging.getLogger(__name__)

MANIFEST_NAME = "engine.yaml"
MANIFEST_SCHEMA_VERSION = 1

#: Closed list of artifact types for v1 (docs/architecture.md section 4).
ARTIFACT_TYPES: tuple[str, ...] = (
    "pointcloud",
    "transform",
    "table",
    "figure",
    "map",
    "report",
    "model",
)

#: Placeholders the shell fills in ``run.command``, besides ``{input:<key>}``.
FIXED_PLACEHOLDERS: tuple[str, ...] = ("python", "action", "params_file", "run_dir")

PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?::([A-Za-z0-9_.-]+))?\}")

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

PathLike = Union[str, Path]


class ManifestError(ValueError):
    """An ``engine.yaml`` is missing, unreadable or invalid."""


# --------------------------------------------------------------------------- #
# JSON Schema - structural validation. Semantic rules are checked afterwards.
# --------------------------------------------------------------------------- #

_IO_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["key", "type"],
    "additionalProperties": False,
    "properties": {
        "key": {"type": "string", "minLength": 1},
        "type": {"type": "string", "enum": list(ARTIFACT_TYPES)},
        "multiple": {"type": "boolean"},
        "optional": {"type": "boolean"},
    },
}

ENGINE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "rockslope-studio engine manifest v1",
    "type": "object",
    "required": ["id", "name", "version", "actions", "run"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "name": {"type": "string", "minLength": 1},
        "version": {"type": "string", "minLength": 1},
        "description": {"type": "string"},
        "actions": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "label"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "label": {"type": "string", "minLength": 1},
                    "description": {"type": "string"},
                    "interactive": {"type": "boolean"},
                    "inputs": {"type": "array", "items": _IO_SCHEMA},
                    "outputs": {"type": "array", "items": _IO_SCHEMA},
                    "params": {"type": "string", "minLength": 1},
                },
            },
        },
        "run": {
            "type": "object",
            "required": ["command"],
            "additionalProperties": False,
            "properties": {
                "command": {"type": "string", "minLength": 1},
                "cwd": {"type": "string"},
            },
        },
    },
}


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class IOSpec:
    """One declared input or output slot of an action."""

    key: str
    type: str
    multiple: bool = False
    optional: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IOSpec":
        return cls(
            key=data["key"],
            type=data["type"],
            multiple=bool(data.get("multiple", False)),
            optional=bool(data.get("optional", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"key": self.key, "type": self.type}
        if self.multiple:
            out["multiple"] = True
        if self.optional:
            out["optional"] = True
        return out


@dataclass(frozen=True)
class Action:
    """One runnable action of an engine (a geohazard stage, ricp's register...)."""

    id: str
    label: str
    interactive: bool = False
    inputs: tuple[IOSpec, ...] = ()
    outputs: tuple[IOSpec, ...] = ()
    params: str | None = None
    description: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Action":
        return cls(
            id=data["id"],
            label=data["label"],
            interactive=bool(data.get("interactive", False)),
            inputs=tuple(IOSpec.from_dict(item) for item in data.get("inputs", ())),
            outputs=tuple(IOSpec.from_dict(item) for item in data.get("outputs", ())),
            params=data.get("params"),
            description=data.get("description", ""),
        )

    def input(self, key: str) -> IOSpec:
        for item in self.inputs:
            if item.key == key:
                return item
        raise KeyError("action {0!r} has no input {1!r}".format(self.id, key))

    def output(self, key: str) -> IOSpec:
        for item in self.outputs:
            if item.key == key:
                return item
        raise KeyError("action {0!r} has no output {1!r}".format(self.id, key))


@dataclass(frozen=True)
class RunSpec:
    """How to launch the engine: a command template and a working directory."""

    command: str
    cwd: str = "."


@dataclass(frozen=True)
class Engine:
    """A validated ``engine.yaml`` plus where it was found."""

    id: str
    name: str
    version: str
    actions: tuple[Action, ...]
    run: RunSpec
    path: Path = field(default_factory=Path)
    manifest_path: Path = field(default_factory=Path)
    description: str = ""

    def action(self, action_id: str) -> Action:
        for item in self.actions:
            if item.id == action_id:
                return item
        known = ", ".join(a.id for a in self.actions)
        raise KeyError(
            "engine {0!r} has no action {1!r} (have: {2})".format(self.id, action_id, known)
        )

    @property
    def action_ids(self) -> tuple[str, ...]:
        return tuple(a.id for a in self.actions)

    def params_path(self, action: "Action | str") -> Path | None:
        """Absolute path of the action's params JSON, or ``None`` if it has none."""
        act = self.action(action) if isinstance(action, str) else action
        if not act.params:
            return None
        return (self.path / act.params).resolve()

    def working_dir(self) -> Path:
        """Absolute working directory for the subprocess (may be a sibling repo)."""
        return (self.path / self.run.cwd).resolve()


@dataclass(frozen=True)
class ManifestProblem:
    """A manifest that could not be loaded. Discovery reports it, never raises."""

    path: Path
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return "{0}: {1}".format(self.path, self.message)


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def load_manifest(path: PathLike) -> Engine:
    """Load and fully validate one ``engine.yaml``.

    *path* may be the manifest file or the engine folder that contains it.
    Raises :class:`ManifestError` on anything that is not a valid v1 manifest.
    """
    path = Path(path)
    if path.is_dir():
        path = path / MANIFEST_NAME
    if not path.is_file():
        raise ManifestError("{0}: no such manifest file".format(path))

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ManifestError("{0}: cannot read YAML - {1}".format(path, exc)) from exc

    if raw is None:
        raise ManifestError("{0}: manifest is empty".format(path))
    if not isinstance(raw, dict):
        raise ManifestError(
            "{0}: top level must be a mapping, got {1}".format(path, type(raw).__name__)
        )

    try:
        jsonschema.validate(raw, ENGINE_SCHEMA)
    except jsonschema.ValidationError as exc:
        where = "/".join(str(part) for part in exc.absolute_path) or "<root>"
        hint = ""
        if list(exc.absolute_path) == ["version"] and not isinstance(raw.get("version"), str):
            # 'version: 1.10' is a float in YAML and would round to 1.1, so the
            # schema insists on a string. Say so instead of just "not of type".
            hint = " - quote it, e.g. version: \"1.0.0\""
        raise ManifestError(
            "{0}: at {1}: {2}{3}".format(path, where, exc.message, hint)
        ) from exc

    engine = Engine(
        id=raw["id"],
        name=raw["name"],
        version=raw["version"],
        actions=tuple(Action.from_dict(item) for item in raw["actions"]),
        run=RunSpec(command=raw["run"]["command"], cwd=raw["run"].get("cwd", ".")),
        path=path.parent.resolve(),
        manifest_path=path.resolve(),
        description=raw.get("description", ""),
    )
    _check_semantics(engine, path)
    return engine


def _check_semantics(engine: Engine, path: Path) -> None:
    """Rules that JSON Schema cannot express."""
    prefix = "{0}: ".format(path)

    if not _ID_RE.match(engine.id):
        raise ManifestError(
            prefix
            + "id {0!r} must be lower-case letters, digits, '_' or '-'".format(engine.id)
        )

    seen_actions: set[str] = set()
    for action in engine.actions:
        if not _ID_RE.match(action.id):
            raise ManifestError(
                prefix
                + "action id {0!r} must be lower-case letters, digits, '_' or '-'".format(
                    action.id
                )
            )
        if action.id in seen_actions:
            raise ManifestError(prefix + "duplicate action id {0!r}".format(action.id))
        seen_actions.add(action.id)

        for slot_name, slots in (("input", action.inputs), ("output", action.outputs)):
            seen_keys: set[str] = set()
            for slot in slots:
                if not _KEY_RE.match(slot.key):
                    raise ManifestError(
                        prefix
                        + "action {0!r}: bad {1} key {2!r}".format(
                            action.id, slot_name, slot.key
                        )
                    )
                if slot.key in seen_keys:
                    raise ManifestError(
                        prefix
                        + "action {0!r}: duplicate {1} key {2!r}".format(
                            action.id, slot_name, slot.key
                        )
                    )
                seen_keys.add(slot.key)
                if slot_name == "output" and (slot.multiple or slot.optional):
                    raise ManifestError(
                        prefix
                        + "action {0!r}: output {1!r} may not be 'multiple' or "
                        "'optional'".format(action.id, slot.key)
                    )

    _check_command_template(engine, prefix)


def _check_command_template(engine: Engine, prefix: str) -> None:
    """Every placeholder in ``run.command`` must be one the shell can fill.

    ``run.command`` is one template shared by all actions, so an
    ``{input:<key>}`` only has to be declared by **at least one** action - an
    engine like geohazard has six stages with different inputs. For an action
    that does not declare the key, rendering treats it as an omitted optional
    (approved 2026-08-27); a key NO action declares is rejected here, so a typo
    still fails at manifest load.
    """
    allowed = ", ".join("{" + name + "}" for name in FIXED_PLACEHOLDERS)
    known_inputs = {slot.key for action in engine.actions for slot in action.inputs}

    for match in PLACEHOLDER_RE.finditer(engine.run.command):
        name, arg = match.group(1), match.group(2)
        if name == "input":
            if arg is None:
                raise ManifestError(
                    prefix + "run.command: '{input}' needs a key, e.g. {input:cloud}"
                )
            if arg not in known_inputs:
                raise ManifestError(
                    prefix
                    + "run.command uses {{input:{0}}} but no action declares an input "
                    "with that key".format(arg)
                )
        elif arg is not None or name not in FIXED_PLACEHOLDERS:
            raise ManifestError(
                prefix
                + "run.command: unknown placeholder {0!r} (allowed: {1}, "
                "{{input:<key>}})".format(match.group(0), allowed)
            )

    for action in engine.actions:
        if action.params and "{params_file}" not in engine.run.command:
            raise ManifestError(
                prefix
                + "action {0!r} declares params but run.command never uses "
                "{{params_file}}".format(action.id)
            )


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #


def discover_engines(
    root: PathLike, *, include_private: bool = False
) -> tuple[list[Engine], list[ManifestProblem]]:
    """Scan ``<root>/engines/*/engine.yaml``.

    *root* may be the repository root or the ``engines`` folder itself. Folders
    whose name starts with ``_`` or ``.`` are skipped unless *include_private*
    is true (session 2 uses that for its ``_demo`` engine).

    Returns ``(engines, problems)``. A broken manifest becomes a
    :class:`ManifestProblem`; discovery never raises because of one bad engine.
    """
    root = Path(root)
    engines_dir = root if root.name == "engines" else root / "engines"

    engines: list[Engine] = []
    problems: list[ManifestProblem] = []
    if not engines_dir.is_dir():
        return engines, problems

    for folder in sorted(p for p in engines_dir.iterdir() if p.is_dir()):
        if not include_private and folder.name.startswith(("_", ".")):
            continue
        manifest_path = folder / MANIFEST_NAME
        if not manifest_path.is_file():
            continue  # scaffold folder, adapter not written yet - not an error
        try:
            engine = load_manifest(manifest_path)
            # Layout rule, enforced here rather than in load_manifest: the shell
            # locates an engine by its folder. A private '_demo' folder holds
            # the engine 'demo'.
            if engine.id != folder.name.lstrip("_"):
                raise ManifestError(
                    "{0}: id {1!r} must match the engine folder name {2!r}".format(
                        manifest_path, engine.id, folder.name
                    )
                )
            engines.append(engine)
        except ManifestError as exc:
            problems.append(ManifestProblem(manifest_path, str(exc)))
        except Exception as exc:  # defensive: discovery must never crash the shell
            problems.append(
                ManifestProblem(manifest_path, "unexpected error - {0!r}".format(exc))
            )

    seen: dict[str, Engine] = {}
    unique: list[Engine] = []
    for engine in engines:
        if engine.id in seen:
            problems.append(
                ManifestProblem(
                    engine.manifest_path,
                    "duplicate engine id {0!r} (already loaded from {1})".format(
                        engine.id, seen[engine.id].manifest_path
                    ),
                )
            )
            continue
        seen[engine.id] = engine
        unique.append(engine)

    unique.sort(key=lambda e: e.id)
    return unique, problems


def find_engines(root: PathLike, *, include_private: bool = False) -> list[Engine]:
    """Engines found under *root*. Broken manifests are logged and skipped.

    Use :func:`discover_engines` when the caller wants to show the problems.
    """
    engines, problems = discover_engines(root, include_private=include_private)
    for problem in problems:
        _log.warning("skipping engine manifest - %s", problem)
    return engines


# --------------------------------------------------------------------------- #
# Command template
# --------------------------------------------------------------------------- #


def render_command(
    engine: Engine,
    action: "Action | str",
    *,
    python: PathLike,
    run_dir: PathLike,
    params_file: PathLike | None = None,
    inputs: Mapping[str, Any] | None = None,
) -> str:
    """Fill ``run.command`` for one concrete run.

    Pure string substitution: how the result is split and executed is the
    shell's decision (session 2). A multi-valued input is joined with spaces.
    Raises :class:`ManifestError` if a required input or the params file is
    missing.
    """
    act = engine.action(action) if isinstance(action, str) else action
    values: dict[str, Any] = dict(inputs or {})

    def replace(match: "re.Match[str]") -> str:
        name, arg = match.group(1), match.group(2)
        if name == "python":
            return str(python)
        if name == "action":
            return act.id
        if name == "run_dir":
            return str(run_dir)
        if name == "params_file":
            if params_file is None:
                raise ManifestError(
                    "{0}/{1}: run.command uses {{params_file}} but no params file was "
                    "given".format(engine.id, act.id)
                )
            return str(params_file)
        if name == "input":
            try:
                slot = act.input(arg)
            except KeyError:
                # Approved 2026-08-27: the template is shared by all actions, so
                # a key the CURRENT action does not declare renders as empty
                # (like an omitted optional). Typos are still caught at load
                # time - load_manifest rejects keys NO action declares.
                return ""
            if arg not in values or values[arg] is None:
                if slot.optional:
                    return ""
                raise ManifestError(
                    "{0}/{1}: missing input {2!r}".format(engine.id, act.id, arg)
                )
            value = values[arg]
            if isinstance(value, (str, Path)):
                return str(value)
            if isinstance(value, Sequence):
                return " ".join(str(item) for item in value)
            return str(value)
        raise ManifestError(
            "{0}/{1}: unknown placeholder {2!r}".format(engine.id, act.id, match.group(0))
        )

    return PLACEHOLDER_RE.sub(replace, engine.run.command).strip()


def render_argv(
    engine: Engine,
    action: "Action | str",
    *,
    python: PathLike,
    run_dir: PathLike,
    params_file: PathLike | None = None,
    inputs: Mapping[str, Any] | None = None,
) -> list[str]:
    """Fill ``run.command`` as an **argument list** - the form to execute.

    Added in session 2 (approved 2026-08-27): a path containing spaces must
    survive as ONE argument on Windows, so execution never goes through a
    single command string. The template is split on whitespace first, then each
    token has its placeholders substituted:

    * a token that is exactly one placeholder becomes one argument - or, for a
      ``multiple`` input, one argument **per file**;
    * a token that is exactly an omitted ``optional`` input is dropped
      (prefer ``--mask={input:mask}`` style for optionals so no dangling flag
      is left behind);
    * inside a larger token (``--out={run_dir}``) the value is substituted
      in place; a multi-valued input embedded like that has no unambiguous
      argv form and raises :class:`ManifestError`.

    Same error behaviour as :func:`render_command` (which remains the
    display/logging form): missing required input, missing params file, or an
    ``{input:<key>}`` the action does not declare all raise
    :class:`ManifestError`.
    """
    act = engine.action(action) if isinstance(action, str) else action
    values: dict[str, Any] = dict(inputs or {})

    _MISSING_OPTIONAL = object()

    def fill(match: "re.Match[str]", *, whole_token: bool) -> Any:
        name, arg = match.group(1), match.group(2)
        if name == "python":
            return str(python)
        if name == "action":
            return act.id
        if name == "run_dir":
            return str(run_dir)
        if name == "params_file":
            if params_file is None:
                raise ManifestError(
                    "{0}/{1}: run.command uses {{params_file}} but no params file was "
                    "given".format(engine.id, act.id)
                )
            return str(params_file)
        if name == "input":
            try:
                slot = act.input(arg)
            except KeyError:
                # Approved 2026-08-27: shared template, heterogeneous actions -
                # a key this action does not declare behaves like an omitted
                # optional (whole token dropped, embedded form empty). Keys NO
                # action declares are still rejected by load_manifest.
                return _MISSING_OPTIONAL
            if arg not in values or values[arg] is None:
                if slot.optional:
                    return _MISSING_OPTIONAL
                raise ManifestError(
                    "{0}/{1}: missing input {2!r}".format(engine.id, act.id, arg)
                )
            value = values[arg]
            if isinstance(value, (str, Path)):
                return str(value)
            if isinstance(value, Sequence):
                items = [str(item) for item in value]
                if not whole_token and len(items) != 1:
                    raise ManifestError(
                        "{0}/{1}: multi-valued input {2!r} cannot be embedded inside "
                        "a larger argument - give {{input:{2}}} its own token".format(
                            engine.id, act.id, arg
                        )
                    )
                return items if whole_token else items[0]
            return str(value)
        raise ManifestError(
            "{0}/{1}: unknown placeholder {2!r}".format(engine.id, act.id, match.group(0))
        )

    argv: list[str] = []
    for token in engine.run.command.split():
        match = PLACEHOLDER_RE.fullmatch(token)
        if match is not None:
            value = fill(match, whole_token=True)
            if value is _MISSING_OPTIONAL:
                continue
            if isinstance(value, list):
                argv.extend(value)
            else:
                argv.append(value)
            continue

        def replace(m: "re.Match[str]") -> str:
            value = fill(m, whole_token=False)
            return "" if value is _MISSING_OPTIONAL else value

        argv.append(PLACEHOLDER_RE.sub(replace, token))
    return argv
