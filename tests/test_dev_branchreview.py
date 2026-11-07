"""LANDED-BRANCH-CONTINUES: one review record per branch; a continuation is reviewed for its increment and carries.

User-approved design 2026-11-07. The record chains a branch's PRs and keeps every carried finding's disposition;
the findings themselves stay in each PR's own review ledger. A continuation's review reads from the last landed
head, hands its reviewer the carried findings, and holds ``tests/review`` at failure while one is open.

Real git repositories and the stateful fake forge, as in ``test_dev_forgereview_scope.py``; every behaviour has its
planted control.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from _branch_repos import advance, clone_pair
from _forge_state import StateForge, called_due

from dev_lab.dev.branchreview import (
    RECORD_TITLE,
    CarryRefused,
    carried_for,
    chained,
    dispose,
    read_record,
)
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgepulls import Marker, marker
from dev_lab.dev.forgereview import carry, review_tick
from dev_lab.dev.forgereview_advice import CARRIED_HOLD, Record, verdict
from dev_lab.dev.forgereview_declared import LENS_FIELD, PATHS_FIELD, RANGE_FIELD, Review
from dev_lab.dev.forgereview_findings import Finding
from dev_lab.dev.forgereview_scope import DISPOSED_FIELD, Budget, plan, review_base
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.platformparts import REVIEW_CONTEXT
from dev_lab.dev.prcontinue import open_continuation

_BASE = 'integrate/main'
_TARGET = f'origin/{_BASE}'
_WIDE = Budget(slice_bytes=10**6, total_bytes=10**7)
_SLICED = ('reviewer', '--range', RANGE_FIELD, '--lens', LENS_FIELD, '--paths', PATHS_FIELD,
           '--disposed', DISPOSED_FIELD)  # fmt: skip


def _finding(fid: str, *, security: bool = False) -> Finding:
    return Finding(fid, 'LOW', security, 'occams-razor', 'old.py', 'a', f'summary of {fid}', 'Bug')


def _reviewed(forge: StateForge, number: int, head: str, *found: Finding) -> None:
    """Post the forge's review ledger of *head* on PR *number*, as the review comment carries it."""
    forge._comment(number, {'body': f'{marker(Marker.REVIEW, head)}\n{Record(head, found).line()}'})


def _landed(forge: StateForge, head: str, *found: Finding, branch: str = 'pr/x') -> int:
    """A PR of *branch* at *head*, reviewed with *found*, then merged: its number."""
    number = forge.add_pull(branch, _BASE, title='feat: x', sha=head)
    _reviewed(forge, number, head, *found)
    forge._merge(number, {})
    return number


def _continued(forge: StateForge, landed: int, head: str) -> int:
    """The continuation the forge opens from *landed*'s branch, its head at *head*."""
    pull = open_continuation(forge, forge.pr_view(landed))
    forge.pulls[pull.number]['head']['sha'] = head
    return pull.number


# --- the record ---------------------------------------------------------------------------------------


def test_the_record_is_one_closed_issue_per_branch_and_a_rewrite_changes_nothing() -> None:
    forge = StateForge()
    first = chained(forge, 'pr/x', 3, 5)
    again = chained(forge, 'pr/x', 5)
    assert again == first
    assert first.prs == (3, 5)
    assert forge.titled(RECORD_TITLE.format(branch='pr/x'), state='closed') == [first.issue]
    assert forge.titled(RECORD_TITLE.format(branch='pr/x')) == [], 'state, never an open work item'
    assert read_record(forge, 'pr/y').prs == (), 'PLANTED CONTROL: another branch has its own record'


def test_a_record_an_untrusted_author_wrote_is_not_read() -> None:
    forge = StateForge(Forge('github.com', 'o', 'r'))
    made = chained(forge, 'pr/x', 3)
    forge.issues_by_number[made.issue]['user'] = {'login': 'stranger'}
    assert read_record(forge, 'pr/x').prs == ()
    forge.permissions['stranger'] = 'write'
    assert read_record(forge, 'pr/x').prs == (3,), 'PLANTED CONTROL: a writer the forge trusts is read'


# --- what a continuation carries -----------------------------------------------------------------------


