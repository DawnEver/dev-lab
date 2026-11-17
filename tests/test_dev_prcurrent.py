"""PR-HEAD-IS-CURRENT (user ruling 2026-11-07): a pr/* head holds integration's tip and a fresh lock.

Real git (a bare origin and a clone); the network fetch and the lock resolution are planted seams. Every refusal
has its planted control: the same head, made current, passes.
"""

from __future__ import annotations

import inspect
import os
import shutil
import subprocess
import time
from datetime import timedelta
from pathlib import Path

import pytest
from _forge_state import StateForge

from dev_lab.dev.locklag import LAG_WINDOW, within_window
from dev_lab.dev.lockpins import Installed
from dev_lab.dev.prcurrent import (
    RULE,
    SYNC,
    behind,
    fetch_ref,
    head_refusals,
    judge,
    kit_stale,
    lock_stale,
    ready_refusals,
    refusals,
)
from dev_lab.dev.relock import BRANCH as RELOCK_BRANCH

_GIT = shutil.which('git') or 'git'
_DECL = (
    "[tool.dev_lab.branchset]\ntrunk = 'stable'\nsessions = ['int/line']\n\n"
    "[tool.dev_lab.integrator]\nintegration = 'int/line'\ntrunk = 'stable'\n"
)
_LAG = 'uv.lock is not the newest resolution: Update lab-commons v0.3.1 -> v0.3.2'
_ZERO = '0' * 40
#: When integration's landing the head lacks was committed: two days ago, far past the window.
_OLD = int(time.time()) - 2 * 86_400
_SECOND = timedelta(seconds=1)
_HOUR = timedelta(hours=1)


