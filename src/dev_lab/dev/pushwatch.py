"""PUSHED-HEAD-IS-WATCHED: every head a session pushes is watched to its verdict -- advised, never blocked.

User ruling 2026-10-29 (D83), the same on both forges; it replaced a ``Stop``-hook round gate, because a gate
that holds a turn open costs more than the red it catches. Three halves, one command:

* ``forge watch <sha> --stream`` (:mod:`dev_lab.dev.forgewatch`) prints ONE line per status change and exits
  0 green, 1 red, 3 at its deadline -- built to run as a Claude Code ``Monitor``, so each change is an event;
* ``forge pr create`` and a successful push through the family door (:mod:`dev_lab.dev.netverb`) print
  :func:`arm_line`, the exact command to arm;
* the ``PostToolUse`` hook (``python -m dev_lab.dev.pushwatch``): after a shell call that pushed, when no live
  ``forge watch <sha>`` process watches the pushed head, ONE line of additional context names the command.
  It never blocks and never exits nonzero: a fact it cannot read is silence.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import sys
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
    'main',
    'pushed_head',
    'pushed_ref',
    'pushed_sha',
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


def watch_command(sha: str) -> str:
    """The command that watches *sha* to its verdict, one line per status change (run it as a ``Monitor``)."""
    return f'{running_interpreter()} -m dev_lab.dev.forge watch {sha} --stream'


def arm_line(sha: str) -> str:
    """The one line a push door prints: arm a ``Monitor`` on *sha* with :func:`watch_command`."""
    return f'{RULE}: arm a Monitor on {sha[:12]}: {watch_command(sha)}'


def watched(sha: str, command_lines: Iterable[str]) -> bool:
    """Whether a live process is ``forge watch``-ing *sha* (named by it or by a prefix of at least 7 hex)."""
    for line in command_lines:
        if _WATCH not in line:
            continue
        named = line.split(_WATCH, 1)[1].split()
        if named and len(named[0]) >= _SHORT and sha.startswith(named[0]):
            return True
    return False


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


def pushed_head(root: Path, command: str) -> str | None:
    """The commit shell *command*, run in *root*, pushes; ``None`` for no push, a deletion, or an unknown ref."""
    found = _PUSH.search(command)
    if found is None:
        return None
    try:
        words = shlex.split(found['rest'])
    except ValueError:
        return None
    where = root / found['dir'].split(maxsplit=1)[1] if found['dir'] else root
    ref = pushed_ref(words)
    return pushed_sha(where, ref) if ref is not None else None


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
    """The ``PostToolUse`` hook on the shell tools: advise once on an unwatched push; never block, always 0."""
    del argv
    try:
        payload = json.load(stdin or sys.stdin)
    except ValueError:
        return 0
    tool_input = payload.get('tool_input') if isinstance(payload, dict) else None
    command = tool_input.get('command') if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return 0
    live = processes or (lambda: (one.command_line for one in census()))
    try:
        said = reminder(Path(payload.get('cwd') or Path.cwd()), command, processes=live)
    except OSError:
        return 0
    if said is not None:
        context = {'hookEventName': 'PostToolUse', 'additionalContext': said}
        emit(json.dumps({'hookSpecificOutput': context}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
