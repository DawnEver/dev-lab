"""A verb that sends no alert loads the host config without its alert environment; an alerting verb still refuses.

``consent ready``, ``config apply --subject`` and ``secret place --subject`` are what a planrun preflight runs
unprivileged on each host: they read consent tables, keys and digests and raise no alert, so the ``SUPERVISE_*``
environment a supervisor's unit carries is not theirs to require (:mod:`dev_lab.ops.alertless`).
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from _ops_fixtures import config

from dev_lab.ops.__main__ import main
from dev_lab.ops.config import load


def _host(tmp_path: Path) -> Path:
    """A host declaring an environment file that never arrives: the file absent, no ``SUPERVISE_*`` variable."""
    path = config(tmp_path, []).path
    declared = f'environment_file = "{(tmp_path / "absent.env").as_posix()}"\n'
    path.write_text(path.read_text(encoding='utf-8').replace('[ops]\n', f'[ops]\n{declared}', 1), encoding='utf-8')
    return path


@pytest.fixture(autouse=True)
def _no_supervise_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [name for name in os.environ if name.startswith('SUPERVISE_')]:
        monkeypatch.delenv(name)
    monkeypatch.setattr('dev_lab.ops.config._is_root', lambda: False)


def test_load_without_alerts_skips_only_the_alert_environment(tmp_path: Path) -> None:
    path = _host(tmp_path)
    with pytest.raises(ValueError, match='alerts would be off'):  # planted control: the default still refuses
        load(path, environ={}, as_root=False)
    assert load(path, environ={}, as_root=False, alerts=False).environment_file.endswith('absent.env')


def test_consent_ready_needs_no_alert_environment(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(['--config', str(_host(tmp_path)), 'consent', 'ready']) == 0
    assert '[ops consent] ready' in capsys.readouterr().out


def test_a_subject_verb_needs_no_alert_environment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _host(tmp_path)
    monkeypatch.setattr('sys.stdin', io.TextIOWrapper(io.BytesIO(b'content')))
    main(['--config', str(path), 'secret', 'place', '--path', '/x', '--subject'])
    main(['--config', str(path), 'config', 'apply', '--from', str(path), '--subject'])
    assert 'alerts would be off' not in capsys.readouterr().err


@pytest.mark.parametrize(
    'argv',
    [['promote'], ['consent', 'serve'], ['config', 'apply', '--from', 'x'], ['secret', 'place', '--path', '/x']],
)
def test_an_alerting_verb_in_the_same_state_still_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    assert main(['--config', str(_host(tmp_path)), *argv]) == 2
    assert 'alerts would be off' in capsys.readouterr().err
