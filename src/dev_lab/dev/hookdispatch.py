"""ONE DISPATCHER PER HOOK EVENT: every handler :data:`~dev_lab.dev.agent_wiring.WIRING` declares, in one interpreter.

Before dev-lab #640 each handler was its own settings row, so one shell call started six interpreters, and the rows
were rendered from the LOCK's dev-lab while each worktree ran its OWN venv's -- a handler added on one machine broke
every machine whose venv lagged (incident #633). Now the settings row names only the event
(:func:`~dev_lab.dev.agent_wiring.dispatch_command`) and this module reads the table from the package it is part
of, so rows and code are one install.

The rows are the family's :data:`~dev_lab.dev.agent_wiring.WIRING` and the repo's own declared ones
(:func:`~dev_lab.dev.agent_wiring.declared`, read from ``$CLAUDE_PROJECT_DIR``, else the payload's ``cwd``), imported
with the repo's root on the path. A refused declaration is one stderr line naming it; the family's rows still run.

``python -m dev_lab.dev.hookdispatch <Event>`` reads the hook payload once, then for each row of the event whose
``tools`` admit the payload's ``tool_name`` (and, for a ``once`` row, that has not run in this session) calls
``<module>.main(argv)`` with the payload as its stdin, its own stdout and stderr, and its ``timeout``. The answers
merge into one:

* a refusal -- exit 2, ``decision: block``, ``permissionDecision: deny`` -- counts only from a ``may_block`` row; any
  other row's is a wiring fault, said on stderr and passed;
* refusals join into one ``deny`` (``PreToolUse``) or one ``decision: block``; additional context and system
  messages join; a row's plain stdout is context on ``UserPromptSubmit``/``SessionStart`` (the tool's own rule) and
  stderr elsewhere;
* a row that crashes, exits another nonzero code or outlives its bound is one stderr line, never a block.

The dispatcher always exits 0: a block is its JSON answer, never an exit code.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import sys
import threading
import traceback
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, TextIO

from lab_commons.log import emit

from dev_lab.dev.agent_wiring import WIRING, Wire, WireRefused, declared, import_root

__all__ = ['Outcome', 'answer', 'main', 'run_row', 'selected']

#: Events whose plain stdout the tool hands the model as context.
_TEXT_IS_CONTEXT: Final = frozenset({'UserPromptSubmit', 'SessionStart'})
#: Events whose JSON answer carries ``hookSpecificOutput.additionalContext``.
_CONTEXT_EVENTS: Final = frozenset(
    {'PreToolUse', 'PostToolUse', 'PostToolUseFailure', 'UserPromptSubmit', 'SessionStart'}
)
#: A handler's refusing exit code (the tool's own convention).
_REFUSED: Final = 2
#: The sessions a ``once`` ledger keeps; older ones are forgotten.
_ONCE_KEPT: Final = 64


@dataclass(frozen=True, slots=True)
class Outcome:
    """What one row did: its exit code (``None``: outlived its bound), its stdout and its stderr."""

    wire: Wire
    code: int | None
    out: str
    err: str


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


def _repo_root(payload: dict[str, Any]) -> Path:
    """The checkout whose settings run this hook: ``$CLAUDE_PROJECT_DIR``, else the payload's ``cwd``."""
    return Path(os.environ.get('CLAUDE_PROJECT_DIR') or payload.get('cwd') or Path.cwd())


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
    """Run *wire* on payload *text* in a thread of its own, bounded by its timeout."""
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

    worker = threading.Thread(target=body, name=wire.name, daemon=True)
    worker.start()
    worker.join(wire.timeout if timeout is None else timeout)
    return Outcome(wire, done[0] if done else None, out.getvalue(), err.getvalue())


