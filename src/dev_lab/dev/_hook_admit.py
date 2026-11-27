"""HOOKS-ARE-WIRED, the REFUSING half: a git verb that writes history never runs from an unwired checkout.

:mod:`dev_lab.dev.hook_install` REPORTS a checkout whose declared stages are not live; nothing refused a
commit there (v1 FAM-14, 2026-11-27: under ``extensions.worktreeConfig`` every ``git worktree add`` started
with no ``core.hooksPath``, and every lane committed, merged and pushed with zero family stages). This module
is the judge the agent guard's ``HOOKS-ARE-WIRED`` row (:mod:`dev_lab.dev._deny_hookswired_row`) asks through
``python -m dev_lab.dev.hook_install --admit`` with the hook payload; :func:`admit` names the tree.

A tree git or the table cannot read is never refused here (:func:`dev_lab.dev.hook_install.unwired`).

A PROBE of which rule owns a shape (:func:`dev_lab.dev.famtests.agentguard.decision_for`) states every tree wired
with :data:`ASSUME_WIRED`: wiring is the state of the box the probe runs on -- a hosted checkout declares stages it
never installs -- as a live run is, and a sanctioned shape must not turn on it (dev-lab fa9d6f2b, every consumer's
hosted famtest). The tool never sends the key, so no agent command can.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ['ASSUME_WIRED', 'RULE_ID', 'WRITE_VERBS', 'admit', 'refusal', 'write_targets']

RULE_ID: Final = 'HOOKS-ARE-WIRED'
#: The payload key a PROBE sets (``run_engine(assume_wired=True)``): every tree its verb targets is taken as wired.
ASSUME_WIRED: Final = 'dev_lab_assume_wired'
#: The git verbs that write history or publish it: each runs a declared stage (commit-msg, merge audit, pre-push).
WRITE_VERBS: Final = ('commit', 'merge', 'push', 'cherry-pick', 'rebase')
HAZARD: Final = 'its declared git hook stages are not live, so this verb would run none of the family checks.'

_SEGMENTS: Final = re.compile(r'&&|\|\||[;|\n]')
_GIT: Final = re.compile(r'(?:.*[/\\])?git(?:\.exe)?', re.IGNORECASE)
_NETVERB: Final = 'dev_lab.dev.netverb'


def refusal(tree: Path, python: str) -> str:
    """The refusal for an unwired *tree*: its cause and its door, both commands spelled with *python*."""
    where = tree.as_posix()
    return (
        f'{RULE_ID}: {where} -- {HAZARD} Wire it: `{python} -m dev_lab.dev.dep --bootstrap {where}` then '
        f'`{python} -m dev_lab.dev.hook_install --repo {where} --install`, and run the verb again.\n'
        'details: docs-src/dev/refusals.md#hooks-are-wired (dev-lab)'
    )


def _words(segment: str) -> list[str]:
    try:
        return [word.strip('"\'') for word in shlex.split(segment, posix=False)]
    except ValueError:
        return []


def _git_verb(words: list[str], base: Path) -> tuple[str, Path] | None:
    """``(verb, dir)`` when *words* invoke git (``-C``/``-c`` options read); else ``None``."""
    if not words or not _GIT.fullmatch(words[0]):
        return None
    at = 1
    while at + 1 < len(words) and words[at] in {'-C', '-c'}:
        if words[at] == '-C':
            base = base / words[at + 1]
        at += 2
    return (words[at], base) if at < len(words) else None


def _netverb_git(words: list[str], base: Path) -> tuple[str, Path] | None:
    """The git verb a ``python -m dev_lab.dev.netverb [--cwd D] [--] git ...`` line forwards, in its directory."""
    if _NETVERB not in words:
        return None
    rest = words[words.index(_NETVERB) + 1 :]
    while rest and rest[0] != 'git' and not _GIT.fullmatch(rest[0]):
        if rest[0] == '--cwd' and len(rest) > 1:
            base = base / rest[1]
            rest = rest[1:]
        rest = rest[1:]
    return _git_verb(rest, base)


def write_targets(command: str, cwd: Path) -> list[Path]:
    """Every directory a history-writing git verb on *command* runs in: ``cd``, ``-C`` and netverb's ``--cwd`` read."""
    here = cwd
    found: list[Path] = []
    for segment in _SEGMENTS.split(command):
        words = _words(segment.strip())
        if words[:1] in (['cd'], ['pushd']) and len(words) > 1:
            here = here / words[1]
            continue
        verb = _git_verb(words, here) or _netverb_git(words, here)
        if verb is not None and verb[0] in WRITE_VERBS:
            found.append(verb[1])
    return found


def admit(payload: object, unwired: Callable[[Path], bool], python: str) -> str | None:
    """The refusal of a shell hook *payload* whose write verb targets an *unwired* tree; ``None`` admits."""
    if not isinstance(payload, dict):
        return None
    fields = cast('dict[str, object]', payload)
    if fields.get(ASSUME_WIRED) is True:
        return None
    tool_input = fields.get('tool_input')
    if not isinstance(tool_input, dict):
        return None
    command = cast('dict[str, object]', tool_input).get('command', '')
    cwd = Path(str(fields.get('cwd') or Path.cwd()))
    for target in write_targets(str(command), cwd):
        if target.is_dir() and unwired(target):
            return refusal(target.resolve(), python)
    return None
