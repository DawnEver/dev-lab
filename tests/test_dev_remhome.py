"""rem reads the machine home from ONE neutral variable, written from lab_commons.home into the user settings."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from lab_commons.home import HOME_ENV, home

from dev_lab.dev import remhome

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_install_writes_the_current_home_and_keeps_the_rest(tmp_path: Path) -> None:
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'env': {'OTHER': '1'}, 'model': 'x'}), encoding='utf-8')
    assert remhome.VARIABLE in (remhome.stale(path) or ''), 'planted control: unset is stale, naming the variable'
    assert remhome.wire(path)
    written = json.loads(path.read_text(encoding='utf-8'))
    assert written == {'env': {'OTHER': '1', remhome.VARIABLE: str(home())}, 'model': 'x'}
    assert remhome.stale(path) is None
    assert not remhome.wire(path), 'a second install changes nothing'


def test_a_moved_home_is_stale_until_rewired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / 'settings.json'
    remhome.wire(path)
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'elsewhere'))
    assert 'elsewhere' in (remhome.stale(path) or '')
    assert remhome.wire(path)
    assert remhome.stale(path) is None


def test_the_settings_live_under_the_claude_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path / 'cfg'))
    assert remhome.settings_path() == tmp_path / 'cfg' / 'settings.json'
    assert remhome.main([]) == 1, 'absent: reported stale'
    assert remhome.main(['--install']) == 0
    assert remhome.main([]) == 0
