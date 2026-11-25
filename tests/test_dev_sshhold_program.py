r"""THE HOLD RUNS THE SSH THE USER'S SHELL RUNS: ``ssh`` resolves through PATH, never CreateProcess's own search.

Measured 2026-11-24: ``subprocess.Popen(['ssh', ...])`` on Windows searches System32 BEFORE PATH, so the
holder ran ``C:\Windows\System32\OpenSSH\ssh.exe`` (OpenSSH_for_Windows 9.5) while the user's own terminal --
whose login to Cirrus with key + code succeeds -- ran PATH's first ssh (Git's OpenSSH 10.6). Three codes were
refused ``Permission denied ()`` through the holder. A bare ``ssh`` word is resolved to PATH's absolute program
at the spawn, and a machine with none is refused by name before any code is read.

PLANTED CONTROLS: an already-absolute program and a non-ssh first word are left as they are.
"""

from __future__ import annotations

import pytest

from dev_lab.dev import _sshholder, sshholdwire
from dev_lab.dev.sshholdwire import HoldRefused

GIT_SSH = r'D:\Program Files\Git\usr\bin\ssh.exe'


def test_a_bare_ssh_word_resolves_through_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sshholdwire.shutil, 'which', lambda name: GIT_SSH if name == 'ssh' else None)
    assert sshholdwire.resolved(['ssh', '-J', 'a@b', 'x']) == [GIT_SSH, '-J', 'a@b', 'x']
    assert sshholdwire.resolved([r'C:\other\ssh.exe', 'x']) == [r'C:\other\ssh.exe', 'x']  # control: absolute kept
    assert sshholdwire.resolved(['plink', 'x']) == ['plink', 'x']  # control: not the ssh word


def test_no_ssh_on_path_is_refused_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sshholdwire.shutil, 'which', lambda _name: None)
    with pytest.raises(HoldRefused, match='no ssh on PATH'):
        sshholdwire.resolved(['ssh', 'x'])


def test_the_holder_spawns_the_path_ssh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sshholdwire.shutil, 'which', lambda _name: GIT_SSH)
    assert _sshholder.ssh_argv(['ssh'], 'u@h')[0] == GIT_SSH
