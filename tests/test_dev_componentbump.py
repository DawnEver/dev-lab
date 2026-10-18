"""COMPONENT-BUMP: one green engine commit becomes one one-pointer lane, verdicted, merged or held.

The pure half drives :func:`tick` with an in-memory product and engines; the git half drives
:class:`GitProduct` over a REAL local bare origin, so the lane commit, its lease-guarded creation
and its deletion are git's own behaviour rather than a fake's.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from _forge_fake import git_out, run_git

from lab_commons.dev.componentbump import (
    HELD,
    IDLE,
    LANDED,
    OPENED,
    RACED,
    READY,
    WAITING,
    GitProduct,
    Lane,
    issue_title,
    tick,
)
from lab_commons.dev.components import Component
from lab_commons.dev.forge import Forge
from lab_commons.dev.forgestatus import Status
from lab_commons.dev.forgework import Client
from lab_commons.dev.platformparts import Part

NUM = Component('numerics-lab', 'https://f/o/numerics-lab.git', 'main', ('base', 'linux'))
OPT = Component('optimi-lab', 'https://f/o/optimi-lab.git', 'main', ('base',))
OLD, NEW = 'a' * 40, 'b' * 40


def part(platform: str, result: str) -> Status:
    """The status a forge holds for *platform* at *result*, in the producer's own description."""
    state = {'PASS': 'success', 'FAIL': 'failure'}[result]
    return Status(f'tests/{platform}', state, Part(platform, 'full', result, 3).description(), f'https://r/{platform}')


CLIENT = Client(Forge('forge.example', 'o', 'product'), 'token')
GREEN: tuple[Status, ...] = (part('base', 'PASS'),)


@dataclass
class FakeProduct:
    """An origin with pointers, at most one lane, statuses per sha and issues -- what a tick reads and writes."""

    pointers: dict[str, str] = field(default_factory=dict)
    current: Lane | None = None
    lane_statuses: tuple[Status, ...] = ()
    titles: list[str] = field(default_factory=list)
    opened: list[tuple[str, str]] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)

    def pointer(self, path: str) -> str:
        return self.pointers.get(path, '')

    def lane(self) -> Lane | None:
        return self.current

    def open_lane(self, path: str, sha: str, message: str) -> bool:
        if self.current is not None:
            return False
        assert message.startswith('chore(deps): bump ')
        self.opened.append((path, sha))
        self.current = Lane('c' * 40, path, sha, absorbed=False)
        return True

    def close_lane(self, tip: str) -> None:
        assert self.current is not None
        assert self.current.tip == tip
        self.closed.append(tip)
        self.current = None

    def statuses(self, _sha: str) -> Sequence[Status]:
        return self.lane_statuses

    def issue_titles(self) -> frozenset[str]:
        return frozenset(self.titles)

    def open_issue(self, title: str, body: str) -> None:
        assert 'held' in body
        self.titles.append(title)


@dataclass
class FakeEngines:
    """Each engine's tip and the statuses on it."""

    tips: dict[str, str]
    green: dict[str, tuple[Status, ...]]

    def tip(self, row: Component) -> str:
        return self.tips[row.name]

    def statuses(self, row: Component, _sha: str) -> Sequence[Status]:
        return self.green.get(row.name, ())


def test_a_forge_green_engine_tip_opens_one_lane_moving_its_pointer() -> None:
    product = FakeProduct({NUM.path: OLD})
    done = tick((NUM,), product, FakeEngines({'numerics-lab': NEW}, {'numerics-lab': GREEN}))
    assert (done.action, done.component, done.sha) == (OPENED, 'numerics-lab', NEW)
    assert product.opened == [(NUM.path, NEW)]


@pytest.mark.parametrize(
    ('tips', 'green', 'titles'),
    [
        ({'numerics-lab': OLD}, {'numerics-lab': GREEN}, []),  # already the pointer
        ({'numerics-lab': NEW}, {}, []),  # the engine tip is not forge-green
        ({'numerics-lab': NEW}, {'numerics-lab': (part('base', 'FAIL'),)}, []),
        ({'numerics-lab': NEW}, {'numerics-lab': GREEN}, [issue_title(NUM, NEW)]),  # held by its issue
    ],
)
def test_nothing_is_bumped_that_is_current_unverified_or_held(
    tips: dict[str, str], green: dict[str, tuple[Status, ...]], titles: list[str]
) -> None:
    product = FakeProduct({NUM.path: OLD}, titles=titles)
    assert tick((NUM,), product, FakeEngines(tips, green)).action == IDLE
    assert product.opened == []


def _in_flight(statuses: tuple[Status, ...], *, absorbed: bool = False) -> FakeProduct:
    return FakeProduct({NUM.path: OLD}, Lane('c' * 40, NUM.path, NEW, absorbed=absorbed), statuses)


