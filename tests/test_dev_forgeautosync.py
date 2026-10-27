"""AUTO-SYNC: the serve tick merges integration INTO a behind ``pr/*`` head and pushes it -- once per tip, never raced.

Real git (a bare ``origin`` and a clone) and the stateful fake forge; the evidence is what ``origin`` holds after
the tick, the head's ``integration/sync`` status and the PR's one integration comment. Every refusal has its
planted control: the same PR with the one condition supplied is synced.
"""

from __future__ import annotations

import functools
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from _branch_repos import advance, clone_pair, commit
from _forge_fake import git_out, run_git
from _forge_state import StateForge

from dev_lab.dev import forgeautosync
from dev_lab.dev.forgeautosync import CONTEXT, sync
from dev_lab.dev.forgeintegration import tick
from dev_lab.dev.lanepolicy import Policy, policy_from
from dev_lab.dev.mergeresolution import judge as resolution_judge
from dev_lab.dev.sessionbranch import MERGED_BRANCH

POLICY = Policy(pr_merges_since='0' * 40)
_MANIFEST = "[tool.lab_commons.branchset]\ntrunk = 'main'\nsessions = ['integrate/main']\nephemeral = ['pr/*']\n"
_LATER = datetime.now(UTC) + timedelta(hours=1)


class _Report:
    ok, remedy, attempts = True, '', ()


def _fresh(_tree: Path) -> _Report:
    return _Report()


def _never(_tree: Path) -> int:
    msg = 'a fresh, unconflicted lock is never relocked'
    raise AssertionError(msg)


def _push(tree: Path, branch: str, to: str = '') -> None:
    run_git(tree, 'push', '-q', '--no-verify', 'origin', f'refs/heads/{branch}:refs/heads/{to or branch}')
    run_git(tree, 'fetch', '-q', 'origin')


def _synced(**seams: object) -> functools.partial[str]:
    return functools.partial(sync, **({'resolve': _fresh, 'upgrade': _never, 'push': _push} | seams))


def _world(tmp_path: Path, branch: str = 'pr/x') -> tuple[Path, str, str]:
    """``(clone, head, tip)``: *branch* one commit off main, integration one commit ahead of main."""
    _, work = clone_pair(tmp_path)
    (work / 'tests').mkdir()
    advance(work, 'main', 'tests/test_a.py', 'def test_a():\n    assert True\n')  # the audit audits something
    _push(work, 'tmp-main', 'integrate/main')
    run_git(work, 'checkout', '-q', '--detach')
    run_git(work, 'branch', '-q', '-D', 'tmp-main')
    tip = advance(work, 'integrate/main', 'i.txt', 'i\n')
    head = advance(work, branch, 'x.txt', 'x\n')
    run_git(work, 'checkout', '-q', '--detach')
    run_git(work, 'branch', '-q', '-D', f'tmp-{branch.replace("/", "-")}', 'tmp-integrate-main')
    (work / 'pyproject.toml').write_text(_MANIFEST, encoding='utf-8')
    return work, head, tip


def _tick(work: Path, forge: StateForge, heads: dict[int, str], *, policy: Policy = POLICY, now: datetime = _LATER,
          host: str = 'h1', run: object = None) -> tuple[str, ...]:  # fmt: skip
    return tick(
        work,
        forge,
        policy,
        fetch_pull=lambda _r, _m, n: heads[n],
        host=host,
        clock=lambda _c: now,
        sync=run or _synced(),
    ).lines


def _origin(work: Path, branch: str) -> str:
    run_git(work, 'fetch', '-q', 'origin')
    return git_out(work, 'rev-parse', f'origin/{branch}')


def _status(forge: StateForge, sha: str) -> dict[str, object]:
    return [one for one in forge.statuses.get(sha, []) if one['context'] == CONTEXT][-1]


