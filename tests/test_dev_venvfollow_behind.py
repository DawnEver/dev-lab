"""The SessionStart notice: a checkout or venv behind the LAST-FETCHED integration says so, in one line, offline."""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING

from lab_commons import launch

from dev_lab.dev import venvfollow
from dev_lab.dev.lockpins import Installed

if TYPE_CHECKING:
    from pathlib import Path

OLD, NEW = 'a' * 40, 'b' * 40


def _lock(pin: str) -> str:
    return f'[[package]]\nname = "dev-lab"\nsource = {{ git = "https://forge.example/o/dev-lab?rev=x#{pin}" }}\n'


def _git(root: Path, *args: str) -> None:
    launch.run(['git', '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@x', *args], check=True,
               capture_output=True)  # fmt: skip


def _pair(tmp_path: Path) -> tuple[Path, Path]:
    """An upstream on ``main`` pinning OLD, and a clone of it: the clone's ``origin/main`` is its last fetch."""
    upstream, clone = tmp_path / 'upstream', tmp_path / 'clone'
    launch.run(['git', 'init', '-q', '-b', 'main', str(upstream)], check=True)
    (upstream / 'uv.lock').write_text(_lock(OLD), encoding='utf-8')
    _git(upstream, 'add', 'uv.lock')
    _git(upstream, 'commit', '-qm', 'pin old')
    launch.run(['git', 'clone', '-q', str(upstream), str(clone)], check=True)
    return upstream, clone


def test_a_current_checkout_and_venv_say_nothing(tmp_path: Path) -> None:
    _, clone = _pair(tmp_path)
    assert venvfollow.behind_notice(clone, installed=(Installed('dev-lab', OLD),)) is None


def test_integration_moved_since_the_last_fetch_names_both_lags_and_the_door(tmp_path: Path) -> None:
    upstream, clone = _pair(tmp_path)
    (upstream / 'uv.lock').write_text(_lock(NEW), encoding='utf-8')
    _git(upstream, 'commit', '-qam', 'pin new')
    assert venvfollow.behind_notice(clone, installed=(Installed('dev-lab', OLD),)) is None  # not fetched: no network
    _git(clone, 'fetch', '-q')
    notice = venvfollow.behind_notice(clone, installed=(Installed('dev-lab', OLD),))
    assert notice is not None
    assert '\n' not in notice
    assert '1 commit(s) behind origin/main' in notice
    assert f'dev-lab {OLD[:10]}' in notice
    assert NEW[:10] in notice
    assert 'dev_lab.dev.dep --bootstrap' in notice


def test_the_session_start_prints_the_notice_and_never_blocks(tmp_path: Path, monkeypatch, capsys) -> None:
    upstream, clone = _pair(tmp_path)
    _git(upstream, 'commit', '-q', '--allow-empty', '-m', 'move')
    _git(clone, 'fetch', '-q')
    monkeypatch.setattr(venvfollow, 'stale', lambda _root: None)
    payload = io.StringIO(json.dumps({'hook_event_name': 'SessionStart', 'cwd': str(clone)}))
    assert venvfollow.main(['--session-start'], stdin=payload) == 0
    assert 'behind origin/main' in capsys.readouterr().out
