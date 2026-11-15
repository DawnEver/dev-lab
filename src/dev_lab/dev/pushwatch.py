"""PUSHED-HEAD-IS-WATCHED: every head a session pushes is watched to its verdict, and the session acts on it.

User ruling 2026-10-29 (D83) advised and never blocked; user ruling 2026-11-04 added the ``Stop`` half after a
session pushed PRs, said "in review" and ended its turn with nothing watching them while reds sat unfixed.
The same on both forges; one command:

* ``forge watch <sha> --stream`` (:mod:`dev_lab.dev.forgewatch`) prints ONE line per status change and exits
  0 green, 1 red, 3 at its deadline -- built to run as a Claude Code ``Monitor``, so each change is an event;
* ``forge pr create`` and a successful push through the family door (:mod:`dev_lab.dev.netverb`) print
  :func:`arm_line`, the exact command to arm;
* the ``PostToolUse`` hook (``python -m dev_lab.dev.pushwatch``): after a shell call that pushed, when no live
  ``forge watch <sha>`` process watches the pushed head, ONE line of additional context names the command.
  It never blocks and never exits nonzero: a fact it cannot read is silence. It also JOURNALS the push --
  ``<git dir>/dev-lab-pushed/<session>.json``, ``{ref: sha}``, a later push of a ref replacing its head;
* the ``Stop`` hook (:mod:`dev_lab.dev.pushstop`) reads that journal and refuses to end a turn whose pushed
  head is pending and unwatched, or red.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

import lab_commons.launch as _door
from lab_commons.census import processes as census
from lab_commons.log import emit

from dev_lab.dev.venvpath import running_interpreter

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

__all__ = [
    'RULE',
    'arm_line',
    'deadline_reached',
    'main',
    'pushed_at',
    'pushed_by',
    'pushed_head',
    'pushed_ref',
    'pushed_sha',
    'pushed_target',
    'record',
    'record_deadline',
    'reminder',
    'watch_command',
    'watched',
]

#: The rule this advises on (``dev_lab.dev.rules``).
RULE: Final = 'PUSHED-HEAD-IS-WATCHED'

_GIT: Final = shutil.which('git') or 'git'

#: The door a head is watched through, as its process command line names it.
_WATCH: Final = '-m dev_lab.dev.forge watch'

#: The shortest sha prefix a watch may be started with and still count as watching the head.
_SHORT: Final = 7

#: A push on a shell line: ``git [-C <dir>] push ...`` or the retry wrapper's ``with-retry.sh push ...``.
_PUSH: Final = re.compile(r'(?:\bgit(?:\.exe)?(?P<dir>\s+-C\s+\S+)?|with-retry\.sh)\s+push\b(?P<rest>[^\n;&|]*)')

#: Push options that take a value as the next word.
_VALUED: Final = frozenset({'--repo', '--receive-pack', '--exec', '-o', '--push-option'})

#: A remote, then at least one refspec: fewer positional words push ``HEAD``.
_WITH_REFSPEC: Final = 2

#: Push options that push no head of their own.
_DELETES: Final = frozenset({'-d', '--delete', '--prune', '--mirror', '--tags'})


#: The directory, in a checkout's own git dir, holding one ``{ref: sha}`` journal per session.
JOURNAL_DIR: Final = 'dev-lab-pushed'

#: The file in :data:`JOURNAL_DIR` recording each sha whose ``forge watch`` ran to its deadline unsettled.
DEADLINES: Final = 'deadlines.json'

#: A session id is a file name here: anything else is refused rather than escaped.
_SESSION: Final = re.compile(r'^[\w.-]{1,128}$')


def watch_command(*shas: str) -> str:
    """The command that watches *shas* until one settles, one line per status change (run it as a ``Monitor``)."""
    return f'{running_interpreter()} -m dev_lab.dev.forge watch {" ".join(shas)} --stream'


def arm_line(sha: str) -> str:
    """The one line a push door prints: arm a ``Monitor`` on *sha* with :func:`watch_command`."""
    return f'{RULE}: arm a Monitor on {sha[:12]}: {watch_command(sha)}'


def _watched_words(command_lines: Iterable[str]) -> list[str]:
    """Every sha (or prefix of at least 7 hex) a live ``forge watch`` in *command_lines* names."""
    words = []
    for line in command_lines:
        if _WATCH not in line:
            continue
        for word in line.split(_WATCH, 1)[1].split():
            if word.startswith('-'):
                break
            if len(word) >= _SHORT:
                words.append(word)
    return words


def watched(sha: str, command_lines: Iterable[str], *, root: Path | None = None) -> bool:
    """Whether a live process is ``forge watch``-ing *sha*, or (with *root*) a newer head descending from it.

    A head the forge's integration sync merged past (2026-11-14: the PR's head became a merge commit on top of the
    pushed one) is carried by a watch on that descendant: the superseded sha needs no watch of its own. Ancestry
    is read from the local repository at *root*; a watched commit it does not hold counts for nothing.
    """
    words = _watched_words(command_lines)
    if any(sha.startswith(word) for word in words):
        return True
    return root is not None and any(_descends(root, sha, word) for word in words)


def _descends(root: Path, sha: str, word: str) -> bool:
    """Whether commit *word* is a strict descendant of *sha* in the repository at *root*."""
    done = _door.run(
        [_GIT, '-C', str(root), 'merge-base', '--is-ancestor', sha, word],
        capture_output=True, text=True, encoding='utf-8', check=False,
    )  # fmt: skip
    return done.returncode == 0 and not word.startswith(sha[: len(word)])


def pushed_ref(words: Sequence[str]) -> str | None:
    """The ref a ``git push`` with *words* (after ``push``) publishes: its last refspec's source, ``HEAD`` if none.

    ``None`` for a push that publishes no head of its own: a deletion (``:<ref>``, ``-d``) or a mirror.
    """
    positional: list[str] = []
    skip = False
    for word in words:
        if skip:
            skip = False
        elif word in _DELETES:
            return None
        elif word in _VALUED:
            skip = True
        elif not word.startswith('-'):
            positional.append(word)
    if len(positional) < _WITH_REFSPEC:
        return 'HEAD'
    source = positional[-1].removeprefix('+').split(':', 1)[0]
    return source or None


def pushed_sha(root: Path, ref: str) -> str | None:
    """The commit *ref* names in *root*, or ``None`` when it names none."""
    done = _door.run(
        [_GIT, '-C', str(root), 'rev-parse', '-q', '--verify', f'{ref}^{{commit}}'],
        capture_output=True, text=True, encoding='utf-8', check=False,
    )  # fmt: skip
    return done.stdout.strip() or None if done.returncode == 0 else None


def pushed_target(root: Path, command: str) -> tuple[Path, str, str] | None:
    """The checkout, the ref and the remote branch (``''`` unless a ``<src>:<dst>`` names it) *command* pushes.

    ``None`` for no push or a deletion; *command* is a shell line run in *root*.
    """
    found = _PUSH.search(command)
    if found is None:
        return None
    try:
        words = shlex.split(found['rest'])
    except ValueError:
        return None
    where = root / found['dir'].split(maxsplit=1)[1] if found['dir'] else root
    ref = pushed_ref(words)
    last = words[-1] if words else ''
    destination = last.partition(':')[2].removeprefix('refs/heads/') if ':' in last else ''
    return (where, ref, destination) if ref is not None else None


def pushed_head(root: Path, command: str) -> str | None:
    """The commit shell *command*, run in *root*, pushes; ``None`` for no push, a deletion, or an unknown ref."""
    pushed = pushed_target(root, command)
    return pushed_sha(*pushed[:2]) if pushed is not None else None


def _git(root: Path, *args: str) -> str:
    done = _door.run([_GIT, '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8', check=False)
    return done.stdout.strip() if done.returncode == 0 else ''


def _journal(root: Path, session: str) -> Path | None:
    git_dir = _git(root, 'rev-parse', '--absolute-git-dir')
    if not git_dir or not _SESSION.match(session):
        return None
    return Path(git_dir) / JOURNAL_DIR / f'{session}.json'


def _read(path: Path | None) -> dict:
    try:
        table = json.loads(path.read_text(encoding='utf-8')) if path is not None else {}
    except (OSError, ValueError):
        return {}
    return table if isinstance(table, dict) else {}


def _write(path: Path, table: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(table, indent=1, sort_keys=True), encoding='utf-8')


def _pushes(root: Path, session: str) -> dict[str, dict]:
    """The journal, ``{ref: {'sha': sha, 'at': epoch seconds}}``; a row of any other shape is not read."""
    rows = _read(_journal(root, session)).items()
    return {str(ref): row for ref, row in rows if isinstance(row, dict) and isinstance(row.get('sha'), str)}


def pushed_by(root: Path, session: str) -> dict[str, str]:
    """The heads *session* pushed from the checkout at *root*, ``{ref: sha}``; empty when it pushed none."""
    return {ref: row['sha'] for ref, row in _pushes(root, session).items()}


def pushed_at(root: Path, session: str) -> dict[str, float]:
    """When *session* last pushed each of its heads, ``{sha: epoch seconds}``."""
    return {row['sha']: float(row.get('at') or 0.0) for row in _pushes(root, session).values()}


def record(root: Path, session: str, ref: str, sha: str, *, at: float | None = None) -> None:
    """Journal that *session* pushed *sha* as *ref* at *at* (now): a later push of the same ref replaces the head."""
    path = _journal(root, session)
    if path is None:
        return
    row = {'sha': sha, 'at': time.time() if at is None else at}
    _write(path, {**_pushes(root, session), ref: row})


def _deadlines(root: Path) -> Path | None:
    git_dir = _git(root, 'rev-parse', '--absolute-git-dir')
    return Path(git_dir) / JOURNAL_DIR / DEADLINES if git_dir else None


def record_deadline(root: Path, sha: str) -> None:
    """Record that a ``forge watch`` of *sha* ran to its deadline unsettled (any session's watch)."""
    if (path := _deadlines(root)) is not None:
        _write(path, {**_read(path), sha: time.time()})


def deadline_reached(root: Path) -> frozenset[str]:
    """Every sha a ``forge watch`` in this checkout ran to its deadline unsettled."""
    return frozenset(str(sha) for sha in _read(_deadlines(root)))


def _record_push(root: Path, command: str, session: str) -> None:
    pushed = pushed_target(root, command)
    if pushed is None or not session:
        return
    where, ref, _ = pushed
    if sha := pushed_sha(where, ref):
        record(where, session, _git(where, 'rev-parse', '--symbolic-full-name', ref) or ref, sha)


def reminder(root: Path, command: str, *, processes: Callable[[], Iterable[str]]) -> str | None:
    """The one-line reminder for shell *command* run in *root*, or ``None``: no push, a watched head, unreadable."""
    sha = pushed_head(root, command)
    if sha is None or watched(sha, processes()):
        return None
    return f'{RULE}: {sha[:12]} was pushed and nothing watches it; arm a Monitor: {watch_command(sha)}'


def main(
    argv: list[str] | None = None,
    *,
    stdin: TextIO | None = None,
    processes: Callable[[], Iterable[str]] | None = None,
) -> int:
    """The ``PostToolUse`` hook on the shell tools: journal a push, advise once when unwatched; never block, 0."""
    del argv
    try:
        payload = json.load(stdin or sys.stdin)
    except ValueError:
        return 0
    live = processes or (lambda: (one.command_line for one in census()))
    tool_input = payload.get('tool_input') if isinstance(payload, dict) else None
    command = tool_input.get('command') if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return 0
    root = Path(payload.get('cwd') or Path.cwd())
    try:
        _record_push(root, command, str(payload.get('session_id') or ''))
        said = reminder(root, command, processes=live)
    except OSError:
        return 0
    if said is not None:
        context = {'hookEventName': 'PostToolUse', 'additionalContext': said}
        emit(json.dumps({'hookSpecificOutput': context}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