def test_a_continuation_carries_its_predecessors_open_findings_and_a_first_pr_carries_none() -> None:
    forge = StateForge()
    landed = _landed(forge, 'a' * 40, _finding('F-1'), _finding('F-2'))
    number = _continued(forge, landed, 'b' * 40)
    found = carried_for(forge, forge.pr_view(number))
    assert found is not None
    assert (found.continues, found.since) == (landed, 'a' * 40)
    assert [one.id for one in found.open] == ['F-1', 'F-2']
    assert carried_for(forge, forge.pr_view(landed)) is None, 'PLANTED CONTROL: the first PR continues none'


def test_the_continuation_opens_with_its_carried_findings_in_its_body() -> None:
    forge = StateForge()
    landed = _landed(forge, 'a' * 40, _finding('F-1'))
    body = forge.pr_view(_continued(forge, landed, 'b' * 40)).body
    assert f'Continues #{landed}' in body
    assert '**open** `F-1`' in body


def test_a_resolved_or_deferred_finding_is_no_longer_open_and_outlives_the_pr() -> None:
    forge = StateForge()
    landed = _landed(forge, 'a' * 40, _finding('F-1'), _finding('F-2'))
    second = _continued(forge, landed, 'b' * 40)
    dispose(forge, forge.pr_view(second), 'F-1', state='resolved', reason='')
    dispose(forge, forge.pr_view(second), 'F-2', state='deferred', reason='needs the solver port first')
    found = carried_for(forge, forge.pr_view(second))
    assert found is not None
    assert found.open == ()
    assert {(one.id, how.state) for one, how in found.settled} == {('F-1', 'resolved'), ('F-2', 'deferred')}
    forge._merge(second, {})
    third = _continued(forge, second, 'c' * 40)
    later = carried_for(forge, forge.pr_view(third))
    assert later is not None
    assert later.continues == second
    assert later.open == (), 'a disposition made in #2 still stands in #3: the record is the branch`s'
    assert read_record(forge, 'pr/x').prs == (landed, second, third)


@pytest.mark.parametrize(
    ('finding', 'state', 'reason', 'why'),
    [
        ('F-1', 'deferred', '  ', 'needs a reason'),
        ('F-9', 'resolved', '', 'not a finding'),
        ('F-1', 'ignored', 'x', 'not a disposition'),
    ],
)
def test_a_disposition_the_record_cannot_take_is_refused(finding: str, state: str, reason: str, why: str) -> None:
    forge = StateForge()
    number = _continued(forge, _landed(forge, 'a' * 40, _finding('F-1')), 'b' * 40)
    with pytest.raises(CarryRefused, match=why):
        dispose(forge, forge.pr_view(number), finding, state=state, reason=reason)
    found = carried_for(forge, forge.pr_view(number))
    assert found is not None
    assert [one.id for one in found.open] == ['F-1'], 'a refusal records nothing'


def test_a_pr_that_continues_nothing_carries_nothing_to_dispose() -> None:
    forge = StateForge()
    number = forge.add_pull('pr/x', _BASE, sha='a' * 40)
    with pytest.raises(CarryRefused, match='continues no landed PR'):
        dispose(forge, forge.pr_view(number), 'F-1', state='resolved', reason='')


def test_an_open_carried_finding_holds_the_verdict() -> None:
    record = Record('b' * 40)
    state, said = verdict(record, 7, (_finding('F-1'),))
    assert state == 'failure'
    assert said.startswith(CARRIED_HOLD)
    assert 'review carry 7' in said
    assert verdict(record, 7)[0] == 'success', 'PLANTED CONTROL: nothing carried, nothing held'


# --- the scope: the increment since the last landed head -----------------------------------------------


def _squashed(tmp_path: Path) -> tuple[Path, str, str]:
    """A branch whose PR landed by SQUASH (its head is not on integration), then grew: ``(work, landed, head)``."""
    _, work = clone_pair(tmp_path)
    landed = advance(work, 'pr/x', 'old.py', 'old = 1\n')
    advance(work, _BASE, 'old.py', 'old = 1\n', 'squash of pr/x')
    head = advance(work, 'pr/x', 'new.py', 'new = 1\n')
    return work, landed, head


def _read(scope_paths: Sequence[Sequence[str]]) -> list[str]:
    return sorted(path for paths in scope_paths for path in paths)


