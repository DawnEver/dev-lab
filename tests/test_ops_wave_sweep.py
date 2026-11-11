"""An open wave lands what is green: the break-glass tick merges every green, non-draft PR of a served repo.

Planted controls: a green PR outside the wave's repos, a red PR, the cap, and no open wave each merge nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from _ops_fixtures import GLASS, config
from test_ops_breakglass import GREEN, HEAD, FakeForge, Host

from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgeheadgate import PR_CURRENT_CONTEXT
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.netverb import Report
from dev_lab.ops.wavesweep import Pull

#: A head a wave may land: green tests AND current (it holds the integration branch, its lock is fresh).
CURRENT = (*GREEN, CommitStatus(PR_CURRENT_CONTEXT, 'success', 'holds integrate/main', ''))
RED = (
    CommitStatus('tests/base', 'failure', 'VERDICT result=fail', ''),
    CommitStatus('tests/security', 'success', 'nothing found', ''),
)


@dataclass
class ListingForge(FakeForge):
    """A forge whose open PRs are listed; each PR carries its own head's statuses."""

    pulls: list[Pull] = field(default_factory=list)
    by_head: dict[str, tuple[CommitStatus, ...]] = field(default_factory=dict)

    def open_pulls(self) -> list[Pull]:
        return list(self.pulls)

    def pull(self, number: int) -> tuple[str, str, str]:
        found = next(one for one in self.pulls if one.number == number)
        return 'open', found.base, found.head

    def statuses(self, head: str) -> list[CommitStatus]:
        return list(self.by_head.get(head, CURRENT))


@dataclass
class Fleet(Host):
    """A host whose wave serves ONE repo (GLASS[0]); every other URL is a forge with no open PR."""

    def _forge(self, url: str) -> FakeForge:
        self.asked.append(url)
        return self.forge if url == GLASS[0] else ListingForge()


def _host(tmp_path, pulls: list[Pull], by_head: dict[str, tuple[CommitStatus, ...]] | None = None,
          *, glass: tuple[str, ...] = GLASS) -> Fleet:  # fmt: skip
    return Fleet(config(tmp_path, [], extra='wave_hours_max = 4.0', glass=glass),
                 forge=ListingForge(pulls=pulls, by_head=by_head or {}))  # fmt: skip


def _merged(host: Host) -> list[int]:
    return [number for verb, number, _ in host.forge.calls if verb == 'merge']


def test_an_open_wave_merges_each_green_pr(tmp_path) -> None:
    host = _host(
        tmp_path, [Pull(7, 'integrate/main', HEAD, draft=False), Pull(8, 'integrate/main', 'b' * 40, draft=False)]
    )
    host.open(max_merges=5)
    said = host.server.tick()
    assert _merged(host) == [7, 8]
    assert 'merged' in said
    assert all('wave' in message for verb, _, message in host.forge.calls if verb == 'merge')


def test_no_open_wave_merges_nothing(tmp_path) -> None:  # PLANTED CONTROL
    host = _host(tmp_path, [Pull(7, 'integrate/main', HEAD, draft=False)])
    host.server.tick()
    assert _merged(host) == []


def test_a_red_pr_is_not_merged(tmp_path) -> None:  # PLANTED CONTROL
    red = 'c' * 40
    host = _host(tmp_path, [Pull(7, 'integrate/main', red, draft=False), Pull(8, 'integrate/main', HEAD, draft=False)],
                 {red: RED})  # fmt: skip
    host.open(max_merges=5)
    host.server.tick()
    assert _merged(host) == [8]


def test_a_draft_and_a_merge_ready_pr_are_left_alone(tmp_path) -> None:
    ready = 'd' * 40
    host = _host(tmp_path, [Pull(7, 'integrate/main', HEAD, draft=True), Pull(8, 'integrate/main', ready, draft=False)],
                 {ready: (*GREEN, CommitStatus('tests/merge-ready', 'success', 'ready', ''))})  # fmt: skip
    host.open(max_merges=5)
    host.server.tick()
    assert _merged(host) == [], 'a draft is not landed; a merge-ready PR lands by the normal path'


def test_a_pr_off_the_integration_branch_is_not_merged(tmp_path) -> None:  # PLANTED CONTROL
    host = _host(tmp_path, [Pull(7, 'main', HEAD, draft=False)])
    host.open(max_merges=5)
    host.server.tick()
    assert _merged(host) == []


def test_at_the_cap_nothing_more_merges(tmp_path) -> None:  # PLANTED CONTROL
    heads = ['e' * 40, 'f' * 40, '1' * 40]
    host = _host(tmp_path, [Pull(n, 'integrate/main', h, draft=False) for n, h in zip((7, 8, 9), heads, strict=True)])
    host.open(max_merges=2)
    host.server.tick()
    assert _merged(host) == [7, 8]
    host.server.tick()
    assert _merged(host) == [7, 8], 'the cap ended the wave'


def test_a_green_pr_outside_the_waves_repos_is_not_merged(tmp_path) -> None:  # PLANTED CONTROL
    host = _host(tmp_path, [Pull(7, 'integrate/main', HEAD, draft=False)], glass=(GLASS[1],))
    host.open(max_merges=5)
    host.server.tick()
    assert _merged(host) == []
    assert GLASS[0] not in host.asked, 'a repo the wave does not serve is never even asked'


@dataclass
class RefusingForge(ListingForge):
    """A forge that refuses the merge of one PR, as GitHub refused dev-lab #307 on 2026-11-11."""

    refuses: int = 0

    def merge(self, number: int, *, head: str, message: str) -> None:
        if number == self.refuses:
            raise ForgeCallFailed(Report(f'PUT /pulls/{number}/merge', (), 1))
        super().merge(number, head=head, message=message)


def test_a_refused_merge_is_skipped_and_the_next_pr_still_merges(tmp_path) -> None:  # PLANTED CONTROL
    pulls = [Pull(7, 'integrate/main', HEAD, draft=False), Pull(8, 'integrate/main', 'b' * 40, draft=False)]
    host = Fleet(config(tmp_path, [], extra='wave_hours_max = 4.0', glass=GLASS),
                 forge=RefusingForge(pulls=pulls, refuses=7))  # fmt: skip
    host.open(max_merges=5)
    host.server.tick()
    assert _merged(host) == [8]


def test_a_green_pr_that_is_not_current_is_not_merged(tmp_path) -> None:  # PLANTED CONTROL
    stale = (*GREEN, CommitStatus(PR_CURRENT_CONTEXT, 'failure', 'lacks integrate/main', ''))
    host = _host(
        tmp_path,
        [Pull(7, 'integrate/main', HEAD, draft=False), Pull(8, 'integrate/main', 'b' * 40, draft=False)],
        {HEAD: stale, 'c' * 40: GREEN},
    )
    host.forge.pulls.append(Pull(9, 'integrate/main', 'c' * 40, draft=False))  # green, pr-current absent
    host.open(max_merges=5)
    host.server.tick()
    assert _merged(host) == [8]
