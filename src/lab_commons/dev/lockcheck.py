"""PIN + FRESHNESS -- the pre-push check that a pushed commit's lock is committed AND at the newest resolution.

User ruling 2026-10-17, superseding the same day's "dependencies float": floating broke a consumer with no
commit of its own (lab-commons renamed a module, and every venv that resolved the new tip broke), and a host's
queue refused a declaration its newer kit did not know. So every family repo COMMITS ``uv.lock`` and every
install is ``uv sync --frozen`` from it (:mod:`lab_commons.dev.dep`, the served venvs): a commit's code and its
exact dependencies are tested together and identical on every host. The lock is the reproducibility.

What keeps a pin from rotting is THIS row, the shape of the behind-push refusal: a PUSHED COMMIT IS REFUSED
(:func:`lock_problems`, judged at the pushed sha, never a dirty working tree) when

* it commits no ``uv.lock``;
* it HOLDS a requirement below the newest -- an upper bound (``<``, ``<=``), an exact pin (``==``, ``===``,
  ``~=``) or a git requirement at a ref -- with no reason: a comment on its line or the comment line above
  (:func:`unreasoned_holds`). A reasoned range is the one way to stay below latest (e.g. ``<3.14``: pyo3 ABI);
* ``uv lock --upgrade --dry-run`` at that sha would change the lock (:func:`stale`): an in-house git dependency
  behind the tip of its declared ref, a PyPI dependency below the newest its declared ranges admit;
* that resolution cannot run -- the network is down, a source is unreachable: refused with its diagnosis
  (:func:`lab_commons.dev.netverb.run_network_verb`, retried, then reported), never admitted unjudged.

The developer who pushes upgrades through :data:`DOOR` (:data:`REMEDY`); no scheduled job does it for them.
Exit codes: ``0``
allowed, ``1`` refused. Only ``refs/heads/**`` lines are judged; a deletion carries no content and is allowed.
"""

from __future__ import annotations

import contextlib
import re
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.dev.forge import _GIT
from lab_commons.dev.netverb import Report, run_network_verb
from lab_commons.log import emit

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence

__all__ = ['DOOR', 'LOCK', 'REMEDY', 'lock_problems', 'main', 'pushed_shas', 'stale', 'unreasoned_holds']

#: The lockfile every family repo commits.
LOCK: Final = 'uv.lock'
#: The one remedy for a missing or stale lock.
#: The door, never a bare ``uv lock --upgrade``: an agent guard refuses a bare dependency mutation, so a
#: remedy naming one would be a refusal pointing at another refusal.
DOOR: Final = '<venv python> -m lab_commons.dev.dep --lock-upgrade [ROOT]'
REMEDY: Final = (
    f'run `{DOOR}` (`uv lock --upgrade`, then a frozen sync of that checkout), then fix, test and commit {LOCK}'
    ' (a hold below the newest names its reason)'
)
#: How long one resolution may take, in seconds: a cold cache resolving every source is the slow case.
RESOLVE_TIMEOUT_S: Final = 600.0

_DELETED: Final = '0' * 40
_BRANCHES: Final = 'refs/heads/'
_REFSPEC_FIELDS: Final = 4
#: The change lines ``uv lock --dry-run`` prints, one per package it would move.
_CHANGE: Final = re.compile(r'^(?:Update|Add|Remove)\s+\S.*$', re.MULTILINE)
_QUOTED: Final = re.compile(r'"([^"\n]*)"|\'([^\'\n]*)\'')
_NAME: Final = re.compile(r'^\s*[A-Za-z0-9][A-Za-z0-9._-]*\s*(?:\[[^\]]*\])?\s*(?P<rest>.*)$')
_CLAUSE: Final = re.compile(r'^\s*(?P<op>~=|===|==|!=|<=|>=|<|>)\s*[\w.*+!-]+\s*$')
#: The operators that keep a requirement BELOW the newest; a floor (``>=``, ``>``) or an exclusion does not.
_HOLDING: Final = frozenset({'<', '<=', '==', '===', '~='})


