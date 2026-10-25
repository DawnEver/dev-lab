"""ONE-SESSION-ONE-PR's identity: the launcher's ``LAB_SESSION`` stamped as ``Lab-Session`` at commit-msg.

PLANTED CONTROLS on each side: a commit with the env is stamped (and so judged), a commit without it -- agent
or human -- passes untouched (and so is not judged), and a trailer the agent wrote itself is replaced by the
launcher's.
"""

from __future__ import annotations

import inspect
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import forgeautosync, labsession, relock
from dev_lab.dev.githooks.table import base_rows

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


@pytest.mark.parametrize(
    'env',
    [{}, {'HARNESS_AGENT': 'codex'}, {'CLAUDECODE': '1'}],
    ids=['human', 'agent-no-launcher', 'vscode-extension'],
)
def test_a_commit_without_the_session_passes_unstamped(tmp_path: Path, env: dict[str, str]) -> None:
    """User ruling 2026-10-21: no id is never refused -- `codc` on a shared app-server must commit."""
    message = _message(tmp_path, 'feat: x\n\nClaude-Session: prose nothing reads\n')
    before = message.read_text(encoding='utf-8')
    assert labsession.main([str(message)], env=env) == 0
    assert message.read_text(encoding='utf-8') == before


def test_a_malformed_session_is_refused_rather_than_stamped(tmp_path: Path) -> None:
    message = _message(tmp_path)
    assert labsession.main([str(message)], env={labsession.ENV: 'a b'}) == 1
    assert labsession.TRAILER not in message.read_text(encoding='utf-8')


def test_machine_env_drops_the_session() -> None:
    env = labsession.machine_env(env={labsession.ENV: _ID, 'PATH': 'p'})
    assert labsession.ENV not in env
    assert env['PATH'] == 'p'


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
    assert rows['lab-session']['run'] == ['python', '-m', 'dev_lab.dev.labsession']


def _bare_env(tmp_path: Path) -> dict[str, str]:
    """An environment with NO git identity anywhere: an HPC account with no gitconfig and a GECOS name."""
    home = tmp_path / 'home'
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('GIT_', 'EMAIL'))}
    env.update(HOME=str(home), USERPROFILE=str(home), XDG_CONFIG_HOME=str(home), GIT_CONFIG_NOSYSTEM='1')
    env.update(GIT_CONFIG_GLOBAL=str(home / 'none'))
    return env


def test_a_forge_commit_is_authored_and_committed_by_the_forge(tmp_path: Path) -> None:
    repo = tmp_path / 'repo'
    bare = _bare_env(tmp_path)
    subprocess.run([_GIT, 'init', '-q', str(repo)], check=True, env=bare)
    subprocess.run([_GIT, '-C', str(repo), 'remote', 'add', 'origin', 'https://git.example.org:3000/o/r.git'],
                   check=True, env=bare)  # fmt: skip
    env = labsession.machine_env(repo, env=bare)
    subprocess.run([_GIT, '-C', str(repo), 'commit', '-q', '--allow-empty', '-m', 'build(deps): relock'],
                   check=True, env=env)  # fmt: skip
    who = subprocess.run([_GIT, '-C', str(repo), 'show', '-s', '--format=%an <%ae>|%cn <%ce>'],
                         capture_output=True, text=True, encoding='utf-8', check=True,
                         env=bare).stdout.strip()  # fmt: skip
    assert who == 'Forge <forge@git.example.org>|Forge <forge@git.example.org>'


def test_a_forge_with_no_readable_remote_signs_as_invalid(tmp_path: Path) -> None:
    env = labsession.machine_env(tmp_path, env={})
    assert (env['GIT_AUTHOR_NAME'], env['GIT_COMMITTER_EMAIL']) == ('Forge', 'forge@invalid')


def test_every_forge_git_call_runs_under_the_machine_env() -> None:
    """No forge module that commits or merges builds its git env any other way (the one source)."""
    for module in (forgeautosync, relock):
        source = inspect.getsource(module._git)
        assert 'env=machine_env(root)' in source, module.__name__
