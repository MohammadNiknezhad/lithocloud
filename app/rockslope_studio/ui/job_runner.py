"""Subprocess job runner (architecture section 5, spec section 3).

One job at a time (16 GB RAM); further requests queue. Every run:

1. ``core.create_run_dir`` - fresh folder, never overwritten;
2. the validated params are written to ``<run_dir>/params.json``;
3. ``core.render_argv`` builds the ARGUMENT LIST - never a joined string, so
   paths with spaces survive on Windows;
4. ``core.write_run_manifest`` records everything before the process starts;
5. non-interactive: ``QProcess`` with merged channels, stdout streamed to the
   log panel. Interactive: ``subprocess.Popen`` with ``CREATE_NEW_CONSOLE`` so
   ``input()`` prompts and matplotlib windows behave exactly as today;
6. on exit: ``core.finish_run`` (``_DONE.json`` only for exit code 0), then -
   only on success - artifacts are registered from the engine's
   ``outputs.json`` (contract decided 2026-08-27: ``{output_key: [files]}``,
   paths relative to the run folder; a declared key missing from it is a
   warning, not a failure);
7. Cancel kills the whole process tree (``taskkill /T /F`` on Windows).

A crashing engine can never crash the shell: every failure path ends in a
recorded run folder without ``_DONE.json`` and an error line in the log.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from rockslope_studio.core import (
    Action,
    Artifact,
    Engine,
    ManifestError,
    artifacts as core_artifacts,
    finish_run,
    render_argv,
    render_command,
    write_run_manifest,
)
from rockslope_studio.core.runs import create_run_dir
from rockslope_studio.core._util import atomic_write_json

from .input_files import ExternalFile

OUTPUTS_NAME = "outputs.json"
PARAMS_NAME = "params.json"
#: Adapters write their early-failure message here (approved 2026-08-27), so
#: an error from an interactive console stays readable after the window closes.
ADAPTER_ERROR_NAME = "adapter_error.txt"

_POLL_MS = 300  # how often an interactive (console) process is checked


def _input_id(value: "Artifact | ExternalFile") -> str:
    """The lineage id of one chosen input."""
    if isinstance(value, Artifact):
        return value.artifact_id
    return str(value.path)  # absolute path (amendment A1)


def _input_path(value: "Artifact | ExternalFile") -> str:
    """The absolute file the engine should read."""
    if isinstance(value, Artifact):
        return str(value.paths[0])
    return str(value.path)


@dataclass
class JobRequest:
    """Everything needed to start one run. Built by the engine panel."""

    engine: Engine
    action: Action
    params: dict[str, Any] = field(default_factory=dict)
    #: input key -> Artifact | ExternalFile, or a list of either for a
    #: ``multiple`` input (the two may be mixed).
    inputs: dict[str, Any] = field(default_factory=dict)

    def input_ids(self) -> dict[str, Any]:
        """Input ids per key, as recorded in the run manifest.

        An artifact contributes its artifact_id; a file browsed from disk
        (amendment A1) contributes its absolute path, which resolves to no
        artifact and so shows up as an unresolved - but visible - lineage
        source.
        """
        out: dict[str, Any] = {}
        for key, value in self.inputs.items():
            if isinstance(value, (Artifact, ExternalFile)):
                out[key] = _input_id(value)
            elif value:
                out[key] = [_input_id(item) for item in value]
        return out

    def input_paths(self) -> dict[str, Any]:
        """Absolute file path per input key, for the engine command."""
        out: dict[str, Any] = {}
        for key, value in self.inputs.items():
            if isinstance(value, (Artifact, ExternalFile)):
                out[key] = _input_path(value)
            elif value:
                out[key] = [_input_path(item) for item in value]
        return out


class Job(QObject):
    """One run in flight. Owns the process and the run folder."""

    log_line = Signal(str)
    finished = Signal(int)  # exit code (nonzero for crash or cancel)

    def __init__(
        self, request: JobRequest, run_dir: Path, argv: list[str], cwd: Path
    ) -> None:
        super().__init__()
        self.request = request
        self.run_dir = run_dir
        self.argv = argv
        self.cwd = cwd
        self.cancelled = False
        self._done = False
        self._proc: QProcess | None = None
        self._popen: subprocess.Popen | None = None
        self._timer: QTimer | None = None

    def _emit_finished(self, code: int) -> None:
        """Exactly once - QProcess can report both errorOccurred and finished."""
        if self._done:
            return
        self._done = True
        self.finished.emit(int(code))

    # -- lifecycle --------------------------------------------------------- #

    def start(self) -> None:
        if self.request.action.interactive:
            self._start_console()
        else:
            self._start_qprocess()

    def _start_qprocess(self) -> None:
        proc = QProcess(self)
        proc.setProgram(self.argv[0])
        proc.setArguments(self.argv[1:])
        proc.setWorkingDirectory(str(self.cwd))
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        # Method slots (not lambdas): Qt auto-disconnects them when this Job is
        # deleted, so a late QProcess signal can never hit a dead receiver.
        proc.readyReadStandardOutput.connect(self._drain)
        proc.finished.connect(self._on_proc_finished)
        proc.errorOccurred.connect(self._on_qprocess_error)
        self._proc = proc
        proc.start()

    def _start_console(self) -> None:
        """Interactive engines get their own console window (spec section 3)."""
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.CREATE_NEW_CONSOLE
        try:
            self._popen = subprocess.Popen(self.argv, cwd=str(self.cwd), creationflags=flags)
        except OSError as exc:
            self.log_line.emit("ERROR: could not launch console process - {0}".format(exc))
            self._emit_finished(-1)
            return
        self.log_line.emit(
            "(interactive - running in its own console window, pid {0})".format(
                self._popen.pid
            )
        )
        timer = QTimer(self)
        timer.setInterval(_POLL_MS)
        timer.timeout.connect(self._poll_console)
        self._timer = timer
        timer.start()

    def _on_proc_finished(self, code: int, _status) -> None:
        self._emit_finished(code)

    def _poll_console(self) -> None:
        assert self._popen is not None
        code = self._popen.poll()
        if code is not None:
            if self._timer is not None:
                self._timer.stop()
            self._emit_finished(code)

    def _drain(self) -> None:
        assert self._proc is not None
        data = bytes(self._proc.readAllStandardOutput())
        text = data.decode("utf-8", errors="replace")
        for line in text.splitlines():
            self.log_line.emit(line)

    def _on_qprocess_error(self, error: QProcess.ProcessError) -> None:
        # FailedToStart does not reliably emit finished; report it ourselves.
        # (_emit_finished de-duplicates if Qt later emits finished anyway.)
        if error == QProcess.ProcessError.FailedToStart:
            self.log_line.emit(
                "ERROR: process failed to start ({0})".format(self.argv[0])
            )
            self._emit_finished(-1)

    # -- cancel ------------------------------------------------------------ #

    def pid(self) -> int | None:
        if self._proc is not None and self._proc.processId():
            return int(self._proc.processId())
        if self._popen is not None:
            return self._popen.pid
        return None

    def cancel(self) -> None:
        """Terminate the whole process tree (spec: Cancel = tree kill)."""
        self.cancelled = True
        pid = self.pid()
        if pid is None:
            return
        self.log_line.emit("Cancelling (killing process tree, pid {0})...".format(pid))
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:  # pragma: no cover - dev convenience only, the studio targets Windows
            if self._proc is not None:
                self._proc.kill()
            if self._popen is not None:
                self._popen.kill()


class JobRunner(QObject):
    """The queue: one job at a time, in submission order."""

    job_started = Signal(object)  # Job
    job_log = Signal(str)
    #: (Job, exit_code, ok) - after finish_run and artifact registration.
    job_finished = Signal(object, int, bool)
    queue_changed = Signal(int)  # jobs waiting

    def __init__(self, workspace: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.workspace = Path(workspace)
        self.python = sys.executable  # the rockslope env (decision D2)
        self._queue: list[JobRequest] = []
        self._current: Job | None = None

    # -- public ------------------------------------------------------------ #

    @property
    def current(self) -> Job | None:
        return self._current

    @property
    def queued(self) -> int:
        return len(self._queue)

    def submit(self, request: JobRequest) -> None:
        self._queue.append(request)
        self.queue_changed.emit(len(self._queue))
        # Deferred: even a job that fails instantly (unlaunchable command) must
        # not run its whole lifecycle inside submit(), or callers could miss
        # its signals. The guard in _start_next keeps repeated shots harmless.
        QTimer.singleShot(0, self._start_next)

    def cancel_current(self) -> None:
        if self._current is not None:
            self._current.cancel()

    # -- internals ---------------------------------------------------------- #

    def _start_next(self) -> None:
        if self._current is not None or not self._queue:
            return
        request = self._queue.pop(0)
        self.queue_changed.emit(len(self._queue))
        try:
            job = self._prepare(request)
        except Exception as exc:  # noqa: BLE001 - any setup failure is a job failure
            self.job_log.emit("ERROR: could not start job - {0}".format(exc))
            self._start_next()
            return
        self._current = job
        job.log_line.connect(self.job_log)
        job.finished.connect(lambda code: self._on_finished(job, code))
        self.job_started.emit(job)
        self.job_log.emit("=== {0} ===".format(job.run_dir.name))
        job.start()

    def _prepare(self, request: JobRequest) -> Job:
        engine, action = request.engine, request.action

        run_dir = create_run_dir(self.workspace, engine.id, action.id)

        params_file: Path | None = None
        if action.params:
            params_file = run_dir / PARAMS_NAME
            atomic_write_json(params_file, request.params)

        argv = render_argv(
            engine,
            action,
            python=self.python,
            run_dir=run_dir,
            params_file=params_file,
            inputs=request.input_paths(),
        )
        cwd = engine.working_dir()
        if not cwd.is_dir():
            raise ManifestError(
                "engine {0}: working directory {1} does not exist".format(engine.id, cwd)
            )

        display = render_command(
            engine,
            action,
            python=self.python,
            run_dir=run_dir,
            params_file=params_file,
            inputs=request.input_paths(),
        )
        write_run_manifest(
            run_dir,
            engine=engine.id,
            engine_version=engine.version,
            action=action.id,
            params=request.params,
            inputs=request.input_ids(),
            command=display,
            cwd=cwd,
            extra={"argv": argv, "interactive": action.interactive},
        )
        return Job(request, run_dir, argv, cwd)

    def _on_finished(self, job: Job, exit_code: int) -> None:
        if job.cancelled and exit_code == 0:
            # taskkill reports 1 on Windows, but be safe on every path:
            exit_code = -2
        ok = exit_code == 0

        outputs_summary: list[str] = []
        registered: list[Artifact] = []
        if ok:
            registered, problems = self._register_outputs(job)
            outputs_summary = [a.artifact_id for a in registered]
            for line in problems:
                self.job_log.emit("WARNING: " + line)

        try:
            finish_run(
                job.run_dir, exit_code, outputs=outputs_summary, cancelled=job.cancelled
            )
        except Exception as exc:  # noqa: BLE001
            self.job_log.emit("ERROR: could not record run end - {0}".format(exc))
            ok = False

        if not ok:
            self._show_adapter_error(job)

        if job.cancelled:
            self.job_log.emit("=== cancelled (exit code {0}) ===".format(exit_code))
        elif ok:
            self.job_log.emit(
                "=== finished OK, {0} artifact(s) registered ===".format(len(registered))
            )
        else:
            self.job_log.emit("=== FAILED with exit code {0} ===".format(exit_code))

        self._current = None
        self.job_finished.emit(job, exit_code, ok)
        self._start_next()

    def _show_adapter_error(self, job: Job) -> None:
        """Echo the adapter's persisted error message into the log panel.

        Interactive engines run in their own console window, which closes with
        the process - without this the reason for an early failure is gone.
        """
        path = job.run_dir / ADAPTER_ERROR_NAME
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            return
        if text:
            self.job_log.emit("--- {0} ---".format(ADAPTER_ERROR_NAME))
            for line in text.splitlines():
                self.job_log.emit(line)

    def _register_outputs(self, job: Job) -> tuple[list[Artifact], list[str]]:
        """Apply the outputs.json contract. Never raises: problems come back
        as warning lines - a bad outputs.json must not un-succeed the run."""
        request = job.request
        outputs_path = job.run_dir / OUTPUTS_NAME
        problems: list[str] = []

        mapping: Mapping[str, Any] = {}
        if not request.action.outputs:
            return [], problems
        if not outputs_path.is_file():
            problems.append(
                "engine wrote no {0}; declared outputs were not registered".format(
                    OUTPUTS_NAME
                )
            )
            return [], problems
        try:
            with open(outputs_path, "r", encoding="utf-8") as handle:
                mapping = json.load(handle)
            if not isinstance(mapping, dict):
                raise ValueError("must be an object of {output_key: [files]}")
        except (OSError, ValueError) as exc:
            problems.append("unreadable {0} - {1}".format(OUTPUTS_NAME, exc))
            return [], problems

        registered: list[Artifact] = []
        input_ids: list[str] = []
        for value in request.input_ids().values():
            input_ids.extend(value if isinstance(value, list) else [value])

        for slot in request.action.outputs:
            files = mapping.get(slot.key)
            if not files:
                problems.append(
                    "declared output {0!r} missing from {1}".format(slot.key, OUTPUTS_NAME)
                )
                continue
            if isinstance(files, str):
                files = [files]
            try:
                registered.append(
                    core_artifacts.write_provenance(
                        job.run_dir,
                        key=slot.key,
                        type=slot.type,
                        files=files,
                        engine=request.engine.id,
                        engine_version=request.engine.version,
                        action=request.action.id,
                        params=request.params,
                        inputs=input_ids,
                    )
                )
            except core_artifacts.ArtifactError as exc:
                problems.append("output {0!r}: {1}".format(slot.key, exc))

        for key in mapping:
            if all(slot.key != key for slot in request.action.outputs):
                problems.append(
                    "{0} names {1!r}, which the manifest does not declare".format(
                        OUTPUTS_NAME, key
                    )
                )
        return registered, problems
