"""A COMPONENT FOLLOWS ITS ENGINE ONE GREEN POINTER AT A TIME -- the bump loop, one tick per call.

THE LOOP (:mod:`dev_lab.dev.components` declares the rows). Each tick derives everything from
origin and the forge; nothing is stored, so a lost tick, a repeated tick and two hosts ticking at once
all see the same state:

1. An engine's tracked branch tip is forge-green (every part on it PASS) and differs from the
   product's pointer on its integration branch.
2. The tick opens ONE lane, :data:`LANE`, holding one commit on the integration tip that moves that one
   gitlink (``chore(deps): bump <engine> to <sha12>``).
3. The forge verdicts the lane like any other.
4. Green on every part the component declares: the lane is READY, and the integrator merges it like
   any other lane (:mod:`dev_lab.dev.integrator`). Once the integration branch holds it, the tick
   deletes the lane and the next bump may start.
   Red on any declared part: the tick opens ONE issue, :func:`issue_title`, naming the engine commit
   and the red parts, and deletes the lane, so nothing merges and the pointer stays on the last green
   commit. That engine commit is HELD while its issue exists; the engine's next green commit is a new
   candidate.
5. Bumps run one at a time BY CONSTRUCTION: there is one lane name, it is created only if absent
   (``--force-with-lease=<lane>:``), and no candidate is considered while it exists.

FETCH FIRST: the CLI fetches origin through the retry door; :func:`tick` reads what that left.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

import lab_commons.launch as _door
from lab_commons.log import emit
from lab_commons.outcomes import Conclusion

from dev_lab.dev.components import Component, components_of
from dev_lab.dev.forge import fetch_origin
from dev_lab.dev.forgepulls import issues
from dev_lab.dev.forgestatus import CommitStatus, status_list
from dev_lab.dev.forgework import Client, client_for
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.platformparts import standing

__all__ = [
    'HELD',
    'IDLE',
    'LANDED',
    'LANE',
    'OPENED',
    'RACED',
    'READY',
    'WAITING',
    'Engines',
    'GitEngines',
    'GitProduct',
    'Lane',
    'Product',
    'Tick',
    'issue_title',
    'main',
    'tick',
]

#: The one bump lane: its existence IS the serialisation.
LANE: Final = 'pr/components-bump'

OPENED: Final = 'opened'  #: a bump lane was opened
RACED: Final = 'raced'  #: another host opened the lane first
WAITING: Final = 'waiting'  #: the lane's declared parts are not all settled
READY: Final = 'ready'  #: every declared part is PASS: the integrator merges it
HELD: Final = 'held'  #: a declared part is FAIL: one issue, the lane deleted, the pointer kept
LANDED: Final = 'landed'  #: the integration branch holds the lane: it is deleted
IDLE: Final = 'idle'  #: nothing to bump

_GIT: Final = shutil.which('git') or 'git'
_GITLINK: Final = '160000'


@dataclass(frozen=True)
class Lane:
    """The bump lane on origin: its tip, the one gitlink it moves, and whether integration holds it."""

    tip: str
    path: str
    sha: str
    absorbed: bool


@dataclass(frozen=True)
class Tick:
    """What one tick did: :data:`OPENED` ... :data:`IDLE`, about which engine commit, and why."""

    action: str
    component: str = ''
    sha: str = ''
    detail: str = ''


class Product(Protocol):
    """The product repository as a bump needs it: origin's refs, its statuses and its issues."""

    def pointer(self, path: str) -> str:
        """The gitlink at *path* on the integration tip; ``''`` when there is none."""

    def lane(self) -> Lane | None:
        """The bump lane on origin, or ``None``."""

    def open_lane(self, path: str, sha: str, message: str) -> bool:
        """Create :data:`LANE` moving *path* to *sha*, only if absent; ``False`` when another host won."""

    def close_lane(self, tip: str) -> None:
        """Delete :data:`LANE`, only while it is still at *tip*."""

    def statuses(self, sha: str) -> Sequence[CommitStatus]:
        """The latest status per context on *sha*."""

    def issue_titles(self) -> frozenset[str]:
        """The title of every issue, open or closed."""

    def open_issue(self, title: str, body: str) -> None:
        """Open one issue."""


