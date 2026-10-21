"""ONE-SESSION-ONE-PR's identity: the launcher's ``LAB_SESSION`` stamped as ``Lab-Session`` at commit-msg.

PLANTED CONTROLS on each side: an agent with the env is stamped, an agent without it is refused, a human
without it is untouched, and a trailer the agent wrote itself is replaced by the launcher's.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from lab_commons.dev import labsession
from lab_commons.dev.githooks.table import base_rows

_GIT = shutil.which('git') or 'git'
_ID = '0f3c2a9e-5b1d-4e7a-9c11-2d3e4f5a6b7c'


def _message(tmp_path: Path, text: str = 'feat: x\n') -> Path:
    message = tmp_path / 'COMMIT_EDITMSG'
    message.write_text(text, encoding='utf-8')
    return message


def test_an_agent_commit_carries_the_launchers_session(tmp_path: Path) -> None:
    message = _message(tmp_path, f'feat: x\n\n{labsession.TRAILER}: forged-by-the-agent\n')
    env = {labsession.ENV: _ID, 'HARNESS_AGENT': 'claude'}
    assert labsession.main([str(message)], env=env) == 0
    text = message.read_text(encoding='utf-8')
    assert text.count(f'{labsession.TRAILER}:') == 1
    assert f'{labsession.TRAILER}: {_ID}' in text


@pytest.mark.parametrize('marker', labsession.AGENT_MARKERS)
def test_an_agent_commit_without_the_session_is_refused(tmp_path: Path, marker: str, capsys) -> None:
    message = _message(tmp_path)
    assert labsession.main([str(message)], env={marker: 'codex'}) == 1
    assert labsession.ENV in capsys.readouterr().err
    assert labsession.TRAILER not in message.read_text(encoding='utf-8')


def test_a_human_commit_without_the_session_is_untouched(tmp_path: Path) -> None:
    message = _message(tmp_path, 'feat: x\n\nClaude-Session: prose nothing reads\n')
    before = message.read_text(encoding='utf-8')
    assert labsession.main([str(message)], env={}) == 0
    assert message.read_text(encoding='utf-8') == before


def test_a_malformed_session_is_refused_rather_than_stamped(tmp_path: Path) -> None:
    message = _message(tmp_path)
    assert labsession.main([str(message)], env={labsession.ENV: 'a b'}) == 1
    assert labsession.TRAILER not in message.read_text(encoding='utf-8')


def test_machine_env_drops_the_session_and_the_agent_markers() -> None:
    env = {labsession.ENV: _ID, 'HARNESS_AGENT': 'claude', 'CLAUDECODE': '1', 'PATH': 'p'}
    assert labsession.machine_env(env) == {'PATH': 'p'}


def test_sessions_reads_the_trailers_between_two_commits(tmp_path: Path) -> None:
    root = tmp_path / 'r'
    root.mkdir()

    def git(*args: str) -> str:
        return subprocess.run(
            [_GIT, '-c', 'user.email=t@t', '-c', 'user.name=t', *args],
            cwd=root, check=True, capture_output=True, text=True, encoding='utf-8', timeout=60,
        ).stdout.strip()  # fmt: skip

    git('init', '-q', '-b', 'main')
    git('commit', '-q', '--allow-empty', '-m', 'base')
    base = git('rev-parse', 'HEAD')
    git('commit', '-q', '--allow-empty', '-m', f'feat: a\n\n{labsession.TRAILER}: s-one-aaaa')
    git('commit', '-q', '--allow-empty', '-m', 'feat: b (a human)')
    git('commit', '-q', '--allow-empty', '-m', f'feat: c\n\n{labsession.TRAILER}: s-two-bbbb')
    assert labsession.sessions(root, base, 'HEAD') == frozenset({'s-one-aaaa', 's-two-bbbb'})
    assert labsession.sessions(root, 'HEAD', 'HEAD') == frozenset()


def test_the_base_table_runs_the_stamp_at_commit_msg() -> None:
    rows = {row['id']: row for row in base_rows()['commit-msg']}
    assert rows['lab-session']['run'] == ['python', '-m', 'lab_commons.dev.labsession']