def test_a_continuation_reads_only_the_increment_since_its_landed_head(tmp_path: Path) -> None:
    work, landed, head = _squashed(tmp_path)
    scope = plan(work, _TARGET, head, _WIDE, since=landed)
    assert scope.range == f'{landed}..{head}'
    assert _read([one.paths for one in scope.slices]) == ['new.py']
    whole = plan(work, _TARGET, head, _WIDE)
    assert _read([one.paths for one in whole.slices]) == ['new.py', 'old.py'], 'PLANTED CONTROL: no since, all'


def test_a_landed_head_the_branch_no_longer_holds_is_not_the_base(tmp_path: Path) -> None:
    """A rewritten branch: the landed head is not an ancestor, so the merge base stands."""
    work, _landed_head, head = _squashed(tmp_path)
    stray = advance(work, 'pr/other', 'stray.py', 'x\n')
    base = review_base(work, _TARGET, head)
    assert review_base(work, _TARGET, head, stray) == base
    assert review_base(work, _TARGET, head, _landed_head) != base


# --- the review of a continuation, end to end -----------------------------------------------------------


class _Command:
    """A review command printing one non-security finding per run, recording each argv and its disposed file."""

    def __init__(self) -> None:
        """No run yet."""
        self.ran: list[list[str]] = []
        self.disposed: list[dict[str, object]] = []

    def __call__(self, argv: Sequence[str], _root: Path) -> str:
        self.ran.append(list(argv))
        if '--disposed' in argv:
            path = Path(argv[argv.index('--disposed') + 1])
            self.disposed.append(json.loads(path.read_text(encoding='utf-8')))
        reviewer = {'name': 'r', 'provider': 'p', 'status': 'ok', 'dropped_findings': 0}
        row = {'id': 'F-new', 'severity': 'LOW', 'security': False, 'rule': 'occams-razor', 'file': 'new.py',
               'anchor': 'new', 'summary': 's', 'category': 'Bug', 'status': 'OPEN', 'reviewers': [],
               'suggestion': '', 'detail': '', 'confidence': 'single'}  # fmt: skip
        return json.dumps({'schema_version': 3, 'range': 'a..b', 'profiles': ['r'], 'reviewers': [reviewer],
                           'findings': [row]})  # fmt: skip


def _can(_argv: Sequence[str], _root: Path) -> str | None:
    return None


def _review(work: Path, forge: StateForge, command: _Command) -> tuple[str, ...]:
    return review_tick(work, forge, Review(command=_SLICED), base=_BASE, run=command, ready=_can, host='box')


def test_a_continuation_is_reviewed_for_its_increment_held_by_its_carry_until_disposed(tmp_path: Path) -> None:
    work, landed_head, head = _squashed(tmp_path)
    forge = StateForge()
    landed = _landed(forge, landed_head, _finding('F-1'), _finding('F-2'))
    number = _continued(forge, landed, head)
    dispose(forge, forge.pr_view(number), 'F-2', state='deferred', reason='after the port')
    called_due(forge, head)
    command = _Command()
    _review(work, forge, command)
    assert len(command.ran) == 1
    assert command.ran[0][command.ran[0].index('--range') + 1] == f'{landed_head}..{head}'
    assert command.ran[0][command.ran[0].index('--paths') + 1 :][:1] == ['new.py']
    assert command.disposed == [{'disposed': [{'id': 'F-2', 'reason': 'deferred: after the port'}]}]
    comment = next(c['body'] for c in forge.comments[number] if marker(Marker.REVIEW, head) in c['body'])
    assert f'over `{landed_head}..{head}`' in comment
    assert '**open** `F-1`' in comment
    latest = next(s for s in status_list(forge, head) if s.context == REVIEW_CONTEXT)
    assert (latest.state, CARRIED_HOLD in latest.description) == ('failure', True)

    said = carry(forge, Review(command=_SLICED), number, 'F-1', state='resolved', reason='', who='s')
    assert 'F-1 resolved' in said
    assert any(marker(Marker.REVIEW_CARRY, 'F-1') in c['body'] for c in forge.comments[number])
    _review(work, forge, command)
    assert len(command.ran) == 1, 'the verdict moves with no model call'
    latest = next(s for s in status_list(forge, head) if s.context == REVIEW_CONTEXT)
    assert latest.state == 'success'
    _review(work, forge, command)
    assert len([s for s in status_list(forge, head) if s.context == REVIEW_CONTEXT and s.state == 'success']) == 1, (
        'PLANTED CONTROL: an unchanged verdict is not posted again'
    )
