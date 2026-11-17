"""``STRAY-FILE-REFUSED``: nothing unclaimed sits in a checkout -- the census, its refusal, and its two hooks.

An UNTRACKED, non-ignored file outside the declared stray roots (the family's ``scratch/`` plus ``stray_roots``
of the placement :mod:`dev_lab.dev.codeplace` reads) is a defect the moment it appears: a file a person meant is
STAGED, an artefact a program wrote belongs under ``output/logs/<yy>/<mm>/<dd>/<kind>/`` (ignored), a one-off in
scratch, and a file a known retirement declares gone is deleted through its door -- never staged (2026-11-17:
twelve stale rem indexes, eleven under ``src/``, were told to be ``git add``-ed). Which files are retired is the
CHECKOUT's data, the ``retired`` rows of its placement (:mod:`dev_lab.dev.retiredfiles`), passed to
:func:`retired_copies`; the leaf holds no consumer's layout (:mod:`dev_lab.dev.foreign`), and a checkout
declaring none gets no such exit. Earned 2026-10-20 in a consumer: a vendor controller run by hand with the
checkout as its cwd left seven log files in the root, and a ``uv`` run in a subdirectory left a ``uv.lock``
there; nothing said so until a human saw them.

:func:`stray_files` is the census. THE CLI: ``hook`` is the ``Stop`` agent hook (:func:`_hook`), which also
names what the session left outside the checkout (:mod:`dev_lab.dev.tmpsweep`); ``check`` is the
``stray-files`` post-commit row, a hint naming each stray after a commit (the forge cannot see an untracked
file, and a style finding blocks nothing -- toolchain plan P3).

Split from :mod:`dev_lab.dev.codeplace` 2026-11-17 (D40): that module had reached the 300-code-line band
holding two rules; the placement declaration and ``CODE-IN-CODE-ROOTS`` stay there.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import TextIO

from lab_commons import launch
from lab_commons.log import emit

from dev_lab.dev import tmpsweep
from dev_lab.dev.codeplace import (
    CODE_SUFFIXES,
    PRUNED_NAMES,
    TASK_ROOT,
    PlacementNotDeclared,
    checkout_root,
    declared_placement,
    is_archived,
)
from dev_lab.dev.disclosure import details_for
from dev_lab.dev.retiredfiles import RetiredFile

__all__ = [
    'StrayCensusUnreadable',
    'declared_strays',
    'main',
    'retired_copies',
    'stray_files',
    'stray_refusal',
]

#: How many strays a refusal names before it counts the rest -- the first line stays one short line.
_SHOWN = 3
#: Where a one-off script and a program's data go: a dated directory of their kind (user ruling 2026-11-03).
_SCRIPT_HOME = 'scratch/<yy>/<mm>/<dd>/<kind>/'
_DATA_HOME = 'output/logs/<yy>/<mm>/<dd>/<kind>/'


def retired_copies(found: Iterable[str], *, retired: Iterable[RetiredFile]) -> dict[RetiredFile, list[str]]:
    """Each *retired* row with a copy among repo-relative POSIX *found* outside an archive, mapped to its copies.

    The table is the CALLER's, with no default: which files a tool retired is a fact of the checkout that used
    the tool, declared in its own ``retired`` rows (:mod:`dev_lab.dev.retiredfiles`), and the leaf holds no
    consumer's layout (:mod:`dev_lab.dev.foreign`).
    """
    paths = tuple(found)
    copies = {one: [rel for rel in paths if one.matches(rel) and not is_archived(rel)] for one in retired}
    return {one: rels for one, rels in copies.items() if rels}


class StrayCensusUnreadable(RuntimeError):
    """git could not list a checkout's untracked files; a silent census is not a clean one."""


def stray_files(root: Path, *, stray_roots: Iterable[str], pruned_paths: Iterable[str] = ()) -> list[str]:
    """Every UNTRACKED, non-ignored file of the checkout *root* outside *stray_roots*, repo-relative POSIX, sorted.

    The index decides, not the filesystem: a staged file was meant, an ignored one is an artefact in its
    place (``output/``), and what is left is a file nobody claimed.

    Raises:
        StrayCensusUnreadable: git could not list the untracked files of *root*.

    """
    allowed = tuple(f'{r.strip("/")}/' for r in (*stray_roots, *pruned_paths, TASK_ROOT))
    return sorted(
        rel
        for rel in _untracked(root)
        if not rel.startswith(allowed) and not PRUNED_NAMES.intersection(rel.split('/')[:-1])
    )


