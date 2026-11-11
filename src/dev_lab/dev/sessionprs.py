"""SESSION-HEARS-ITS-PRS, the record: every pull request a session opened or pushed, across every repository.

User ruling 2026-11-11: lab-commons #158 went red and the session heard nothing, because the push journal
(:mod:`dev_lab.dev.pushwatch`) lives in ONE checkout's git dir while a session works in many. So this record
lives in the machine home (:func:`lab_commons.home.home`), one file per session -- ``sessions/<id>.json`` --
and holds one row per PR, keyed ``<host>/<owner>/<repo>#<number>``, or ``...@<branch>`` while a pushed
branch's PR number is not yet known (:func:`resolve` renames it once the forge names one):

* ``forge pr create``, seen by the ``PostToolUse`` hook, records the PR its output names (:func:`record_pr`);
* a push, seen by the same hook, records the branch and its head (:func:`record_push`);
* ``forge watch --session <id> --stream`` (:mod:`dev_lab.dev.forgewatch`) reads it, and marks a PR
  ``merged``/``closed`` once it has said so (:func:`close`), so a merge is reported once;
* ``forge watch --session <id> --ack <key> --reason <why>`` records why a red head may stand (:func:`ack`);
  a newer head is not covered by an older head's reason.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, TextIO

import lab_commons.launch as _door
from lab_commons import home as _home
from lab_commons.log import emit

from dev_lab.dev.forge import Forge, UnreadableRemote, forge_from_remote
from dev_lab.dev.pushwatch import pushed_sha, pushed_target
from dev_lab.dev.venvpath import running_interpreter

__all__ = [
    'RULE',
    'Row',
    'ack',
    'close',
    'main',
    'open_rows',
    'opened_pr',
    'pr_of_url',
    'record_pr',
    'record_push',
    'recorded_push',
    'resolve',
    'rows',
    'valid',
    'watch_session_command',
]

_GIT: Final = shutil.which('git') or 'git'

#: The rule this record serves (``dev_lab.dev.rules``).
RULE: Final = 'SESSION-HEARS-ITS-PRS'

#: The directory, under the machine home, holding one record per session.
SESSIONS: Final = 'sessions'

#: A session id is a file name here: anything else is refused rather than escaped.
_SESSION: Final = re.compile(r'^[\w.-]{1,128}$')

#: A pull request's web URL on either forge: ``https://<host>/<owner>/<repo>/pull[s]/<n>``.
_PR_URL: Final = re.compile(r'https?://(?P<host>[^/\s]+)/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/pulls?/(?P<n>\d+)\b')


@dataclass(frozen=True)
class Row:
    """One PR of the session: its repository, branch, number (0 while unknown), last head, end and acks."""

    forge: Forge
    branch: str = ''
    number: int = 0
    sha: str = ''
    at: float = 0.0
    #: ``merged`` or ``closed`` once the watch reported it; ``''`` while open.
    done: str = ''
    #: ``{head sha: reason}``: a red on that head the session recorded as standing on purpose.
    acks: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """``<host>/<owner>/<repo>#<number>``, or ``@<branch>`` while the number is unknown."""
        return f'{self.forge.identity}#{self.number}' if self.number else f'{self.forge.identity}@{self.branch}'


def watch_session_command(session: str) -> str:
    """The command reporting every change on *session*'s PRs until none is open (run it as a ``Monitor``)."""
    return f'{running_interpreter()} -m dev_lab.dev.forge watch --session {session} --stream'


def valid(session: str) -> bool:
    """Whether *session* is an id this record keeps a file for."""
    return bool(_SESSION.match(session))


def _path(session: str) -> Path | None:
    return _home.home() / SESSIONS / f'{session}.json' if valid(session) else None


def _row(raw: dict) -> Row | None:
    try:
        forge = Forge(str(raw['host']), str(raw['owner']), str(raw['repo']))
        acks = {str(sha): str(why) for sha, why in dict(raw.get('acks') or {}).items()}
        return Row(forge, str(raw.get('branch') or ''), int(raw.get('number') or 0), str(raw.get('sha') or ''),
                   float(raw.get('at') or 0.0), str(raw.get('done') or ''), acks)  # fmt: skip
    except (KeyError, TypeError, ValueError):
        return None


def rows(session: str) -> dict[str, Row]:
    """Every PR *session* recorded, by key; empty for an unknown session or an unreadable file."""
    path = _path(session)
    try:
        table = json.loads(path.read_text(encoding='utf-8')) if path is not None else {}
    except (OSError, ValueError):
        return {}
    found = (_row(raw) for raw in table.values() if isinstance(raw, dict)) if isinstance(table, dict) else ()
    return {row.key: row for row in found if row is not None}


def open_rows(session: str) -> tuple[Row, ...]:
    """The session's PRs not yet reported merged or closed, by key."""
    return tuple(row for _, row in sorted(rows(session).items()) if not row.done)


def _save(session: str, table: dict[str, Row]) -> None:
    path = _path(session)
    if path is None:
        return
    data = {
        key: {'host': row.forge.host, 'owner': row.forge.owner, 'repo': row.forge.repo, 'branch': row.branch,
              'number': row.number, 'sha': row.sha, 'at': row.at, 'done': row.done, 'acks': row.acks}
        for key, row in table.items()
    }  # fmt: skip
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True), encoding='utf-8')


