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

from lab_commons.dev.forge import Forge
from lab_commons.dev.forgeintegration import tick
from lab_commons.dev.forgemerge import FORGE_PULL, decide, merge, merge_message
from lab_commons.dev.forgepulls import Marker, marker
from lab_commons.dev.forgestatus import CommitStatus
from lab_commons.dev.lanepolicy import Policy
from lab_commons.dev.sessionbranch import MERGED_BRANCH, merged_branch

POLICY = Policy(pr_merges_since='0' * 40)
_MANIFEST = "[tool.lab_commons.branchset]\ntrunk = 'main'\nsessions = ['integrate/main']\nephemeral = ['pr/*']\n"


def _green() -> list[dict[str, object]]:
    return [{'id': 1, 'context': 'tests/base', 'status': 'success', 'description': 'scope=full ran=3 hands=-'}]


def _statuses(raw: list[dict[str, object]]) -> tuple[CommitStatus, ...]:
    return tuple(CommitStatus(str(r['context']), str(r['status']), str(r['description']), '', 1) for r in raw)


def _work(tmp_path: Path) -> tuple[Path, str]:
    """A clone whose ``pr/x`` is one commit off ``integrate/main`` (itself one ahead of main), and its head."""
    _, work = clone_pair(tmp_path)
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


def test_a_conflicting_pr_waits_and_says_merge_integration_into_the_branch(tmp_path: Path) -> None:
    """PLANTED control: once integration is merged into the branch, the same PR is ready."""
    _, work = clone_pair(tmp_path)
    advance(work, 'integrate/main', 'c.txt', 'ours\n')
    run_git(work, 'checkout', '-q', '-B', 'pr/x', 'origin/main')
    head = commit(work, 'c.txt', 'theirs\n')
    found = decide(work, POLICY, branch='pr/x', number=4, head=head, statuses=_statuses(_green()))
    assert not found.ready
    (why,) = found.missing
    assert '`c.txt`' in why
    assert 'merge `integrate/main` into the branch' in why
    run_git(work, 'merge', '-q', '-X', 'ours', '--no-edit', 'origin/integrate/main')
    synced = git_out(work, 'rev-parse', 'HEAD')
    assert decide(work, POLICY, branch='pr/x', number=4, head=synced, statuses=_statuses(_green())).ready


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