def _git(cwd: Path, *args: str, at: int | None = None) -> str:
    dated = {} if at is None else {'GIT_COMMITTER_DATE': f'{at} +0000', 'GIT_AUTHOR_DATE': f'{at} +0000'}
    done = subprocess.run(
        [_GIT, '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'core.hooksPath=', *args],
        cwd=cwd, capture_output=True, text=True, encoding='utf-8', check=True, timeout=60, env={**os.environ, **dated},
    )  # fmt: skip
    return done.stdout.strip()


def _kit_current(_root: Path, _sha: str) -> str | None:
    return None


def _fresh(_lock: str) -> tuple[str, ...]:
    return ()


def _lagging(_lock: str) -> tuple[str, ...]:
    return (_LAG,)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A clone on ``pr/x`` cut from ``int/line``, after which ``int/line`` moved on origin."""
    origin = tmp_path / 'origin.git'
    _git(tmp_path, 'init', '--bare', '-b', 'stable', str(origin))
    work = tmp_path / 'work'
    _git(tmp_path, 'clone', str(origin), str(work))
    (work / 'pyproject.toml').write_text(_DECL, encoding='utf-8')
    (work / 'uv.lock').write_text('seed lock\n', encoding='utf-8')
    _git(work, 'checkout', '-b', 'int/line')
    _git(work, 'add', '.')
    _git(work, 'commit', '-m', 'chore: seed')
    _git(work, 'branch', 'pr/x')
    _git(work, 'commit', '--allow-empty', '-m', 'chore: integration moves on', at=_OLD)
    _git(work, 'push', 'origin', 'int/line')
    _git(work, 'checkout', 'pr/x')
    _git(work, 'commit', '--allow-empty', '-m', 'feat: x')
    return work


def _line(work: Path, branch: str = 'pr/x', sha: str | None = None) -> str:
    tip = sha or _git(work, 'rev-parse', 'HEAD')
    return f'refs/heads/{branch} {tip} refs/heads/{branch} {_ZERO}\n'


def test_a_head_behind_integration_past_the_window_is_refused_naming_sync_and_once_synced_passes(repo: Path) -> None:
    (why,) = refusals(repo, _line(repo), fetch=fetch_ref, read=_fresh, kit=_kit_current)
    assert RULE in why
    assert 'lacks 1 landings (' in why
    assert f'of origin/int/line, past the window of {LAG_WINDOW.total_seconds() / 3600:.1f} h' in why
    assert SYNC in why
    _git(repo, 'merge', '--no-edit', 'origin/int/line')
    assert refusals(repo, _line(repo), fetch=fetch_ref, read=_fresh, kit=_kit_current) == [], 'CONTROL: synced'


def test_a_head_just_inside_the_time_window_passes_and_just_outside_is_refused(repo: Path) -> None:
    """Integration moves on while the head's tests run: within the window that is current enough.

    The age is the missed landing's committer time to now. PLANTED CONTROL: one second past the window refuses.
    """
    head = _git(repo, 'rev-parse', 'HEAD')
    assert behind(repo, head, 'int/line', now=lambda: _OLD + (LAG_WINDOW - _SECOND).total_seconds()) is None
    assert behind(repo, head, 'int/line', now=lambda: _OLD + (LAG_WINDOW + _SECOND).total_seconds()) is not None


def test_the_window_ages_integrations_first_parent_landing_not_what_it_merged(repo: Path) -> None:
    """A PR merged into integration lands when its merge does, however old the commits it held."""
    _git(repo, 'merge', '--no-edit', 'origin/int/line')  # the head holds the old landing
    _git(repo, 'checkout', '-b', 'pr/other', 'origin/int/line')
    for n in range(3):
        _git(repo, 'commit', '--allow-empty', '-m', f'feat: other {n}', at=_OLD + n)
    _git(repo, 'checkout', '-B', 'int/line', 'origin/int/line')
    landed = _OLD + 86_400
    _git(repo, 'merge', '--no-ff', '--no-edit', 'pr/other', at=landed)
    _git(repo, 'push', 'origin', 'int/line')
    _git(repo, 'checkout', 'pr/x')
    head = _git(repo, 'rev-parse', 'HEAD')
    at = landed + 2 * 3600
    assert behind(repo, head, 'int/line', window=3 * _HOUR, now=lambda: at) is None
    assert behind(repo, head, 'int/line', window=_HOUR, now=lambda: at) is not None, 'CONTROL: the merge is 2 h old'


def test_the_behind_check_reads_origin_afresh_never_a_stale_remote_ref(repo: Path) -> None:
    """The local origin/int/line is rewound to the head's base: only the fetch shows the head is behind."""
    _git(repo, 'update-ref', 'refs/remotes/origin/int/line', 'pr/x~1')
    assert behind(repo, _git(repo, 'rev-parse', 'HEAD'), 'int/line') is not None


def test_a_failed_fetch_refuses_with_the_networks_reason(repo: Path) -> None:
    _git(repo, 'merge', '--no-edit', 'origin/int/line')
    (why,) = refusals(
        repo, _line(repo), fetch=lambda _root, _branch: 'forge unreachable', read=_fresh, kit=_kit_current
    )
    assert 'could not be fetched' in why
    assert 'forge unreachable' in why


def test_a_lock_lagging_a_floated_head_is_refused_naming_sync_and_a_fresh_one_passes(repo: Path) -> None:
    sha = _git(repo, 'rev-parse', 'HEAD')
    why = lock_stale(repo, sha, read=_lagging)
    assert why is not None
    assert _LAG in why
    assert SYNC in why
    assert lock_stale(repo, sha, read=_fresh) is None, 'PLANTED CONTROL'


def test_the_lock_is_read_at_the_pushed_head_never_the_working_tree(repo: Path) -> None:
    """A later commit and an uncommitted edit move the lock; the reading is the pushed head's. PLANTED: no lock."""
    old = _git(repo, 'rev-parse', 'HEAD')
    (repo / 'uv.lock').write_text('newer lock\n', encoding='utf-8')
    _git(repo, 'commit', '-am', 'build: newer lock')
    (repo / 'uv.lock').write_text('dirty lock\n', encoding='utf-8')
    seen: list[str] = []

    def read(lock: str) -> tuple[str, ...]:
        seen.append(lock)
        return ()

    assert lock_stale(repo, old, read=read) is None
    assert seen == ['seed lock\n']
    _git(repo, 'checkout', '--', 'uv.lock')  # git rm refuses a file with uncommitted changes
    _git(repo, 'rm', '-q', 'uv.lock')
    _git(repo, 'commit', '-m', 'build: no lock')
    assert lock_stale(repo, _git(repo, 'rev-parse', 'HEAD'), read=_lagging) is None, 'no lock: nothing floats'


def test_a_machine_branch_and_a_deletion_are_not_judged(repo: Path) -> None:
    """The relock is what makes a lock fresh. PLANTED CONTROL: the same tip pushed as pr/x is refused."""
    machine = _line(repo, RELOCK_BRANCH)
    deletion = f'(delete) {_ZERO} refs/heads/pr/x {_git(repo, "rev-parse", "HEAD")}\n'

    def stale_kit(_root: Path, _sha: str) -> str:
        return 'stale kit'

    assert refusals(repo, machine + deletion, fetch=fetch_ref, read=_lagging, kit=stale_kit) == []
    assert len(refusals(repo, _line(repo), fetch=fetch_ref, read=_lagging, kit=stale_kit)) == 3


def test_ready_judges_the_pushed_head_never_the_local_tree_and_passes_once_current(repo: Path) -> None:
    """User ruling 2026-11-13: ready is a forge call -- a dirty checkout (the 11-12 ``M uv.lock``) has no say."""
    forge = StateForge()
    _git(repo, 'push', 'origin', 'pr/x')
    number = forge.add_pull('pr/x', 'int/line', title='WIP: x', sha=_git(repo, 'rev-parse', 'HEAD'))
    (repo / 'uv.lock').write_text('an unrelated local edit\n', encoding='utf-8')
    (why,) = ready_refusals(repo, forge, forge.pr_view(number), read=_fresh)
    assert 'past the window of' in why, 'a stale head still refuses'
    assert 'uncommitted' not in why
    _git(repo, 'checkout', '--', 'uv.lock')
    _git(repo, 'merge', '--no-edit', 'origin/int/line')
    _git(repo, 'push', 'origin', 'pr/x')
    forge.pulls[number]['head']['sha'] = _git(repo, 'rev-parse', 'HEAD')
    (why,) = ready_refusals(repo, forge, forge.pr_view(number), read=_lagging)
    assert _LAG in why
    assert ready_refusals(repo, forge, forge.pr_view(number), read=_fresh) == [], 'PLANTED CONTROL'
    (repo / 'uv.lock').write_text('an unrelated local edit\n', encoding='utf-8')
    assert ready_refusals(repo, forge, forge.pr_view(number), read=_fresh) == [], 'a dirty checkout readies too'


def test_pr_current_reads_the_lock_lag_window_never_exact_heads() -> None:
    """DECISION 14: one source for current enough -- the default lock reading IS ``lock/lag``'s window."""
    for judged_by in (lock_stale, refusals, ready_refusals):
        assert inspect.signature(judged_by).parameters['read'].default is within_window, judged_by.__name__


def test_pr_current_reads_the_one_lag_window_for_integration_too() -> None:
    """DECISION 14: the integration window is ``lock/lag``'s, read at every door."""
    for judged_by in (behind, judge, head_refusals, refusals, ready_refusals):
        assert inspect.signature(judged_by).parameters['window'].default == LAG_WINDOW, judged_by.__name__


_KIT = 'a' * 40
_LOCK_PINNING_THE_KIT = (
    'version = 1\n\n[[package]]\nname = "dev-lab"\nversion = "0.1.0"\n'
    f'source = {{ git = "https://forge.example/t/dev-lab.git?branch=integrate%2Fmain#{_KIT}" }}\n'
)


def test_a_push_from_a_venv_off_the_pushed_lock_is_refused_naming_the_bootstrap_door(repo: Path) -> None:
    """The stale kit: the hooks judging this push ran a dev-lab the pushed tip's lock does not pin.

    PLANTED CONTROLS: the pinned kit passes; a sibling the lock does not pin by git is not judged.
    """
    (repo / 'uv.lock').write_text(_LOCK_PINNING_THE_KIT, encoding='utf-8')
    _git(repo, 'commit', '-qam', 'build: lock the kit')
    (repo / 'uv.lock').write_text('the working tree is not the pushed tip\n', encoding='utf-8')
    head = _git(repo, 'rev-parse', 'HEAD')
    why = kit_stale(repo, head, installed=lambda: (Installed('dev-lab', 'b' * 40),))
    assert why is not None
    assert RULE in why
    assert f'dev-lab installed {"b" * 12}, uv.lock pins {_KIT[:12]}' in why
    assert '-m dev_lab.dev.dep --bootstrap' in why
    assert kit_stale(repo, head, installed=lambda: (Installed('dev-lab', _KIT),)) is None, 'CONTROL: current kit'
    assert kit_stale(repo, head, installed=lambda: (Installed('elsewhere', 'b' * 40),)) is None, 'not pinned'


def test_the_kit_is_judged_once_per_push_and_never_on_an_unjudged_branch(repo: Path) -> None:
    seen: list[str] = []

    def kit(_root: Path, sha: str) -> str | None:
        seen.append(sha)
        return 'stale kit'

    _git(repo, 'merge', '--no-edit', 'origin/int/line')
    two = _line(repo) + _line(repo, 'pr/y')
    assert refusals(repo, two, fetch=fetch_ref, read=_fresh, kit=kit) == ['stale kit']
    assert len(seen) == 1
    assert refusals(repo, _line(repo, RELOCK_BRANCH), fetch=fetch_ref, read=_fresh, kit=kit) == []
    assert len(seen) == 1, 'CONTROL: a machine branch reads no kit'


def test_an_unreadable_sibling_line_is_named_and_refuses_never_passes(repo: Path, tmp_path: Path) -> None:
    """A sibling ref that cannot be fetched is named, with its fetch -- never silently current."""
    gone = (tmp_path / 'gone' / 'dev-lab.git').as_uri()
    lock = _LOCK_PINNING_THE_KIT.replace('https://forge.example/t/dev-lab.git', gone)
    (repo / 'uv.lock').write_text(lock, encoding='utf-8')
    _git(repo, 'commit', '-qam', 'build: lock the kit')
    why = lock_stale(repo, _git(repo, 'rev-parse', 'HEAD'))
    assert why is not None
    assert 'dev-lab' in why
    assert 'could not be fetched (`git fetch' in why
