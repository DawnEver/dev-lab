"""VENV-FOLLOWS-THE-LOCK (user ruling 2026-11-04): a checkout's venv is re-bootstrapped when its lock moved.

A session venv ran an older kit than its own ``uv.lock``: only a served checkout's host tick ever compared the two
(:func:`dev_lab.dev.hostrefresh.sync_venv`). That one hash-and-stamp check now has one home, called by the host tick,
the ``SessionStart`` hook and the ``post-checkout`` git hook alike.
"""

from __future__ import annotations

import io
import json
import os
import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING

from lab_commons.census import Process

from dev_lab.dev import venvfollow, venvpointer
from dev_lab.dev.githooks.table import ADVISORY, base_rows, merge
from dev_lab.dev.venvpath import VENV_LAYOUTS

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


def test_the_busy_reading_names_a_run_in_the_tree_but_not_one_only_using_its_venv(tmp_path: Path) -> None:
    """dev-lab #632: the bootstrap builds beside the venv, so a process executing from it is no obstacle."""
    root = _checkout(tmp_path)
    (root / '.git').mkdir()
    (root / 'app.py').write_text('', encoding='utf-8')  # the run's module is IN the tree: it reads it
    python = str(venvfollow.venv_python(root))
    run = Process(4242, 1, python, f'{python} -m app run', 600.0, str(root))
    assert '4242' in venvfollow.busy(root, census=lambda: (run,))
    elsewhere = Process(4343, 1, python, f'{python} -m app run', 600.0, str(tmp_path / 'elsewhere'))
    assert venvfollow.busy(root, census=lambda: (elsewhere,)) == ''
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


def test_a_checkout_runs_the_follow_as_its_one_advisory_git_hook() -> None:
    """post-checkout is the one event a new worktree fires. PLANTED CONTROL: no other stage carries the row."""
    table = merge(base_rows(), {})
    follow = [(stage, hook) for stage, hooks in table.items() for hook in hooks if hook.id == 'venv-follows-lock']
    assert [stage for stage, _ in follow] == ['post-checkout']
    assert 'post-checkout' in ADVISORY
    assert 'dev_lab.dev.venvfollow' in follow[0][1].run


def test_the_follow_moves_the_checkout_then_the_venv_then_the_hooks_unprompted(tmp_path: Path, monkeypatch) -> None:
    """User ruling 2026-11-12: a checkout, its venv and its hooks follow integration with no person asked."""
    root, done = _checkout(tmp_path), []
    monkeypatch.setattr(venvfollow.checkoutfollow, 'advance', lambda _r: done.append('checkout') or 'moved')
    monkeypatch.setattr(venvfollow, 'follow', lambda _r: done.append('venv') or venvfollow.CURRENT)
    monkeypatch.setattr(venvfollow.hook_install, 'rewire', lambda _r: done.append('hooks') or '')
    assert venvfollow.main(['--root', str(root)]) == 0
    assert done == ['checkout', 'venv', 'hooks'], 'the checkout moves first: the venv follows the moved lock'


def test_a_second_follow_of_one_checkout_waits_for_none_and_runs_nothing(tmp_path: Path, monkeypatch) -> None:
    """One follow per checkout: a second one runs nothing and says why.

    Measured 2026-11-17: four session starts detached four follows of one worktree, whose bootstraps published over
    and reclaimed each other until the venv pointer named a deleted env. PLANTED CONTROL: once the lock is free, the
    follow runs.
    """
    root, done = _checkout(tmp_path), []
    monkeypatch.setattr(venvfollow.checkoutfollow, 'advance', lambda _r: done.append('checkout') or '')
    monkeypatch.setattr(venvfollow, 'follow', lambda _r: done.append('venv') or venvfollow.CURRENT)
    monkeypatch.setattr(venvfollow.hook_install, 'rewire', lambda _r: '')
    lock = venvfollow.follow_lock(root)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(f'{os.getpid()}\n', encoding='utf-8')
    out = io.StringIO()
    monkeypatch.setattr(sys, 'stdout', out)
    assert venvfollow.main(['--root', str(root)]) == 0
    assert done == []
    assert 'another follow of this checkout is running' in out.getvalue()
    lock.unlink()
    assert venvfollow.main(['--root', str(root)]) == 0
    assert done == ['checkout', 'venv']
    assert not lock.exists(), 'the follow lets go of its lock'


