"""SESSION-HEARS-ITS-PRS, the record: every pull request a session opened or pushed, across every repository.

User ruling 2026-11-11: lab-commons #158 went red and the session heard nothing, because the push journal
(:mod:`dev_lab.dev.pushwatch`) lives in ONE checkout's git dir while a session works in many. So this record
lives in the machine home (:func:`lab_commons.home.home`), one file per session -- ``sessions/<id>.json`` --
and holds one row per PR, keyed ``<host>/<owner>/<repo>#<number>``, or ``...@<branch>`` while a pushed
branch's PR number is not yet known (:func:`resolve` renames it once the forge names one).

THE DOOR THAT ACTS RECORDS (2026-11-12: a hook scraping the shell line missed a second create, a create whose
output was piped away, and a push after ``cd`` into another repository -- all silently):

* the one door that OPENS a PR (``forgework.Client.pr_create``) records it with the number the forge returned
  (:func:`record_opened`);
* a push records itself where it RAN: the family ``pre-push`` row ``session-prs`` reads git's own ref lines in
  the repository git is pushing (:func:`record_pushed`);
* the session is :data:`SESSION_ENV`; absent or invalid, nothing is recorded;
* the ``PostToolUse`` hook (:func:`main`) only tells the agent to arm the watch, or WARNS when a push or a create
  left the session no open PR on record (:func:`said_after`);
* ``forge watch --session <id> --stream`` (:mod:`dev_lab.dev.forgewatch`) reads it, and marks a PR
  ``merged``/``closed`` once it has said so (:func:`close`), so a merge is reported once;
* ``forge watch --session <id> --ack <key> --reason <why>`` records why a red head may stand (:func:`ack`);
  a newer head is not covered by an older head's reason.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from lab_commons import home as _home
from lab_commons.liveness import creation_stamp, still_the_same_process
from lab_commons.log import emit

from dev_lab.dev.forge import Forge, UnreadableRemote, forge_from_remote
from dev_lab.dev.refspec import pushed_refs
from dev_lab.dev.venvpath import running_interpreter

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = [
    'RULE',
    'SESSION_ENV',
    'Row',
    'ack',
    'close',
    'main',
    'open_rows',
    'record_opened',
    'record_pr',
    'record_push',
    'record_pushed',
    'resolve',
    'rows',
    'said_after',
    'session_of',
    'unwatch',
    'valid',
    'watch',
    'watch_session_command',
    'watching',
]

#: The rule this record serves (``dev_lab.dev.rules``).
RULE: Final = 'SESSION-HEARS-ITS-PRS'

#: The variable naming the agent session a door runs for; Claude Code sets it on every shell it spawns.
SESSION_ENV: Final = 'CLAUDE_CODE_SESSION_ID'

#: The directory, under the machine home, holding one record per session.
SESSIONS: Final = 'sessions'

#: A session id is a file name here: anything else is refused rather than escaped.
_SESSION: Final = re.compile(r'^[\w.-]{1,128}$')


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


def session_of(env: Mapping[str, str] | None = None) -> str:
    """The session :data:`SESSION_ENV` names in *env* (the process's by default), or ``''`` when none is valid."""
    session = (os.environ if env is None else env).get(SESSION_ENV, '')
    return session if valid(session) else ''


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


def _loud(what: str, env: Mapping[str, str] | None) -> str:
    """The session to record *what* for, or ``''``; a set but invalid :data:`SESSION_ENV` is SAID on stderr."""
    named = (os.environ if env is None else env).get(SESSION_ENV, '')
    if named and not valid(named):
        emit(f'[{RULE}] {what} NOT recorded: {SESSION_ENV}={named!r} is not a session id', err=True)
    return session_of(env)


def record_opened(
    forge: Forge, number: int, *, branch: str = '', sha: str = '', env: Mapping[str, str] | None = None
) -> Row | None:
    """Record PR *number* of *forge*, just opened, as the session's in *env*; ``None`` outside a session.

    A record that fails is SAID on stderr and never raised: the PR is open either way.
    """
    what = f'{forge.identity}#{number}'
    if not (session := _loud(what, env)):
        return None
    try:
        return record_pr(session, forge, number, branch=branch, sha=sha)
    except OSError as failed:
        emit(f'[{RULE}] {what} NOT recorded for session {session}: {failed}', err=True)
        return None


def record_pushed(
    root: Path, lines: Iterable[str], *, env: Mapping[str, str] | None = None, remote: str = 'origin'
) -> tuple[Row, ...]:
    """Record every branch git's pre-push *lines* update on *root*'s *remote*, as the session's in *env*.

    A deletion records nothing, nor does a run outside a session. Inside one, a remote that names no forge or a
    record that fails is SAID on stderr and never raised: the push goes through either way.
    """
    refs = [ref for ref in pushed_refs(lines) if ref.branch and not ref.deleted]
    what = 'push of ' + ' '.join(str(ref.branch) for ref in refs)
    if not refs or not (session := _loud(what, env)):
        return ()
    try:
        forge = forge_from_remote(root, remote=remote)
        found = [record_push(session, forge, str(ref.branch), ref.local_sha) for ref in refs]
    except (UnreadableRemote, OSError) as failed:
        emit(f'[{RULE}] {what} in {root} NOT recorded for session {session}: {failed}', err=True)
        return ()
    return tuple(row for row in found if row is not None)


def _marker(session: str) -> Path | None:
    path = _path(session)
    return path.with_suffix('.watch') if path is not None else None


def watch(session: str, pid: int | None = None) -> None:
    """Leave the liveness marker of *session*'s watch: the pid (this process by default) and its creation stamp."""
    marker = _marker(session)
    if marker is None:
        return
    pid = os.getpid() if pid is None else pid
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({'pid': pid, 'created': creation_stamp(pid)}), encoding='utf-8')