def _put(session: str, row: Row, *, drop: str = '') -> Row:
    table = {key: one for key, one in rows(session).items() if key != drop}
    table[row.key] = row
    _save(session, table)
    return row


def pr_of_url(text: str) -> tuple[Forge, int] | None:
    """The repository and number of the first PR URL in *text*, or ``None``."""
    found = _PR_URL.search(text)
    if found is None:
        return None
    return Forge(found['host'], found['owner'], found['repo'].removesuffix('.git')), int(found['n'])


def record_pr(session: str, forge: Forge, number: int, *, branch: str = '', sha: str = '') -> Row | None:
    """Record that *session* opened PR *number* of *forge* (from *branch*); a branch row it was becomes it."""
    if not valid(session):
        return None
    table = rows(session)
    pending = Row(forge, branch).key
    before = table.get(Row(forge, branch, number).key) or table.get(pending)
    acks = before.acks if before is not None else {}
    head = sha or (before.sha if before is not None else '')
    return _put(session, Row(forge, branch, number, head, time.time(), '', acks), drop=pending if branch else '')


def record_push(session: str, forge: Forge, branch: str, sha: str, *, at: float | None = None) -> Row | None:
    """Record that *session* pushed *sha* as *branch* of *forge*: its PR's row when known, else a branch row.

    A push of a PR the watch already reported merged or closed opens nothing: a new PR is recorded by number.
    """
    if not valid(session) or not branch:
        return None
    when = time.time() if at is None else at
    for row in rows(session).values():
        if row.forge == forge and row.branch == branch and row.number and not row.done:
            return _put(session, Row(forge, branch, row.number, sha, when, '', row.acks))
    return _put(session, Row(forge, branch, 0, sha, when))


def resolve(session: str, row: Row, number: int) -> Row:
    """*row* (a branch row) as the PR *number* the forge names for its branch."""
    return _put(session, Row(row.forge, row.branch, number, row.sha, row.at, row.done, row.acks), drop=row.key)


def close(session: str, row: Row, done: str) -> Row:
    """Mark *row* ``merged`` or ``closed``: it is reported once, and no longer watched or blocked on."""
    return _put(session, Row(row.forge, row.branch, row.number, row.sha, row.at, done, row.acks))


def ack(session: str, row: Row, sha: str, reason: str) -> Row:
    """Record *reason* for letting the red on *row*'s head *sha* stand; a newer head is judged afresh."""
    return _put(session, Row(row.forge, row.branch, row.number, row.sha, row.at, row.done, {**row.acks, sha: reason}))


#: ``forge pr create`` on a shell line, through any interpreter.
_PR_CREATE: Final = re.compile(r'-m\s+dev_lab\.dev\.forge\s+pr\s+create\b(?P<rest>[^\n;&|]*)')


def opened_pr(command: str, response: str, session: str) -> str | None:
    """Record the PR ``forge pr create`` *command* opened, read from *response*; the line to arm a watch.

    ``None`` when *command* opened no PR.
    """
    found = _PR_CREATE.search(command)
    named = pr_of_url(response) if found is not None else None
    if named is None:
        return None
    try:
        words = shlex.split(found['rest'])
    except ValueError:
        words = []
    head = words[words.index('--head') + 1] if '--head' in words[:-1] else ''
    if record_pr(session, *named, branch=head) is None:
        return None
    return (
        f"{RULE}: {named[0].identity}#{named[1]} is recorded as this session's; arm ONE persistent "
        f'Monitor on every PR of the session (it ends when none is open): {watch_session_command(session)}'
    )


def _git(root: Path, *args: str) -> str:
    done = _door.run([_GIT, '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8', check=False)
    return done.stdout.strip() if done.returncode == 0 else ''


def recorded_push(root: Path, command: str, session: str) -> Row | None:
    """Record the branch and head shell *command*, run in *root*, pushed; ``None`` for no push or no forge."""
    target = pushed_target(root, command) if valid(session) else None
    if target is None:
        return None
    where, ref, destination = target
    sha = pushed_sha(where, ref)
    if not sha:
        return None
    try:
        forge = forge_from_remote(where)
    except UnreadableRemote:
        return None
    branch = destination or (_git(where, 'rev-parse', '--abbrev-ref', ref) if ref == 'HEAD' else ref)
    return record_push(session, forge, branch.removeprefix('refs/heads/'), sha)


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """The ``PostToolUse`` hook on the shell tools: record a push or an opened PR; never blocks, always 0."""
    del argv
    try:
        payload = json.load(stdin or sys.stdin)
    except ValueError:
        return 0
    tool_input = payload.get('tool_input') if isinstance(payload, dict) else None
    command = tool_input.get('command') if isinstance(tool_input, dict) else None
    session = str(payload.get('session_id') or '')
    if not isinstance(command, str) or not valid(session):
        return 0
    try:
        recorded_push(Path(payload.get('cwd') or Path.cwd()), command, session)
        said = opened_pr(command, json.dumps(payload.get('tool_response') or ''), session)
    except OSError:
        return 0
    if said is not None:
        emit(json.dumps({'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext': said}}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
