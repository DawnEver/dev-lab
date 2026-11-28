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
  recorded (an issue, a memory task); the line names which;
* :func:`standby` -- the forge door's record of a standby this session posted (:mod:`dev_lab.dev.standby`): while
  the latest is newer than the checkout's last commit, the session is at rest and ``walls stop`` neither blocks nor
  nags (STANDBY-IS-RESTING, v1 ruling D218).

A line never holds the command: only a sha256 prefix of it (:data:`DIGEST_CHARS`), because a refused command is
exactly the one that may carry a token. It keeps the refusal's CAUSE line instead (:func:`cause_line`: the first line
of what the agent was shown, token- and address-shaped runs masked, capped), so a gap can be read afterwards (#825).
WHERE: ``<checkout>/output/logs/<yy>/<mm>/<dd>/walls/walls.jsonl``, the main worktree's, beside the
metrics, appended one whole line per ``O_APPEND`` write.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, TextIO

from lab_commons.log import emit

from dev_lab.dev import metrics
from dev_lab.dev.datedlog import date_parts
from dev_lab.dev.disclosure import DETAILS_PREFIX
from dev_lab.dev.native_session import session_of
from dev_lab.dev.storage import output_path
from dev_lab.dev.venvpath import running_interpreter

__all__ = [
    'CAUSE_CHARS',
    'DIGEST_CHARS',
    'HARNESS_PERMISSION',
    'LOG_KIND',
    'RULE',
    'UNNAMED',
    'cause_line',
    'close',
    'digest',
    'has_remedy',
    'hook_rule',
    'ledger',
    'main',
    'open_walls',
    'record',
    'refused',
    'refused_text',
    'resting',
    'rule_of',
    'standby',
]

RULE: Final = 'WALLS-ARE-RECORDED'
LOG_KIND: Final = 'walls'
#: The rule of a denial from the harness's permission layer (a classifier, a declined prompt), which names none.
HARNESS_PERMISSION: Final = 'HARNESS-PERMISSION'
#: The prefix of a denial that names no rule: ``UNNAMED-<DOOR>`` when a door printed it, else ``UNNAMED-REFUSAL``.
#: Measured 2026-11-14/15: such walls were recorded as rule 'unknown', which no reader could act on.
UNNAMED: Final = 'UNNAMED'
_HARNESS: Final = re.compile(
    r"(?i)permission to use \S+ (?:has been|was) denied|doesn't want to proceed|tool use was rejected"
)
#: A door's own refusal line, ``box: refused -- ...``: the door is the word before the colon.
_DOOR: Final = re.compile(r'(?im)^\s*([a-z][\w.-]*):\s+(?:refused|denied|blocked)\b')
#: Hex characters of a command's sha256 kept on a line: enough to tell two commands apart, never the command.
DIGEST_CHARS: Final = 16
#: A tool's error text that is a REFUSAL rather than an ordinary failure.
_DENIAL: Final = re.compile(r'(?i)\b(?:hook error|denied|refused|blocked|not permitted|not allowed)\b')
#: A refusal line as the deny engine and the refusal printers emit one: ``<RULE-ID>: ...`` at the start of a line,
#: after the harness's ``<Event>:<Tool> hook error:`` prefix if any. An id anywhere else is tool OUTPUT (a grep hit,
#: quoted source) and names no wall -- measured: a docstring in grep output was recorded as a wall.
_RULE_LINE: Final = re.compile(r'(?m)^(?:\w+:\w+ hook error:\s*)?([A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+):')
#: The harness's first line of a failed shell call, before the program's own text.
_EXIT_LINE: Final = re.compile(r'^Exit code -?\d+[^\n]*\n?')
#: The harness's own wrapper of a hook's refusal: a refusal whatever its body names.
_HOOK_ERROR: Final = re.compile(r'(?m)^\w+:\w+ hook error:')
#: A refusal that names a door has at least its cause line and its door line.
_CAUSE_AND_DOOR: Final = 2
#: The engine's header when a command targets another checkout: context, not the cause or the door.
_TARGET_HEADER: Final = re.compile(r'^\[targets .*\]$')
#: A hook's refusal line naming its rule, ``[REFUSED: ]<RULE-ID>: ...``: the rule a hook row's wall is recorded as.
_HOOK_RULE_LINE: Final = re.compile(r'(?m)^\s*(?:REFUSED:\s*)?([A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+):')
#: The longest cause line kept; a refusal's cause is one sentence, a longer line is output.
CAUSE_CHARS: Final = 240
#: The most the stop hook waits on git for the last commit's time (HOOK-UNDER-FIVE-SECONDS).
_GIT_TIMEOUT_S: Final = 3.0
#: Masked in a cause line: address-shaped and token-shaped runs (crude by design: a precise redactor misses).
_ADDRESS: Final = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
#: A token carries a digit and a lower-case letter; an upper-case RULE-ID of any length is never one.
_TOKEN: Final = re.compile(r'\b(?:Bearer\s+)?(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[a-z])[A-Za-z0-9_-]{24,}\b')


def ledger(root: Path, day: tuple[str, str, str] | None = None) -> Path:
    """``<output kind>/logs/<yy>/<mm>/<dd>/walls/walls.jsonl`` for *day* (today); ``'*'`` parts glob."""
    return _logs(metrics.checkout(root)).joinpath(*(day or date_parts()), LOG_KIND, f'{LOG_KIND}.jsonl')


def _logs(checkout: Path) -> Path:
    """The dated-log root of *checkout*: its ``output`` storage kind (bound or in-tree), then ``logs``."""
    return output_path(checkout, *metrics.BASE.parts)


def digest(command: str) -> str:
    """A sha256 prefix of *command*: the ledger's only trace of it."""
    return hashlib.sha256(command.encode('utf-8')).hexdigest()[:DIGEST_CHARS]


def has_remedy(text: str) -> bool:
    """Whether a refusal names a door: a line beyond its cause that is not only the ``details:`` pointer."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    lines = [line for line in lines if not line.startswith(DETAILS_PREFIX) and not _TARGET_HEADER.match(line)]
    return len(lines) >= _CAUSE_AND_DOOR


def cause_line(text: str) -> str:
    """The first line of *text* past the harness's ``Exit code N`` and hook prefixes, redacted and capped.

    What a refusal or failure SAID, kept so a wall can be read afterwards (#825); an address or a token-shaped run
    becomes a fixed marker, never the value.
    """
    for raw in _EXIT_LINE.sub('', text.lstrip(), count=1).splitlines():
        line = _HOOK_ERROR.sub('', raw).strip()
        if line and not _TARGET_HEADER.match(line):
            masked = _TOKEN.sub('<redacted>', _ADDRESS.sub('<address>', line))
            return masked[:CAUSE_CHARS]
    return ''


def hook_rule(hook_id: str, output: str, declared: str = '') -> str:
    """The rule a failed hook row's wall is: the rule its refusal line names, else *declared*, else *hook_id*.

    A row's id is a table key (``milestone-base``), not a rule; the refusal it prints names the rule
    (``BASE-HOLDS-THE-MILESTONE``), which is what a reader looks up (#870).
    """
    found = _HOOK_RULE_LINE.search(output)
    return found.group(1) if found else (declared or hook_id)


def _session(session: str | None) -> str:
    return session if session is not None else session_of()


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
    root: Path,
    *,
    rule: str,
    remedy: bool,
    command: str = '',
    command_sha256: str = '',
    cause: str = '',
    session: str | None = None,
) -> Path:
    """Append one wall *rule* (a refused *command*'s digest, its *cause* line) for *session*; the ledger file."""
    return _append(
        root,
        {
            'ts': _now(),
            'session': _session(session),
            'rule': rule or f'{UNNAMED}-REFUSAL',
            'command_sha256': command_sha256 or (digest(command) if command else ''),
            'cause': cause_line(cause),
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
    cause: str = '',
    session: str | None = None,
) -> Path:
    """THE refusal choke point: the metrics refusal line and the ledger's wall, in one call; the ledger file."""
    metrics.record(metrics.REFUSAL, root=root, repo=repo, rule=rule, reason=reason)
    return record(
        root, rule=rule, remedy=remedy, command=command, command_sha256=command_sha256, cause=cause, session=session
    )


def rule_of(text: str) -> str:
    """The rule a denial *text* names; else its source: :data:`HARNESS_PERMISSION`, or ``UNNAMED-<DOOR|REFUSAL>``."""
    if found := _RULE_LINE.search(text):
        return found.group(1)
    if _HARNESS.search(text):
        return HARNESS_PERMISSION
    door = _DOOR.search(text)
    return f'{UNNAMED}-{door.group(1).upper().replace(".", "-").replace("_", "-") if door else "REFUSAL"}'


def refused_text(root: Path, text: str, *, reason: str, rule: str = '', session: str | None = None) -> Path:
    """A family refusal's *text* through :func:`refused`: its *rule* (else the first rule id it names) and remedy.

    The remedy is :func:`has_remedy` of the text the agent was shown, the same test every refusal path takes.
    """
    named = rule or rule_of(text)
    return refused(
        root,
        repo=metrics.repo_of(root),
        rule=named,
        reason=reason,
        remedy=has_remedy(text),
        cause=text,
        session=session or None,
    )


def close(root: Path, *, rule: str, by: str, session: str | None = None) -> Path:
    """Record that *rule*'s gap is closed or recorded *by* a commit, an issue or a path; the ledger file."""
    if not by.strip():
        msg = 'a closure names what closed or recorded the gap: a commit, an issue or a path'
        raise ValueError(msg)
    return _append(root, {'ts': _now(), 'session': _session(session), 'rule': rule, 'closed_by': by.strip()})


def standby(root: Path, *, issue: str, session: str | None = None) -> Path:
    """Record that *session* posted a standby on *issue* (its URL) now; the ledger file."""
    return _append(root, {'ts': _now(), 'session': _session(session), 'standby': issue})


def _last_commit(cwd: Path) -> datetime | None:
    """The committer time of *cwd*'s HEAD, or ``None`` when no commit is readable."""
    try:
        done = subprocess.run(
            [shutil.which('git') or 'git', '-C', str(cwd), 'log', '-1', '--format=%cI'],
            capture_output=True, text=True, encoding='utf-8', check=False, timeout=_GIT_TIMEOUT_S,
        )  # fmt: skip
        return datetime.fromisoformat(done.stdout.strip()) if done.returncode == 0 and done.stdout.strip() else None
    except OSError, subprocess.TimeoutExpired, ValueError:
        return None


def resting(root: Path, session: str) -> bool:
    """Whether *session*'s latest posted standby is newer than the last commit at *root* (STANDBY-IS-RESTING)."""
    posted = [str(line['ts']) for line in _read(root, session) if line.get('session') == session and 'standby' in line]
    if not posted:
        return False
    commit = _last_commit(root)
    return commit is None or datetime.fromisoformat(max(posted)) > commit


def _dirs(path: Path) -> list[Path]:
    try:
        return sorted(Path(entry.path) for entry in os.scandir(path) if entry.is_dir())
    except OSError:
        return []


def _ledgers(base: Path) -> list[Path]:
    """Every day's ledger under checkout *base*, oldest first: the date levels listed, one stat per day.

    Never a glob: it lists every kind's directory of every day, and measured 2026-11-17 it took 0.3-0.5 s of the Stop
    hook over five ledgers on a workstation.
    """
    days = (day for year in _dirs(_logs(base)) for month in _dirs(year) for day in _dirs(month))
    return [path for day in days if (path := day / LOG_KIND / f'{LOG_KIND}.jsonl').is_file()]


def _read(root: Path, session: str) -> list[dict[str, object]]:
    """Every ledger line of *session*, every day; a line not naming it is never parsed (the ledger only grows)."""
    found: list[dict[str, object]] = []
    for path in _ledgers(metrics.checkout(root)):
        for raw in path.read_text(encoding='utf-8', errors='replace').splitlines():
            if session not in raw:
                continue
            try:
                found.append(json.loads(raw))
            except ValueError:
                continue  # a torn tail after a crash
    return found


def open_walls(root: Path, session: str) -> tuple[str, ...]:
    """The rules of *session*'s walls with no remedy that no later closure answers, first seen first."""
    still: dict[str, None] = {}
    for line in _read(root, session):
        if line.get('session') != session:
            continue
        rule = str(line.get('rule', ''))
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


def _leads_with_rule(text: str) -> bool:
    """Whether *text*'s first line, past the harness's ``Exit code N``, is a rule line: a refusal leads its text.

    MEASURED 2026-11-17: test and lint output QUOTING a rule (an assertion message, a refusal under test) was recorded
    three times as an unremedied wall of a rule that did refuse nothing; a rule line deeper in the text is output.
    """
    return bool(_RULE_LINE.match(_EXIT_LINE.sub('', text.lstrip(), count=1).lstrip()))


def _is_refusal(text: str) -> bool:
    """Whether *text* carries a refusal LINE (a hook, harness or door line, or a leading rule line), not output."""
    if not _DENIAL.search(text):
        return False
    return _leads_with_rule(text) or any(pattern.search(text) for pattern in (_HOOK_ERROR, _HARNESS, _DOOR))


def _family_lines(text: str) -> str:
    """*text* with a family refusal's lines restored, its ``details:`` pointer at a line start.

    A harness that escapes newlines or runs the pointer into the line before it (a Write-tool denial, #997) hid it.
    """
    return re.sub(r'[ \t]+(?=' + re.escape(DETAILS_PREFIX) + r')', '\n', text.replace('\\n', '\n'))


def _post_tool(payload: dict) -> None:
    text = _family_lines(_error_text(payload))
    if not _is_refusal(text) or any(line.lstrip().startswith(DETAILS_PREFIX) for line in text.splitlines()):
        return
    command = (payload.get('tool_input') or {}).get('command') or ''
    record(
        Path(payload.get('cwd') or Path.cwd()),
        rule=rule_of(text),
        remedy=False,
        command=str(command),
        cause=text,
        session=str(payload.get('session_id') or ''),
    )


def _stop(payload: dict) -> dict[str, str] | None:
    if payload.get('stop_hook_active'):
        return None
    session = str(payload.get('session_id') or '')
    root = Path(payload.get('cwd') or Path.cwd())
    if resting(root, session):
        return None  # STANDBY-IS-RESTING: a posted standby newer than the last commit is a resting state
    found = open_walls(root, session)
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
    one.add_argument('--cause', default='', help="the refusal's cause line (redacted and capped on the way in)")
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
            command_sha256=args.command_sha256, cause=args.cause, session=args.session,
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
