"""PIN -- the pre-push check that a pushed commit COMMITS its lock and holds nothing below the newest unreasoned.

User ruling 2026-10-17, superseding the same day's "dependencies float": floating broke a consumer with no
commit of its own (lab-commons renamed a module, and every venv that resolved the new tip broke), and a host's
queue refused a declaration its newer kit did not know. So every family repo COMMITS ``uv.lock`` and every
install is ``uv sync --frozen`` from it (:mod:`dev_lab.dev.dep`, the served venvs): a commit's code and its
exact dependencies are tested together and identical on every host. The lock is the reproducibility.

A PUSHED COMMIT IS REFUSED (:func:`lock_problems`, judged at the pushed sha, never a dirty working tree) when

* it commits no ``uv.lock``;
* it HOLDS a requirement below the newest -- an upper bound (``<``, ``<=``), an exact pin (``==``, ``===``,
  ``~=``) or a git requirement at a ref -- with no reason: a comment on its line or the comment line above
  (:func:`unreasoned_holds`). A reasoned range is the one way to stay below latest (e.g. ``<3.14``: pyo3 ABI);
* it commits Rust (a ``Cargo.toml``) without a root ``rust-toolchain.toml`` pinning ONE exact version, never a
  channel name like ``stable`` (user ruling 2026-10-25: the toolchain is pinned exactly like the lock;
  :func:`toolchain_problems`).

All read git objects only: the row costs milliseconds and never touches the network.

FRESHNESS IS THE FORGE'S ALONE (2026-10-21 for lanes; user ruling 2026-10-22 for every branch): a hook keeps
only irreversible-harm and second-scale checks, and a resolution is neither -- it is minutes of network that
refused a push whenever any dependency published. The serve tick keeps integration at the newest resolution
itself through a relock pull request (:mod:`dev_lab.dev.relock`), reading :func:`stale` -- the one
staleness reading, of the lock and of the toolchain against :func:`newest_stable` -- and a lane takes it with
``forge sync``.
Exit codes: ``0`` allowed, ``1`` refused. Only ``refs/heads/**`` lines are judged; a deletion carries no content
and is allowed, and a sha a remote branch already holds was judged when it was first pushed (:func:`published`).
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.forge import _GIT
from dev_lab.dev.netverb import Report, run_network_verb

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

__all__ = [
    'DOOR', 'FRESHENED', 'LOCK', 'REMEDY', 'TOOLCHAIN', 'lock_problems', 'main', 'mount_submodules',
    'newest_stable', 'pin_stable', 'published', 'pushed_refs', 'refreshable', 'stale', 'toolchain_problems',
    'unreasoned_holds',
]  # fmt: skip

#: The lockfile every family repo commits.
LOCK: Final = 'uv.lock'
#: The Rust toolchain pin every repository committing Rust carries at its root.
TOOLCHAIN: Final = 'rust-toolchain.toml'
#: The pinned inputs the forge keeps at the newest; a :func:`stale` sentence naming one is :func:`refreshable`.
FRESHENED: Final = (LOCK, TOOLCHAIN)
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
_CHANNEL: Final = re.compile(r'^(?P<lead>\s*channel\s*=\s*)["\'](?P<channel>[^"\'\n]*)["\']', re.MULTILINE)
_EXACT: Final = re.compile(r'^\d+\.\d+\.\d+$')
#: ``rustup check``'s stable line: ``Up to date : <v> (...)`` or ``Update available : <old> (...) -> <v> (...)``.
_STABLE: Final = re.compile(
    r'^stable-\S+ - (?:Up to date : |Update available : .*-> )(?P<version>\d+\.\d+\.\d+)\b', re.MULTILINE
)


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


def _rustup_check() -> Report:
    rustup = shutil.which('rustup') or 'rustup'
    return run_network_verb([rustup, 'check'], timeout=RESOLVE_TIMEOUT_S)


def newest_stable(*, check: Callable[[], Report] = _rustup_check) -> str:
    """The newest stable Rust version (``1.99.1``) as *check*, ``rustup check``, reports it; RAISES on none."""
    report = check()
    output = report.attempts[-1].output if report.attempts else ''
    if not report.ok or not (found := _STABLE.search(output)):
        msg = f'rustup check named no stable toolchain ({report.remedy}): {output.strip()[-200:]}'
        raise OSError(msg)
    return found['version']


def _channel(text: str) -> str | None:
    found = _CHANNEL.search(text)
    return found['channel'] if found else None


def toolchain_problems(root: Path, sha: str) -> tuple[str, ...]:
    """Why commit *sha* of *root* does not pin one exact Rust toolchain, one sentence; empty without Rust."""
    _, names = _git(root, 'ls-tree', '-r', '--name-only', sha)
    if not any(name.rsplit('/', 1)[-1] == 'Cargo.toml' for name in names.splitlines()):
        return ()
    if _git(root, 'cat-file', '-e', f'{sha}:{TOOLCHAIN}')[0] != 0:
        return (f'{sha[:12]} commits Rust but no {TOOLCHAIN}: its toolchain would be whatever is installed',)
    channel = _channel(_git(root, 'show', f'{sha}:{TOOLCHAIN}')[1])
    if channel is None or not _EXACT.match(channel):
        return (f'{sha[:12]} {TOOLCHAIN} pins channel "{channel}", not one exact version like "1.99.1"',)
    return ()


def pin_stable(tree: Path, version: str) -> None:
    """Rewrite the channel of *tree*'s :data:`TOOLCHAIN` to *version*, every other line as it was."""
    path = tree / TOOLCHAIN
    text = path.read_text(encoding='utf-8')
    path.write_text(_CHANNEL.sub(lambda m: f'{m["lead"]}"{version}"', text, count=1), encoding='utf-8')


