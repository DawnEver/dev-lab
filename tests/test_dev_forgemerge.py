"""INTEGRATION-TAKES-ONLY-FORGE-MERGES: the forge merges a green, clean, audit-passing PR -- and nothing else.

Real git repositories (a bare ``origin`` and a clone) and the stateful fake forge; the evidence is the merge the
forge was asked for (or not) and the one integration comment on the PR. Every refusal has its planted control:
the same PR, with the one missing condition supplied, is merged.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _branch_repos import advance, clone_pair, commit
from _forge_fake import git_out, run_git
from _forge_state import StateForge

from dev_lab.dev import forgeintegration
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgeintegration import Ticked, tick
from dev_lab.dev.forgemerge import FORGE_PULL, decide, merge, merge_message
from dev_lab.dev.forgepulls import Marker, marker
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.lanepolicy import Policy
from dev_lab.dev.sessionbranch import MERGED_BRANCH, merged_branch

POLICY = Policy(pr_merges_since='0' * 40)
_MANIFEST = "[tool.lab_commons.branchset]\ntrunk = 'main'\nsessions = ['integrate/main']\nephemeral = ['pr/*']\n"


def _green() -> list[dict[str, object]]:
    """Every part PASS and the review posted with no blocking finding open (the family declares a review)."""
    return [
        {'id': 1, 'context': 'tests/base', 'status': 'success', 'description': 'scope=full ran=3 hands=-'},
        {'id': 2, 'context': 'tests/review', 'status': 'success', 'description': 'review round 1: no blocking'},
        {'id': 3, 'context': 'tests/security', 'status': 'success', 'description': 'nothing found'},
    ]


def _statuses(raw: list[dict[str, object]]) -> tuple[CommitStatus, ...]:
    return tuple(CommitStatus(str(r['context']), str(r['status']), str(r['description']), '', 1) for r in raw)


def _tested(tmp_path: Path) -> Path:
    """A clone whose ``integrate/main`` carries a test, so the merge audit has something to audit."""
    _, work = clone_pair(tmp_path)
    (work / 'tests').mkdir()
    advance(work, 'integrate/main', 'tests/test_a.py', 'def test_a():\n    assert True\n')
    return work


def _work(tmp_path: Path) -> tuple[Path, str]:
    """A clone whose ``pr/x`` is one commit off main, ``integrate/main`` two ahead of it, and the PR head."""
    work = _tested(tmp_path)
    advance(work, 'integrate/main', 'i.txt', 'i\n')
    head = advance(work, 'pr/x', 'x.txt', 'x\n')
    (work / 'pyproject.toml').write_text(_MANIFEST, encoding='utf-8')
    return work, head


# --- the decision ---------------------------------------------------------------------------------


def test_a_green_clean_pr_is_ready_and_its_message_names_branch_and_pull(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    found = decide(work, POLICY, branch='pr/x', number=4, head=head, statuses=_statuses(_green()))
    assert found.ready, found.missing
    assert merged_branch(found.message) == 'pr/x'
    assert f'{FORGE_PULL}: 4' in found.message
    assert found.message.startswith('chore(merge): pr/x into integrate/main (#4)')


def test_a_pr_whose_parts_are_not_all_pass_waits_naming_them(tmp_path: Path) -> None:
    """PLANTED control: the same head with a PASS part is ready (the test above)."""
    work, head = _work(tmp_path)
    pending = [{'id': 1, 'context': 'tests/base', 'status': 'pending', 'description': 'scope=full ran=0 hands=-'}]
    for statuses in ((), _statuses(pending)):
        found = decide(work, POLICY, branch='pr/x', number=4, head=head, statuses=statuses)
        assert not found.ready
        assert any('every `tests/<part>` part PASS' in why for why in found.missing), found.missing


def test_a_pr_nobody_posted_on_says_unclaimed_and_a_claimed_one_inconclusive(tmp_path: Path) -> None:
    """The two waits are told apart: nothing posted is UNCLAIMED, a pending claim is INCONCLUSIVE."""
    work, head = _work(tmp_path)
    pending = [{'id': 1, 'context': 'tests/base', 'status': 'pending', 'description': 'claim machine=G'}]
    nothing = decide(work, POLICY, branch='pr/x', number=4, head=head, statuses=()).missing[0]
    claimed = decide(work, POLICY, branch='pr/x', number=4, head=head, statuses=_statuses(pending)).missing[0]
    assert 'UNCLAIMED' in nothing, nothing
    assert 'INCONCLUSIVE' not in nothing, nothing
    assert 'INCONCLUSIVE' in claimed, claimed


def test_a_conflicting_pr_waits_and_says_merge_integration_into_the_branch(tmp_path: Path) -> None:
    """PLANTED control: once integration is merged into the branch, the same PR is ready."""
    work = _tested(tmp_path)
    advance(work, 'integrate/main', 'c.txt', 'ours\n')
    run_git(work, 'checkout', '-q', '-B', 'pr/x', 'origin/main')
    head = commit(work, 'c.txt', 'theirs\n')
    found = decide(work, POLICY, branch='pr/x', number=4, head=head, statuses=_statuses(_green()))
    assert not found.ready
    (why,) = found.missing
    assert '`c.txt`' in why
    assert 'merge `integrate/main` into the branch' in why
    declared = 'merge integration\n\nc.txt: simpler-side -- the branch holds the live value\n'
    run_git(work, 'merge', '-q', '-X', 'ours', '-m', declared, 'origin/integrate/main')
    synced = git_out(work, 'rev-parse', 'HEAD')
    assert decide(work, POLICY, branch='pr/x', number=4, head=synced, statuses=_statuses(_green())).ready


def test_a_pr_whose_head_holds_an_undeclared_conflicted_merge_waits_naming_it(tmp_path: Path) -> None:
    """MERGE-RESOLUTION-DECLARED on the forge: a merge no client hook met is refused by sha, file and remedy.

    PLANTED control: the declared redo of the same merge is ready (the test above).
    """
    work = _tested(tmp_path)
    advance(work, 'integrate/main', 'c.txt', 'ours\n')
    run_git(work, 'checkout', '-q', '-B', 'pr/x', 'origin/main')
    commit(work, 'c.txt', 'theirs\n')
    run_git(work, 'merge', '-q', '-X', 'ours', '--no-edit', 'origin/integrate/main')
    synced = git_out(work, 'rev-parse', 'HEAD')
    found = decide(work, POLICY, branch='pr/x', number=4, head=synced, statuses=_statuses(_green()))
    (why,) = found.missing
    assert f'merge {synced[:12]}' in why
    assert 'c.txt: not declared' in why
    assert 'redo that merge' in why


def test_the_merge_door_is_a_merge_commit_pinned_to_the_judged_head() -> None:
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', sha='a' * 40)
    merge(forge, number, head='a' * 40, message=merge_message('pr/x', number, POLICY), delete_branch=True)
    ((merged, body),) = forge.merges
    assert merged == number
    assert body['Do'] == 'merge'
    assert body['head_commit_id'] == 'a' * 40
    assert body['delete_branch_after_merge'] is True
    assert f'{MERGED_BRANCH}: pr/x' in body['MergeMessageField']


def test_the_merge_door_refuses_a_forge_it_was_not_built_for() -> None:
    github = StateForge(Forge('github.com', 'o', 'r'))
    with pytest.raises(ValueError, match='gitea only'):
        merge(github, 1, head='a' * 40, message='m', delete_branch=False)


# --- the tick -------------------------------------------------------------------------------------


def _tick(work: Path, forge: StateForge, head: str, policy: Policy) -> tuple[str, ...]:
    return tick(work, forge, policy, fetch_pull=lambda _r, _m, _n: head).lines


def test_the_tick_merges_a_green_pr_once_declared_and_never_without(tmp_path: Path) -> None:
    """PLANTED control: the same green PR is only REPORTED where ``pr_merges_since`` is not declared."""
    work, head = _work(tmp_path)
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', sha=head)
    forge.statuses[head] = _green()
    _tick(work, forge, head, Policy())
    assert forge.merges == []
    _tick(work, forge, head, POLICY)
    ((merged, body),) = forge.merges
    assert merged == number
    assert body['delete_branch_after_merge'] is True, 'a pr/* head is ephemeral: the forge deletes it'
    (comment,) = forge.comments[number]
    assert marker(Marker.INTEGRATION) in comment['body']
    assert 'merged by the forge' in comment['body']


def test_a_red_pr_stays_open_with_what_is_missing_in_its_one_comment(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', sha=head)
    forge.statuses[head] = [{'id': 1, 'context': 'tests/base', 'status': 'failure', 'description': 'scope=full ran=3'}]
    _tick(work, forge, head, POLICY)
    _tick(work, forge, head, POLICY)
    assert forge.merges == []
    assert forge.pulls[number]['state'] == 'open'
    (comment,) = forge.comments[number]
    assert 'the forge merges it once it has: every `tests/<part>` part PASS' in comment['body']


# --- the verb -------------------------------------------------------------------------------------


def test_the_integration_verb_prints_the_tick_lines_before_the_branch_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``forge integration`` is the integrator's whole loop, so its rendering is part of the flow.

    PLANTED control: the same tick with no child prints the one placeholder line instead.
    """
    root = tmp_path

    class Row:
        def line(self) -> str:
            return 'deletable  local  pr/gone  landed'

    monkeypatch.setattr(forgeintegration, 'client_for', lambda _root: object())
    monkeypatch.setattr(forgeintegration, 'load_policy', lambda _root: POLICY)
    monkeypatch.setattr(forgeintegration, 'tick', lambda *_a, **_k: Ticked(('pr/x #4: merged by the forge',), ()))
    monkeypatch.setattr(forgeintegration, 'listing', lambda *_a, **_k: (Row(),))
    assert forgeintegration.main([], cwd=root, fetch=lambda _root: None) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [
        '[integration] pr/x #4: merged by the forge',
        '[integration] branch: deletable  local  pr/gone  landed',
    ]

    monkeypatch.setattr(forgeintegration, 'tick', lambda *_a, **_k: Ticked((), ()))
    monkeypatch.setattr(forgeintegration, 'listing', lambda *_a, **_k: ())
    assert forgeintegration.main([], cwd=root, fetch=lambda _root: None) == 0
    assert capsys.readouterr().out.strip() == '[integration] no open child branch'