class Engines(Protocol):
    """Each engine's tracked tip and its forge statuses."""

    def tip(self, row: Component) -> str:
        """The sha *row*'s branch points at on its repository."""

    def statuses(self, row: Component, sha: str) -> Sequence[CommitStatus]:
        """The latest status per context on *sha* in *row*'s repository."""


def issue_title(row: Component, sha: str) -> str:
    """The one issue a red bump of *row* to *sha* opens -- and the hold on that commit while it exists."""
    return f'components: bump {row.name} to {sha[:12]} is red'


def tick(rows: Sequence[Component], product: Product, engines: Engines) -> Tick:
    """Advance the bump loop by one step (module docstring)."""
    lane = product.lane()
    if lane is not None:
        return _advance(rows, product, lane)
    titles = product.issue_titles()
    for row in rows:
        tip = engines.tip(row)
        if not tip or tip == product.pointer(row.path) or issue_title(row, tip) in titles:
            continue
        if standing(engines.statuses(row, tip), head=tip).result is not Conclusion.PASS:
            continue
        message = f'chore(deps): bump {row.name} to {tip[:12]}\n\n{row.url} {row.branch} is forge-green at {tip}.\n'
        opened = product.open_lane(row.path, tip, message)
        return Tick(OPENED if opened else RACED, row.name, tip)
    return Tick(IDLE)


def _advance(rows: Sequence[Component], product: Product, lane: Lane) -> Tick:
    row = next((row for row in rows if row.path == lane.path), None)
    if row is None:
        return Tick(WAITING, detail=f'{LANE} moves {lane.path or "no gitlink"}, which no component declares')
    if lane.absorbed:
        product.close_lane(lane.tip)
        return Tick(LANDED, row.name, lane.sha)
    parts = {part.platform: part for part in standing(product.statuses(lane.tip), head=lane.tip).parts}
    red = [parts[name] for name in row.parts if name in parts and parts[name].result is Conclusion.FAIL]
    if red:
        title = issue_title(row, lane.sha)
        if title not in product.issue_titles():
            lines = [f'- tests/{part.platform}: {part.description()}' for part in red]
            body = '\n'.join([
                f'The bump of {row.path} to {row.url} {lane.sha} ({row.branch}) is red on {lane.tip}:',
                '', *lines, '',
                f'The pointer stays on the last green commit; {lane.sha[:12]} is held while this issue exists.',
            ])  # fmt: skip
            product.open_issue(title, body)
        product.close_lane(lane.tip)
        return Tick(HELD, row.name, lane.sha, ', '.join(part.platform for part in red))
    if all(name in parts and parts[name].result is Conclusion.PASS for name in row.parts):
        return Tick(READY, row.name, lane.sha)
    return Tick(WAITING, row.name, lane.sha)