def test_the_background_follow_detaches_for_a_behind_checkout_or_unwired_hooks(tmp_path: Path, monkeypatch) -> None:
    root, started = _checkout(tmp_path), []
    venvfollow.stamp(root, venvfollow.env_key(root))
    monkeypatch.setattr(venvfollow, 'detach_argv', lambda _r, args: started.append(args))
    for behind, unwired in ((True, False), (False, True), (False, False)):
        monkeypatch.setattr(venvfollow.checkoutfollow, 'behind', lambda _r, b=behind: b)
        monkeypatch.setattr(venvfollow.hook_install, 'unwired', lambda _r, u=unwired: u)
        venvfollow.main(['--root', str(root), '--background'])
    assert len(started) == 2, 'PLANTED CONTROL: a current venv, checkout and hooks detach nothing'


def _published(tmp_path: Path, other: str) -> tuple[Path, Path, Path]:
    """A checkout whose pointer names ``.venvs/x`` beside an *other* environment directory: (root, other, current)."""
    root = tmp_path / 'main'
    root.mkdir()
    (root / 'pyproject.toml').write_text('[project]\nname = "r"\n', encoding='utf-8')
    pythons = []
    for env in (root / other, root / venvpointer.HOME / 'x'):
        python = env.joinpath(*VENV_LAYOUTS[os.name][1:])
        python.parent.mkdir(parents=True)
        python.write_text('', encoding='utf-8')
        pythons.append(python)
    (root / venvpointer.POINTER).write_text('x\n', encoding='utf-8')
    return root, pythons[0], pythons[1]


def test_the_bootstrap_runs_from_the_current_environment(tmp_path: Path, monkeypatch) -> None:
    root, older, current = _published(tmp_path, f'{venvpointer.HOME}/old')
    ran: list[list[str]] = []
    monkeypatch.setattr(venvfollow._door, 'run', lambda argv, **_: ran.append(argv) or SimpleNamespace(returncode=0))
    monkeypatch.setattr(sys, 'executable', str(older))
    assert venvfollow.follow(root, busy=lambda _r: '') == venvfollow.BOOTSTRAPPED
    assert ran[-1][:4] == [str(current), '-m', 'dev_lab.dev.dep', '--bootstrap']
    (root / venvpointer.POINTER).unlink()
    (root / 'uv.lock').write_text('rev = "2"\n', encoding='utf-8')
    venvfollow.follow(root, busy=lambda _r: '')
    assert ran[-1][0] == str(older), 'PLANTED CONTROL: no pointer names a current one: the launcher stays'


def test_a_retired_venv_makes_the_follow_due_and_goes_once_unheld(tmp_path: Path, monkeypatch) -> None:
    """The migration retries at every follow: held, the retired ``.venv`` stays; unheld, it moves aside."""
    root, legacy, current = _published(tmp_path, venvpointer.RETIRED_ALIAS)
    venvfollow.stamp(root, venvfollow.env_key(root))
    monkeypatch.setattr(venvfollow.checkoutfollow, 'behind', lambda _r: False)
    monkeypatch.setattr(venvfollow.hook_install, 'unwired', lambda _r: False)
    monkeypatch.setattr(venvfollow.checkoutfollow, 'advance', lambda _r: '')
    monkeypatch.setattr(venvfollow.hook_install, 'rewire', lambda _r: '')
    assert venvfollow.due(root), 'a retired .venv is due for its migration'
    holder = Process(4242, 1, str(legacy), f'{legacy} -m app run', 3600.0, str(tmp_path))
    monkeypatch.setattr(venvfollow, 'processes', lambda: [holder])
    venvfollow.main(['--root', str(root)])
    assert legacy.is_file(), 'PLANTED CONTROL: held, the legacy directory stays'
    monkeypatch.setattr(venvfollow, 'processes', list)
    venvfollow.main(['--root', str(root)])
    assert not (root / venvpointer.RETIRED_ALIAS).exists(), 'unheld: .venv is gone'
    assert venvpointer.named(root) == current.parents[1], 'the pointer still names the current env'
    assert not venvfollow.due(root), 'PLANTED CONTROL: migrated, nothing is due'
