"""WALLS-ARE-RECORDED: every refusal is one ledger line; a wall that named no door holds the stop until closed.

The loop this serves is ``docs-src/dev/feedback.md``.

Principle ``every-wall-teaches`` (user ruling 2026-11-13): a refusal or failure names its cause and its door; one
that does not is a mechanism gap. A gap nobody records is met again next session, so this module RECORDS:

* :func:`refused` -- THE refusal choke point: one :mod:`dev_lab.dev.metrics` refusal line (the baseline's
  count) and one ledger line (this session's wall). The agent-guard engine reaches it as ``walls refused``, the
  git hook runner calls it, and every family hook or CLI that refuses with a TEXT goes through
  :func:`refused_text`, so no refusal path writes either log on its own;
* ``walls post-tool`` -- a ``PostToolUse``/``PostToolUseFailure`` hook: a denial in a tool's error text that
  carries no family ``details:`` pointer (a classifier, a tool's own refusal) is a wall NO family emit path saw,
  recorded with no remedy;
* ``walls stop`` -- the ``Stop``/``SubagentStop`` hook: while this session's ledger holds a wall with no remedy
  that no ``walls close`` line answers, the stop is refused ONCE, naming the walls and the gap loop;
* ``walls close --rule R --by <sha|issue|path>`` -- the gap is closed (a row, a remedy, a test committed) or
  recorded (an issue, a memory task); the line names which.

A line never holds the command: only a sha256 prefix of it (:data:`DIGEST_CHARS`), because a refused command is
exactly the one that may carry a token. WHERE: ``<checkout>/output/logs/<yy>/<mm>/<dd>/walls/walls.jsonl``,
the main worktree's, beside the metrics, appended one whole line per ``O_APPEND`` write.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, TextIO

from lab_commons.log import emit

from dev_lab.dev import metrics
from dev_lab.dev.datedlog import date_parts
from dev_lab.dev.disclosure import DETAILS_PREFIX
from dev_lab.dev.venvpath import running_interpreter

__all__ = [
    'DIGEST_CHARS',
    'LOG_KIND',
    'RULE',
    'UNKNOWN',
    'close',
    'digest',
    'has_remedy',
    'ledger',
    'main',
    'open_walls',
    'record',
    'refused',
    'refused_text',
]

RULE: Final = 'WALLS-ARE-RECORDED'
LOG_KIND: Final = 'walls'
#: The rule a denial names when it names none: the classifier's, or a tool's own.
UNKNOWN: Final = 'unknown'
#: Hex characters of a command's sha256 kept on a line: enough to tell two commands apart, never the command.
DIGEST_CHARS: Final = 16
#: The tool's own session id, in the environment of every command an agent runs (a git hook's included).
SESSION_ENV: Final = 'CLAUDE_CODE_SESSION_ID'

#: A tool's error text that is a REFUSAL rather than an ordinary failure.
_DENIAL: Final = re.compile(r'(?i)\b(?:hook error|denied|refused|blocked|not permitted|not allowed)\b')
#: A rule id as the family spells one (``WORKTREES-STAY-INSIDE``).
_RULE_ID: Final = re.compile(r'\b[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+\b')
#: A refusal that names a door has at least its cause line and its door line.
_CAUSE_AND_DOOR: Final = 2
#: The engine's header when a command targets another checkout: context, not the cause or the door.
_TARGET_HEADER: Final = re.compile(r'^\[targets .*\]$')


def ledger(root: Path, day: tuple[str, str, str] | None = None) -> Path:
    """``<checkout>/output/logs/<yy>/<mm>/<dd>/walls/walls.jsonl`` for *day* (today); ``'*'`` parts glob."""
    return metrics.checkout(root).joinpath(metrics.BASE, *(day or date_parts()), LOG_KIND, f'{LOG_KIND}.jsonl')


def digest(command: str) -> str:
    """A sha256 prefix of *command*: the ledger's only trace of it."""
    return hashlib.sha256(command.encode('utf-8')).hexdigest()[:DIGEST_CHARS]


