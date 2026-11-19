"""rem reads the machine home from ONE neutral variable, written from lab_commons.home into the user settings.

Those settings may be one file synced to every machine (D41): the value is the machine-independent ``~/<relative>``,
never this machine's absolute path.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest
from lab_commons.home import HOME_ENV

from dev_lab.dev import remhome


@pytest.fixture
def user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A user home at ``tmp_path/user`` whose machine home is ``~/.machine-home``."""
    root = tmp_path / 'user'
    monkeypatch.setattr(Path, 'home', classmethod(lambda _cls: root))
    monkeypatch.setenv(HOME_ENV, str(root / '.machine-home'))
    return root


def test_install_writes_the_tilde_form_and_keeps_the_rest(tmp_path: Path, user: Path) -> None:
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'env': {'OTHER': '1'}, 'model': 'x'}), encoding='utf-8')
    assert remhome.VARIABLE in (remhome.stale(path) or ''), 'planted control: unset is stale, naming the variable'
    assert remhome.wire(path)
    written = json.loads(path.read_text(encoding='utf-8'))
    assert written == {'env': {'OTHER': '1', remhome.VARIABLE: '~/.machine-home'}, 'model': 'x'}
    assert str(user) not in path.read_text(encoding='utf-8'), 'no machine path in a synced file'
    assert remhome.stale(path) is None, 'a ~ value expanding to the machine home is current'
    assert not remhome.wire(path), 'a second install changes nothing'


#: Another machine's absolute homes, assembled so no literal home path sits in the source.
FOREIGN = [
    str(PureWindowsPath('C:/', 'Users', 'other', '.machine-home')),
    str(PurePosixPath('/', 'home', 'other', '.machine-home')),
]


@pytest.mark.parametrize('held', FOREIGN)
@pytest.mark.usefixtures('user')
def test_a_foreign_machine_absolute_value_is_stale_and_replaced(tmp_path: Path, held: str) -> None:
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'env': {remhome.VARIABLE: held}}), encoding='utf-8')
    assert repr(held) in (remhome.stale(path) or '')
    assert remhome.wire(path)
    assert json.loads(path.read_text(encoding='utf-8'))['env'][remhome.VARIABLE] == '~/.machine-home'


def test_this_machine_absolute_value_is_still_stale(tmp_path: Path, user: Path) -> None:
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'env': {remhome.VARIABLE: str(user / '.machine-home')}}), encoding='utf-8')
    assert remhome.stale(path) is not None, 'an absolute path is machine-specific even when it is right here'


@pytest.mark.usefixtures('user')
def test_a_home_outside_the_user_home_is_refused_never_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / 'settings.json'
    path.write_text('{}', encoding='utf-8')
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'elsewhere'))
    with pytest.raises(ValueError, match=r'(?s)machine-specific.*environment of this machine'):
        remhome.wire(path)
    assert path.read_text(encoding='utf-8') == '{}', 'nothing written'
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path))
    assert remhome.main(['--install']) == 1
    assert path.read_text(encoding='utf-8') == '{}'


@pytest.mark.usefixtures('user')
def test_the_settings_live_under_the_claude_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path / 'cfg'))
    assert remhome.settings_path() == tmp_path / 'cfg' / 'settings.json'
    assert remhome.main([]) == 1, 'absent: reported stale'
    assert remhome.main(['--install']) == 0
    assert remhome.main([]) == 0
