"""IDLE-IS-ACTIVITY (dev-lab #611): idle is read off the last push or PR activity, and UNKNOWN when neither exists.

The forge half runs through a recording fake on each backend: GitHub answers both the ref's push activity and the
PRs of a head; Gitea records no push time, so only a PR's ``updated_at`` counts. PLANTED controls beside each: a
branch committed long ago but pushed an hour ago is not idle, and a branch the forge knows nothing about is UNKNOWN,
never "idle since its commit".
"""

from __future__ import annotations

import urllib.parse
from datetime import UTC, datetime

from dev_lab.dev.branchactivity import idle_hours, last_activity
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgework import Client
from dev_lab.dev.netverb import Attempt, Diagnosis, Report

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
LONG_AGO = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


class Answering(Client):
    """A forge answering each GET route (query stripped) from *answers*; a route it lacks is a 404."""

    def __init__(self, forge: Forge, answers: dict[str, object]) -> None:
        """A client of *forge* whose every call is answered from *answers*."""
        super().__init__(forge, 'T', sleep=lambda _s: None)
        self.answers = answers
        self.asked: list[str] = []

    def call(self, method: str, path: str, body: object = None, landed: object = None) -> object:
        del body, landed
        assert method == 'GET', (method, path)
        self.asked.append(path)
        route = urllib.parse.unquote(path.partition('?')[0])
        if route not in self.answers:
            raise ForgeCallFailed(Report(('GET', path), (Attempt(1, 404, 'not found', Diagnosis.FORGE_REFUSED),), 1))
        return self.answers[route]


GITHUB = Forge('github.com', 'o', 'r')
GITEA = Forge('forge.example.org', 'o', 'r')


def test_github_reads_the_newer_of_the_last_push_and_the_last_pr_update() -> None:
    forge = Answering(
        GITHUB,
        {
            '/repos/o/r/activity': [{'timestamp': '2026-11-26T11:00:00Z'}],
            '/repos/o/r/pulls': [{'updated_at': '2026-11-25T09:00:00Z'}, {'updated_at': '2026-11-24T09:00:00Z'}],
        },
    )
    assert last_activity(forge, 'pr/a', 'integrate/main') == datetime(2026, 11, 26, 11, 0, tzinfo=UTC)
    activity = next(asked for asked in forge.asked if '/activity?' in asked)
    assert 'ref=refs%2Fheads%2Fpr%2Fa' in activity


def test_github_with_a_pr_newer_than_the_last_push_reads_the_pr() -> None:
    forge = Answering(
        GITHUB,
        {
            '/repos/o/r/activity': [{'timestamp': '2026-11-20T11:00:00Z'}],
            '/repos/o/r/pulls': [{'updated_at': '2026-11-25T09:00:00Z'}],
        },
    )
    assert last_activity(forge, 'pr/a', 'integrate/main') == datetime(2026, 11, 25, 9, 0, tzinfo=UTC)


def test_gitea_reads_the_pr_of_the_head_into_integration_and_records_no_push() -> None:
    forge = Answering(GITEA, {'/api/v1/repos/o/r/pulls/integrate/main/pr/a': {'updated_at': '2026-11-25T09:00:00Z'}})
    assert last_activity(forge, 'pr/a', 'integrate/main') == datetime(2026, 11, 25, 9, 0, tzinfo=UTC)
    assert not any('/activity' in asked for asked in forge.asked), 'Gitea has no push record to ask'


def test_no_push_and_no_pr_is_unknown_never_the_commit_age() -> None:
    """PLANTED: the forge knows nothing of the branch -- UNKNOWN, not idle since its commit."""
    assert last_activity(Answering(GITEA, {}), 'pr/a', 'integrate/main') is None
    assert last_activity(Answering(GITHUB, {'/repos/o/r/activity': [], '/repos/o/r/pulls': []}), 'pr/a', 'x') is None
    assert idle_hours('pr/a', LONG_AGO, now=NOW, bound=24, activity=lambda _b: None) is None


def test_an_old_commit_pushed_an_hour_ago_is_not_idle() -> None:
    """The committer date of a rebased or resurrected branch is days old; its push is what counts."""
    pushed = datetime(2026, 11, 26, 11, 0, tzinfo=UTC)
    assert idle_hours('pr/a', LONG_AGO, now=NOW, bound=24, activity=lambda _b: pushed) == 1.0


def test_a_commit_inside_the_bound_never_asks_the_forge() -> None:
    """A commit is pushed after it is made: a young commit is a lower bound, so the forge is not asked."""
    asked: list[str] = []

    def activity(branch: str) -> datetime | None:
        asked.append(branch)
        return None

    young = datetime(2026, 11, 26, 10, 0, tzinfo=UTC)
    assert idle_hours('pr/a', young, now=NOW, bound=24, activity=activity) == 2.0
    assert asked == []
