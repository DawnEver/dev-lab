"""The public CLI, same file and real Git bytes; batching changes no admission decision."""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Never

import pytest

from dev_lab.dev import czbatch


@pytest.mark.parametrize(
    'message',
    [
        'feat: ordinary\n',
        'fix: unicode λ "quotes"\n\n' + ('λ "literal" $text\n' * 3000),
        "Merge branch 'topic'\n",
        'Revert "feat: old"\n\nThis reverts commit abc.\n',
        'not conventional\n',
        'fix: comments\n\n# ignored comment\n',
    ],
)
def test_same_file_public_entrypoint_matches_real_cli(tmp_path: Path, monkeypatch, message: str) -> None:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / 'message'
    path.write_bytes(message.encode('utf-8'))
    expected = subprocess.run(
        [sys.executable, '-m', 'commitizen', 'check', '--commit-msg-file', str(path)],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=60,
    )
    original_argv, original_hook = sys.argv, sys.excepthook
    for _ in range(2):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = czbatch.check_file(path)
        assert code == expected.returncode
        assert out.getvalue() == expected.stdout
        assert err.getvalue() == expected.stderr
        assert sys.argv is original_argv
        assert sys.excepthook is original_hook


def test_invalid_then_valid_restores_cli_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / 'message'
    path.write_bytes(b'not conventional\n')
    assert czbatch.check_file(path) != 0
    path.write_bytes(b'fix: next message\n')
    assert czbatch.check_file(path) == 0


def test_unexpected_failure_restores_cli_state(tmp_path: Path, monkeypatch) -> None:
    def broken() -> Never:
        sys.excepthook = object()
        msg = 'planted unexpected failure'
        raise RuntimeError(msg)

    original_argv, original_hook = sys.argv, sys.excepthook
    monkeypatch.setattr(czbatch, 'commitizen_main', broken)
    with pytest.raises(RuntimeError, match='planted unexpected failure'):
        czbatch.check_file(tmp_path / 'message')
    assert sys.argv is original_argv
    assert sys.excepthook is original_hook


def test_missing_git_refuses_explicitly(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(czbatch.shutil, 'which', lambda _name: None)
    with pytest.raises(FileNotFoundError, match='missing TOOL git'):
        czbatch.check_messages(tmp_path / 'message', [], set())


def test_real_git_raw_bytes_order_exact_exemption_and_failure_survive_batch(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    git = shutil.which('git')
    assert git is not None

    def run(*args: str) -> bytes:
        return subprocess.run(
            [git, '-c', 'user.name=test', '-c', 'user.email=test@example.invalid', *args],
            capture_output=True,
            check=True,
            timeout=60,
            env={**os.environ, 'GIT_CONFIG_NOSYSTEM': '1'},
        ).stdout

    run('init', '-b', 'main')
    messages = [
        'data(history): exempt exactly this SHA',
        'data(ordinary): still refuse',
        'fix: unicode λ "quotes"\n\n' + ('λ "literal" $text\n' * 3000),
        'fix: still checked after refusal',
    ]
    source = tmp_path / 'original-message'
    shas = []
    for message in messages:
        source.write_bytes(message.encode('utf-8'))
        run('commit', '--allow-empty', '-F', str(source))
        shas.append(run('rev-parse', 'HEAD').decode().strip())
    selected = run('rev-list', '--reverse', 'HEAD').decode().splitlines()
    assert selected == shas
    path = tmp_path / 'private-message'
    observed = []
    real_check = czbatch.check_file

    def inspect(current: Path) -> int:
        raw = current.read_bytes()
        code = real_check(current)
        observed.append((current, hashlib.sha256(raw).hexdigest(), len(raw), code))
        return code

    monkeypatch.setattr(czbatch, 'check_file', inspect)
    monkeypatch.setattr(sys, 'stdin', io.StringIO(shas[0] + '\n' + '\n'.join(selected) + '\n'))
    assert czbatch.main([str(path)]) == 1
    assert len(observed) == 3
    for row, sha in zip(observed, shas[1:], strict=True):
        raw = run('log', '-1', '--format=%B', sha)
        assert row[:3] == (path, hashlib.sha256(raw).hexdigest(), len(raw))
    assert [row[3] == 0 for row in observed] == [False, True, True]
    assert observed[1][2] > 32767
    assert capsys.readouterr().out.count(f'exempt {shas[0]} (LAB_CZ_EXEMPT)') == 1
