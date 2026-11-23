"""MSYS-PATH-REWRITE: a remote command whose POSIX paths Git Bash rewrote is refused BEFORE anything is sent.

Measured 2026-11-23: from Git Bash on Windows, ``sshhold run ops@<host> sudo -n /opt/x/.venv/bin/python -m
dev_lab.ops --config /etc/x/supervise.toml install`` reached the host as ``D:/Program Files/Git/opt/...``; sudo
matched no row and asked for a password. PLANTED CONTROL: the clean argv is sent; the rewritten one is refused,
naming the cause and the doors (``MSYS_NO_PATHCONV=1``, or a plan step: the command as data).
"""

from __future__ import annotations

import pytest

from dev_lab.dev import msyspath, sshhold

_ROOT = 'D:/Program Files/Git'
_CLEAN = ['sudo', '-n', '/opt/x/.venv/bin/python', '-m', 'dev_lab.ops', '--config', '/etc/x/supervise.toml', 'install']
_MANGLED = [word.replace('/opt/', f'{_ROOT}/opt/').replace('/etc/', f'{_ROOT}/etc/') for word in _CLEAN]


def test_a_rewritten_argument_is_named() -> None:
    assert msyspath.rewritten(_MANGLED, root=_ROOT) == [
        f'{_ROOT}/opt/x/.venv/bin/python',
        f'{_ROOT}/etc/x/supervise.toml',
    ]
    assert msyspath.rewritten(_CLEAN, root=_ROOT) == []
    assert msyspath.rewritten([r'D:\Program Files\Git\usr\bin'], root=_ROOT) == [r'D:\Program Files\Git\usr\bin']


def test_no_git_root_or_no_msys_shell_judges_nothing() -> None:
    assert msyspath.rewritten(_MANGLED, root='') == []
    assert msyspath.git_root(env={}, which=lambda _name: 'C:/Program Files/Git/cmd/git.exe', windows=True) == ''
    found = msyspath.git_root(
        env={'MSYSTEM': 'MINGW64'}, which=lambda _n: 'C:/Program Files/Git/cmd/git.exe', windows=True
    )
    assert found == 'C:/Program Files/Git'
    assert msyspath.git_root(env={'MSYSTEM': 'MINGW64'}, which=lambda _n: '/usr/bin/git', windows=False) == ''


@pytest.mark.parametrize(('words', 'sent'), [(_CLEAN, True), (_MANGLED, False)])
def test_sshhold_run_sends_a_clean_command_and_refuses_a_rewritten_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], words: list[str], *, sent: bool
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(msyspath, 'git_root', lambda **_k: _ROOT)
    monkeypatch.setattr(sshhold, 'run_command', lambda _dest, command, _t: calls.append(command) or ('ok\n', 0))
    status = sshhold.main(['run', 'ops@h.example', '--', *words])
    assert (status == 0) is sent
    assert bool(calls) is sent
    if not sent:
        err = capsys.readouterr().err
        assert 'MSYS-PATH-REWRITE' in err
        assert 'MSYS_NO_PATHCONV=1' in err
        assert 'nothing was sent' in err
