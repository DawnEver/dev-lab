"""rem reads the machine home from ONE neutral variable, written from lab_commons.home into the user settings.

Those settings may be one file synced to every machine (D41): the value is the machine-independent ``~/<relative>``,
never this machine's absolute path.
"""

from __future__ import annotations

import json
import sys
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
    monkeypatch.setattr(sys, 'executable', str(root / 'venv' / 'python'))
    return root


#: The forge door rem spawns, as written for the ``user`` fixture.
DOOR = json.dumps(['~/venv/python', '-m', 'dev_lab.dev.forge'])


def test_install_writes_the_tilde_form_and_keeps_the_rest(tmp_path: Path, user: Path) -> None:
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'env': {'OTHER': '1'}, 'model': 'x'}), encoding='utf-8')
    assert remhome.VARIABLE in (remhome.stale(path) or ''), 'planted control: unset is stale, naming the variable'
    assert remhome.wire(path)
    written = json.loads(path.read_text(encoding='utf-8'))
    assert written == {
        'env': {'OTHER': '1', remhome.VARIABLE: '~/.machine-home', remhome.FORGE_VARIABLE: DOOR},
        'model': 'x',
    }
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


def test_a_current_home_without_the_forge_door_is_stale_and_gains_it(tmp_path: Path, user: Path) -> None:
    """PLANTED CONTROL: the home alone is not enough -- rem also needs the forge door."""
    del user
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'env': {remhome.VARIABLE: '~/.machine-home'}}), encoding='utf-8')
    assert remhome.FORGE_VARIABLE in (remhome.stale(path) or '')
    assert remhome.wire(path)
    assert json.loads(json.loads(path.read_text(encoding='utf-8'))['env'][remhome.FORGE_VARIABLE]) == [
        '~/venv/python',
        '-m',
        'dev_lab.dev.forge',
    ]
    assert remhome.stale(path) is None


@pytest.mark.parametrize('door', ['not json', json.dumps(['~/other/python', '-m', 'dev_lab.dev.forge']), '[]'])
@pytest.mark.usefixtures('user')
def test_a_wrong_forge_door_is_stale_and_replaced(tmp_path: Path, door: str) -> None:
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'env': {remhome.VARIABLE: '~/.machine-home', remhome.FORGE_VARIABLE: door}}), 'utf-8')
    assert repr(door) in (remhome.stale(path) or '')
    assert remhome.wire(path)
    assert json.loads(path.read_text(encoding='utf-8'))['env'][remhome.FORGE_VARIABLE] == DOOR


@pytest.mark.usefixtures('user')
def test_an_interpreter_outside_the_user_home_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / 'settings.json'
    path.write_text('{}', encoding='utf-8')
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'elsewhere' / 'python'))
    with pytest.raises(ValueError, match=r'(?s)interpreter.*REM_FORGE'):
        remhome.wire(path)
    assert path.read_text(encoding='utf-8') == '{}', 'nothing written'
