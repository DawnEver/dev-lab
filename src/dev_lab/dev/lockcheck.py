"""PIN -- the reading that a commit COMMITS its lock and holds nothing below the newest unreasoned.

User ruling 2026-10-17, superseding the same day's "dependencies float": floating broke a consumer with no
commit of its own (lab-commons renamed a module, and every venv that resolved the new tip broke), and a host's
queue refused a declaration its newer kit did not know. So every family repo COMMITS ``uv.lock`` and every
install is ``uv sync --frozen`` from it (:mod:`dev_lab.dev.dep`, the served venvs): a commit's code and its
exact dependencies are tested together and identical on every host. The lock is the reproducibility.

A COMMIT IS REFUSED (:func:`lock_problems`, judged at a sha, never a dirty working tree) when

* it commits no ``uv.lock``;
* it HOLDS a requirement below the newest -- an upper bound (``<``, ``<=``), an exact pin (``==``, ``===``,
  ``~=``) or a git requirement at a ref -- with no reason: a comment on its line or the comment line above
  (:func:`unreasoned_holds`). A reasoned range is the one way to stay below latest (e.g. ``<3.14``: pyo3 ABI).

Both read git objects only and never touch the network.

PIN AND FRESHNESS ARE THE FORGE'S ALONE (user rulings 2026-10-22 and 2026-10-24): a local hook keeps only
irreversible-harm and second-scale format checks, so no pre-push row reads the lock. The forge judges the PIN in
the repo's own suite (:mod:`dev_lab.dev.famtests.lockpin`, at the checked-out ``HEAD``), and a PR head's
freshness as a status (:mod:`dev_lab.dev.forgeheadgate`). The serve tick keeps integration at the newest
resolution itself through a relock pull request (:mod:`dev_lab.dev.relock`), reading :func:`stale` -- the one
staleness reading -- and a lane takes it with ``forge sync``.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

from dev_lab.dev.forge import _GIT
from dev_lab.dev.netverb import Report, run_network_verb

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

__all__ = [
    'DOOR', 'LOCK', 'REMEDY', 'lock_problems', 'mount_submodules', 'stale', 'unreasoned_holds',
]  # fmt: skip

#: The lockfile every family repo commits.
LOCK: Final = 'uv.lock'
#: The one remedy for a missing or stale lock.
#: The door, never a bare ``uv lock --upgrade``: an agent guard refuses a bare dependency mutation, so a
#: remedy naming one would be a refusal pointing at another refusal.
DOOR: Final = '<venv python> -m dev_lab.dev.dep --lock-upgrade [ROOT]'
REMEDY: Final = (
    f'run `{DOOR}` (`uv lock --upgrade`, then a frozen sync of that checkout), then fix, test and commit {LOCK}'
    ' (a hold below the newest names its reason)'
)
#: How long one resolution may take, in seconds: a cold cache resolving every source is the slow case.
RESOLVE_TIMEOUT_S: Final = 600.0

#: The change lines ``uv lock --dry-run`` prints, one per package it would move.
_CHANGE: Final = re.compile(r'^(?:Update|Add|Remove)\s+\S.*$', re.MULTILINE)
_QUOTED: Final = re.compile(r'"([^"\n]*)"|\'([^\'\n]*)\'')
_NAME: Final = re.compile(r'^\s*[A-Za-z0-9][A-Za-z0-9._-]*\s*(?:\[[^\]]*\])?\s*(?P<rest>.*)$')
_CLAUSE: Final = re.compile(r'^\s*(?P<op>~=|===|==|!=|<=|>=|<|>)\s*[\w.*+!-]+\s*$')
#: The operators that keep a requirement BELOW the newest; a floor (``>=``, ``>``) or an exclusion does not.
_HOLDING: Final = frozenset({'<', '<=', '==', '===', '~='})


def _git(root: Path, *argv: str, env: Mapping[str, str] | None = None) -> tuple[int, str]:
    done = _door.run(
        [_GIT, '-C', str(root), *argv],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=120,
        env=env,
    )
    return done.returncode, done.stdout


#: The variables that point git at ONE repository. A hook runs with them set to the repository pushing, so a
#: clone or checkout of ANOTHER repository from inside a hook must run without them.
_REPOSITORY_LOCATORS: Final = frozenset({
    'GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES',
    'GIT_COMMON_DIR', 'GIT_PREFIX',
})  # fmt: skip


def _unlocated() -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if name not in _REPOSITORY_LOCATORS}


def _holds(text: str) -> bool:
    """Whether quoted *text* is a requirement (or a bare specifier set) that keeps something below the newest."""
    named = _NAME.match(text)
    rest = (named['rest'] if named else text).split(';', 1)[0].strip()
    if rest.startswith('@'):
        url = rest[1:].strip()
        return url.startswith('git+') and '@' in url.removeprefix('git+').split('://', 1)[-1].split('#', 1)[0]
    if not rest:
        return False
    clauses = [_CLAUSE.match(clause) for clause in rest.split(',')]
    return all(clauses) and any(clause['op'] in _HOLDING for clause in clauses if clause)


def unreasoned_holds(manifest: str) -> tuple[str, ...]:
    """Every requirement of pyproject text *manifest* held below the newest with no reason, as ``line N: <text>``.

    A reason is a ``#`` comment on the requirement's own line or the line above it.
    """
    lines = manifest.splitlines()
    found = []
    for index, line in enumerate(lines):
        if line.lstrip().startswith('#'):
            continue
        for match in _QUOTED.finditer(line):
            text = match[1] if match[1] is not None else match[2]
            if not _holds(text):
                continue
            above = lines[index - 1].lstrip() if index else ''
            if '#' not in line[match.end() :] and not above.startswith('#'):
                found.append(f'line {index + 1}: "{text}"')
    return tuple(found)


def mount_submodules(root: Path, tree: Path) -> None:
    """Give *tree* every submodule its commit records, each an INDEPENDENT clone of *root*'s checkout of it.

    A path dependency may point into a submodule (a product's engine crate, plan C5), so the tree resolved must
    hold it. `git submodule update` inside a linked worktree writes the submodule's SHARED git state (its
    ``core.worktree``) and strands every other checkout of it; a ``--shared`` clone writes nothing shared.
    """
    _, listing = _git(tree, 'ls-tree', '-r', 'HEAD')
    for line in listing.splitlines():
        meta, _, path = line.partition('	')
        mode, _, gitlink = meta.split()
        if mode != '160000':
            continue
        source, target = root / path, tree / path
        if not (source / '.git').exists():
            msg = f'{path} is not initialised in {root}; run `git submodule update --init` there to resolve this sha'
            raise OSError(msg)
        if target.is_dir() and not any(target.iterdir()):
            target.rmdir()  # git leaves an empty directory at an uninitialised submodule
        bare = _unlocated()
        code, _ = _git(root, 'clone', '--quiet', '--no-checkout', '--shared', str(source), str(target), env=bare)
        if code == 0:
            code, _ = _git(target, 'checkout', '--quiet', gitlink, env=bare)
        if code != 0:
            msg = f'cannot mount submodule {path} at {gitlink[:12]} to resolve this sha'
            raise OSError(msg)


def _dry_run(tree: Path) -> Report:
    uv = shutil.which('uv') or 'uv'
    return run_network_verb([uv, 'lock', '--upgrade', '--dry-run'], cwd=tree, timeout=RESOLVE_TIMEOUT_S)


def stale(tree: Path, *, resolve: Callable[[Path], Report] = _dry_run) -> tuple[str, ...]:
    """Why the lock in *tree* is not at the newest resolution, one sentence each; empty when it is.

    A resolution that could not run is one sentence carrying its diagnosis, so it refuses rather than admits.
    """
    try:
        report = resolve(tree)
    except OSError as why:
        return (f'the newest resolution could not run: {why}',)
    output = report.attempts[-1].output if report.attempts else ''
    if not report.ok:
        tail = ' | '.join(line.strip() for line in output.strip().splitlines()[-4:])
        return (f'the newest resolution could not run ({report.remedy}): {tail}',)
    return tuple(f'{LOCK} is not the newest resolution: {change.strip()}' for change in _CHANGE.findall(output))


def lock_problems(root: Path, sha: str) -> tuple[str, ...]:
    """Why commit *sha* of *root* may not be pushed, one sentence each; empty when its lock is pinned."""
    if _git(root, 'cat-file', '-e', f'{sha}:{LOCK}')[0] != 0:
        return (f'{sha[:12]} commits no {LOCK}: its environment would be whatever resolves on the day',)
    _, manifest = _git(root, 'show', f'{sha}:pyproject.toml')
    return tuple(f'{hold} holds a requirement below the newest with no reason' for hold in unreasoned_holds(manifest))