def unwatch(session: str) -> None:
    """Remove *session*'s liveness marker: its watch ended."""
    if (marker := _marker(session)) is not None:
        marker.unlink(missing_ok=True)


def watching(session: str) -> bool:
    """Whether a live ``forge watch --session`` of *session* left its marker (a recycled pid reads as gone)."""
    marker = _marker(session)
    try:
        held = json.loads(marker.read_text(encoding='utf-8')) if marker is not None else None
        return isinstance(held, dict) and still_the_same_process(int(held['pid']), held.get('created'))
    except (OSError, ValueError, KeyError, TypeError):
        return False


#: A shell line that pushes or opens a PR: the moments the hook speaks after.
_ACTS: Final = re.compile(r'\bgit\b[^\n;&|]*\spush\b|with-retry\.sh\S*\s+push\b|\bforge\s+pr\s+create\b')


def said_after(command: str, session: str) -> str | None:
    """What the hook tells the agent after shell *command*: arm the watch, or a warning; ``None`` when silent.

    It reads the record the doors wrote, never the command's output: a push or a create that left the session
    no open PR on record is SAID, because the watch would hear nothing of it.
    """
    if not _ACTS.search(command):
        return None
    open_now = open_rows(session)
    if not open_now:
        return (
            f'{RULE}: WARNING -- this command pushes or opens a PR, yet session {session} has no open PR on record, '
            'so no merge or red check will reach you. The doors record one (`forge pr create`, the family pre-push '
            f'row `session-prs`) only when {SESSION_ENV} is set and the repository runs the family hooks.'
        )
    keys = ', '.join(row.key for row in open_now)
    return (
        f"{RULE}: this session's open PRs on record: {keys}. Arm ONE persistent Monitor on every PR of the session "
        f'(it ends when none is open): {watch_session_command(session)}'
    )


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """``--push [ROOT]``: the pre-push row (git's ref lines on stdin); else the ``PostToolUse`` hook. Always 0."""
    args = list(sys.argv[1:] if argv is None else argv)
    source = stdin or sys.stdin
    if args[:1] == ['--push']:
        with contextlib.suppress(OSError):
            record_pushed(Path(args[1]) if len(args) > 1 else Path.cwd(), source.read().splitlines())
        return 0
    try:
        payload = json.load(source)
    except ValueError:
        return 0
    tool_input = payload.get('tool_input') if isinstance(payload, dict) else None
    command = tool_input.get('command') if isinstance(tool_input, dict) else None
    session = str(payload.get('session_id') or '')
    if not isinstance(command, str) or not valid(session):
        return 0
    if (said := said_after(command, session)) is not None:
        emit(json.dumps({'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext': said}}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
