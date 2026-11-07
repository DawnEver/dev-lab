"""THE FORGE RELOCKS INTEGRATION: a stale ``uv.lock`` on ``origin/<integration>`` rides ONE ROLLING pull request.

So does every other :data:`~dev_lab.dev.lockcheck.FRESHENED` input below the newest -- the Rust toolchain and
dev-lab's uv pin, which is written by the uv it raises to (a host without that uv refuses, naming the update).

FRESHNESS IS ONE PARTY'S JOB (2026-10-21). Every commit is judged on its PIN alone, on the forge
(:mod:`dev_lab.dev.famtests.lockpin`), and each ``forge serve`` tick runs :func:`carry`
(:func:`dev_lab.dev.forgeservesteps.relock`).

ONE ROLLING RELOCK PER REPO (user ruling 2026-11-05). Consumers follow their in-house siblings' integration line,
so every sibling merge made every consumer's lock stale, and each opened its own ``pr/relock-<dist>-<sha>``
pull request with a full verification: 114 relock merges in two weeks, half of all merges in the small repos.
Now the relock lives on ONE branch, :data:`BRANCH`, with no sha in its name:

* :func:`carry` reads ``origin/<integration>`` through :func:`dev_lab.dev.lockcheck.stale` -- the ONE staleness
  reading -- in a detached worktree under the repository's git directory, and :func:`chosen` keeps the moves due;
* nothing due: an open relock pull request is closed (integration already holds what it carried), else nothing;
* the open relock already carries exactly these moves on exactly this integration tip (:func:`carried`): nothing;
* else the door rewrites the lock ON THE CURRENT TIP -- a tip that moved while the pull request was open is
  rebuilt on, never merged into -- and the files the new pin renders are rendered again in the same tree
  (:func:`rerender`); both are ONE commit on integration, force-pushed to :data:`BRANCH` with a lease on the
  head it replaces (a racing writer loses the push and the next tick reads afresh), and the open pull request's
  body is rewritten, or one is opened. It merges like every other once its parts pass.

THIRD-PARTY MOVES ON A CADENCE, IN-HOUSE MOVES AT ONCE (user ruling 2026-11-05). A moved package is IN-HOUSE when
the lock sources it from git FOLLOWING a line -- no ``rev``/``tag`` pin (:func:`in_house`): exactly a floated
family sibling, read off the lock, never listed. Everything else -- an index package, the Rust toolchain, the uv
pin -- is third-party and moves only when :func:`third_party_due`: the newest relock commit on integration's
history that carried the full upgrade (trailer :data:`SCOPE` ``full``) is at least the repo's declared
``[tool.dev_lab.relock] third_party_every`` old (:func:`cadence`, default :data:`DEFAULT_CADENCE`). Declared in
the REPO'S pyproject, not a host's serve config: every host serving the repo reads the one cadence at the tip it
relocks. An in-house relock before the cadence upgrades only its sibling names (``--upgrade-package``), so a
third-party move never rides early.

A step that cannot finish RAISES :class:`RelockFailed` naming why (no integration branch, the resolution could
not run, the door failed or moved nothing, the push lost its lease); the serve step alarms it and the next tick
tries afresh.
"""

from __future__ import annotations

import contextlib
import re
import shutil
import sys
import tomllib
from collections.abc import Callable, Iterator, Sequence
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final, NamedTuple
from urllib.parse import parse_qs, unquote

import lab_commons.launch as _door

from dev_lab.dev._dep_project import follow_pin, uv_remedy
from dev_lab.dev.ciworkflows import WORKFLOW_DIRS
from dev_lab.dev.family import declared_table
from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S
from dev_lab.dev.forgenotice import duration
from dev_lab.dev.labsession import machine_env
from dev_lab.dev.lockcheck import (
    FRESHENED,
    LOCK,
    TOOLCHAIN,
    UV_PIN,
    mount_submodules,
    newest_stable,
    newest_uv,
    refreshable,
    stale,
)
from dev_lab.dev.netverb import run_network_verb

if TYPE_CHECKING:
    from dev_lab.dev.forgework import PullRequest
    from dev_lab.dev.lanepolicy import Policy
    from dev_lab.dev.netverb import Report

