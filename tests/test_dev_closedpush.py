"""NO-PUSH-ONTO-A-CLOSED-PR: a push to a branch whose PR the forge closed UNMERGED is refused.

A branch whose PR MERGED takes the push: the forge opens its continuation PR (LANDED-BRANCH-CONTINUES,
:mod:`dev_lab.dev.prcontinue`), so the push is carried. A PR closed unmerged was refused work, and nothing
reopens it: the push would reach no integration branch.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _forge_state import StateForge

from dev_lab.dev.closedpush import RULE, refusals
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import pr_by_head
from dev_lab.dev.netverb import Attempt, Diagnosis, Report

_BASE = 'integrate/main'
_SHA = 'a' * 40
_OLD = 'b' * 40


def _line(branch: str) -> str:
    return f'refs/heads/{branch} {_SHA} refs/heads/{branch} {_OLD}\n'


def _judged(forge: StateForge, branch: str) -> list[str]:
    return refusals(Path(), _line(branch), integration=_BASE, client=lambda: forge)


def _close(forge: StateForge, number: int) -> None:
    forge._edit_pull(number, {'state': 'closed'})


def test_a_merged_prs_branch_passes_its_continuation_is_the_forges() -> None:
    forge = StateForge()
    forge._merge(forge.add_pull('pr/x', _BASE), {})
    assert _judged(forge, 'pr/x') == []


def test_a_closed_unmerged_prs_branch_is_refused_naming_the_remedy() -> None:
    """PLANTED CONTROL for the pass above: the same branch, its PR closed unmerged, is refused."""
    forge = StateForge()
    _close(forge, forge.add_pull('pr/x', _BASE))
    found = _judged(forge, 'pr/x')
    assert len(found) == 1
    assert found[0].startswith(f'{RULE}:')
    assert 'closed' in found[0]
    assert f'forge pr create --head pr/x --base {_BASE}' in found[0]
    assert 'new branch name' in found[0]


def test_an_open_prs_branch_passes() -> None:
    forge = StateForge()
    forge.add_pull('pr/x', _BASE)
    assert _judged(forge, 'pr/x') == []


def test_a_branch_with_no_pr_passes() -> None:
    forge = StateForge()
    _close(forge, forge.add_pull('pr/other', _BASE))
    assert _judged(forge, 'pr/x') == []


_HOSTS = pytest.mark.parametrize('host', ['forge.example.org', 'github.com'])


@_HOSTS
def test_a_closed_old_pr_and_a_new_open_one_pass(host: str) -> None:
    forge = StateForge(Forge(host, 'o', 'r'))
    _close(forge, forge.add_pull('pr/x', _BASE))
    forge.add_pull('pr/x', _BASE)
    assert _judged(forge, 'pr/x') == []


@_HOSTS
def test_an_open_draft_wins_over_an_older_closed_pr_of_the_same_pair(host: str) -> None:
    """The 2026-11-10 defect: closed #6078 and open draft #6151 of one pair, were refused."""
    forge = StateForge(Forge(host, 'o', 'r'))
    _close(forge, forge.add_pull('pr/x', _BASE))
    draft = forge.add_pull('pr/x', _BASE, draft=True)
    assert _judged(forge, 'pr/x') == []
    found = pr_by_head(forge, 'pr/x', _BASE)
    assert found is not None
    assert found.number == draft


@_HOSTS
def test_an_open_pr_wins_over_a_newer_closed_one(host: str) -> None:
    forge = StateForge(Forge(host, 'o', 'r'))
    kept = forge.add_pull('pr/x', _BASE)
    _close(forge, forge.add_pull('pr/x', _BASE))
    found = pr_by_head(forge, 'pr/x', _BASE)
    assert found is not None
    assert found.number == kept


def test_the_pair_lookup_alone_answered_the_closed_pr_planted_control() -> None:
    """PLANTED CONTROL: gitea's pair route, read alone, answers the closed PR: the refusal."""
    forge = StateForge()
    closed = forge.add_pull('pr/x', _BASE)
    _close(forge, closed)
    forge.add_pull('pr/x', _BASE, draft=True)
    assert forge.call('GET', f'{forge.repo}/pulls/integrate%2Fmain/pr/x')['number'] == closed


def test_a_closed_pr_into_another_base_does_not_judge_the_branch() -> None:
    forge = StateForge()
    _close(forge, forge.add_pull('pr/x', 'elsewhere'))
    assert _judged(forge, 'pr/x') == []


def test_a_deletion_and_the_integration_branch_ask_no_forge() -> None:
    forge = StateForge()
    lines = f'(delete) {"0" * 40} refs/heads/pr/x {_OLD}\n' + _line(_BASE) + 'refs/tags/v1 c refs/tags/v1 d\n'
    assert refusals(Path(), lines, integration=_BASE, client=lambda: forge) == []
    assert forge.asked == []


def test_an_unreadable_forge_refuses_naming_it() -> None:
    def down() -> StateForge:
        raise ForgeCallFailed(Report(('GET', 'pulls'), (Attempt(1, 503, 'down', Diagnosis.FORGE_REFUSED),), 1))

    found = refusals(Path(), _line('pr/x'), integration=_BASE, client=down)
    assert len(found) == 1
    assert 'the forge cannot be read' in found[0]


def test_the_guard_asks_a_bounded_question_per_branch_however_many_prs_closed() -> None:
    """The pair route; for a pair with a PR, one open page and the first recently-updated closed page."""
    forge = StateForge()
    for n in range(120):
        _close(forge, forge.add_pull(f'pr/old{n}', _BASE))
    _close(forge, forge.add_pull('pr/x', _BASE))
    lines = _line('pr/x') + _line('pr/y')
    assert len(refusals(Path(), lines, integration=_BASE, client=lambda: forge)) == 1
    assert len(forge.asked) == 4


@pytest.mark.parametrize('host', ['forge.example.org', 'github.com'])
def test_pr_by_head_answers_the_newest_pr_of_a_head_into_a_base_on_both_forges(host: str) -> None:
    forge = StateForge(Forge(host, 'o', 'r'))
    forge._merge(forge.add_pull('pr/x', _BASE), {})
    newest = forge.add_pull('pr/x', _BASE)
    forge.add_pull('pr/x', 'elsewhere')
    found = pr_by_head(forge, 'pr/x', _BASE)
    assert found is not None
    assert found.number == newest
    assert pr_by_head(forge, 'pr/none', _BASE) is None