class GitProduct:
    """:class:`Product` over a checkout's ``origin`` remote-tracking refs (fetched first) and its forge."""

    def __init__(self, root: Path, client: Client, integration: str) -> None:
        """*root* is the product checkout; *integration* the branch bumps land on."""
        self.root, self.client, self.base = root, client, f'refs/remotes/origin/{integration}'

    def _git(self, *args: str, env: dict[str, str] | None = None, check: bool = True) -> str:
        done = _door.run(
            [_GIT, '-C', str(self.root), *args],
            capture_output=True, text=True, encoding='utf-8', errors='replace', check=check, env=env,
        )  # fmt: skip
        return done.stdout.strip() if done.returncode == 0 else ''

    def pointer(self, path: str) -> str:
        """The gitlink at *path* on the integration tip; ``''`` when there is none."""
        meta, _, _ = self._git('ls-tree', self.base, '--', path).partition('\t')
        mode, _, sha = meta.partition(' commit ')
        return sha if mode == _GITLINK else ''

    def lane(self) -> Lane | None:
        """The bump lane on origin, or ``None``."""
        tip = self._git('rev-parse', '--verify', '-q', f'refs/remotes/origin/{LANE}', check=False)
        if not tip:
            return None
        moved = [
            line.split('\t', 1) for line in self._git('diff-tree', '-r', f'{tip}^1', tip).splitlines() if '\t' in line
        ]
        links = [(meta.split()[3], path) for meta, path in moved if meta.split()[1] == _GITLINK]
        sha, path = links[0] if len(links) == 1 else ('', '')
        absorbed = _door.run([_GIT, '-C', str(self.root), 'merge-base', '--is-ancestor', tip, self.base], check=False)
        return Lane(tip, path, sha, absorbed.returncode == 0)

    def open_lane(self, path: str, sha: str, message: str) -> bool:
        """Create :data:`LANE` moving *path* to *sha*, only if absent; ``False`` when another host won."""
        with tempfile.TemporaryDirectory() as scratch:
            env = {**os.environ, 'GIT_INDEX_FILE': str(Path(scratch) / 'index')}
            self._git('read-tree', self.base, env=env)
            self._git('update-index', '--add', '--cacheinfo', f'{_GITLINK},{sha},{path}', env=env)
            tree = self._git('write-tree', env=env)
        commit = self._git('commit-tree', tree, '-p', self.base, '-m', message)
        report = run_network_verb(
            [_GIT, 'push', f'--force-with-lease=refs/heads/{LANE}:', 'origin', f'{commit}:refs/heads/{LANE}'],
            cwd=self.root,
        )
        if report.ok:
            return True
        fetch_origin(self.root)
        if self.lane() is None:
            raise OSError(report.remedy)
        return False

    def close_lane(self, tip: str) -> None:
        """Delete :data:`LANE`, only while it is still at *tip*."""
        report = run_network_verb(
            [_GIT, 'push', f'--force-with-lease=refs/heads/{LANE}:{tip}', 'origin', f':refs/heads/{LANE}'],
            cwd=self.root,
        )
        if not report.ok:
            raise OSError(report.remedy)

    def statuses(self, sha: str) -> Sequence[CommitStatus]:
        """The latest status per context on *sha*."""
        return status_list(self.client, sha)

    def issue_titles(self) -> frozenset[str]:
        """The title of every issue, open or closed."""
        return frozenset(str(raw.get('title', '')) for raw in issues(self.client))

    def open_issue(self, title: str, body: str) -> None:
        """Open one issue."""
        self.client.issue_create(title, body)


class GitEngines:
    """:class:`Engines` over each engine's repository: ``git ls-remote`` and its own forge."""

    def __init__(self, root: Path, client: Callable[[str], Client]) -> None:
        """*client* builds the forge client of an engine url."""
        self.root, self.client = root, client

    def tip(self, row: Component) -> str:
        """The sha *row*'s branch points at on its repository."""
        report = run_network_verb([_GIT, 'ls-remote', row.url, f'refs/heads/{row.branch}'], cwd=self.root)
        if not report.ok:
            raise OSError(report.remedy)
        return report.attempts[-1].output.split('\t', 1)[0].strip()

    def statuses(self, row: Component, sha: str) -> Sequence[CommitStatus]:
        """The latest status per context on *sha* in *row*'s repository."""
        return status_list(self.client(row.url), sha)


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m dev_lab.dev.componentbump [--root R]``: fetch origin, run one tick, print it."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.componentbump', description=main.__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='the product checkout (default: here)')
    root = parser.parse_args(argv).root
    rows = components_of((root / 'pyproject.toml').read_text(encoding='utf-8'))
    fetch_origin(root)
    product = GitProduct(root, client_for(root), load_policy(root).integration)
    done = tick(rows, product, GitEngines(root, lambda url: client_for(root, url=url)))
    emit(f'components bump: {done.action} {done.component} {done.sha[:12]} {done.detail}'.rstrip())
    return 0


if __name__ == '__main__':
    sys.exit(main())