__all__ = [
    'BRANCH',
    'DEFAULT_CADENCE',
    'DEFAULT_LINE',
    'FULL',
    'IN_HOUSE',
    'RENDERED',
    'SCOPE',
    'TITLE',
    'Floated',
    'RelockFailed',
    'cadence',
    'carried',
    'carry',
    'chosen',
    'detached_worktree',
    'dist_of',
    'door_upgrade',
    'floated',
    'in_house',
    'rerender',
    'siblings',
    'third_party_due',
]  # fmt: skip

#: THE one relock branch of a repository, inside the declared ephemeral ``pr/*`` namespace; no sha in its name.
BRANCH: Final = 'pr/relock'
#: The title of every relock commit and pull request; what it carries is in its body.
TITLE: Final = 'build(deps): relock to the newest resolution'
#: The trailer a relock commit names its scope by: :data:`FULL` (every move) or :data:`IN_HOUSE` (siblings only).
SCOPE: Final = 'Relock-Scope'
FULL: Final = 'full'
IN_HOUSE: Final = 'in-house'
#: The line a floated sibling follows when its git source names no ``branch``.
DEFAULT_LINE: Final = 'integrate/main'
#: How often third-party moves land where the repo declares no ``[tool.dev_lab.relock] third_party_every``.
DEFAULT_CADENCE: Final = timedelta(days=1)
_TABLE: Final = 'relock'
_KEYS: Final = frozenset({'third_party_every'})

#: The directories a render writes (:data:`dev_lab.dev.ciworkflows.WORKFLOW_DIRS`), staged with the lock.
RENDERED: Final = tuple(sorted({path.as_posix() for path in WORKFLOW_DIRS.values()}))

#: How much of a sha names a commit in what the relock says -- enough to be unique on one host, short to read.
SHORT: Final = 12

#: How long the dependency door may take: a cold cache resolving every source, then a frozen sync.
DOOR_TIMEOUT_S: Final = 1800.0

#: The verbs a resolution's change line opens with, and where the distribution sits after one.
_VERBS: Final = frozenset({'Update', 'Add', 'Remove'})
_NAME_INDEX: Final = 2
#: A git source query that holds the package at one commit rather than following a line.
_HELD_GIT: Final = re.compile(r'[?&](?:rev|tag)=')


class RelockFailed(OSError):
    """A relock that could not be carried, with the reason; the next tick tries afresh."""


def dist_of(change: str) -> str:
    """The distribution a :func:`~dev_lab.dev.lockcheck.stale` sentence names.

    The sentence is ``uv.lock is not the newest resolution: Update pint v0.26.1 -> v0.26.2``; the word after
    the verb is the distribution, a toolchain sentence answers ``'rust'``, a uv pin sentence ``'uv'``,
    and a sentence of another shape answers ``'lock'`` rather than guessing.
    """
    if change.startswith(f'{TOOLCHAIN} '):
        return 'rust'
    if change.startswith(f'{UV_PIN} '):
        return 'uv'
    _, _, rest = change.partition('resolution: ')
    words = rest.split()
    name = words[1] if len(words) >= _NAME_INDEX and words[0] in _VERBS else ''
    return name or 'lock'


def _canon(name: str) -> str:
    """PEP 503's normal form: the lock's and a change line's spellings meet here."""
    return re.sub(r'[-_.]+', '-', name).lower()


class Floated(NamedTuple):
    """One sibling the lock sources from git FOLLOWING a line: its name, repository, line and locked commit."""

    name: str
    url: str
    branch: str
    sha: str


def floated(lock: str) -> tuple[Floated, ...]:
    """The packages lock text *lock* sources from git FOLLOWING a line (no ``rev``/``tag``), in lock order.

    The line is the source's ``branch`` query, else :data:`DEFAULT_LINE`. An unreadable lock follows nothing.
    """
    try:
        packages = tomllib.loads(lock).get('package', [])
    except tomllib.TOMLDecodeError:
        return ()
    found = []
    for entry in packages:
        source = entry.get('source', {}) if isinstance(entry, dict) else {}
        locator = source.get('git') if isinstance(source, dict) else None
        if not isinstance(locator, str) or not isinstance(entry.get('name'), str):
            continue
        address, _, sha = locator.partition('#')
        if _HELD_GIT.search(address):
            continue
        url, _, query = address.partition('?')
        branch = parse_qs(query).get('branch', [DEFAULT_LINE])[0]
        found.append(Floated(_canon(entry['name']), url, unquote(branch), sha))
    return tuple(found)


def in_house(lock: str) -> frozenset[str]:
    """The names of :func:`floated`: the siblings an in-house relock moves off-cadence."""
    return frozenset(one.name for one in floated(lock))


