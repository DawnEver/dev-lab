"""A forced command's ANSWER is its stdout alone; its notices on stderr never ride into the answer.

Measured 2026-11-11 on a forge host: the consent issuer's config load printed an upgrade-on-read notice on stderr,
:func:`dev_lab.dev.remote.piped` returned stdout + stderr, the client parsed the JSON plus the notice
(``json.JSONDecodeError: Extra data``) and a spent code's thirteen credentials were lost.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable

import pytest

from dev_lab.dev import remote

ANSWER = '[{"action": "ops.config"}]'
NOTICE = '[ops] upgraded [ops.forge] read_only on read: [server-reader] -> accounts role read'


def _ran(code: int, out: str, err: str) -> Callable[..., subprocess.CompletedProcess[str]]:
    def run(argv: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, code, out, err)

    return run


def test_a_success_answers_its_stdout_alone_whatever_stderr_said(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL: two upgrade-on-read notices on stderr, one JSON answer on stdout -> exactly that answer."""
    monkeypatch.setattr(remote._door, 'run', _ran(0, ANSWER + '\n', f'{NOTICE}\n{NOTICE}\n'))
    status, said = remote.piped('consent@forge', '{}\n', identity=None, timeout_s=5)
    assert (status, said) == (0, ANSWER)
    assert said.splitlines() == [ANSWER]


def test_a_refusal_still_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refused request's reason is on stderr (``refused: ...``); a failure keeps it, or the remedy is lost."""
    monkeypatch.setattr(remote._door, 'run', _ran(2, '', 'refused: the code is wrong\n'))
    status, said = remote.piped('consent@forge', '{}\n', identity=None, timeout_s=5)
    assert status == 2
    assert 'the code is wrong' in said


def test_a_declared_known_hosts_file_is_the_one_ssh_checks_strictly(monkeypatch: pytest.MonkeyPatch) -> None:
    """A root door on a host whose root has no ``~/.ssh`` checks the issuer against the DECLARED file, strictly."""
    seen: list[list[str]] = []

    def run(argv: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, 'ok', '')

    monkeypatch.setattr(remote._door, 'run', run)
    remote.piped('consent@forge', '{}\n', identity=None, known_hosts='/srv/ops/ssh/kh', timeout_s=5)
    remote.piped('consent@forge', '{}\n', identity=None, timeout_s=5)  # the control: ssh's own default
    declared, default = (' '.join(argv) for argv in seen)
    assert '-o UserKnownHostsFile=/srv/ops/ssh/kh -o StrictHostKeyChecking=yes' in declared
    assert 'BatchMode=yes' in declared
    assert 'UserKnownHostsFile' not in default
