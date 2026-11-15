"""A MAIN CHECKOUT FOLLOWS ITS BRANCH: ``python -m dev_lab.dev.mainsync --root <checkout> [--branch B] [--dry-run]``.

INCIDENT 2026-11-14: a main checkout sat on a detached HEAD 174 commits behind, and an untracked file
byte-identical to the one its branch tracks blocked ``git switch``; the only way past was a forced checkout,
which a guard rightly refuses because it cannot tell a lossless overwrite from a lost edit. This door can:

1. a TRACKED change refuses, naming each path -- the checkout holds work this door does not own;
2. it fetches through the retry door (:func:`dev_lab.dev.hostrefresh.network`);
3. an UNTRACKED file the target tracks is an obstacle only when its bytes DIFFER from the target's blob
   (``git hash-object`` against ``origin/<branch>:<path>``); an identical one is removed -- the switch
   writes the same bytes back, so nothing is lost -- and a differing one refuses, naming it, untouched;
4. a local branch that is not an ancestor of ``origin/<branch>`` DIVERGES and refuses: this door never merges;
5. it switches to the branch (tracking ``origin/<branch>`` when absent locally) and fast-forwards;
6. the venv follows through ``dep --bootstrap`` (:func:`dev_lab.dev.hostrefresh.sync_venv`), whose own
   live-run refusal is reported, never forced.

Every check runs before the first change, so a refusal leaves the checkout exactly as it was.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lab_commons.log import emit

from dev_lab.dev.hostrefresh import network, read, sync_venv
from dev_lab.dev.hpcaccount.steps import Step, Tools

__all__ = ['main', 'sync']

#: The venv door this checkout's environment moves through.
BOOTSTRAP: tuple[str, ...] = (sys.executable, '-m', 'dev_lab.dev.dep', '--bootstrap')


def _lines(git: Sequence[str], *args: str) -> list[str]:
    return [line for line in read([*git, *args]).stdout.splitlines() if line.strip()]


def _obstacles(git: Sequence[str], target: str) -> tuple[list[str], list[str]]:
    """The untracked files *target* tracks: (byte-identical ones, differing ones)."""
    identical, differing = [], []
    for path in _lines(git, 'ls-files', '--others', '--exclude-standard'):
        blob = read([*git, 'rev-parse', '-q', '--verify', f'{target}:{path}']).stdout.strip()
        if not blob:
            continue
        mine = read([*git, 'hash-object', '--', path]).stdout.strip()
        (identical if mine == blob else differing).append(path)
    return identical, differing


@dataclass(frozen=True)
class _Plan:
    """What the checks found: why it cannot move (``''`` when it can), the lossless obstacles, the local tip."""

    why: str = ''
    identical: tuple[str, ...] = ()
    local: str = ''


def _check(step: Step, here: Sequence[str], name: str, branch: str) -> _Plan:
    """Every refusal, before the first change: tracked changes, the fetch, the target, differing files, divergence."""
    if tracked := _lines(here, 'status', '--porcelain', '--untracked-files=no'):
        return _Plan(f'{name} has tracked changes, commit or discard them first: ' + ', '.join(t[3:] for t in tracked))
    if (fetched := network(step, f'{name}: git fetch', [*here, 'fetch', '-q', 'origin'])).rc:
        return _Plan(fetched.why or f'its fetch exited {fetched.rc}')
    target = f'origin/{branch}'
    if not read([*here, 'rev-parse', '-q', '--verify', target]).stdout.strip():
        return _Plan(f'{name} has no {target}; name the branch it follows with --branch')
    identical, differing = _obstacles(here, target)
    if differing:
        return _Plan(
            f'{name}: untracked files that {target} tracks and whose bytes differ from it: ' + ', '.join(differing)
        )
    local = read([*here, 'rev-parse', '-q', '--verify', f'refs/heads/{branch}']).stdout.strip()
    if local and read([*here, 'merge-base', '--is-ancestor', local, target]).returncode:
        return _Plan(f'{name}: {branch} at {local[:12]} diverges from {target}; this door never merges -- reconcile it')
    return _Plan(identical=tuple(identical), local=local)


def sync(
    root: Path, *, branch: str = 'main', bootstrap: Sequence[str] = BOOTSTRAP, git: Sequence[str] = ('git',),
    dry: bool = False,
) -> str:  # fmt: skip
    """Bring the main checkout *root* to ``origin/<branch>`` and its venv in step; ``''``, else why it cannot be."""
    if not (root / '.git').exists():
        return f'{root} is not a checkout'
    here, target = [*git, '-C', str(root)], f'origin/{branch}'
    step = Step(Tools(git=tuple(git)), dry=dry)
    if (plan := _check(step, here, root.name, branch)).why:
        return plan.why
    for path in plan.identical:
        if not dry:
            (root / path).unlink()
        emit(f'  {root.name}: {path} is byte-identical to {target}; the switch writes it back')
    switch = [*here, 'switch', '-q', branch] if plan.local else [*here, 'switch', '-q', '-c', branch, '--track', target]
    for what, argv in (
        (f'switch to {branch}', switch),
        (f'fast-forward to {target}', [*here, 'merge', '--ff-only', '-q', target]),
    ):
        if rc := step.change(f'{root.name}: {what}', argv):
            return f'its {what} exited {rc}'
    if rc := sync_venv(step, bootstrap, root):
        return f'its venv sync exited {rc}; the bootstrap printed why (a live run in it waits for that run)'
    return ''


def main(argv: Sequence[str] | None = None) -> int:
    """``mainsync --root <checkout> [--branch B] [--dry-run]``: 0, else 2 with the reason."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.mainsync', description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, required=True, help='the main checkout')
    parser.add_argument('--branch', default='main', help='the branch it follows (default: main)')
    parser.add_argument('--dry-run', action='store_true', help='print each change; make none')
    args = parser.parse_args(argv)
    if why := sync(args.root.resolve(), branch=args.branch, dry=args.dry_run):
        emit(f'[mainsync] refused: {why}')
        return 2
    emit(f'[mainsync] {args.root.name}: on {args.branch}, current with origin/{args.branch}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
