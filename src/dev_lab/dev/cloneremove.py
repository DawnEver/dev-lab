"""CLONE-REMOVE: the door that removes a whole redundant clone, refused while anything in it is unique.

RECURSIVE-DELETE refuses every raw recursive delete, and its doors cover scratch, lanes and linked worktrees -- none
covers a WHOLE CLONE a user decided is redundant (2026-11-19: a second clone of a family repo outside the
checkout). This is that door. It refuses, naming each cause, while:

* a branch (or a linked worktree's detached HEAD) carries commits on no remote;
* any of its trees holds uncommitted or untracked work, or the clone holds a stash;
* a live process works in, executes from or reads it (:func:`dev_lab.dev.liverun.removal_holders`);
* a declared consumer still points at it: a machine-file ``[repos]`` row naming it or a path inside it.

Then it removes the linked worktrees, then the folder -- moved aside first, so a holder Windows reports refuses
before a byte is gone -- and writes one line echoing the user's words, like ``branchset --discard --approved``.

``python -m dev_lab.dev.cloneremove <path> --approved "<the user's words>"``; exit 1 with every cause, else 0.
"""

from __future__ import annotations

import argparse
import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from lab_commons import config as machineconfig
from lab_commons.census import processes
from lab_commons.log import emit

from dev_lab.dev.checkout import git_out
from dev_lab.dev.diskusage import remove_tree
from dev_lab.dev.liverun import Census, removal_holders

__all__ = ['EVENT', 'RULE_ID', 'consumers', 'main', 'refusals', 'remove']

RULE_ID: Final = 'CLONE-REMOVE'
EVENT: Final = 'dev_lab.clone-remove'


def consumers() -> dict[str, str]:
    """The machine file's ``[repos]`` rows as ``repos.<name> -> path`` (``{}`` when there is no file)."""
    path = machineconfig.config_path()
    live = tomllib.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    table = live.get('repos', {})
    return {f'repos.{name}': str(where) for name, where in table.items()} if isinstance(table, Mapping) else {}


def _inside(path: str, clone: Path) -> bool:
    try:
        Path(path).resolve().relative_to(clone.resolve())
    except (OSError, ValueError):
        return False
    return True


def _trees(clone: Path) -> list[tuple[Path, str]]:
    """``(tree, HEAD sha)`` of the clone and each linked worktree, from ``git worktree list --porcelain``."""
    found: list[tuple[Path, str]] = []
    tree: Path | None = None
    for line in (git_out(clone, 'worktree', 'list', '--porcelain') or '').splitlines():
        if line.startswith('worktree '):
            tree = Path(line.removeprefix('worktree '))
        elif line.startswith('HEAD ') and tree is not None:
            found.append((tree, line.removeprefix('HEAD ')))
    return found


def refusals(clone: Path, *, census: Census, declared: Mapping[str, str]) -> list[str]:
    """Every reason *clone* must stay; ``[]`` when nothing in it is unique."""
    if not (clone / '.git').is_dir():
        return [f'{clone} is not a main checkout (no .git directory): only a whole clone goes through this door']
    found: list[str] = []
    heads = (git_out(clone, 'for-each-ref', '--format=%(refname:short) %(objectname)', 'refs/heads') or '').split('\n')
    tips = [tuple(row.split(' ', 1)) for row in heads if ' ' in row]
    tips += [(f'detached HEAD of {tree}', sha) for tree, sha in _trees(clone)[1:]]
    for name, sha in tips:
        alone = (git_out(clone, 'rev-list', '--count', sha, '--not', '--remotes') or '0').strip()
        if alone not in {'', '0'}:
            found.append(f'{name} carries {alone} commit(s) on no remote: push it through a PR first')
    trees = _trees(clone)
    for tree, _sha in trees:
        nested = [other.resolve() for other, _ in trees if other != tree and _inside(str(other), tree)]
        changed = [
            line[3:].strip().strip('"')
            for line in (git_out(tree, 'status', '--porcelain', '--untracked-files=all') or '').splitlines()
            if line.strip()
        ]
        if [path for path in changed if not any(_inside(str(tree / path), one) for one in nested)]:
            found.append(f'{tree} holds uncommitted or untracked work: commit it on a branch and land it first')
    if (git_out(clone, 'stash', 'list') or '').strip():
        found.append(f'{clone} holds a stash: apply it on a branch and land it, or the user drops it first')
    found += [
        f'process {one.pid} ({one.command_line[:80]}) holds {clone}: stop it first'
        for one in removal_holders(clone, census=census)
    ]
    found += [
        f'{key} still points at {where}: point it at the kept checkout first'
        for key, where in sorted(declared.items())
        if _inside(where, clone)
    ]
    return found


def remove(
    clone: Path, approved: str, *, census: Census = processes, declared: Mapping[str, str] | None = None
) -> tuple[int, str]:
    """Remove *clone* the user approved (*approved*: their words); ``(exit code, the one line)``."""
    if not approved.strip():
        return 1, f'{RULE_ID}: refused -- removing a whole clone needs the user own words in --approved'
    if found := refusals(clone, census=census, declared=consumers() if declared is None else declared):
        return 1, f'{RULE_ID}: {clone} stays:\n' + '\n'.join(f'  {why}' for why in found)
    for tree, _sha in _trees(clone)[1:]:
        git_out(clone, 'worktree', 'remove', '--force', str(tree))
    aside = clone.with_name(f'{clone.name}.removing')
    try:
        clone.rename(aside)
    except OSError as error:
        return 1, f'{RULE_ID}: {clone} stays (in use -- {error}; nothing more was deleted)'
    remove_tree(aside)
    record = {'event': EVENT, 'path': str(clone), 'approved': approved.strip()}
    return 0, f'{json.dumps(record)}\nremoved clone {clone} -- approved: "{approved.strip()}"'


def main(argv: list[str] | None = None) -> int:
    """``<path> --approved "<words>"``: remove a whole clone nothing unique lives in."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.cloneremove', description=main.__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--approved', required=True, help="the user's own words approving the removal")
    args = parser.parse_args(argv)
    code, line = remove(args.path, args.approved)
    emit(line, err=code != 0)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
