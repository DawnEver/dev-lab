"""VENV-FOLLOWS-THE-LOCK (user ruling 2026-11-04): a checkout's venv is re-bootstrapped when its lock moved.

A session venv ran an older kit than its own ``uv.lock``: only a served checkout's host tick ever compared the two
(:func:`dev_lab.dev.hostrefresh.sync_venv`). That one hash-and-stamp check now has one home, called by the host tick,
the ``SessionStart`` hook and the ``post-merge``/``post-checkout`` git hooks alike.
"""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING

from lab_commons.census import Process

from dev_lab.dev import venvfollow
from dev_lab.dev.githooks.table import ADVISORY, base_rows, merge

if TYPE_CHECKING:
    from pathlib import Path


def _checkout(tmp_path: Path) -> Path:
    root = tmp_path / 'repo'
    root.mkdir()
    (root / 'pyproject.toml').write_text('[project]\nname = "r"\n', encoding='utf-8')
    (root / 'uv.lock').write_text('rev = "1"\n', encoding='utf-8')
    python = venvfollow.venv_python(root)
    python.parent.mkdir(parents=True)
    python.write_text('', encoding='utf-8')
    return root


class _Boot:
    def __init__(self, code: int = 0) -> None:
        self.code, self.ran = code, []

    def __call__(self, root: Path) -> int:
        self.ran.append(root)
        return self.code


def test_a_moved_lock_rebootstraps_once_and_an_unchanged_one_costs_one_hash(tmp_path: Path, monkeypatch) -> None:
    root, boot = _checkout(tmp_path), _Boot()
    assert venvfollow.follow(root, bootstrap=boot, busy=lambda _r: '') == venvfollow.BOOTSTRAPPED
    hashed: list[Path] = []
    real = venvfollow.env_key
    monkeypatch.setattr(venvfollow, 'env_key', lambda c: hashed.append(c) or real(c))
    assert venvfollow.follow(root, bootstrap=boot, busy=lambda _r: 'never asked') == venvfollow.CURRENT
    assert len(boot.ran) == 1
    assert hashed == [root], 'an unchanged lock costs one hash and asks nothing else'
    (root / 'uv.lock').write_text('rev = "2"\n', encoding='utf-8')
    assert venvfollow.follow(root, bootstrap=boot, busy=lambda _r: '') == venvfollow.BOOTSTRAPPED
    assert len(boot.ran) == 2


def test_a_live_run_skips_the_rebootstrap_and_a_failed_one_is_retried(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same moved lock with no live run is bootstrapped."""
    root = _checkout(tmp_path)
    boot = _Boot()
    said = venvfollow.follow(root, bootstrap=boot, busy=lambda _r: 'pid 7 deck run')
    assert said.startswith(venvfollow.SKIPPED)
    assert 'pid 7' in said
    assert boot.ran == []
    assert venvfollow.follow(root, bootstrap=_Boot(1), busy=lambda _r: '') == venvfollow.FAILED
    assert venvfollow.stale(root) is not None, 'a failed bootstrap writes no stamp, so the next one retries'


def test_the_busy_reading_names_a_run_in_the_tree_or_its_venv(tmp_path: Path) -> None:
    root = _checkout(tmp_path)
    python = str(venvfollow.venv_python(root))
    run = Process(4242, 1, python, f'{python} -m app run', 600.0, str(root))
    assert '4242' in venvfollow.busy(root, census=lambda: (run,))
    assert venvfollow.busy(root, census=lambda: ()) == ''


def test_the_session_start_hook_detaches_only_when_stale(tmp_path: Path, monkeypatch) -> None:
    root, started = _checkout(tmp_path), []
    monkeypatch.setattr(venvfollow, 'detach_argv', lambda r, args: started.append((r, args)))
    monkeypatch.setattr(venvfollow, 'toplevel', lambda cwd: cwd)
    payload = io.StringIO(json.dumps({'hook_event_name': 'SessionStart', 'cwd': str(root)}))
    assert venvfollow.main(['--session-start'], stdin=payload) == 0
    assert len(started) == 1
    assert started[0][1][:2] == ['-m', 'dev_lab.dev.venvfollow']
    venvfollow.stamp(root, venvfollow.env_key(root))
    payload = io.StringIO(json.dumps({'hook_event_name': 'SessionStart', 'cwd': str(root)}))
    assert venvfollow.main(['--session-start'], stdin=payload) == 0
    assert len(started) == 1, 'PLANTED CONTROL: a current venv detaches nothing'


def test_a_merge_and_a_checkout_run_the_follow_as_advisory_git_hooks() -> None:
    table = merge(base_rows(), {})
    for stage in ('post-merge', 'post-checkout'):
        assert stage in ADVISORY
        follow = [hook for hook in table[stage] if hook.id == 'venv-follows-lock']
        assert len(follow) == 1, stage
        assert 'dev_lab.dev.venvfollow' in follow[0].run


def test_the_follow_moves_the_checkout_then_the_venv_then_the_hooks_unprompted(tmp_path: Path, monkeypatch) -> None:
    """User ruling 2026-11-12: a checkout, its venv and its hooks follow integration with no person asked."""
    root, done = _checkout(tmp_path), []
    monkeypatch.setattr(venvfollow.checkoutfollow, 'advance', lambda _r: done.append('checkout') or 'moved')
    monkeypatch.setattr(venvfollow, 'follow', lambda _r: done.append('venv') or venvfollow.CURRENT)
    monkeypatch.setattr(venvfollow.hook_install, 'rewire', lambda _r: done.append('hooks') or '')
    assert venvfollow.main(['--root', str(root)]) == 0
    assert done == ['checkout', 'venv', 'hooks'], 'the checkout moves first: the venv follows the moved lock'


def test_the_background_follow_detaches_for_a_behind_checkout_or_unwired_hooks(tmp_path: Path, monkeypatch) -> None:
    root, started = _checkout(tmp_path), []
    venvfollow.stamp(root, venvfollow.env_key(root))
    monkeypatch.setattr(venvfollow, 'detach_argv', lambda _r, args: started.append(args))
    for behind, unwired in ((True, False), (False, True), (False, False)):
        monkeypatch.setattr(venvfollow.checkoutfollow, 'behind', lambda _r, b=behind: b)
        monkeypatch.setattr(venvfollow.hook_install, 'unwired', lambda _r, u=unwired: u)
        venvfollow.main(['--root', str(root), '--background'])
    assert len(started) == 2, 'PLANTED CONTROL: a current venv, checkout and hooks detach nothing'
