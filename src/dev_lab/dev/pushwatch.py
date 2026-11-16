"""PUSHED-HEAD-IS-WATCHED: a push door names who hears the head it pushed -- the machine PR watcher.

User ruling 2026-10-29 (D83), then dev-lab #640: ONE hearer of a session's PRs, the machine watcher
(:mod:`dev_lab.dev.prwatcher`), which polls every PR a session opened or pushed (:mod:`dev_lab.dev.sessionprs`, the
record the doors write) and says each change at the session's next prompt. So:

* ``forge pr create`` and a successful push through the family door (:mod:`dev_lab.dev.netverb`) print
  :func:`heard_line`: the head, the hearer, and the one idempotent door that starts it if none runs;
* :func:`pushed_head` reads which commit a shell push line publishes, the same on every spelling the doors run.

``forge watch <sha>... --stream`` (:mod:`dev_lab.dev.forgewatch`) still reads one head to its verdict on request.
"""

from __future__ import annotations

import re
import shlex
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

from dev_lab.dev.venvpath import running_interpreter

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ['RULE', 'heard_line', 'pushed_head', 'pushed_ref', 'pushed_sha', 'pushed_target']

#: The rule this serves (``dev_lab.dev.rules``).
RULE: Final = 'PUSHED-HEAD-IS-WATCHED'

_GIT: Final = shutil.which('git') or 'git'

#: A push on a shell line: ``git [-C <dir>] push ...`` or the retry wrapper's ``with-retry.sh push ...``.
_PUSH: Final = re.compile(r'(?:\bgit(?:\.exe)?(?P<dir>\s+-C\s+\S+)?|with-retry\.sh)\s+push\b(?P<rest>[^\n;&|]*)')

#: Push options that take a value as the next word.
_VALUED: Final = frozenset({'--repo', '--receive-pack', '--exec', '-o', '--push-option'})

#: A remote, then at least one refspec: fewer positional words push ``HEAD``.
_WITH_REFSPEC: Final = 2

#: Push options that push no head of their own.
_DELETES: Final = frozenset({'-d', '--delete', '--prune', '--mirror', '--tags'})


def heard_line(sha: str) -> str:
    """The one line a push door prints for pushed *sha*: the machine PR watcher hears it, and how to start one."""
    return (
        f"{RULE}: {sha[:12]} pushed; the machine PR watcher hears this session's PRs and says each change at your "
        f'next prompt -- if none runs, start it: {running_interpreter()} -m dev_lab.dev.prwatcher start'
    )


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