def test_a_behind_pr_head_is_merged_with_integration_and_pushed_under_its_own_name(tmp_path: Path) -> None:
    """PLANTED control: no forge merges (``pr_merges_since`` undeclared), or no serving host: the PR is left alone."""
    work, head, tip = _world(tmp_path)
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', sha=head)
    _tick(work, forge, {number: head}, policy=Policy())
    _tick(work, forge, {number: head}, host='')
    assert _origin(work, 'pr/x') == head
    _tick(work, forge, {number: head})
    new = _origin(work, 'pr/x')
    assert git_out(work, 'rev-list', '--parents', '-n', '1', new).split()[1:] == [head, tip], 'a merge, head first'
    assert f'{MERGED_BRANCH}: integrate/main' in git_out(work, 'log', '-1', '--format=%B', new)
    assert _status(forge, head)['state'] == 'success'
    assert 'auto-sync: merged `integrate/main`' in forge.comments[number][0]['body']
    assert git_out(work, 'worktree', 'list', '--porcelain').count('worktree ') == 1, 'its worktree is removed'
    assert not git_out(work, 'branch', '--list', 'pr/x'), 'its local branch is removed'


def test_one_sync_per_integration_tip(tmp_path: Path) -> None:
    """PLANTED control: a new integration tip earns the same head one new attempt."""
    work, head, _ = _world(tmp_path)
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', sha=head)
    calls: list[str] = []

    def refused(*_a: object, **_k: object) -> str:
        calls.append('sync')
        raise forgeautosync.SyncRefused(forgeautosync.PUSH.format(branch='pr/x', why='planted'))

    _tick(work, forge, {number: head}, run=refused)
    _tick(work, forge, {number: head}, run=refused)
    assert calls == ['sync']
    assert 'the push of pr/x failed' in forge.comments[number][0]['body']
    advance(work, 'integrate/main', 'j.txt', 'j\n')
    _tick(work, forge, {number: head}, run=refused)
    assert calls == ['sync', 'sync']


def test_a_textual_conflict_is_said_once_and_never_resolved(tmp_path: Path) -> None:
    """PLANTED control: the clean PR of the first test is synced."""
    work, _, _ = _world(tmp_path)
    head = advance(work, 'pr/c', 'i.txt', 'theirs\n')
    forge = StateForge()
    number = forge.add_pull('pr/c', 'integrate/main', sha=head)
    _tick(work, forge, {number: head})
    _tick(work, forge, {number: head})
    assert _origin(work, 'pr/c') == head
    assert _status(forge, head)['state'] == 'failure'
    assert len([s for s in forge.statuses[head] if s['context'] == CONTEXT]) == 1, 'said once'
    (comment,) = forge.comments[number]
    assert 'conflicts with integrate/main in `i.txt`' in comment['body']


def test_a_stacked_pr_names_the_pr_it_waits_behind_and_syncs_once_that_one_merged(tmp_path: Path) -> None:
    """PLANTED control: once the lower PR's head is in integration, the stacked one is synced."""
    work, lower, _ = _world(tmp_path)
    run_git(work, 'checkout', '-q', '-B', 'tmp-up', lower)
    upper = commit(work, 'y.txt', 'y\n')
    run_git(work, 'push', '-q', '--no-verify', 'origin', 'HEAD:refs/heads/pr/y')
    run_git(work, 'checkout', '-q', '--detach')
    run_git(work, 'branch', '-q', '-D', 'tmp-up')
    forge = StateForge()
    a = forge.add_pull('pr/x', 'integrate/main', sha=lower)
    b = forge.add_pull('pr/y', 'integrate/main', sha=upper)
    _tick(work, forge, {a: lower, b: upper}, run=_synced(push=lambda *_: None))
    assert f'waits behind #{a} (pr/x)' in forge.comments[b][0]['body']
    assert _origin(work, 'pr/y') == upper
    run_git(work, 'checkout', '-q', '-B', 'tmp-i', 'origin/integrate/main')
    run_git(work, 'merge', '-q', '--no-ff', '--no-edit', lower)
    run_git(work, 'push', '-q', '--no-verify', 'origin', 'HEAD:refs/heads/integrate/main')
    run_git(work, 'checkout', '-q', '--detach')
    run_git(work, 'branch', '-q', '-D', 'tmp-i')
    forge.pulls[a]['state'] = 'closed'
    _tick(work, forge, {b: upper})
    assert _origin(work, 'pr/y') != upper
    assert 'auto-sync: merged' in forge.comments[b][0]['body']


def test_a_head_committed_inside_the_quiet_period_is_not_raced(tmp_path: Path) -> None:
    """PLANTED control: the same head past the quiet period is synced."""
    work, head, _ = _world(tmp_path)
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', sha=head)
    _tick(work, forge, {number: head}, now=datetime.now(UTC) + timedelta(minutes=1))
    assert _origin(work, 'pr/x') == head
    assert 'inside auto_sync_quiet 10 min' in forge.comments[number][0]['body']
    _tick(work, forge, {number: head})
    assert _origin(work, 'pr/x') != head