def test_a_lane_green_on_every_declared_part_is_ready_for_the_integrator() -> None:
    product = _in_flight((part('base', 'PASS'), part('linux', 'PASS')))
    assert tick((NUM,), product, FakeEngines({}, {})).action == READY
    assert product.closed == [], 'a ready lane is the integrator to merge, never deleted'


def test_a_lane_missing_a_declared_part_waits() -> None:
    assert tick((NUM,), _in_flight((part('base', 'PASS'),)), FakeEngines({}, {})).action == WAITING


def test_a_lane_the_integration_branch_holds_is_deleted_as_landed() -> None:
    product = _in_flight((), absorbed=True)
    assert tick((NUM,), product, FakeEngines({}, {})).action == LANDED
    assert product.closed == ['c' * 40]


def test_a_red_lane_is_held_and_deleted() -> None:
    product = _in_flight((part('base', 'PASS'), part('linux', 'FAIL')))
    done = tick((NUM,), product, FakeEngines({}, {}))
    assert (done.action, done.detail) == (HELD, 'linux')
    assert product.titles == [issue_title(NUM, NEW)]
    assert product.closed == ['c' * 40]


def test_a_lane_moving_no_declared_component_is_never_judged() -> None:
    product = FakeProduct(current=Lane('c' * 40, 'components/ai-lab', NEW, absorbed=True))
    done = tick((NUM,), product, FakeEngines({}, {}))
    assert done.action == WAITING
    assert 'no component declares' in done.detail
    assert product.closed == []


# --- the git half -------------------------------------------------------------------------------


def _origin(tmp_path: Path) -> tuple[Path, str]:
    """A bare origin whose ``integrate/main`` holds a gitlink at numerics-lab's mount, and a clone of it."""
    seed = tmp_path / 'seed'
    seed.mkdir()
    run_git(seed, 'init', '-q', '-b', 'integrate/main')
    (seed / 'README').write_text('x\n', encoding='utf-8')
    run_git(seed, 'add', 'README')
    run_git(seed, 'update-index', '--add', '--cacheinfo', f'160000,{OLD},{NUM.path}')
    run_git(seed, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'seed')
    bare = tmp_path / 'origin.git'
    run_git(tmp_path, 'clone', '-q', '--bare', str(seed), str(bare))
    clone = tmp_path / 'product'
    run_git(tmp_path, 'clone', '-q', str(bare), str(clone))
    run_git(clone, 'config', 'user.name', 't')
    run_git(clone, 'config', 'user.email', 't@t')
    return clone, git_out(clone, 'rev-parse', 'origin/integrate/main')


def test_the_git_product_opens_reads_and_deletes_the_one_lane(tmp_path: Path) -> None:
    clone, base = _origin(tmp_path)
    product = GitProduct(clone, client=CLIENT, integration='integrate/main')
    assert (product.pointer(NUM.path), product.lane()) == (OLD, None)

    assert product.open_lane(NUM.path, NEW, 'chore(deps): bump numerics-lab to bbbbbbbbbbbb')
    run_git(clone, 'fetch', '-q', 'origin')
    lane = product.lane()
    assert lane is not None
    assert (lane.path, lane.sha, lane.absorbed) == (NUM.path, NEW, False)
    assert git_out(clone, 'rev-parse', f'{lane.tip}^1') == base, 'one commit on the integration tip'
    assert product.pointer(NUM.path) == OLD, 'the integration branch is untouched until the integrator merges'

    assert not product.open_lane(OPT.path, NEW, 'chore(deps): bump optimi-lab'), 'the lane exists: RACED'
    product.close_lane(lane.tip)
    run_git(clone, 'fetch', '-q', '--prune', 'origin')
    assert product.lane() is None


def test_a_raced_open_is_reported_as_raced(tmp_path: Path) -> None:
    clone, _ = _origin(tmp_path)
    product = GitProduct(clone, client=CLIENT, integration='integrate/main')
    other = GitProduct(clone, client=CLIENT, integration='integrate/main')
    assert other.open_lane(NUM.path, NEW, 'chore(deps): bump numerics-lab')
    engines = FakeEngines({'numerics-lab': NEW, 'optimi-lab': NEW}, {'numerics-lab': GREEN, 'optimi-lab': GREEN})

    class Stale(GitProduct):
        reads = 0

        def lane(self) -> Lane | None:
            self.reads += 1
            return None if self.reads == 1 else super().lane()  # the first read predates the other host's push

        def issue_titles(self) -> frozenset[str]:
            return frozenset()

    stale = Stale(clone, client=CLIENT, integration='integrate/main')
    assert tick((OPT,), stale, engines).action == RACED
    assert product.lane() is not None