def siblings(tree: Path) -> frozenset[str]:
    """The floated siblings (:func:`in_house`) of *tree*'s lock; none where *tree* commits no lock."""
    return in_house((tree / LOCK).read_text(encoding='utf-8')) if (tree / LOCK).is_file() else frozenset()


def chosen(found: Sequence[str], siblings: frozenset[str], *, due: bool) -> tuple[str, ...]:
    """The :func:`~dev_lab.dev.lockcheck.stale` sentences of *found* a relock carries now.

    Every one when third-party moves are *due*; else only those moving a sibling of *siblings*.
    """
    return tuple(found) if due else tuple(line for line in found if _canon(dist_of(line)) in siblings)


def cadence(manifest: str) -> timedelta:
    """``[tool.dev_lab.relock] third_party_every`` of pyproject text *manifest*, else :data:`DEFAULT_CADENCE`."""
    table = declared_table(tomllib.loads(manifest), _TABLE, {})
    if unknown := sorted(set(table) - _KEYS):
        msg = f'[tool.dev_lab.{_TABLE}] has unknown key(s) {unknown}; the keys are {sorted(_KEYS)}'
        raise ValueError(msg)
    text = table.get('third_party_every')
    return DEFAULT_CADENCE if text is None else duration('third_party_every', str(text))


def third_party_due(root: Path, tip: str, every: timedelta, now: float) -> bool:
    """Whether the newest full relock in *tip*'s history is at least *every* older than *now* (epoch seconds).

    None in the history: due. Read off the commits (the :data:`SCOPE` trailer), so no state is kept anywhere.
    """
    code, stamp = _git(root, 'log', '-1', '--format=%ct', f'--grep=^{SCOPE}: {FULL}$', tip)
    if code != 0 or not stamp.isdigit():
        return True
    return now - int(stamp) >= every.total_seconds()


def _git(root: Path, *argv: str) -> tuple[int, str]:
    done = _door.run(
        [_GIT, '-C', str(root), *argv], capture_output=True, text=True, encoding='utf-8', errors='replace',
        check=False, timeout=_GIT_TIMEOUT_S, env=machine_env(root),  # a relock commit is the forge's, no session's
    )  # fmt: skip
    return done.returncode, (done.stdout + done.stderr).strip()


def _must(root: Path, *argv: str) -> str:
    code, out = _git(root, *argv)
    if code != 0:
        msg = f'git {" ".join(argv[:2])} failed in {root}: {out}'
        raise RelockFailed(msg)
    return out


def _changes(lines: Sequence[str]) -> str:
    return '\n'.join(f'- {line}' for line in lines)


def carried(root: Path, head: str, tip: str, lines: Sequence[str]) -> bool:
    """Whether relock commit *head* sits directly on *tip* and carries exactly the moves *lines* say."""
    code, parent = _git(root, 'rev-parse', '--verify', '--quiet', f'{head}^')
    if code != 0 or parent != tip:
        return False
    body = _git(root, 'log', '-1', '--format=%B', head)[1].split('\n\nThird-party moves held', 1)[0]
    return sorted(line[2:] for line in body.splitlines() if line.startswith('- ')) == sorted(lines)


@contextlib.contextmanager
def detached_worktree(root: Path, sha: str) -> Iterator[Path]:
    """A detached worktree of *root* at *sha* under its git directory, with its submodules; removed after."""
    common = Path(_must(root, 'rev-parse', '--path-format=absolute', '--git-common-dir'))
    tree = common / 'relock' / sha[:SHORT]
    _git(root, 'worktree', 'remove', '--force', str(tree))
    _must(root, 'worktree', 'add', '--detach', str(tree), sha)
    try:
        mount_submodules(root, tree)
        yield tree
    finally:
        _git(root, 'worktree', 'remove', '--force', str(tree))


def door_upgrade(tree: Path, packages: Sequence[str] = ()) -> int:
    """The one writer of a lock: ``dev_lab.dev.dep --lock-upgrade <tree>``, moving only *packages* when named."""
    argv = [sys.executable, '-m', 'dev_lab.dev.dep', '--lock-upgrade', str(tree)]
    argv += [f'--upgrade-package={package}' for package in packages]
    return _door.run(argv, check=False, timeout=DOOR_TIMEOUT_S, cwd=tree).returncode


