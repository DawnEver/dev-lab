"""NO-PUSH-ONTO-A-LANDED-PR: a push to a branch whose PR the forge already merged or closed is refused.

Seen twice on 2026-11-02 (dev-lab #44, motronics #5397): the forge merged a reviewed head, a later push landed
on the same branch, and no PR would ever carry it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _forge_state import StateForge

from dev_lab.dev.forge import Forge
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import pr_by_head
from dev_lab.dev.landedpush import RULE, judge, refusals
from dev_lab.dev.netverb import Attempt, Diagnosis, Report

_BASE = 'integrate/main'
_SHA = 'a' * 40
_OLD = 'b' * 40


def _line(branch: str) -> str:
    return f'refs/heads/{branch} {_SHA} refs/heads/{branch} {_OLD}\n'


def _judged(forge: StateForge, branch: str) -> list[str]:
    return refusals(Path(), _line(branch), integration=_BASE, client=lambda: forge)


def test_a_merged_prs_branch_is_refused_naming_the_remedy() -> None:
    forge = StateForge()
    forge._merge(forge.add_pull('pr/x', _BASE), {})
    found = _judged(forge, 'pr/x')
    assert len(found) == 1
    assert found[0].startswith(f'{RULE}:')
    assert 'merged' in found[0]
    assert f'forge pr create --head pr/x --base {_BASE}' in found[0]
    assert 'new branch name' in found[0]


def test_a_closed_prs_branch_is_refused() -> None:
    forge = StateForge()
    forge._edit_pull(forge.add_pull('pr/x', _BASE), {'state': 'closed'})
    found = _judged(forge, 'pr/x')
    assert len(found) == 1
    assert 'closed' in found[0]


def test_an_open_prs_branch_passes() -> None:
    forge = StateForge()
    forge.add_pull('pr/x', _BASE)
    assert _judged(forge, 'pr/x') == []


def test_a_branch_with_no_pr_passes() -> None:
    forge = StateForge()
    forge._merge(forge.add_pull('pr/other', _BASE), {})
    assert _judged(forge, 'pr/x') == []


def test_a_merged_old_pr_and_a_new_open_one_pass() -> None:
    forge = StateForge()
    forge._merge(forge.add_pull('pr/x', _BASE), {})
    forge.add_pull('pr/x', _BASE)
    assert _judged(forge, 'pr/x') == []


def test_a_landed_pr_into_another_base_does_not_judge_the_branch() -> None:
    forge = StateForge()
    forge._merge(forge.add_pull('pr/x', 'elsewhere'), {})
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


def test_the_guard_asks_one_question_per_branch_however_many_prs_closed() -> None:
    forge = StateForge()
    for n in range(120):
        forge._merge(forge.add_pull(f'pr/old{n}', _BASE), {})
    forge._merge(forge.add_pull('pr/x', _BASE), {})
    lines = _line('pr/x') + _line('pr/y')
    assert len(refusals(Path(), lines, integration=_BASE, client=lambda: forge)) == 1
    assert len(forge.asked) == 2


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


# USER RULING 2026-11-07: a DECLARED long-lived branch (a `[tool.dev_lab.branchset] sessions` name) is reopened
# after each landing -- new commits pass and the pusher is told to open the next PR; landed-only commits do not.
_LONG = 'pr/session'


def _judged_long(forge: StateForge, *, integrated: bool) -> tuple[list[str], list[str]]:
    seen: list[str] = []

    def is_integrated(sha: str) -> bool:
        seen.append(sha)
        return integrated

    verdict = judge(
        Path(), _line(_LONG), integration=_BASE, client=lambda: forge, sessions={_LONG}, integrated=is_integrated
    )
    assert seen == [_SHA]
    return verdict.refusals, verdict.notices


def test_a_declared_long_lived_branch_with_new_commits_passes_and_is_told_to_open_the_next_pr() -> None:
    forge = StateForge()
    forge._merge(forge.add_pull(_LONG, _BASE), {})
    found, notices = _judged_long(forge, integrated=False)
    assert found == []
    assert len(notices) == 1
    assert f'forge pr create --head {_LONG} --base {_BASE}' in notices[0]


def test_a_declared_long_lived_branch_with_only_landed_commits_is_refused_as_nothing_new() -> None:
    forge = StateForge()
    forge._merge(forge.add_pull(_LONG, _BASE), {})
    found, notices = _judged_long(forge, integrated=True)
    assert notices == []
    assert len(found) == 1
    assert found[0].startswith(f'{RULE}:')
    assert 'nothing new' in found[0]


def test_an_undeclared_landed_head_is_still_refused_whatever_its_commits() -> None:
    forge = StateForge()
    forge._merge(forge.add_pull('pr/x', _BASE), {})
    verdict = judge(
        Path(), _line('pr/x'), integration=_BASE, client=lambda: forge, sessions={_LONG}, integrated=lambda _: False
    )
    assert len(verdict.refusals) == 1
    assert 'merged' in verdict.refusals[0]
    assert verdict.notices == []