def _untracked(root: Path) -> list[str]:
    done = launch.run(
        ['git', '-C', str(root), 'ls-files', '--others', '--exclude-standard', '-z'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
    )
    if done.returncode != 0:
        msg = f'git could not list the untracked files of {root}: {done.stderr.strip()}'
        raise StrayCensusUnreadable(msg)
    return list(filter(None, done.stdout.split('\0')))


def declared_strays(root: Path) -> list[str]:
    """:func:`stray_files` over *root* with the placement *root* declares -- the adopter's scan."""
    placement = declared_placement(root)
    return stray_files(root, stray_roots=placement.stray_roots, pruned_paths=placement.pruned_paths)


def stray_refusal(root: Path) -> str | None:
    """The ``STRAY-FILE-REFUSED`` message for *root* in three lines; ``None`` if clean.

    The first line counts the strays and names a few; the second gives each file ONE exit chosen by its kind --
    a file the checkout's own ``retired`` rows declare gone is deleted through its door, a file under a code root
    was meant (``git add``), a script is a one-off (``scratch/<yy>/<mm>/<dd>/<kind>/``), anything else is a
    program's data (``output/logs/...``); the third points at the details. A checkout that declares no placement
    is not judged: the adopter's own test reds on the missing table.
    """
    try:
        placement = declared_placement(root)
    except PlacementNotDeclared:
        return None
    found = stray_files(root, stray_roots=placement.stray_roots, pruned_paths=placement.pruned_paths)
    if not found:
        return None
    shown = ', '.join(found[:_SHOWN]) + (f' (+{len(found) - _SHOWN} more)' if len(found) > _SHOWN else '')
    retired = retired_copies(found, retired=placement.retired)
    gone = {rel for copies in retired.values() for rel in copies}
    rest = [rel for rel in found if rel not in gone]
    meant = [rel for rel in rest if rel.startswith(placement.code_roots)]
    scripts = [rel for rel in rest if rel not in meant and Path(rel).suffix.lower() in CODE_SUFFIXES]
    exits = [f'{len(rels)} x {one.path} retired ({one.what}): {one.door}' for one, rels in retired.items()]
    exits.append(f'git add {" ".join(meant[:_SHOWN])}' if meant else '')
    exits.append(f'{", ".join(scripts[:_SHOWN])} -> {_SCRIPT_HOME}' if scripts else '')
    exits.append(f'data -> {_DATA_HOME}' if len(rest) > len(meant) + len(scripts) else '')
    return (
        f'STRAY-FILE-REFUSED: {len(found)} untracked file(s) outside output/ and scratch/ in {root.as_posix()}: '
        f'{shown}.\n{"; ".join(one for one in exits if one)}.\n{details_for("STRAY-FILE-REFUSED")}'
    )


def _hook(payload: object) -> int:
    """``Stop``: block with the stray census, else stay silent.

    ``Stop`` is blocked once: with ``stop_hook_active`` the agent already saw the census, and a stray it
    cannot clear (a human's file) must not hold the session in a loop.
    """
    if not isinstance(payload, dict) or payload.get('stop_hook_active'):
        return 0
    cwd = Path(payload.get('cwd') or Path.cwd()).resolve()
    root = cwd if (cwd / '.git').exists() else checkout_root(cwd)
    if root is None:
        return 0
    try:
        reason = stray_refusal(root)
    except StrayCensusUnreadable as exc:
        reason = f'STRAY-FILE-REFUSED: the stray census could not be read: {exc}'
    roots, excluded = tmpsweep.declared()  # WRITES-STAY-IN-THE-TREE: what the session left outside the checkout
    since = time.time() - tmpsweep.REPORT_WINDOW_S
    mentions = tmpsweep.tool_text(payload.get('transcript_path'))
    outside = tmpsweep.session_report(
        roots, excluded, since=since, suffixes=CODE_SUFFIXES | {'.md', '.txt'}, mentions=mentions
    )
    reason = '\n'.join(one for one in (reason, outside) if one) or None
    if reason is not None:
        emit(json.dumps({'decision': 'block', 'reason': reason}))
    return 0


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """``hook``: the ``Stop`` agent hook on the payload in *stdin*. ``check``: exit 1 naming every stray of the cwd."""
    mode = (argv or [None])[0]
    if mode == 'check':
        reason = stray_refusal(Path.cwd())
        if reason is not None:
            emit(reason)
        return 1 if reason is not None else 0
    if mode != 'hook':
        emit('usage: python -m dev_lab.dev.strays hook|check')
        return 2
    try:
        payload = json.load(stdin or sys.stdin)
    except ValueError:
        return 0
    return _hook(payload)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