def _tree_python(tree: Path) -> str:
    """The interpreter the door synced into *tree*: it holds the NEW pin.

    Raises RelockFailed when *tree* has no ``.venv``: this interpreter holds the OLD pin, and rendering with it
    would carry the stale workflow the relock exists to replace.
    """
    for candidate in (tree / '.venv' / 'Scripts' / 'python.exe', tree / '.venv' / 'bin' / 'python'):
        if candidate.is_file():
            return str(candidate)
    msg = f'{tree} has no .venv: the render needs the interpreter that holds the new pin; run the lock door first'
    raise RelockFailed(msg)


def rerender(tree: Path) -> int:
    """Render *tree*'s generated workflows with the dev-lab its lock now pins (``dev_lab.dev.ciworkflows render``).

    A tree that declares no workflow table renders nothing and answers 0.
    """
    manifest = tree / 'pyproject.toml'
    if not manifest.is_file() or '[tool.dev_lab.ci' not in manifest.read_text(encoding='utf-8'):
        return 0
    argv = [_tree_python(tree), '-m', 'dev_lab.dev.ciworkflows', 'render', '--root', str(tree)]
    return _door.run(argv, check=False, timeout=DOOR_TIMEOUT_S, cwd=tree).returncode


def _follow_host_uv(version: str) -> str:
    """Move the uv on this host's PATH to *version* (:func:`~dev_lab.dev.uvfollow.follow`); ``''`` once it is."""
    uv = shutil.which('uv')
    return follow_pin(uv, version) if uv else 'this host has no uv on PATH'


def _uv_raise(lines: Sequence[str]) -> str | None:
    """The uv version a relock raises the pin to, read from its uv sentence; ``None`` when it raises none."""
    for line in lines:
        if line.startswith(f'{UV_PIN} '):
            return line.rsplit('-> ', 1)[-1].strip()
    return None


def _remote_head(root: Path) -> str:
    """The sha origin's :data:`BRANCH` holds, fetched here when absent; ``''`` when origin holds none."""
    report = run_network_verb([_GIT, '-C', str(root), 'ls-remote', 'origin', f'refs/heads/{BRANCH}'], timeout=300)
    if not report.ok:
        msg = f'origin could not be asked for {BRANCH}: {report.remedy}'
        raise RelockFailed(msg)
    sha = (report.attempts[-1].output.split() or [''])[0] if report.attempts else ''
    if sha and _git(root, 'cat-file', '-e', f'{sha}^{{commit}}')[0] != 0:
        run_network_verb([_GIT, '-C', str(root), 'fetch', '--quiet', 'origin', sha], timeout=300)
    return sha


def _push(tree: Path, lease: str) -> None:
    """Force *tree*'s HEAD onto origin's :data:`BRANCH`, only while origin still holds *lease* (``''``: none)."""
    argv = [_GIT, 'push', f'--force-with-lease=refs/heads/{BRANCH}:{lease}', 'origin', f'HEAD:refs/heads/{BRANCH}']
    report = run_network_verb(argv, cwd=tree, timeout=300)
    if not report.ok:
        msg = f'the push of {BRANCH} failed (a lease lost to a racing writer reads afresh next tick): {report.remedy}'
        raise RelockFailed(msg)


def _body(tip: str, scope: str, lines: Sequence[str], held: Sequence[str]) -> str:
    waiting = f'\n\nThird-party moves held for the cadence:\n\n{_changes(held)}' if held else ''
    return (
        f'Integration at `{tip[:SHORT]}` is not at the newest resolution ({scope}):\n\n{_changes(lines)}{waiting}\n\n'
        f'Relocked by the forge through the dependency door (`dev_lab.dev.dep --lock-upgrade`) on `{BRANCH}`, the '
        'one rolling relock (`dev_lab.dev.relock`). A lane takes it with `python -m dev_lab.dev.forge sync`.'
    )


def _due(
    root: Path, tree: Path, tip: str, found: Sequence[str], now: float
) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    """``(moves carried now, third-party moves held, third-party due)`` of *tree* at *tip*; RAISES on doubt."""
    if not all(refreshable(line) for line in found):
        raise RelockFailed('; '.join(found))
    due = third_party_due(root, tip, cadence((tree / 'pyproject.toml').read_text(encoding='utf-8')), now)
    lines = chosen(found, siblings(tree), due=due)
    return lines, tuple(line for line in found if line not in lines), due


