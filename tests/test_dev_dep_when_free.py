"""A venv update waits its turn: ``dep --bootstrap --when-free`` queues, the launcher replays, a watch yields."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import venv
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

from _forge_state import StateForge
from lab_commons.census import Process

from dev_lab.dev import _dep_pending, dep, forgewatch, liverun
from dev_lab.dev.jsrun import node_path

LAUNCHER = Path(dep.__file__).with_name('agent_launcher.js')


def _project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'pyproject.toml').write_text(
        '[project]\nname="example"\nversion="0"\n[project.optional-dependencies]\ndev=[]\n', encoding='utf-8'
    )
    return root / '.venv'


def _run(calls: list[tuple[str, ...]]) -> Callable[..., SimpleNamespace]:
    def run(argv, **_kwargs: object) -> SimpleNamespace:
        calls.append(tuple(argv))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    return run


def test_a_held_when_free_bootstrap_is_queued_not_run_and_a_plain_one_still_refuses(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dep, 'current_env_key', lambda: 'stable')
    monkeypatch.setattr(dep, 'executing_from', liverun.executing_from)
    prefix = _project(tmp_path / 'main')
    watcher = Process(1, 0, str(prefix / 'python.exe'), 'python -m dev_lab.dev.forge watch', 3600.0, str(tmp_path))
    calls: list[tuple[str, ...]] = []
    held = {'run': _run(calls), 'cwd': tmp_path, 'census': lambda: [watcher]}
    argv = ['--bootstrap', str(tmp_path / 'main'), '--extra', 'dev']
    assert dep.main(argv, **held) == 1, 'PLANTED CONTROL: without --when-free a held venv refuses'
    assert _dep_pending.pending(prefix) is None
    assert dep.main([*argv, '--when-free'], **held) == 0
    assert not any('sync' in call for call in calls), 'a held venv is never synced'
    assert _dep_pending.pending(prefix) == ('--bootstrap', str(tmp_path / 'main'), '--extra', 'dev')


def test_once_free_the_replayed_request_runs_and_is_answered(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dep, 'current_env_key', lambda: 'stable')
    monkeypatch.setattr(dep, 'executing_from', liverun.executing_from)
    prefix = _project(tmp_path / 'main')
    _dep_pending.request(prefix, ['--bootstrap', str(tmp_path / 'main')])
    calls: list[tuple[str, ...]] = []
    queued = list(_dep_pending.pending(prefix) or ())
    assert dep.main([*queued, '--when-free'], run=_run(calls), cwd=tmp_path, census=list) == 0
    assert any('sync' in call for call in calls)
    assert _dep_pending.pending(prefix) is None


def test_a_watch_sees_a_queued_update_of_its_venv_and_exits_cleanly(tmp_path, monkeypatch) -> None:
    forge, said = StateForge(), []
    forge.call('POST', f'{forge.repo}/statuses/{"c" * 40}', {'context': 'tests/x', 'state': 'pending'})
    monkeypatch.setattr(sys, 'prefix', str(tmp_path))
    never = {'deadline_s': 0, 'every_s': 1, 'say': said.append, 'sleep': lambda _s: None}
    assert forgewatch.watch(forge, ('c' * 40,), **never) == 3, 'PLANTED CONTROL: nothing queued, it watches'
    _dep_pending.request(tmp_path, ['--bootstrap', 'x'])
    said.clear()
    assert forgewatch.watch(forge, ('c' * 40,), **never) == forgewatch.YIELDED
    assert said == [f'venv update pending for {tmp_path}: this watch exits so it can run; re-arm this watch']


def _fake_venv(root: Path) -> tuple[Path, Path]:
    """A real venv whose ``dev_lab.dev.dep`` records its argv and answers the request, as the real one does."""
    venv.EnvBuilder(with_pip=False).create(root / '.venv')
    site = next((root / '.venv').glob('**/site-packages'))
    (site / 'dev_lab' / 'dev').mkdir(parents=True)
    (site / 'dev_lab' / '__init__.py').write_text('', encoding='utf-8')
    (site / 'dev_lab' / 'dev' / '__init__.py').write_text('', encoding='utf-8')
    log = root / 'dep-calls.jsonl'
    (site / 'dev_lab' / 'dev' / 'dep.py').write_text(
        'import json, pathlib, sys\n'
        f'pathlib.Path({str(log)!r}).open("a").write(json.dumps(sys.argv[1:]) + "\\n")\n'
        f'(pathlib.Path(sys.prefix) / {_dep_pending.PENDING!r}).unlink(missing_ok=True)\n',
        encoding='utf-8',
    )
    return root / '.venv', log


def _launch(root: Path, every_ms: int) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, 'CLAUDE_PROJECT_DIR': str(root), 'DEV_LAB_REPLAY_EVERY_MS': str(every_ms)}
    return subprocess.run(
        [str(node_path()), str(LAUNCHER), '-c', 'print("hook ran")'],
        capture_output=True, text=True, encoding='utf-8', env=env, cwd=root, check=False,
    )  # fmt: skip


def test_the_hook_launcher_performs_a_queued_update_before_its_hook(tmp_path) -> None:
    prefix, log = _fake_venv(tmp_path)
    plain = _launch(tmp_path, 0)
    assert (plain.returncode, plain.stdout.strip()) == (0, 'hook ran'), plain.stderr
    assert not log.exists(), 'PLANTED CONTROL: nothing queued, nothing replayed'
    _dep_pending.request(prefix, ['--bootstrap', str(tmp_path)])
    fresh = _launch(tmp_path, 60_000)
    assert fresh.stdout.strip() == 'hook ran', fresh.stderr
    assert not log.exists(), 'a request asked under a minute ago is not replayed on every hook'
    old = time.time() - 120
    os.utime(prefix / _dep_pending.PENDING, (old, old))
    done = _launch(tmp_path, 60_000)
    assert (done.returncode, done.stdout.strip()) == (0, 'hook ran'), done.stderr
    calls = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    assert calls == [['--bootstrap', str(tmp_path), '--when-free']]
    assert not (prefix / _dep_pending.PENDING).exists()
    assert not (prefix / f'{_dep_pending.PENDING}.claim').exists()
