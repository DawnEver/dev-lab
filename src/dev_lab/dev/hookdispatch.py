"""ONE DISPATCHER PER HOOK EVENT: every handler :data:`~dev_lab.dev.agent_wiring.WIRING` declares, in one interpreter.

Before dev-lab #640 each handler was its own settings row, so one shell call started six interpreters, and the rows
were rendered from the LOCK's dev-lab while each worktree ran its OWN venv's -- a handler added on one machine broke
every machine whose venv lagged (incident #633). Now the settings row names only the event
(:func:`~dev_lab.dev.agent_wiring.dispatch_command`) and this module reads the table from the package it is part
of, so rows and code are one install.

The rows are the family's :data:`~dev_lab.dev.agent_wiring.WIRING` and the repo's own declared ones
(:func:`~dev_lab.dev.agent_wiring.declared`, read from ``$CLAUDE_PROJECT_DIR``, else the payload's ``cwd``), imported
with the repo's root on the path. A refused declaration is one stderr line naming it; the family's rows still run.

``python -m dev_lab.dev.hookdispatch [--timing] <Event>`` reads the hook payload once, then for each row of the event
whose ``tools`` admit the payload's ``tool_name`` (and, for a ``once`` row, that has not run in this session) calls
``<module>.main(argv)`` with the payload as its stdin and its own stdout and stderr. The answers merge into one
(:mod:`dev_lab.dev._hookanswer`); ``--timing`` adds one stderr line per row with its wall time.

FIVE SECONDS, AND NOTHING DROPPED (``HOOK-UNDER-FIVE-SECONDS``, user ruling D24, 2026-11-17). Guards run first and
keep running to :data:`~dev_lab.dev.agent_wiring.GUARD_BUDGET_S`; every other row must finish within
:data:`~dev_lab.dev.agent_wiring.DISPATCH_BUDGET_S` of the dispatcher's start. A ``detached`` row, a row the budget
ran out before, and a row that outlived it are HANDED OFF (:mod:`dev_lab.dev.hookhandoff`): one background runner
runs them to completion and their answer reaches the session at its next context event, which this dispatcher
delivers. A hand-off past the budget is said in the answer, by name. ``--background <job>`` is that runner. The
queue is written BEFORE the first inline row runs -- the detached rows as a job, the inline rows as a write-ahead
record the runner adopts if this process dies -- so a dispatcher the harness kills at its timeout loses no row.

The dispatcher always exits 0: a block is its JSON answer, never an exit code.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import sys
import threading
import time
import traceback
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, Final, TextIO

from lab_commons.log import emit

from dev_lab.dev import harness, hookhandoff
from dev_lab.dev._hookanswer import CONTEXT_EVENTS, Outcome, answer, deferred_text, parsed
from dev_lab.dev._hookonce import first_runs
from dev_lab.dev.agent_wiring import (
    DISPATCH_BUDGET_S,
    GUARD_BUDGET_S,
    WIRING,
    Wire,
    WireRefused,
    declared,
    import_root,
)
from dev_lab.dev.disclosure import details_for
from dev_lab.dev.gitdirs import git_dir

__all__ = ['Outcome', 'answer', 'main', 'run_row', 'selected']

_RULE: Final = 'HOOK-UNDER-FIVE-SECONDS'


class _Routed(io.TextIOBase):
    """A stream each thread may bind to its own buffer; an unbound thread writes through to *fallback*."""

    def __init__(self, fallback: TextIO) -> None:
        super().__init__()
        self._fallback = fallback
        self._bound: dict[int, TextIO] = {}

    @contextlib.contextmanager
    def bound(self, stream: TextIO) -> Iterator[None]:
        self._bound[threading.get_ident()] = stream
        try:
            yield
        finally:
            self._bound.pop(threading.get_ident(), None)

    def _target(self) -> TextIO:
        return self._bound.get(threading.get_ident(), self._fallback)

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return self._target().encoding or 'utf-8'

    def readable(self) -> bool:
        return True

    def writable(self) -> bool:
        return True

    def read(self, size: int | None = -1) -> str:
        return self._target().read(-1 if size is None else size)

    def readline(self, size: int | None = -1) -> str:
        return self._target().readline(-1 if size is None else size)

    def write(self, text: str) -> int:
        return self._target().write(text)

    def flush(self) -> None:
        self._target().flush()


def selected(event: str, payload: dict[str, Any], wires: Sequence[Wire]) -> tuple[Wire, ...]:
    """The rows of *wires* on *event* whose tools admit *payload*'s ``tool_name``."""
    tool = str(payload.get('tool_name') or '')
    return tuple(wire for wire in wires if event in wire.events and (not wire.tools or tool in wire.tools))


