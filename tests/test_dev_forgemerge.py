"""INTEGRATION-TAKES-ONLY-FORGE-MERGES: the forge merges a green, clean, audit-passing PR -- and nothing else.

Real git repositories (a bare ``origin`` and a clone) and the stateful fake forge; the evidence is the merge the
forge was asked for (or not) and the one integration comment on the PR. Every refusal has its planted control:
the same PR, with the one missing condition supplied, is merged.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from _branch_repos import advance, clone_pair, commit
from _forge_fake import git_out, run_git
from _forge_state import StateForge
from test_dev_githook_scripts import _plant_checker

from dev_lab.dev import forgeintegration, forgemerge
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgeintegration import Ticked, tick
from dev_lab.dev.forgemerge import FORGE_PULL, decide, merge, merge_message
from dev_lab.dev.forgepulls import Marker, marker
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.forgework import ACTIONS_BOT
from dev_lab.dev.lanepolicy import Policy
from dev_lab.dev.reviewgate import github_posted, status_gate
from dev_lab.dev.sessionbranch import MERGED_BRANCH, merged_branch

_DECLARED = Policy(integration='integrate/main')  # every repo declares its integration branch (D83)

POLICY = dataclasses.replace(_DECLARED, pr_merges_since='0' * 40)
_MANIFEST = "[tool.dev_lab.branchset]\ntrunk = 'main'\nsessions = ['integrate/main']\nephemeral = ['pr/*']\n"


def _green() -> list[dict[str, object]]:
    """Every part PASS and the review posted with no blocking finding open (the family declares a review)."""
    return [
        {'id': 1, 'context': 'tests/base', 'status': 'success', 'description': 'scope=full ran=3 hands=-'},
        {
            'id': 2,
            'context': 'tests/review',
            'status': 'success',
            'description': 'reviewed abc: advice 0 HIGH, 0 MEDIUM, 0 LOW; none blocks',
            'creator': None,
        },  # the review job: a null creator, which Gitea counts as it counts every poster
        {'id': 3, 'context': 'tests/security', 'status': 'success', 'description': 'nothing found'},
    ]


def _statuses(raw: list[dict[str, object]]) -> tuple[CommitStatus, ...]:
    return tuple(
        CommitStatus(str(r['context']), str(r['status']), str(r['description']), '', 1, ACTIONS_BOT) for r in raw
    )


def _tested(tmp_path: Path) -> Path:
    """A clone whose ``integrate/main`` carries a test, so the merge audit has something to audit."""
    _, work = clone_pair(tmp_path)
    (work / 'tests').mkdir()
    advance(work, 'integrate/main', 'tests/test_a.py', 'def test_a():\n    assert True\n')
    return work


def _work(tmp_path: Path) -> tuple[Path, str]:
    """A clone whose ``pr/x`` is one commit off main, ``integrate/main`` two ahead of it, and the PR head."""
    work = _tested(tmp_path)
    advance(work, 'integrate/main', 'i.txt', 'i\n', 'feat: i')
    head = advance(work, 'pr/x', 'x.txt', 'x\n', 'feat: x')
    (work / 'pyproject.toml').write_text(_MANIFEST, encoding='utf-8')
    return work, head


# --- the decision ---------------------------------------------------------------------------------


def test_a_green_clean_pr_is_ready_and_its_message_names_branch_and_pull(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    found = decide(
        work,
        POLICY,
        branch='pr/x',
        number=4,
        head=head,
        statuses=_statuses(_green()),
        reviewed=status_gate(github_posted),
    )
    assert found.ready, found.missing
    assert merged_branch(found.message) == 'pr/x'
    assert f'{FORGE_PULL}: 4' in found.message
    assert found.message.startswith('chore(merge): pr/x into integrate/main (#4)')


def test_a_pr_whose_base_failed_is_not_ready_though_review_and_security_pass(tmp_path: Path) -> None:
    """dev-lab#78 (head f661172d): review and security pass, ``tests/base`` and ``tests/base@windows`` FAILED.

    User ruling 2026-11-04: a PR merges only when every part it needs stands green at its head; #78 merged.
    PLANTED CONTROL: the same PR with its parts PASS is ready (``test_a_green_clean_pr_is_ready...``).
    """
    work, head = _work(tmp_path)
    gates = [r for r in _green() if r['context'] != 'tests/base']
    red = 'scope=full ran=5882 hands=workstation:5'
    raw = [
        *gates,
        {'id': 7, 'context': 'tests/base', 'status': 'failure', 'description': red},
        {'id': 8, 'context': 'tests/base@windows', 'status': 'failure', 'description': red},
        {'id': 9, 'context': 'tests/workstation', 'status': 'success', 'description': 'scope=full ran=5 hands=-'},
    ]
    found = decide(
        work, POLICY, branch='pr/x', number=78, head=head, statuses=_statuses(raw), reviewed=status_gate(github_posted)
    )
    assert not found.ready
    assert any(one.startswith('its test parts: ') and 'FAIL' in one for one in found.missing), found.missing


def test_a_pr_whose_parts_are_absent_or_pending_waits(tmp_path: Path) -> None:
    """An unsettled part is no green: the PR waits, naming its parts, until every one stands PASS."""
    work, head = _work(tmp_path)
    gates = [r for r in _green() if r['context'] != 'tests/base']
    for part in ('pending', None):
        raw = gates + (
            [{'id': 9, 'context': 'tests/base', 'status': part, 'description': 'scope=full'}] if part else []
        )
        found = decide(
            work,
            POLICY,
            branch='pr/x',
            number=4,
            head=head,
            statuses=_statuses(raw),
            reviewed=status_gate(github_posted),
        )
        assert any(one.startswith('its test parts: ') for one in found.missing), (part, found.missing)


def test_a_conflicting_pr_waits_and_says_merge_integration_into_the_branch(tmp_path: Path) -> None:
    """PLANTED control: once integration is merged into the branch, the same PR is ready."""
    work = _tested(tmp_path)
    advance(work, 'integrate/main', 'c.txt', 'ours\n')
    run_git(work, 'checkout', '-q', '-B', 'pr/x', 'origin/main')
    head = commit(work, 'c.txt', 'theirs\n')
    found = decide(
        work,
        POLICY,
        branch='pr/x',
        number=4,
        head=head,
        statuses=_statuses(_green()),
        reviewed=status_gate(github_posted),
    )
    assert not found.ready
    (why,) = found.missing
    assert '`c.txt`' in why
    assert 'merge `integrate/main` into the branch' in why
    declared = 'merge integration\n\nc.txt: simpler-side -- the branch holds the live value\n'
    run_git(work, 'merge', '-q', '-X', 'ours', '-m', declared, 'origin/integrate/main')
    synced = git_out(work, 'rev-parse', 'HEAD')
    assert decide(
        work,
        POLICY,
        branch='pr/x',
        number=4,
        head=synced,
        statuses=_statuses(_green()),
        reviewed=status_gate(github_posted),
    ).ready


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
    found = decide(
        work,
        POLICY,
        branch='pr/x',
        number=4,
        head=synced,
        statuses=_statuses(_green()),
        reviewed=status_gate(github_posted),
    )
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


def test_on_github_the_merge_door_puts_a_merge_commit_pinned_to_the_head() -> None:
    github = StateForge(Forge('github.com', 'o', 'r'))
    number = github.add_pull('pr/x', 'integrate/main', sha='a' * 40)
    merge(github, number, head='a' * 40, message='subject\n\nbody', delete_branch=False)
    assert github.merges == [
        (number, {'commit_title': 'subject', 'commit_message': 'body', 'sha': 'a' * 40, 'merge_method': 'merge'})
    ]
    assert github.deleted_refs == []


# --- the tick -------------------------------------------------------------------------------------


def _tick(work: Path, forge: StateForge, head: str, policy: Policy) -> tuple[str, ...]:
    return tick(work, forge, policy, fetch_pull=lambda _r, _m, _n: head).lines


def test_the_tick_merges_a_green_pr_once_declared_and_never_without(tmp_path: Path) -> None:
    """PLANTED control: the same green PR is only REPORTED where ``pr_merges_since`` is not declared."""
    work, head = _work(tmp_path)
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', sha=head)
    forge.statuses[head] = _green()
    _tick(work, forge, head, _DECLARED)
    assert forge.merges == []
    _tick(work, forge, head, POLICY)
    ((merged, body),) = forge.merges
    assert merged == number
    assert body['delete_branch_after_merge'] is True, 'a pr/* head is ephemeral: the forge deletes it'
    (comment,) = forge.comments[number]
    assert marker(Marker.INTEGRATION) in comment['body']
    assert 'merged by the forge' in comment['body']


def test_the_tick_leaves_the_merge_to_a_repo_s_merge_job_and_still_says_the_decision(tmp_path: Path) -> None:
    """P3: a repo declaring the CI merger is merged by its Gitea job; PLANTED CONTROL: the test above merges."""
    work, head = _work(tmp_path)
    (work / 'pyproject.toml').write_text(_MANIFEST + '[tool.dev_lab.ci."merge.yml"]\n', encoding='utf-8')
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', sha=head)
    forge.statuses[head] = _green()
    _tick(work, forge, head, POLICY)
    assert forge.merges == []
    (comment,) = forge.comments[number]
    assert 'ready: the merge.yml job merges it' in comment['body']


def test_a_pr_with_a_failed_part_stays_open(tmp_path: Path) -> None:
    """A red ``tests/<part>`` holds the merge into integration (user ruling 2026-11-04)."""
    work, head = _work(tmp_path)
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', sha=head)
    red = {'id': 1, 'context': 'tests/base', 'status': 'failure', 'description': 'scope=full ran=3 hands=-'}
    forge.statuses[head] = [red, *(r for r in _green() if r['context'] != 'tests/base')]
    _tick(work, forge, head, POLICY)
    assert forge.merges == []
    assert forge.pulls[number]['state'] == 'open'


def test_an_unsafe_pr_stays_open_with_what_is_missing_in_its_one_comment(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', sha=head)
    unsafe = {'id': 3, 'context': 'tests/security', 'status': 'failure', 'description': 'B602 shell=True'}
    forge.statuses[head] = [*(r for r in _green() if r['context'] != 'tests/security'), unsafe]
    _tick(work, forge, head, POLICY)
    _tick(work, forge, head, POLICY)
    assert forge.merges == []
    assert forge.pulls[number]['state'] == 'open'
    (comment,) = forge.comments[number]
    assert 'the forge merges it once it has: its security check' in comment['body']


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


# --- the commit messages, judged at the merge by the repo's own declared row ----------------------

_CZ_ROW = (
    '[tool.dev_lab.hooks]\npre-push = [{ id = "message-range", run = ["python", "-m", "dev_lab.dev.githooks", '
    '"script", "cz-push-range"], always_run = true, refs = "^refs/heads/", env = { LAB_CZ_BASE_REF = '
    '"origin/integrate/main" } }]\n'
)


@pytest.mark.parametrize(('message', 'mergeable'), [('data(x): y', False), ('feat(x): y', True)])
def test_a_pr_whose_commit_message_is_off_format_is_NOT_mergeable(
    tmp_path: Path, message: str, *, mergeable: bool
) -> None:
    """A worktree without hooks (no venv: the hooks never ran) cannot land ``data(x): y``.

    PLANTED CONTROL: the same PR with a conventional subject is ready.
    """
    work, _ = _work(tmp_path)
    (work / 'pyproject.toml').write_text(_MANIFEST + _CZ_ROW, encoding='utf-8')
    head = advance(work, 'pr/x', 'y.txt', 'y\n', message)
    _plant_checker(work)
    found = decide(
        work,
        POLICY,
        branch='pr/x',
        number=4,
        head=head,
        statuses=_statuses(_green()),
        reviewed=status_gate(github_posted),
    )
    assert found.ready is mergeable, found.missing
    if not mergeable:
        assert any(one.startswith('conventional commit messages') and "'data(x): y'" in one for one in found.missing), (
            found.missing
        )


def test_a_repo_declaring_no_message_row_is_not_judged_on_messages(tmp_path: Path) -> None:
    work, _ = _work(tmp_path)
    head = advance(work, 'pr/x', 'y.txt', 'y\n', 'data(x): y')
    found = decide(
        work,
        POLICY,
        branch='pr/x',
        number=4,
        head=head,
        statuses=_statuses(_green()),
        reviewed=status_gate(github_posted),
    )
    assert found.ready, found.missing


# --- a review that did not run warns and merges (user rulings 2026-11-05, 2026-11-06) ----------------

_UNREVIEWED = 'Unreviewed: no reviewer returned findings (a unsupported)'


def _unreviewed_review(raw: list[dict[str, object]]) -> list[dict[str, object]]:
    """*raw* with ``tests/review`` the pending the serve posts for a review that did not run: never a success."""
    review = {
        'id': 2,
        'context': 'tests/review',
        'status': 'pending',
        'description': 'not reviewed, merges unreviewed: x',
    }
    return [review if r['context'] == 'tests/review' else r for r in raw]


def test_a_unreviewed_review_with_green_tests_merges_warned_in_its_message(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    found = decide(
        work, POLICY, branch='pr/x', number=4, head=head, statuses=_statuses(_unreviewed_review(_green())),
        reviewed=status_gate(github_posted), waiver=_UNREVIEWED,
    )  # fmt: skip
    assert found.ready, found.missing
    assert found.unreviewed == _UNREVIEWED
    assert _UNREVIEWED in found.message
    assert merged_branch(found.message) == 'pr/x'


def test_a_unreviewed_review_with_red_tests_does_not_merge(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    raw = [r for r in _unreviewed_review(_green()) if r['context'] != 'tests/base']
    raw.append({'id': 7, 'context': 'tests/base', 'status': 'failure', 'description': 'scope=full ran=3 hands=-'})
    found = decide(
        work, POLICY, branch='pr/x', number=4, head=head, statuses=_statuses(raw),
        reviewed=status_gate(github_posted), waiver=_UNREVIEWED,
    )  # fmt: skip
    assert not found.ready
    assert any(one.startswith('its test parts: ') for one in found.missing), found.missing
    assert not any(one.startswith('its review: ') for one in found.missing), found.missing


def test_a_security_finding_with_no_waiver_still_blocks(tmp_path: Path) -> None:
    """PLANTED CONTROL: a security finding with no waiver recorded waits on the review, unwarned."""
    work, head = _work(tmp_path)
    raw = [
        {**r, 'status': 'failure', 'description': 'security finding(s) F-1'} if r['context'] == 'tests/review' else r
        for r in _green()
    ]
    for statuses in (raw, _unreviewed_review(_green())):  # a status saying "unreviewed" is no waiver: the record is
        found = decide(
            work, POLICY, branch='pr/x', number=4, head=head, statuses=_statuses(statuses),
            reviewed=status_gate(github_posted),
        )  # fmt: skip
        assert any(one.startswith('its review: ') for one in found.missing), found.missing
        assert not found.unreviewed
        assert 'Unreviewed' not in found.message


def test_a_missing_integration_ref_is_a_NAMED_reason_never_a_crash(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    (work / 'pyproject.toml').write_text(_MANIFEST + _CZ_ROW, encoding='utf-8')
    said = forgemerge.message_wait(work, 'refs/remotes/origin/no-such-branch', head)
    assert said is not None
    assert 'no-such-branch' in said
    assert 'does not resolve' in said


def test_a_message_check_past_its_timeout_is_a_NAMED_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work, head = _work(tmp_path)
    (work / 'pyproject.toml').write_text(_MANIFEST + _CZ_ROW, encoding='utf-8')
    monkeypatch.setattr(forgemerge, 'MESSAGE_TIMEOUT_S', 0.001)
    said = forgemerge.message_wait(work, 'refs/remotes/origin/integrate/main', head)
    assert said is not None
    assert 'timed out' in said


def test_a_ready_decision_with_no_message_row_SAYS_messages_are_not_declared(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    found = decide(work, POLICY, branch='pr/x', number=4, head=head, statuses=_statuses(_green()))
    assert found.ready, found.missing
    assert 'messages: not declared' in found.notes
