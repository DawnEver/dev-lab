"""REACH-EQUIVALENCE -- a part's verdict at A carries to a descendant B whose diff no test can reach.

THE WASTE THIS CLOSES, measured 2026-10-13 on a consumer: a ``tests/jmag`` part ran two hours on a
workstation and was cancelled "superseded by" a commit that changed only ``.claude/memory/`` plan lines;
a linux part went the same way. Superseding is right when the new tip COULD change the verdict, and
pure waste when it cannot reach any test the part runs.

THE RULE IS DECLARED, NOT INFERRED. A repo names the paths no test reads, once, in its pyproject::

    [tool.lab_commons.parts]
    inert = [".claude/memory/**", "docs-src/**", "*.md"]

Matched by :func:`fnmatch.fnmatchcase` against the repo-relative POSIX path, so ``*`` crosses ``/``:
``*.md`` is every Markdown file at any depth. Nothing declared means nothing is inert, and nothing carries.

B is EQUIVALENT to A (:func:`equivalent`) when B descends from A and EVERY path in ``git diff
--no-renames A B`` matches the list A declares -- a rename counts both its sides, so moving a file out
of an inert tree is a code change. Any doubt (no ancestry, an unreadable declaration) is NOT equivalent:
the carry is an optimisation, and refusing it only costs the run it would have saved.

APPLIED IN THREE PLACES, one rule each reads:

* a producer whose ref moved on to an equivalent tip is NOT superseded -- it finishes
  (:mod:`lab_commons.dev.forgeproduce`, :func:`lab_commons.dev.forgerun.supersede_moved`);
* its finished part is posted on A as always, and ALSO on the tip (:func:`carry_target`), naming A:
  ``... carried from <A12>: only inert paths changed`` (:class:`lab_commons.dev.platformparts.Part`);
* admission and promote read that status as the part it is -- same state, same scope -- so they accept
  it with no change of their own.

A tip whose part is already settled (``success``/``failure``) is never overwritten: a real verdict on B
outranks one carried to it.
"""

from __future__ import annotations

import subprocess
from fnmatch import fnmatchcase
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.dev.forge import _GIT
from lab_commons.dev.forgeschedule import tip_of
from lab_commons.dev.forgestatus import status_history
from lab_commons.dev.platformparts import part_context, post
from lab_commons.hpc.declared import OutdatedKit, kit_tables, pyproject_at

if TYPE_CHECKING:
    from lab_commons.dev.forgework import Client

__all__ = ['SETTLED', 'carry_target', 'changed_paths', 'equivalent', 'inert_globs', 'publish']

#: The states that are a part's verdict; ``pending`` is a claim and ``error`` a release.
SETTLED: Final = frozenset({'success', 'failure'})

_GIT_TIMEOUT_S: Final = 60


def inert_globs(root: Path, sha: str) -> tuple[str, ...]:
    """``[tool.lab_commons.parts] inert`` as commit *sha* of *root* declares it; ``()`` when undeclared.

    Raises:
        ValueError: the commit is unreadable, or the key is not an array of non-empty strings.

    """
    value = kit_tables(pyproject_at(root, sha)).get('parts', {}).get('inert', [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        msg = (
            'pyproject.toml must declare [tool.lab_commons.parts] inert as an array of path globs, '
            f'e.g. inert = [".claude/memory/**", "*.md"] -- not {value!r}'
        )
        raise ValueError(msg)
    return tuple(value)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_GIT, '-C', str(root), *args],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=_GIT_TIMEOUT_S,
        check=False,
    )


def changed_paths(root: Path, a: str, b: str) -> tuple[str, ...] | None:
    """Every path ``git diff --no-renames`` names from *a* to *b*, sorted; ``None`` unless *b* descends from *a*."""
    if _git(root, 'merge-base', '--is-ancestor', a, b).returncode != 0:
        return None
    done = _git(root, 'diff', '--no-renames', '--name-only', a, b)
    if done.returncode != 0:
        return None
    return tuple(sorted(line for line in done.stdout.splitlines() if line))


def equivalent(root: Path, a: str, b: str) -> bool:
    """Whether every path changed from *a* to its descendant *b* is inert by *a*'s declaration (module docstring)."""
    changed = changed_paths(root, a, b)
    if changed is None:
        return False
    try:
        globs = inert_globs(root, a)
    except (ValueError, OutdatedKit):
        return False
    return bool(globs) and all(any(fnmatchcase(path, glob) for glob in globs) for path in changed)


def carry_target(root: Path, client: Client, *, ref: str, sha: str, platform: str) -> str:
    """*ref*'s origin tip when *sha*'s *platform* part should also be posted there; else ``''``.

    The tip must have moved past *sha*, be :func:`equivalent` to it, and hold no settled part of its own.
    """
    tip = tip_of(root, ref)
    if not tip or tip == sha or not equivalent(root, sha, tip):
        return ''
    context = part_context(platform)
    posts = [status for status in status_history(client, tip) if status.context == context]
    return '' if posts and posts[-1].state in SETTLED else tip


def publish(root: Path, record: Path, *, client: Client, ref: str, sha: str, platform: str) -> str:
    """Post *record* as *sha*'s part (:func:`~lab_commons.dev.platformparts.post`); also onto an equivalent tip."""
    lines = post(root, record)
    if target := carry_target(root, client, ref=ref, sha=sha, platform=platform):
        lines += '\n' + post(root, record, onto=target)
    return lines
