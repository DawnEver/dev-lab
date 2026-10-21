"""The forge relocks integration: a stale lock becomes ONE pull request, a fresh one nothing, an open one waits.

The staleness reading is ``lockcheck.stale`` -- the same one the pre-push ``lock`` row makes -- so these cases
plant that reading (and the door's rewrite of the lock) and run everything else for real: a bare ``origin``, a
clone fetching ``origin/integrate/main``, a worktree, a commit and a push.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from lab_commons.dev import forgeservesteps, relock
from lab_commons.dev.forgealarm import Alarm
from lab_commons.dev.forgework import Client, PullRequest
from lab_commons.dev.lanepolicy import Policy
from lab_commons.dev.relock import PREFIX, Relock, RelockFailed, branch_for, carry, decision, dist_of

_SHA = 'dca72b71758ee4c70fb991fbcb44c56a9e52498d'
_GIT = shutil.which('git') or 'git'
_CHANGE = 'Update pint v0.26.1 -> v0.26.2'


class _Attempt:
    def __init__(self, output: str) -> None:
        self.output = output


class _Report:
    """The shape ``stale`` reads: ok, its last attempt's output, and a remedy."""

    ok = True
    remedy = ''

    def __init__(self, output: str = '') -> None:
        self.attempts = (_Attempt(output),) if output else ()


def _fresh(_tree: Path) -> _Report:
    return _Report()


def _stale(_tree: Path) -> _Report:
    return _Report(f'{_CHANGE}\n')


def _never(_tree: Path) -> _Report:
    msg = 'nothing may resolve while a relock pull request is open'
    raise AssertionError(msg)


def test_a_fresh_lock_needs_no_relock(tmp_path: Path) -> None:
    assert decision(tmp_path, _SHA, resolve=_fresh) is None


def test_a_stale_lock_names_the_dist_its_branch_and_its_pull_request(tmp_path: Path) -> None:
    """PLANTED control: the same checkout with a fresh lock needs nothing (the test above)."""
    found = decision(tmp_path, _SHA, resolve=_stale)
    assert isinstance(found, Relock)
    assert (found.dist, found.branch) == ('pint', f'{PREFIX}-pint-{_SHA[:12]}')
    assert found.title == 'build(deps): relock pint to the newest resolution'
    assert _CHANGE in found.body
    assert found.branch in found.body


def test_the_dist_is_the_word_the_change_names() -> None:
    assert dist_of('uv.lock is not the newest resolution: Update pint v0.26.1 -> v0.26.2') == 'pint'
    assert dist_of('uv.lock is not the newest resolution: Add ruff v0.17.1') == 'ruff'
    assert dist_of('uv.lock is not the newest resolution: something else entirely') == 'lock'


def test_one_branch_per_dist_and_short_sha() -> None:
    assert branch_for('pint', _SHA) == f'pr/relock-pint-{_SHA[:12]}'
    assert branch_for('pint', _SHA) != branch_for('ruff', _SHA)


def _git(root: Path, *argv: str) -> str:
    done = subprocess.run(
        [_GIT, '-C', str(root), *argv], check=False, capture_output=True, text=True, encoding='utf-8', timeout=120
    )  # fmt: skip
    assert done.returncode == 0, f'{argv}: {done.stderr}'
    return done.stdout.strip()


@pytest.fixture
def world(tmp_path: Path) -> tuple[Path, Path, str]:
    """``(clone, origin, integration sha)``: a clone whose ``origin/integrate/main`` commits a lock."""
    origin, seed, clone = tmp_path / 'origin.git', tmp_path / 'seed', tmp_path / 'clone'
    _git(tmp_path, 'init', '-q', '--bare', str(origin))
    _git(tmp_path, 'init', '-q', '-b', 'integrate/main', str(seed))
    (seed / 'pyproject.toml').write_text('[project]\nname = "x"\nversion = "0"\n', encoding='utf-8')
    (seed / 'uv.lock').write_text('version = 1\n', encoding='utf-8')
    _git(seed, 'add', '-A')
    _git(seed, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'seed')
    _git(seed, 'push', '-q', str(origin), 'integrate/main')
    _git(tmp_path, 'clone', '-q', '-b', 'integrate/main', str(origin), str(clone))
    _git(clone, 'config', 'user.name', 't')
    _git(clone, 'config', 'user.email', 't@t')
    return clone, origin, _git(clone, 'rev-parse', 'origin/integrate/main')


def _relocked(tree: Path) -> int:
    (tree / 'uv.lock').write_text('version = 1\n# pint 0.26.2\n', encoding='utf-8')
    return 0


class _Forge:
    """The two forge calls a relock makes: list the open pull requests, open one."""

    def __init__(self, *open_heads: str) -> None:
        self.open = [_pull(n, head) for n, head in enumerate(open_heads, 1)]
        self.created: list[tuple[str, str, str, str]] = []

    def pulls(self) -> list[PullRequest]:
        return self.open

    def create(self, title: str, body: str, *, head: str, base: str) -> PullRequest:
        self.created.append((title, body, head, base))
        return _pull(99, head)


def _pull(number: int, head: str) -> PullRequest:
    return PullRequest(number, 't', 'open', '', f'https://forge/pulls/{number}', 'serve', head, 'integrate/main')