def _cwd(payload: dict[str, Any]) -> Path:
    return Path(str(payload.get('cwd') or Path.cwd()))


def _repo_root(payload: dict[str, Any]) -> Path:
    """The checkout whose settings run this hook: ``$CLAUDE_PROJECT_DIR``, else the payload's ``cwd``."""
    return Path(harness.context().project_dir or _cwd(payload))


def _repo_wires(root: Path) -> tuple[tuple[Wire, ...], str]:
    """*root*'s declared wires and ``''``, or none and the one line naming why the declaration was refused."""
    try:
        return declared(root), ''
    except (WireRefused, OSError, ValueError) as refused:
        return (), f"[hook] the repo's declared wires did not run: {refused}"


def _call(wire: Wire) -> int:
    module = importlib.import_module(wire.module)
    try:
        code = module.main(list(wire.argv))
    except SystemExit as exit_:
        code = exit_.code
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    emit(code, err=True)
    return 1


def run_row(wire: Wire, text: str, *, timeout: float | None = None) -> Outcome:
    """Run *wire* on payload *text* in a thread of its own, bounded by *timeout* (default its inline bound)."""
    out, err = io.StringIO(), io.StringIO()
    done: list[int] = []
    stdin, stdout, stderr = sys.stdin, sys.stdout, sys.stderr
    if not (isinstance(stdin, _Routed) and isinstance(stdout, _Routed) and isinstance(stderr, _Routed)):
        msg = 'run_row needs the routed streams main() installs'
        raise TypeError(msg)

    def body() -> None:
        with stdin.bound(io.StringIO(text)), stdout.bound(out), stderr.bound(err):
            try:
                done.append(_call(wire))
            except Exception:  # noqa: BLE001 -- a crashed handler is one line, never the dispatcher's crash
                err.write(traceback.format_exc())
                done.append(1)

    began = time.monotonic()
    worker = threading.Thread(target=body, name=wire.name, daemon=True)
    worker.start()
    worker.join(wire.inline_bound if timeout is None else timeout)
    elapsed = time.monotonic() - began
    return Outcome(wire, done[0] if done else None, out.getvalue(), err.getvalue(), elapsed)


def _inline(wires: Sequence[Wire], text: str, started: float) -> tuple[list[Outcome], list[Wire]]:
    """Run *wires*, guards first, each within its budget from *started*; the outcomes, and the rows to hand off."""
    outcomes: list[Outcome] = []
    late: list[Wire] = []
    for wire in sorted(wires, key=lambda one: not one.may_block):
        # A row past the budget and every row after it are late: a timed wait may return early (Windows' timer), so
        # time still "left" after a late row never starts the next one on that sliver.
        left = started + wire.budget - time.monotonic()
        one = run_row(wire, text, timeout=min(wire.inline_bound, left)) if left > 0 and not late else None
        if one is None or one.code is None:
            late.append(wire)
        else:
            outcomes.append(one)
    return outcomes, late


def _failed(wires: Sequence[Wire], failed: OSError, *, then: str = 'they did not run') -> str:
    names = ', '.join(wire.name for wire in wires)
    return f'{_RULE}: {names} could not be handed to the background ({failed}); {then}\n{details_for(_RULE)}'


def _queue_first(
    event: str, text: str, payload: dict[str, Any], wires: Sequence[Wire]
) -> tuple[Path | None, list[str]]:
    """Before any inline row runs: hand the detached rows off and record the inline ones (``hookhandoff``).

    The record, and the messages naming what could not be queued. A dispatcher the harness kills from here on loses
    nothing: the runner holds the detached job and adopts the record of a writer that died.
    """
    cwd, root = _cwd(payload), _repo_root(payload)
    detached = [wire for wire in wires if wire.detached]
    inline = [wire for wire in wires if not wire.detached]
    said: list[str] = []
    record = None
    try:
        record = hookhandoff.write_ahead(cwd, event, text, inline, root)
    except OSError as failed:
        said.append(_failed(inline, failed, then='they run inline, and a kill would lose them'))
    if detached:
        try:
            hookhandoff.hand_off(cwd, event, text, detached, root)
        except OSError as failed:
            said.append(_failed(detached, failed))
    return record, said