def carry(
    root: Path,
    policy: Policy,
    *,
    pulls: Callable[[], Sequence[PullRequest]],
    create: Callable[..., PullRequest],
    edit: Callable[[int, str], object],
    close: Callable[[int], object],
    now: float,
    resolve: Callable[[Path], Report] | None = None,
    stable: Callable[[], str] = newest_stable,
    uv: Callable[[], str] = newest_uv,
    follow_uv: Callable[[str], str] = _follow_host_uv,
    upgrade: Callable[[Path, Sequence[str]], int] = door_upgrade,
    rerender: Callable[[Path], int] = rerender,
    remote_head: Callable[[Path], str] = _remote_head,
    push: Callable[[Path, str], None] = _push,
) -> str:
    """Keep the one relock pull request of *root* carrying what ``origin/<integration>`` needs now; the line said.

    *pulls* lists the open pull requests, *create* opens one (``Client.pr_create``), *edit* rewrites one's body and
    *close* closes one (``Client.issue_edit``/``issue_close``); *now* is the epoch clock the cadence reads.
    *resolve*, *stable*, *uv*, *follow_uv*, *upgrade*, *rerender*, *remote_head* and *push* are the resolution, the
    newest Rust stable, the newest uv, this host's uv moved to a version, the door, the render, origin's relock head
    and the leased push -- each a seam a test plants. A relock that raises the uv pin is written BY the new uv: the
    host's uv follows to it first, and where it cannot, the relock RAISES naming why and the update rather than
    writing with the old one.
    """
    rolling = next((pull for pull in pulls() if pull.head == BRANCH), None)
    base = f'origin/{policy.integration}'
    code, tip = _git(root, 'rev-parse', '--verify', '--quiet', f'refs/remotes/{base}^{{commit}}')
    if code != 0:
        msg = f'there is no {base} in {root} to relock'
        raise RelockFailed(msg)
    with detached_worktree(root, tip) as tree:
        found = (
            stale(tree, stable=stable, uv=uv) if resolve is None else stale(tree, resolve=resolve, stable=stable, uv=uv)
        )
        lines, held, due = _due(root, tree, tip, found, now)
        if not lines:
            waiting = f'; {len(held)} third-party move(s) held for the cadence' if held else ''
            if rolling is not None:
                close(rolling.number)
                return f'closed #{rolling.number}: {policy.integration} at {tip[:SHORT]} needs no relock{waiting}'
            return f'the lock of {policy.integration} at {tip[:SHORT]} needs no relock{waiting}'
        lease = remote_head(root)
        if rolling is not None and lease and carried(root, lease, tip, lines):
            return f'#{rolling.number} already carries the {len(lines)} move(s) {policy.integration} needs'
        if (raised := _uv_raise(lines)) is not None and (why := follow_uv(raised)):
            msg = (
                f'the relock raises {UV_PIN} to uv {raised}, but {why}, and a lock is '
                f'written by the uv it pins: {uv_remedy(raised)} on this host'
            )
            raise RelockFailed(msg)
        scope = FULL if due else IN_HOUSE
        packages = () if due else tuple(sorted({_canon(dist_of(line)) for line in lines}))
        if (exited := upgrade(tree, packages)) != 0:
            msg = f'the dependency door exited {exited} relocking {policy.integration} at {tip[:SHORT]} ({scope})'
            raise RelockFailed(msg)
        pinned = [path for path in FRESHENED if (tree / path).is_file()]
        if not _must(tree, 'status', '--porcelain', '--', *pinned):
            msg = f'the dependency door left {" and ".join(pinned)} unchanged though the resolution moves it ({scope})'
            raise RelockFailed(msg)
        if (exited := rerender(tree)) != 0:
            msg = f'the render of the generated files exited {exited} after relocking {tip[:SHORT]} ({scope})'
            raise RelockFailed(msg)
        rendered = [path for path in RENDERED if (tree / path).is_dir()]
        _must(tree, 'add', '--', *pinned, *rendered)
        body = _body(tip, scope, lines, held)
        _must(tree, 'commit', '-q', '-m', TITLE, '-m', body, '-m', f'{SCOPE}: {scope}')
        push(tree, lease)
    if rolling is not None:
        edit(rolling.number, body)
        return f'rebuilt #{rolling.number} on {tip[:SHORT]} ({scope}, {len(lines)} move(s)): {rolling.url}'
    opened = create(TITLE, body, head=BRANCH, base=policy.integration, draft=False)
    return f'relocked {policy.integration} at {tip[:SHORT]} onto {BRANCH} ({scope}, {len(lines)} move(s)): {opened.url}'