def _git(root: Path, *argv: str) -> tuple[int, str]:
    done = _door.run(
        [_GIT, '-C', str(root), *argv], capture_output=True, text=True, encoding='utf-8', check=False, timeout=120
    )
    return done.returncode, done.stdout


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


@contextlib.contextmanager
def _tree_at(root: Path, sha: str) -> Iterator[Path]:
    """A directory holding commit *sha*: the checkout itself when its HEAD is *sha* and its lock inputs are clean.

    Else a detached worktree under the repository's own git directory, removed afterwards -- never outside it.
    """
    _, head = _git(root, 'rev-parse', 'HEAD')
    _, dirty = _git(root, 'status', '--porcelain', '--', 'pyproject.toml', LOCK)
    if head.strip() == sha and not dirty.strip():
        yield root
        return
    _, common = _git(root, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    tree = Path(common.strip()) / 'lockcheck' / sha[:12]
    _git(root, 'worktree', 'remove', '--force', str(tree))
    code, _ = _git(root, 'worktree', 'add', '--detach', str(tree), sha)
    if code != 0:
        msg = f'cannot check out {sha[:12]} to resolve it'
        raise OSError(msg)
    # A path dependency may point into a submodule (a product's engine crate, plan C5): the tree resolved
    # must hold it, or the build backend fails on a path that a checkout would have.
    code, _ = _git(tree, 'submodule', 'update', '--init', '--recursive')
    if code != 0:
        _git(root, 'worktree', 'remove', '--force', str(tree))
        msg = f'cannot initialise the submodules of {sha[:12]} to resolve it'
        raise OSError(msg)
    try:
        yield tree
    finally:
        _git(root, 'worktree', 'remove', '--force', str(tree))


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


def lock_problems(root: Path, sha: str, *, resolve: Callable[[Path], Report] = _dry_run) -> tuple[str, ...]:
    """Why commit *sha* of *root* may not be pushed, one sentence each; empty when its lock is pinned and newest."""
    if _git(root, 'cat-file', '-e', f'{sha}:{LOCK}')[0] != 0:
        return (f'{sha[:12]} commits no {LOCK}: its environment would be whatever resolves on the day',)
    _, manifest = _git(root, 'show', f'{sha}:pyproject.toml')
    out = [f'{hold} holds a requirement below the newest with no reason' for hold in unreasoned_holds(manifest)]
    try:
        with _tree_at(root, sha) as tree:
            out.extend(stale(tree, resolve=resolve))
    except OSError as why:
        out.append(f'the newest resolution could not run: {why}')
    return tuple(out)


def pushed_shas(lines: Iterable[str]) -> tuple[str, ...]:
    """The local shas git's pre-push lines would put on a branch; deletions and non-branch refs are skipped."""
    found = []
    for line in lines:
        fields = line.split()
        if len(fields) == _REFSPEC_FIELDS and fields[1] != _DELETED and fields[2].startswith(_BRANCHES):
            found.append(fields[1])
    return tuple(dict.fromkeys(found))


def main(
    argv: Sequence[str] | None = None,
    *,
    lines: Iterable[str] | None = None,
    resolve: Callable[[Path], Report] = _dry_run,
) -> int:
    """``python -m lab_commons.dev.lockcheck [ROOT]`` -- the pre-push entry: refspec lines on stdin."""
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else Path.cwd()
    if lines is None:
        lines = () if sys.stdin.isatty() else sys.stdin.read().splitlines()
    refused = [f'{sha[:12]}: {why}' for sha in pushed_shas(lines) for why in lock_problems(root, sha, resolve=resolve)]
    if not refused:
        return 0
    emit('[lock] REFUSED -- ' + '\n[lock]   '.join(refused) + f'\n[lock]   REMEDY: {REMEDY}.', err=True)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