def has_remedy(text: str) -> bool:
    """Whether a refusal names a door: a line beyond its cause that is not only the ``details:`` pointer."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    lines = [line for line in lines if not line.startswith(DETAILS_PREFIX) and not _TARGET_HEADER.match(line)]
    return len(lines) >= _CAUSE_AND_DOOR


def _session(session: str | None) -> str:
    return session if session is not None else os.environ.get(SESSION_ENV, '')


def _append(root: Path, line: dict[str, object]) -> Path:
    target = ledger(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps(line, sort_keys=True) + '\n').encode('utf-8'))
        os.fsync(fd)
    finally:
        os.close(fd)
    return target


def _now() -> str:
    return datetime.now(UTC).isoformat()


def record(
    root: Path, *, rule: str, remedy: bool, command: str = '', command_sha256: str = '', session: str | None = None
) -> Path:
    """Append one wall *rule* (a refused *command*, or its digest) for *session* (the tool's); the ledger file."""
    return _append(
        root,
        {
            'ts': _now(),
            'session': _session(session),
            'rule': rule or UNKNOWN,
            'command_sha256': command_sha256 or (digest(command) if command else ''),
            'remedy_present': remedy,
        },
    )


def refused(
    root: Path,
    *,
    repo: str,
    rule: str,
    reason: str,
    remedy: bool,
    command: str = '',
    command_sha256: str = '',
    session: str | None = None,
) -> Path:
    """THE refusal choke point: the metrics refusal line and the ledger's wall, in one call; the ledger file."""
    metrics.record(metrics.REFUSAL, root=root, repo=repo, rule=rule, reason=reason)
    return record(root, rule=rule, remedy=remedy, command=command, command_sha256=command_sha256, session=session)


def refused_text(root: Path, text: str, *, reason: str, rule: str = '', session: str | None = None) -> Path:
    """A family refusal's *text* through :func:`refused`: its *rule* (else the first rule id it names) and remedy.

    The remedy is :func:`has_remedy` of the text the agent was shown, the same test every refusal path takes.
    """
    named = rule or ((found := _RULE_ID.search(text)) and found.group(0)) or UNKNOWN
    return refused(
        root, repo=metrics.repo_of(root), rule=named, reason=reason, remedy=has_remedy(text), session=session or None
    )


def close(root: Path, *, rule: str, by: str, session: str | None = None) -> Path:
    """Record that *rule*'s gap is closed or recorded *by* a commit, an issue or a path; the ledger file."""
    if not by.strip():
        msg = 'a closure names what closed or recorded the gap: a commit, an issue or a path'
        raise ValueError(msg)
    return _append(root, {'ts': _now(), 'session': _session(session), 'rule': rule, 'closed_by': by.strip()})


def _read(root: Path) -> list[dict[str, object]]:
    base = metrics.checkout(root)
    found: list[dict[str, object]] = []
    for path in sorted(base.glob(ledger(base, ('*', '*', '*')).relative_to(base).as_posix())):
        for raw in path.read_text(encoding='utf-8').splitlines():
            try:
                found.append(json.loads(raw))
            except ValueError:
                continue  # a torn tail after a crash
    return found


def open_walls(root: Path, session: str) -> tuple[str, ...]:
    """The rules of *session*'s walls with no remedy that no later closure answers, first seen first."""
    still: dict[str, None] = {}
    for line in _read(root):
        if line.get('session') != session:
            continue
        rule = str(line.get('rule') or UNKNOWN)
        if 'closed_by' in line:
            still.pop(rule, None)
        elif line.get('remedy_present') is False:
            still[rule] = None
    return tuple(still)


def _error_text(payload: dict) -> str:
    said = payload.get('error')
    if isinstance(said, str):
        return said
    response = payload.get('tool_response')
    if isinstance(response, dict):
        return str(response.get('stderr') or '')
    return response if isinstance(response, str) else ''


def _post_tool(payload: dict) -> None:
    text = _error_text(payload)
    if not _DENIAL.search(text) or any(line.startswith(DETAILS_PREFIX) for line in text.splitlines()):
        return
    named = _RULE_ID.search(text)
    command = (payload.get('tool_input') or {}).get('command') or ''
    record(
        Path(payload.get('cwd') or Path.cwd()),
        rule=named.group(0) if named else UNKNOWN,
        remedy=False,
        command=str(command),
        session=str(payload.get('session_id') or ''),
    )


def _stop(payload: dict) -> dict[str, str] | None:
    if payload.get('stop_hook_active'):
        return None
    session = str(payload.get('session_id') or '')
    found = open_walls(Path(payload.get('cwd') or Path.cwd()), session)
    if not found:
        return None
    return {
        'decision': 'block',
        'reason': f'{RULE}: this session hit walls that named no door: {", ".join(found)}. '
        'close the gap: add the row/remedy, or record the gap (an issue, a task); then '
        f'{running_interpreter()} -m dev_lab.dev.walls close --rule {found[0]} --by <sha|issue|path> '
        '(docs-src/dev/feedback.md).',
    }


def _hook(verb: str, stdin: TextIO | None, out: TextIO | None) -> int:
    try:
        payload = json.load(stdin or sys.stdin)
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    if verb == 'post-tool':
        _post_tool(payload)
        return 0
    answer = _stop(payload)
    if answer is not None:
        (out.write(json.dumps(answer)) if out is not None else emit(json.dumps(answer)))
    return 0


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None, out: TextIO | None = None) -> int:
    """``python -m dev_lab.dev.walls refused|close|post-tool|stop``; the hooks always exit 0."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.walls', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    one = verbs.add_parser('refused', help='record one refusal (the agent-guard engine calls this)')
    one.add_argument('--rule', required=True)
    one.add_argument('--reason', default='')
    one.add_argument('--repo', default='')
    one.add_argument('--command-sha256', default='')
    one.add_argument('--remedy', action=argparse.BooleanOptionalAction, required=True)
    one.add_argument('--session', default=None)
    shut = verbs.add_parser('close', help="record that a wall's gap is closed or recorded")
    shut.add_argument('--rule', required=True)
    shut.add_argument('--by', required=True, help='the commit, issue or path that closed or recorded the gap')
    shut.add_argument('--session', default=None)
    verbs.add_parser('post-tool', help='the PostToolUse hook: record a foreign denial')
    verbs.add_parser('stop', help='the Stop hook: refuse once over a wall that named no door')
    args = parser.parse_args(argv)
    root = Path.cwd()
    if args.verb == 'refused':
        refused(
            root, repo=args.repo or metrics.repo_of(root), rule=args.rule, reason=args.reason, remedy=args.remedy,
            command_sha256=args.command_sha256, session=args.session,
        )  # fmt: skip
        return 0
    if args.verb == 'close':
        try:
            close(root, rule=args.rule, by=args.by, session=args.session)
        except ValueError as exc:
            parser.error(str(exc))
        return 0
    return _hook(args.verb, stdin, out)


if __name__ == '__main__':
    raise SystemExit(main())