def refreshable(sentence: str) -> bool:
    """Whether a :func:`stale` sentence names a :data:`FRESHENED` input the dependency door moves."""
    return sentence.startswith(tuple(f'{path} is not the newest ' for path in FRESHENED))


def stale(
    tree: Path, *, resolve: Callable[[Path], Report] = _dry_run, stable: Callable[[], str] = newest_stable
) -> tuple[str, ...]:
    """Why the lock or the toolchain in *tree* is not at the newest, one sentence each; empty when both are.

    A resolution that could not run is one sentence carrying its diagnosis, so it refuses rather than admits.
    The toolchain is read against *stable* only where *tree* pins one.
    """
    try:
        report = resolve(tree)
    except OSError as why:
        return (f'the newest resolution could not run: {why}',)
    output = report.attempts[-1].output if report.attempts else ''
    if not report.ok:
        tail = ' | '.join(line.strip() for line in output.strip().splitlines()[-4:])
        return (f'the newest resolution could not run ({report.remedy}): {tail}',)
    found = tuple(f'{LOCK} is not the newest resolution: {change.strip()}' for change in _CHANGE.findall(output))
    if not (tree / TOOLCHAIN).is_file():
        return found
    try:
        newest = stable()
    except OSError as why:
        return (*found, f'the newest stable toolchain could not be read: {why}')
    pinned = _channel((tree / TOOLCHAIN).read_text(encoding='utf-8'))
    return found if pinned == newest else (*found, f'{TOOLCHAIN} is not the newest stable: {pinned} -> {newest}')


def lock_problems(root: Path, sha: str) -> tuple[str, ...]:
    """Why commit *sha* of *root* may not be pushed, one sentence each; empty when its lock is pinned."""
    if _git(root, 'cat-file', '-e', f'{sha}:{LOCK}')[0] != 0:
        return (f'{sha[:12]} commits no {LOCK}: its environment would be whatever resolves on the day',)
    _, manifest = _git(root, 'show', f'{sha}:pyproject.toml')
    holds = tuple(f'{hold} holds a requirement below the newest with no reason' for hold in unreasoned_holds(manifest))
    return holds + toolchain_problems(root, sha)


def pushed_refs(lines: Iterable[str]) -> tuple[tuple[str, str], ...]:
    """``(sha, branch)`` per pre-push line putting a commit on a branch; deletions and non-branch refs are skipped."""
    found = []
    for line in lines:
        fields = line.split()
        if len(fields) == _REFSPEC_FIELDS and fields[1] != _DELETED and fields[2].startswith(_BRANCHES):
            found.append((fields[1], fields[2].removeprefix(_BRANCHES)))
    return tuple(dict.fromkeys(found))


def published(root: Path, sha: str) -> bool:
    """Whether a remote branch already holds *sha*: it was judged when it was first pushed, so it is not judged again.

    A promotion fast-forwards `main` to a sha the integration branch already carries; re-resolving it against
    a newer kit would refuse every verified sha the moment any dependency moved.
    """
    code, held = _git(root, 'branch', '-r', '--contains', sha)
    return code == 0 and bool(held.strip())


def main(argv: Sequence[str] | None = None, *, lines: Iterable[str] | None = None) -> int:
    """``python -m dev_lab.dev.lockcheck [ROOT]`` -- the pre-push entry: refspec lines on stdin."""
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else Path.cwd()
    if lines is None:
        lines = () if sys.stdin.isatty() else sys.stdin.read().splitlines()
    shas = dict.fromkeys(sha for sha, _ in pushed_refs(lines) if not published(root, sha))
    refused = [f'{sha[:12]}: {why}' for sha in shas for why in lock_problems(root, sha)]
    if not refused:
        return 0
    emit('[lock] REFUSED -- ' + '\n[lock]   '.join(refused) + f'\n[lock]   REMEDY: {REMEDY}.', err=True)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
