"""ONE-SESSION-ONE-PR and NO-STACKED-PRS ADVISE, driven on a REAL repository with real ``origin/*`` refs.

PLANTED CONTROLS on each side: a second head of the same session is told the first head's branch, a head of
another session hears nothing; a head holding another open head's unmerged commit is told it is stacked, the
same commit once in integration is not a stack. Nothing here refuses (user ruling 2026-10-25).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import pradmit
from dev_lab.dev.forgework import PullRequest
from dev_lab.dev.labsession import TRAILER
from dev_lab.dev.trialmerge import shares_unmerged

_GIT = shutil.which('git') or 'git'
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


def test_a_second_head_of_one_session_is_told_the_first(repo: Path) -> None:
    first = _head(repo, 'pr/first', ('feat: a', 'session-one'))
    second = _head(repo, 'pr/second', ('feat: b', 'session-one'))
    (said,) = pradmit.advice(repo, head=second, tip=_TIP, others=[_open(7, 'pr/first', first)])
    assert '#7' in said
    assert 'pr/first' in said
    assert 'session-one' in said


def test_a_head_of_another_session_hears_nothing(repo: Path) -> None:
    first = _head(repo, 'pr/first', ('feat: a', 'session-one'))
    second = _head(repo, 'pr/second', ('feat: b', 'session-two'), ('feat: c (a human)', ''))
    assert pradmit.advice(repo, head=second, tip=_TIP, others=[_open(7, 'pr/first', first)]) == ()


def test_heads_whose_commits_carry_no_session_are_not_judged(repo: Path) -> None:
    """User ruling 2026-10-21: a commit with no id is not judged; the planted control is the advice above."""
    first = _head(repo, 'pr/first', ('feat: a', ''))
    second = _head(repo, 'pr/second', ('feat: b', ''))
    assert pradmit.advice(repo, head=second, tip=_TIP, others=[_open(7, 'pr/first', first)]) == ()


def test_a_head_stacked_on_another_open_head_is_told_so(repo: Path) -> None:
    first = _head(repo, 'pr/first', ('feat: a', 'session-one'))
    stacked = _head(repo, 'pr/stacked', ('feat: b', 'session-two'), start='pr/first')
    grown = _head(repo, 'pr/first', ('feat: a2', 'session-one'), start=first)  # it moved on after the cut
    (said,) = pradmit.advice(repo, head=stacked, tip=_TIP, others=[_open(7, 'pr/first', grown)])
    assert 'stacked' in said
    assert '#7' in said


def test_the_same_commit_once_in_integration_is_not_a_stack(repo: Path) -> None:
    first = _head(repo, 'pr/first', ('feat: a', 'session-one'))
    _git(repo, 'update-ref', _TIP, first)  # integration took pr/first; its PR is still listed open
    later = _head(repo, 'pr/later', ('feat: b', 'session-two'))
    assert not shares_unmerged(repo, later, first, _TIP)
    assert pradmit.advice(repo, head=later, tip=_TIP, others=[_open(7, 'pr/first', first)]) == ()


def test_a_head_that_moved_past_the_shared_commit_is_still_a_stack(repo: Path) -> None:
    """The other head grew after the cut: the stack is the SHARED commit, not the other head's tip."""
    first = _head(repo, 'pr/first', ('feat: a', 'session-one'))
    stacked = _head(repo, 'pr/stacked', ('feat: b', 'session-two'), start='pr/first')
    grown = _head(repo, 'pr/first', ('feat: a2', 'session-one'), start=first)
    assert shares_unmerged(repo, stacked, grown, _TIP)


def test_the_head_itself_is_never_its_own_other(repo: Path) -> None:
    head = _head(repo, 'pr/first', ('feat: a', 'session-one'))
    assert pradmit.advice(repo, head=head, tip=_TIP, others=[_open(7, 'pr/first', head)]) == ()


def test_create_advice_reads_the_forges_open_prs(repo: Path, monkeypatch) -> None:
    first = _head(repo, 'pr/first', ('feat: a', 'session-one'))
    _head(repo, 'pr/second', ('feat: b', 'session-one'))
    listed = [_open(7, 'pr/first', first)]
    monkeypatch.setattr(pradmit, 'pr_list', lambda _client: listed)
    (said,) = pradmit.create_advice(repo, object(), head='pr/second', base='integrate/main')
    assert 'pr/first' in said
    listed[:] = []  # PLANTED CONTROL: with no other open PR the same head hears nothing
    assert pradmit.create_advice(repo, object(), head='pr/second', base='integrate/main') == ()


def test_an_open_head_not_fetched_is_named_unjudged_and_never_refuses(repo: Path, monkeypatch) -> None:
    _head(repo, 'pr/second', ('feat: b', 'session-one'))
    monkeypatch.setattr(pradmit, 'pr_list', lambda _client: [_open(7, 'pr/first', 'f' * 40)])
    (said,) = pradmit.create_advice(repo, object(), head='pr/second', base='integrate/main')
    assert 'fetch' in said
    assert '#7' in said


def test_a_head_carrying_another_open_head_whole_is_told_it_lands_it(repo: Path) -> None:
    """A milestone that merges an open PR whole carries it; PLANTED CONTROL: a partial share is a stack."""
    first = _head(repo, 'pr/first', ('feat: a', 'session-one'))
    carrier = _head(repo, 'pr/milestone', ('merge: first', 'session-two'), start='pr/first')
    (said,) = pradmit.advice(repo, head=carrier, tip=_TIP, others=[_open(7, 'pr/first', first)])
    assert 'carries open PR #7' in said
    grown = _head(repo, 'pr/first', ('feat: a2', 'session-one'), start=first)
    (said,) = pradmit.advice(repo, head=carrier, tip=_TIP, others=[_open(7, 'pr/first', grown)])
    assert 'stacked' in said