def test_a_stale_integration_lock_is_carried_as_one_pull_request(world: tuple[Path, Path, str]) -> None:
    """PLANTED control: the same integration with a fresh lock pushes and opens nothing."""
    clone, origin, sha = world
    forge = _Forge()
    said = carry(clone, Policy(), pulls=forge.pulls, create=forge.create, resolve=_fresh, upgrade=_relocked)
    assert said == f'the lock of integrate/main at {sha[:12]} is the newest resolution'
    assert (forge.created, _git(origin, 'branch', '--list', f'{PREFIX}-*')) == ([], '')

    said = carry(clone, Policy(), pulls=forge.pulls, create=forge.create, resolve=_stale, upgrade=_relocked)
    branch = branch_for('pint', sha)
    assert said == f'relocked pint onto {branch}: https://forge/pulls/99'
    ((title, body, head, base),) = forge.created
    assert (head, base, title) == (branch, 'integrate/main', 'build(deps): relock pint to the newest resolution')
    assert _CHANGE in body
    assert _git(origin, 'rev-parse', f'{branch}^') == sha, 'the relock is one commit on integration'
    assert _git(origin, 'diff', '--name-only', sha, branch) == 'uv.lock', 'it moves the lock and nothing else'
    assert _git(origin, 'log', '-1', '--format=%s', branch) == title
    assert _git(clone, 'worktree', 'list', '--porcelain').count('worktree ') == 1, 'its worktree is removed'
    assert _git(clone, 'status', '--porcelain') == '', 'the serving checkout is never written'


def test_an_open_relock_pull_request_is_waited_for_and_nothing_resolves(world: tuple[Path, Path, str]) -> None:
    clone, _, _ = world
    forge = _Forge('pr/other', f'{PREFIX}-pint-0123456789ab')
    said = carry(clone, Policy(), pulls=forge.pulls, create=forge.create, resolve=_never, upgrade=_relocked)
    assert said == f'a relock is already open: #2 {PREFIX}-pint-0123456789ab'
    assert forge.created == []


def test_a_door_that_moves_nothing_is_a_named_refusal(world: tuple[Path, Path, str]) -> None:
    """The resolution says stale and the door leaves the lock as it was: refused, never an empty PR."""
    clone, origin, _ = world
    forge = _Forge()
    with pytest.raises(RelockFailed, match=r'left uv\.lock unchanged'):
        carry(clone, Policy(), pulls=forge.pulls, create=forge.create, resolve=_stale, upgrade=lambda _t: 0)
    with pytest.raises(RelockFailed, match='the dependency door exited 1'):
        carry(clone, Policy(), pulls=forge.pulls, create=forge.create, resolve=_stale, upgrade=lambda _t: 1)
    assert (forge.created, _git(origin, 'branch', '--list', f'{PREFIX}-*')) == ([], '')
    assert _git(clone, 'worktree', 'list', '--porcelain').count('worktree ') == 1


def test_no_integration_branch_is_a_named_refusal(tmp_path: Path) -> None:
    _git(tmp_path, 'init', '-q')
    forge = _Forge()
    with pytest.raises(RelockFailed, match='no origin/integrate/main'):
        carry(tmp_path, Policy(), pulls=forge.pulls, create=forge.create, resolve=_never, upgrade=_relocked)


def test_the_serve_step_relocks_only_where_the_forge_merges_and_alarms_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a repo declaring ``pr_merges_since`` lands a relock PR by itself; a failed relock is an alarm."""
    said: list[str] = []
    raised: list[Alarm] = []

    def failing(*_a: object, **_k: object) -> str:
        msg = 'there is no origin/integrate/main here to relock'
        raise RelockFailed(msg)

    monkeypatch.setattr(forgeservesteps, 'carry', failing)
    monkeypatch.setattr(forgeservesteps, 'pr_list', lambda _client: ())
    forgeservesteps.relock(tmp_path, 'r', _CLIENT, say=said.append, alarm=raised.append)
    assert (said, raised) == ([], []), 'CONTROL: no pr_merges_since, no relock'
    manifest = '[project]\nname = "x"\nversion = "0"\n[tool.lab_commons.integrator]\npr_merges_since = "abc"\n'
    (tmp_path / 'pyproject.toml').write_text(manifest, encoding='utf-8')
    forgeservesteps.relock(tmp_path, 'r', _CLIENT, say=said.append, alarm=raised.append)
    (alarm,) = raised
    assert alarm.subject == 'the integrate/main lock could not be relocked'
    assert 'no origin/integrate/main' in alarm.body


_CLIENT = cast('Client', SimpleNamespace(pr_create=lambda *_a, **_k: None))


def test_a_relock_commit_is_the_forges_and_carries_no_session(monkeypatch, tmp_path: Path) -> None:
    """ONE-SESSION-ONE-PR: a forge started inside a session must not stamp that session on its own commits."""
    seen: dict = {}

    def fake(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, '', '')

    monkeypatch.setenv('LAB_SESSION', 'session-from-the-host-shell')
    monkeypatch.setattr(relock._door, 'run', fake)
    relock._git(tmp_path, 'status')
    assert 'LAB_SESSION' not in seen['env']
    assert 'PATH' in {key.upper() for key in seen['env']}