def _settle(event: str, text: str, payload: dict[str, Any], record: Path | None, late: Sequence[Wire]) -> list[str]:
    """The inline rows have run: drop the record, or hand the *late* ones off; the message naming them."""
    try:
        if record is None and late:  # the record could not be written: the late rows still go to the background
            hookhandoff.hand_off(_cwd(payload), event, text, late, _repo_root(payload))
        hookhandoff.settle(record, late, _repo_root(payload))
    except OSError as failed:
        return [_failed(late, failed)]
    if not late:
        return []
    names = ', '.join(wire.name for wire in late)
    said = (
        f'{_RULE}: {names} ran past the hook budget ({DISPATCH_BUDGET_S:g} s, a guard {GUARD_BUDGET_S:g} s); it runs '
        f'to completion in the background and its answer arrives at the next prompt\n{details_for(_RULE)}'
    )
    return [said]


def _run_job(job: dict[str, Any]) -> None:
    """The runner's half: run one handed-off job's rows to completion and defer what they said to its session."""
    text, event = str(job.get('payload') or ''), str(job.get('event') or '')
    payload = parsed(text) or {}
    root = Path(str(job.get('root') or _repo_root(payload)))
    mine, refused = _repo_wires(root)
    by_name = {wire.name: wire for wire in (*WIRING, *mine)}
    rows = job.get('rows') if isinstance(job.get('rows'), list) else []
    wires = [by_name[name] for name in rows if isinstance(name, str) and name in by_name]
    with import_root(root) if mine else contextlib.nullcontext():
        outcomes = [run_row(wire, text, timeout=wire.background_bound) for wire in wires]
    said = '\n'.join(line for line in (refused, deferred_text(event, outcomes)) if line)
    if said:
        hookhandoff.defer(_cwd(payload), str(payload.get('session_id') or ''), event, said)


def _timing(event: str, outcomes: Sequence[Outcome], late: Sequence[Wire], started: float, queued: float) -> str:
    rows = [f'[hook-timing] {event} queue written {queued * 1000:.0f} ms']
    rows += [f'[hook-timing] {event} {one.wire.name} {one.elapsed * 1000:.0f} ms' for one in outcomes]
    rows += [f'[hook-timing] {event} {wire.name} handed off' for wire in late]
    return '\n'.join([*rows, f'[hook-timing] {event} total {(time.monotonic() - started) * 1000:.0f} ms'])


def _background(job: Path) -> int:
    streams = (sys.stdin, sys.stdout, sys.stderr)
    sys.stdin, sys.stdout, sys.stderr = (_Routed(stream) for stream in streams)
    try:
        hookhandoff.drain(job.parent, _run_job)
    finally:
        sys.stdin, sys.stdout, sys.stderr = streams
    return 0


def main(argv: list[str] | None = None) -> int:
    """``python -m dev_lab.dev.hookdispatch [--timing] <Event> | --background <job>``; always exit 0.

    The budget counts from this call. The interpreter's start and this module's imports come before it (measured
    2026-11-17: 0.2-0.4 s warm, up to 1.3 s cold) and sit in the margin the budgets leave under the ceiling.
    """
    started = time.monotonic()
    args = list(sys.argv[1:] if argv is None else argv)
    timing = '--timing' in args
    match [arg for arg in args if arg != '--timing']:
        case ['--background', job]:
            return _background(Path(job))
        case [event]:
            pass
        case _:
            emit('usage: python -m dev_lab.dev.hookdispatch [--timing] <Event> | --background <job>', err=True)
            return 0
    text = sys.stdin.read()
    payload = parsed(text) or {}
    root = _repo_root(payload)
    mine, refused = _repo_wires(root)
    wires = first_runs(selected(event, payload, (*WIRING, *mine)), payload, git_dir(_cwd(payload)))
    session = str(payload.get('session_id') or '')
    before = time.monotonic()
    record, handed = _queue_first(event, text, payload, wires)
    queued = time.monotonic() - before
    deferred = hookhandoff.take_deferred(_cwd(payload), session) if event in CONTEXT_EVENTS else []
    streams = (sys.stdin, sys.stdout, sys.stderr)
    sys.stdin, sys.stdout, sys.stderr = (_Routed(stream) for stream in streams)
    with import_root(root) if mine else contextlib.nullcontext():
        outcomes, late = _inline([wire for wire in wires if not wire.detached], text, started)
    if not late:  # a row still running keeps writing into its own buffer
        sys.stdin, sys.stdout, sys.stderr = streams
    handed += _settle(event, text, payload, record, late)
    said, notes = answer(event, outcomes, contexts=deferred, messages=handed)
    timed = _timing(event, outcomes, late, started, queued) if timing else ''
    notes = '\n'.join(line for line in (refused, notes, timed) if line)
    if notes:
        emit(notes, err=True)
    if said:
        emit(said)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