def test_a_head_outside_the_ephemeral_namespace_is_never_synced(tmp_path: Path) -> None:
    """PLANTED control: the same PR on a ``pr/*`` head is synced (the first test)."""
    work, head, _ = _world(tmp_path, 'feat/x')
    forge = StateForge()
    number = forge.add_pull('feat/x', 'integrate/main', sha=head)
    _tick(work, forge, {number: head})
    assert _origin(work, 'feat/x') == head
    assert 'feat/x is not an ephemeral head' in forge.comments[number][0]['body']


def test_a_conflict_in_the_lock_alone_is_relocked_inside_the_merge(tmp_path: Path) -> None:
    """PLANTED control: a conflict in any other file is refused (the conflict test)."""
    work, _, _ = _world(tmp_path)
    advance(work, 'integrate/main', 'uv.lock', 'ours\n')
    head = advance(work, 'pr/l', 'uv.lock', 'theirs\n')
    forge = StateForge()
    number = forge.add_pull('pr/l', 'integrate/main', sha=head)

    def door(tree: Path) -> int:
        (tree / 'uv.lock').write_text('relocked\n', encoding='utf-8')
        return 0

    _tick(work, forge, {number: head}, run=_synced(upgrade=door))
    new = _origin(work, 'pr/l')
    assert new != head
    assert git_out(work, 'show', f'{new}:uv.lock') == 'relocked'
    parents = git_out(work, 'rev-parse', f'{new}^1', f'{new}^2').split()
    message = git_out(work, 'log', '-1', '--format=%B', new)
    assert resolution_judge(work, parents, message) == ()  # MERGE-RESOLUTION-DECLARED: the forge's own merge lands


def test_a_stale_lock_after_a_clean_merge_is_relocked_and_an_unrunnable_resolution_refuses(tmp_path: Path) -> None:
    """PLANTED control: a fresh lock is never relocked (``_never`` in every other test)."""
    work, head, _ = _world(tmp_path)
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', sha=head)

    class Broken(_Report):
        ok, remedy = False, 'the network is down'

    _tick(work, forge, {number: head}, run=_synced(resolve=lambda _t: Broken()))
    assert _origin(work, 'pr/x') == head
    assert 'the lock could not be relocked' in forge.comments[number][0]['body']


def test_a_merge_the_audit_refuses_is_never_pushed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED: the audit names a deviation. Control: the unplanted audit passes the same merge (the first test)."""
    work, head, _ = _world(tmp_path)
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', sha=head)
    monkeypatch.setattr(forgeautosync, 'judge', lambda *_a, **_k: ('LOST tests/test_a.py::test_a',))
    _tick(work, forge, {number: head})
    assert _origin(work, 'pr/x') == head
    assert 'the merge audit refuses the machine merge: LOST' in forge.comments[number][0]['body']


def test_a_local_branch_of_the_heads_name_is_an_authors_and_is_refused(tmp_path: Path) -> None:
    work, head, _ = _world(tmp_path)
    run_git(work, 'branch', 'pr/x', head)
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', sha=head)
    _tick(work, forge, {number: head})
    assert _origin(work, 'pr/x') == head
    assert 'a local branch pr/x exists on this host' in forge.comments[number][0]['body']
    assert git_out(work, 'rev-parse', 'pr/x') == head, 'the local branch is never reset'


def test_auto_sync_has_no_switch_of_its_own_and_its_quiet_period_is_a_duration() -> None:
    """Auto-sync rides auto-merge's declaration (``pr_merges_since``); an ``auto_sync`` key is refused."""
    declared = policy_from('[tool.lab_commons.integrator]\nauto_sync_quiet = "5 min"\n', 't')
    assert forgeautosync.quiet_after(declared) == timedelta(minutes=5)
    with pytest.raises(ValueError, match='unknown key'):
        policy_from('[tool.lab_commons.integrator]\nauto_sync = true\n', 't')
    with pytest.raises(ValueError, match='needs a unit'):
        forgeautosync.quiet_after(Policy(auto_sync_quiet='10'))
