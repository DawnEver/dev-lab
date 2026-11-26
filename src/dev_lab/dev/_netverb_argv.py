"""Which argv is a network verb, and how the door spells it -- the recognition half of :mod:`dev_lab.dev.netverb`.

The retry loop and its report stay in :mod:`dev_lab.dev.netverb`; this module only answers "does this
command talk to a remote" (:func:`is_network_verb`) and "what argv runs" (:func:`spelled`). The deny row,
``dep`` and the arch scan read the same lists from here.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import PurePath
from typing import Final

__all__ = [
    'CARGO_NETWORK_VERBS',
    'GIT_NETWORK_VERBS',
    'LOCAL_REPOSITORY',
    'UV_NETWORK_VERBS',
    'NotANetworkVerb',
    'is_network_verb',
    'spelled',
]


#: The git verbs that talk to a remote -- the one list the deny row, the arch scan and the door's spelling
#: read. ``submodule`` is one only as ``submodule update``, which clones and fetches.
GIT_NETWORK_VERBS: Final = ('push', 'fetch', 'pull', 'clone', 'ls-remote', 'submodule')

#: The uv verbs that RESOLVE, reaching an index or a git dependency on the forge (2026-10-19: one `uv sync`
#: of a git dependency failed on auth and the re-run passed). ``pip`` is one only as ``pip install|sync|compile``.
UV_NETWORK_VERBS: Final = ('sync', 'lock', 'add', 'remove', 'pip')

#: Cargo dependency operations that can reach registries or Git. Admitting a build or a test run is not this door.
CARGO_NETWORK_VERBS: Final = ('update', 'fetch', 'generate-lockfile')

#: A verb that is a network verb only with one of these second words.
_SUBVERBS: Final = {'submodule': frozenset({'update'}), 'pip': frozenset({'install', 'sync', 'compile'})}

#: Each program's global options that take a SEPARATE value (``git -C <path>``, ``uv --directory <path>``):
#: the verb is the first word after them, so a program's own set is what finds it.
_VALUED: Final = {
    'git': frozenset({'-C', '-c', '--git-dir', '--work-tree', '--namespace'}),
    'uv': frozenset({'--directory', '--project', '--python', '-p', '--config-file', '--cache-dir', '--color'}),
    'cargo': frozenset({'--config', '--color', '-Z'}),
}

_PROGRAMS: Final = {'git': GIT_NETWORK_VERBS, 'uv': UV_NETWORK_VERBS, 'cargo': CARGO_NETWORK_VERBS}


def _program(word: str) -> str:
    """``C:/x/uv.EXE`` -> ``uv``: the program a path names, case- and suffix-free."""
    return PurePath(word.replace('\\', '/')).name.lower().removesuffix('.exe')


def is_network_verb(argv: Sequence[str]) -> bool:
    """Whether *argv* talks to a remote -- the ONE predicate the door, ``dep`` and the arch scan read."""
    program = _program(argv[0]) if argv else ''
    verbs = _PROGRAMS.get(program)
    if verbs is None:
        return False
    words, index = list(argv[1:]), 0
    if program == 'cargo' and words and words[0].startswith('+'):
        words = words[1:]  # rustup's explicit toolchain; preserve the original argv for execution
    while index < len(words) and words[index].startswith('-'):
        if program == 'cargo' and words[index] in {'--help', '-h', '--version', '-V', '--list'}:
            return False
        index += 2 if words[index] in _VALUED[program] else 1
    words = [word for word in words[index:] if not word.startswith('-')]
    if not words or words[0] not in verbs:
        return False
    if program == 'git' and words[0] in _GIT_REPOSITORY_VERBS and len(words) > 1 and _LOCAL_REPOSITORY.match(words[1]):
        return False
    return words[0] not in _SUBVERBS or (len(words) > 1 and words[1] in _SUBVERBS[words[0]])


#: The git verbs whose first operand is the repository they talk to.
_GIT_REPOSITORY_VERBS: Final = frozenset({'push', 'fetch', 'pull', 'clone', 'ls-remote'})

#: A repository named by a local path -- ``.``, ``../x``, ``/c/x``, a drive-letter path, ``file://`` -- is no remote
#: (measured 2026-11-16: ``git -C . fetch . a:b`` was hinted as a network verb). The row's shell spelling is
#: :data:`dev_lab.dev._deny_rows.NETWORK_VERB_PATTERN`.
LOCAL_REPOSITORY: Final = r'(?:\.{1,2}(?:[/\\]\S*)?|[/\\]\S*|[A-Za-z]:[/\\]\S*|file://\S*)'
_LOCAL_REPOSITORY: Final = re.compile(rf'^["\']?{LOCAL_REPOSITORY}["\']?$')


class NotANetworkVerb(ValueError):
    """The command after ``--`` is no network verb (:func:`is_network_verb`)."""


def _no_followed_tags(words: list[str]) -> list[str]:
    """A ``git push`` pinned to ``--no-follow-tags`` right after the verb; any other command unchanged.

    WHO DECIDED TO PUSH A TAG (wall 2026-11-13): with ``push.followTags`` on, a branch push carried
    another session's milestone tag and VERSION-TAG-NEEDS-APPROVAL refused a tag the pusher never
    named. The pre-push hook cannot tell a followed tag from a named one -- git hands it identical
    ref lines -- so the door decides: a tag goes only when the push names it (a refspec, ``--tags``),
    and a ``--follow-tags`` typed after the verb still wins, git reading its options in order.
    """
    if not words or _program(words[0]) != 'git':
        return words
    index = 1
    while index < len(words) and words[index].startswith('-'):
        index += 2 if words[index] in _VALUED['git'] else 1
    if words[index : index + 1] != ['push']:
        return words
    return [*words[: index + 1], '--no-follow-tags', *words[index + 1 :]]


def spelled(command: Sequence[str]) -> list[str]:
    """The argv to run: ``--`` dropped, ``git`` prepended to a bare git verb, a push held to its named tags.

    A push is pinned to ``--no-follow-tags`` (:func:`_no_followed_tags`).

    Only the separator in front is dropped; a later ``--`` is git's own pathspec separator.

    Raises:
        NotANetworkVerb: any other first token, as one line naming the right spelling.

    """
    words = list(command)
    if words[:1] == ['--']:
        words = words[1:]
    if words[:1] == ['git'] or is_network_verb(words):
        return _no_followed_tags(words)
    if is_network_verb(['git', *words]):
        return _no_followed_tags(['git', *words])
    first = ' '.join(words[:2]) if words else '<nothing>'
    msg = (
        f'netverb: {first!r} is not a network verb -- spell it '
        f'`python -m dev_lab.dev.netverb -- git push ...` (or `-- {"|".join(GIT_NETWORK_VERBS)} ...`, '
        f'`-- uv {"|".join(UV_NETWORK_VERBS)} ...`, '
        f'`-- cargo {"|".join(CARGO_NETWORK_VERBS)} ...`)'
    )
    raise NotANetworkVerb(msg)
