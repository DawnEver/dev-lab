"""ONE-SESSION-ONE-PR and NO-STACKED-PRS, driven on a REAL repository with real ``origin/*`` refs.

PLANTED CONTROLS on each side: a second head of the same session is refused naming the first head's branch, a
head of another session passes; a head holding another open head's unmerged commit is refused, the same
commit once in integration passes; a declared split admits its session; only a NEW ``pr/*`` is judged at push.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import pradmit
from dev_lab.dev.forgework import PullRequest
from dev_lab.dev.labsession import TRAILER
from dev_lab.dev.lanepolicy import Policy
from dev_lab.dev.trialmerge import shares_unmerged

_GIT = shutil.which('git') or 'git'
_ZERO = '0' * 40
_TIP = 'refs/remotes/origin/integrate/main'


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        [_GIT, '-c', 'user.email=t@t', '-c', 'user.name=t', *args],
        cwd=root, check=True, capture_output=True, text=True, encoding='utf-8', timeout=60,
    )  # fmt: skip
    return done.stdout.strip()


def _commit(root: Path, subject: str, session: str = '') -> str:
    message = f'{subject}\n\n{TRAILER}: {session}' if session else subject
    _git(root, 'commit', '-q', '--allow-empty', '-m', message)
    return _git(root, 'rev-parse', 'HEAD')


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / 'r'
    root.mkdir()
    _git(root, 'init', '-q', '-b', 'integrate/main')
    _git(root, 'update-ref', _TIP, _commit(root, 'base'))
    return root


def _head(root: Path, name: str, *subjects: tuple[str, str], start: str = _TIP) -> str:
    """A branch *name* cut from *start* with one commit per ``(subject, session)``, published as origin/*name*."""
    _git(root, 'checkout', '-q', '-B', name, start)
    sha = ''
    for subject, session in subjects:
        sha = _commit(root, subject, session)
    _git(root, 'update-ref', f'refs/remotes/origin/{name}', sha)
    return sha


def _open(number: int, branch: str, sha: str) -> PullRequest:
    return PullRequest(number, branch, 'open', '', f'u/{number}', 'a', branch, 'integrate/main', head_sha=sha)


def test_a_second_head_of_one_session_is_refused_naming_the_first(repo: Path) -> None:
    first = _head(repo, 'pr/first', ('feat: a', 'session-one'))
    second = _head(repo, 'pr/second', ('feat: b', 'session-one'))
    why = pradmit.refusal(repo, head=second, tip=_TIP, others=[_open(7, 'pr/first', first)])
    assert why is not None
    assert '#7' in why
    assert 'pr/first' in why
    assert 'session-one' in why


def test_a_head_of_another_session_is_admitted(repo: Path) -> None:
    first = _head(repo, 'pr/first', ('feat: a', 'session-one'))
    second = _head(repo, 'pr/second', ('feat: b', 'session-two'), ('feat: c (a human)', ''))
    assert pradmit.refusal(repo, head=second, tip=_TIP, others=[_open(7, 'pr/first', first)]) is None


def test_heads_whose_commits_carry_no_session_are_not_judged(repo: Path) -> None:
    """User ruling 2026-10-21: a commit with no id is not judged; the planted control is the refusal above."""
    first = _head(repo, 'pr/first', ('feat: a', ''))
    second = _head(repo, 'pr/second', ('feat: b', ''))
    assert pradmit.refusal(repo, head=second, tip=_TIP, others=[_open(7, 'pr/first', first)]) is None
    _git(repo, 'checkout', '-q', '-B', 'pr/third', _TIP)
    third = _commit(repo, 'feat: c')
    assert pradmit.push_refusal(repo, lines=[_line('pr/third', third)], policy=Policy()) == (0, '')


def test_the_integrators_back_door_merge_is_not_judged(repo: Path) -> None:
    """The integrator's break-glass merge updates integration, not a new `pr/*`: neither rule judges it."""
    first = _head(repo, 'pr/first', ('feat: a', 'session-one'))
    stacked = _head(repo, 'pr/stacked', ('feat: b', 'session-one'), start='pr/first')
    tip = _git(repo, 'rev-parse', _TIP)
    line = f'refs/heads/integrate/main {stacked} refs/heads/integrate/main {tip}'
    assert pradmit.refusal(repo, head=stacked, tip=_TIP, others=[_open(7, 'pr/first', first)]) is not None
    assert pradmit.push_refusal(repo, lines=[line], policy=Policy()) == (0, '')


def test_a_declared_split_admits_its_session(repo: Path, monkeypatch) -> None:
    first = _head(repo, 'pr/first', ('feat: a', 'session-one'))
    second = _head(repo, 'pr/second', ('feat: b', 'session-one'))
    monkeypatch.setattr(pradmit, 'SPLITS', (('session-one', 'two unrelated fixes, the user asked for two PRs'),))
    assert pradmit.refusal(repo, head=second, tip=_TIP, others=[_open(7, 'pr/first', first)]) is None


def test_a_head_stacked_on_another_open_head_is_refused(repo: Path) -> None:
    first = _head(repo, 'pr/first', ('feat: a', 'session-one'))
    stacked = _head(repo, 'pr/stacked', ('feat: b', 'session-two'), start='pr/first')
    why = pradmit.refusal(repo, head=stacked, tip=_TIP, others=[_open(7, 'pr/first', first)])
    assert why is not None
    assert 'stacked' in why
    assert '#7' in why


def test_the_same_commit_once_in_integration_is_not_a_stack(repo: Path) -> None:
    first = _head(repo, 'pr/first', ('feat: a', 'session-one'))
    _git(repo, 'update-ref', _TIP, first)  # integration took pr/first; its PR is still listed open
    later = _head(repo, 'pr/later', ('feat: b', 'session-two'))
    assert not shares_unmerged(repo, later, first, _TIP)
    assert pradmit.refusal(repo, head=later, tip=_TIP, others=[_open(7, 'pr/first', first)]) is None


def test_a_head_that_moved_past_the_shared_commit_is_still_a_stack(repo: Path) -> None:
    """The other head grew after the cut: the stack is the SHARED commit, not the other head's tip."""
    first = _head(repo, 'pr/first', ('feat: a', 'session-one'))
    stacked = _head(repo, 'pr/stacked', ('feat: b', 'session-two'), start='pr/first')
    grown = _head(repo, 'pr/first', ('feat: a2', 'session-one'), start=first)
    assert shares_unmerged(repo, stacked, grown, _TIP)


def test_the_head_itself_is_never_its_own_other(repo: Path) -> None:
    head = _head(repo, 'pr/first', ('feat: a', 'session-one'))
    assert pradmit.refusal(repo, head=head, tip=_TIP, others=[_open(7, 'pr/first', head)]) is None


def _line(branch: str, sha: str, remote: str = _ZERO) -> str:
    return f'refs/heads/{branch} {sha} refs/heads/{branch} {remote}'


def test_a_new_pr_branch_of_an_open_session_is_refused_at_push(repo: Path) -> None:
    _head(repo, 'pr/first', ('feat: a', 'session-one'))
    _git(repo, 'checkout', '-q', '-B', 'pr/second', _TIP)
    second = _commit(repo, 'feat: b', 'session-one')
    code, text = pradmit.push_refusal(repo, lines=[_line('pr/second', second)], policy=Policy())
    assert code == pradmit.REFUSED
    assert 'pr/first' in text


def test_an_update_or_a_non_pr_branch_is_not_judged_at_push(repo: Path) -> None:
    first = _head(repo, 'pr/first', ('feat: a', 'session-one'))
    _git(repo, 'checkout', '-q', '-B', 'pr/second', _TIP)
    second = _commit(repo, 'feat: b', 'session-one')
    assert pradmit.push_refusal(repo, lines=[_line('pr/second', second, remote=first)], policy=Policy()) == (0, '')
    assert pradmit.push_refusal(repo, lines=[_line('lane/second', second)], policy=Policy()) == (0, '')


def test_a_merged_pr_branch_is_not_an_open_head_at_push(repo: Path) -> None:
    first = _head(repo, 'pr/first', ('feat: a', 'session-one'))
    _git(repo, 'update-ref', _TIP, first)
    _git(repo, 'checkout', '-q', '-B', 'pr/second', _TIP)
    second = _commit(repo, 'feat: b', 'session-one')
    assert pradmit.push_refusal(repo, lines=[_line('pr/second', second)], policy=Policy()) == (0, '')


def test_the_split_set_is_reasoned_and_its_ceiling_only_falls() -> None:
    """ESCAPE-HATCH-CEILING: every split names its reason, and the count is pinned. Lower this pin, never raise it."""
    ceiling = 0
    assert all(session and reason.strip() for session, reason in pradmit.SPLITS)
    assert len(pradmit.SPLITS) == ceiling, 'a freed split lowers the ceiling here in the same commit'


def test_create_refusal_reads_the_forges_open_prs(repo: Path, monkeypatch) -> None:
    first = _head(repo, 'pr/first', ('feat: a', 'session-one'))
    _head(repo, 'pr/second', ('feat: b', 'session-one'))
    listed = [_open(7, 'pr/first', first)]
    monkeypatch.setattr(pradmit, 'pr_list', lambda _client: listed)
    why = pradmit.create_refusal(repo, object(), head='pr/second', base='integrate/main')
    assert why is not None
    assert 'pr/first' in why
    listed[:] = []  # PLANTED CONTROL: with no other open PR the same head is admitted
    assert pradmit.create_refusal(repo, object(), head='pr/second', base='integrate/main') is None


def test_create_refusal_asks_for_a_fetch_when_an_open_head_is_not_here(repo: Path, monkeypatch) -> None:
    _head(repo, 'pr/second', ('feat: b', 'session-one'))
    monkeypatch.setattr(pradmit, 'pr_list', lambda _client: [_open(7, 'pr/first', 'f' * 40)])
    why = pradmit.create_refusal(repo, object(), head='pr/second', base='integrate/main')
    assert why is not None
    assert 'fetch' in why


def _door_commit(root: Path, why: str, email: str, session: str = 'session-one') -> str:
    message = f'feat: salvage\n\n{TRAILER}: {session}\n{pradmit.INTEGRATOR_DOOR}: {why}'
    _git(root, '-c', f'user.email={email}', 'commit', '-q', '--allow-empty', '-m', message)
    return _git(root, 'rev-parse', 'HEAD')


_INTEGRATOR = Policy(integrators=('integrator@lab',))


def test_the_integrator_door_admits_a_declared_integrators_salvage_at_push(repo: Path) -> None:
    first = _head(repo, 'pr/first', ('feat: a', 'session-one'))
    _git(repo, 'checkout', '-q', '-B', 'pr/salvage', first)  # same session AND stacked: exempt from both
    salvage = _door_commit(repo, 'forge cannot split this session', 'integrator@lab')
    assert pradmit.push_refusal(repo, lines=[_line('pr/salvage', salvage)], policy=_INTEGRATOR) == (0, '')


def test_the_integrator_door_stays_shut_to_an_undeclared_author_or_an_empty_reason(repo: Path) -> None:
    _head(repo, 'pr/first', ('feat: a', 'session-one'))
    _git(repo, 'checkout', '-q', '-B', 'pr/salvage', _TIP)
    stranger = _door_commit(repo, 'I say so', 't@t')  # PLANTED CONTROL: a non-integrator is still refused
    assert pradmit.push_refusal(repo, lines=[_line('pr/salvage', stranger)], policy=_INTEGRATOR)[0] == 1
    _git(repo, 'checkout', '-q', '-B', 'pr/salvage', _TIP)
    empty = _door_commit(repo, '', 'integrator@lab')
    assert pradmit.push_refusal(repo, lines=[_line('pr/salvage', empty)], policy=_INTEGRATOR)[0] == 1
    assert pradmit.door(repo, empty, _INTEGRATOR) is None


def test_the_integrator_door_admits_at_create_and_names_who_and_why(repo: Path, monkeypatch) -> None:
    first = _head(repo, 'pr/first', ('feat: a', 'session-one'))
    _git(repo, 'checkout', '-q', '-B', 'pr/salvage', first)
    salvage = _door_commit(repo, 'salvage of a dead lane', 'integrator@lab')
    _git(repo, 'update-ref', 'refs/remotes/origin/pr/salvage', salvage)
    monkeypatch.setattr(pradmit, 'pr_list', lambda _client: [_open(7, 'pr/first', first)])
    args = {'head': 'pr/salvage', 'base': 'integrate/main', 'policy': _INTEGRATOR}
    assert pradmit.create_refusal(repo, object(), **args) is None
    record = pradmit.door(repo, salvage, _INTEGRATOR)
    assert record is not None
    assert 'integrator@lab' in record
    assert 'salvage of a dead lane' in record
    assert pradmit.create_refusal(repo, object(), **(args | {'policy': Policy()})) is not None  # PLANTED CONTROL