def _json(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


@dataclass(slots=True)
class _Merged:
    """The rows' answers, gathered: refusals, contexts, system messages and stderr notes."""

    event: str
    blocks: list[str] = field(default_factory=list)
    contexts: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def take(self, one: Outcome) -> None:
        name = one.wire.name
        if one.code == _REFUSED and one.wire.may_block:
            self.blocks.append(one.err.strip() or f'{name} refused')
            return
        if one.err:
            self.notes.append(one.err.rstrip('\n'))
        if one.code is None:
            self.notes.append(f'[hook] {name} outlived its {one.wire.timeout}s bound; passed')
        elif one.code:
            self.notes.append(f'[hook] {name} exited {one.code}; not a refusal, so it passed')
        elif (said := _json(one.out.strip())) is not None:
            self._said(name, said, may_block=one.wire.may_block)
        elif one.out.strip():
            (self.contexts if self.event in _TEXT_IS_CONTEXT else self.notes).append(one.out.strip())

    def _said(self, name: str, said: dict[str, Any], *, may_block: bool) -> None:
        specific = said.get('hookSpecificOutput') if isinstance(said.get('hookSpecificOutput'), dict) else {}
        refusal = said.get('reason') if said.get('decision') == 'block' else None
        if specific.get('permissionDecision') == 'deny':
            refusal = specific.get('permissionDecisionReason')
        if refusal is not None and not may_block:
            self.notes.append(f'[hook] {name} answered a refusal but is not wired may_block; passed: {refusal}')
        elif refusal is not None:
            self.blocks.append(str(refusal))
        if specific.get('additionalContext'):
            self.contexts.append(str(specific['additionalContext']))
        if said.get('systemMessage'):
            self.messages.append(str(said['systemMessage']))


def answer(event: str, outcomes: Sequence[Outcome]) -> tuple[str, str]:
    """``(stdout, stderr)`` of the dispatcher: the rows' answers merged into one."""
    merged = _Merged(event)
    for one in outcomes:
        merged.take(one)
    return _render(event, merged.blocks, merged.contexts, merged.messages), '\n'.join(merged.notes)


def _render(event: str, blocks: list[str], contexts: list[str], messages: list[str]) -> str:
    out: dict[str, Any] = {}
    if blocks and event == 'PreToolUse':
        reason = '\n'.join(blocks)
        out['hookSpecificOutput'] = {
            'hookEventName': event,
            'permissionDecision': 'deny',
            'permissionDecisionReason': reason,
        }
    elif blocks:
        out.update(decision='block', reason='\n'.join(blocks))
    if contexts and event in _CONTEXT_EVENTS:
        out.setdefault('hookSpecificOutput', {'hookEventName': event})['additionalContext'] = '\n'.join(contexts)
    else:
        messages = [*contexts, *messages]
    if messages:
        out['systemMessage'] = '\n'.join(messages)
    return json.dumps(out) if out else ''


def _ledger(payload: dict[str, Any]) -> Path | None:
    """The ``once`` ledger in the git dir of *payload*'s ``cwd``; ``None`` outside a checkout."""
    here = Path(str(payload.get('cwd') or Path.cwd()))
    for folder in (here, *here.parents):
        dot = folder / '.git'
        if dot.is_dir():
            return dot / 'dev-lab-hook-once.json'
        if dot.is_file():
            line = dot.read_text(encoding='utf-8').strip()
            if line.startswith('gitdir:'):
                return (folder / line.removeprefix('gitdir:').strip()) / 'dev-lab-hook-once.json'
    return None


def _first_runs(wires: Sequence[Wire], payload: dict[str, Any]) -> tuple[Wire, ...]:
    """*wires* without the ``once`` rows this session already ran; records the ones it runs now."""
    session = str(payload.get('session_id') or '')
    ledger = _ledger(payload) if session and any(wire.once for wire in wires) else None
    if ledger is None:
        return tuple(wires)
    try:
        seen: dict[str, list[str]] = json.loads(ledger.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        seen = {}
    ran = set(seen.get(session, ()))
    keep = tuple(wire for wire in wires if not (wire.once and wire.name in ran))
    seen[session] = sorted(ran | {wire.name for wire in keep if wire.once})
    with contextlib.suppress(OSError):
        ledger.write_text(json.dumps(dict(list(seen.items())[-_ONCE_KEPT:])), encoding='utf-8')
    return keep


def main(argv: list[str] | None = None) -> int:
    """``python -m dev_lab.dev.hookdispatch <Event>``: run the event's rows on the payload on stdin; always exit 0."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        emit('usage: python -m dev_lab.dev.hookdispatch <Event>', err=True)
        return 0
    event = args[0]
    text = sys.stdin.read()
    payload = _json(text) or {}
    root = _repo_root(payload)
    mine, refused = _repo_wires(root)
    wires = _first_runs(selected(event, payload, (*WIRING, *mine)), payload)
    streams = (sys.stdin, sys.stdout, sys.stderr)
    sys.stdin, sys.stdout, sys.stderr = (_Routed(stream) for stream in streams)
    with import_root(root) if mine else contextlib.nullcontext():
        outcomes = [run_row(wire, text) for wire in wires]
    if all(one.code is not None for one in outcomes):  # a row still running keeps writing into its own buffer
        sys.stdin, sys.stdout, sys.stderr = streams
    said, notes = answer(event, outcomes)
    notes = '\n'.join(line for line in (refused, notes) if line)
    if notes:
        emit(notes, err=True)
    if said:
        emit(said)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
