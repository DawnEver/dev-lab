"""The family's conventional-commit message check (dev_lab.dev.commitmsg), with a planted negative per shape."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import commitmsg
from dev_lab.dev.commitmsg import DEFAULT_PREFIXES, TYPES, refusal


@pytest.mark.parametrize(
    'message',
    [
        'feat: add a thing',
        'fix(euclid): mend the ring',
        'refactor(dev)!: break the surface',
        'feat!: break it',
        'chore(merge): lane into integrate/main\n\nbody line\n\nClaude-Session: x',
        'docs: subject\n',
        *(f'{kind}: subject' for kind in TYPES),
    ],
)
def test_a_conventional_message_passes(message: str) -> None:
    assert refusal(message, DEFAULT_PREFIXES) is None


@pytest.mark.parametrize(
    'message',
    [
        'data(femm): not a type',
        'Feat: capitalised type',
        'feat:no space',
        'feat(): empty scope',
        'feat(a b): spaced scope',
        'feat: ',
        'add a thing',
        'wip: checkpoint',
        'feat: subject\nbody glued to the subject',
    ],
)
def test_planted_an_off_format_message_is_REFUSED(message: str) -> None:
    """PLANTED CONTROL: the checker can say no, and names the expected shape when it does."""
    said = refusal(message, DEFAULT_PREFIXES)
    assert said is not None
    assert 'type(scope)!: subject' in said


@pytest.mark.parametrize(
    'message',
    ['Merge branch x into y', 'Revert "feat: x"', 'Pull request #3', 'fixup! feat: x', 'squash! x', 'amend! x'],
)
def test_the_default_prefixes_pass_whatever_follows(message: str) -> None:
    assert refusal(message, DEFAULT_PREFIXES) is None


def test_a_repo_declared_prefix_EXTENDS_the_defaults(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.dev_lab.commit_msg]\nallowed_prefixes = ["wip", "data("]\n', encoding='utf-8'
    )
    prefixes = commitmsg.declared_prefixes(tmp_path)
    assert refusal('wip checkpoint', prefixes) is None
    assert refusal('data(femm): x', prefixes) is None
    assert refusal('Merge x', prefixes) is None
    assert refusal('datum: x', prefixes) is not None  # PLANTED: `data(` carries its paren


def test_no_pyproject_is_the_defaults(tmp_path: Path) -> None:
    assert commitmsg.declared_prefixes(tmp_path) == DEFAULT_PREFIXES


def _file(tmp_path: Path, text: str) -> str:
    path = tmp_path / 'COMMIT_EDITMSG'
    path.write_text(text, encoding='utf-8')
    return str(path)


def test_a_commit_msg_file_ignores_comments_and_the_scissors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    text = '# a comment\nfeat: x\n# ------------------------ >8 ------------------------\nnot: judged at all\n'
    assert commitmsg.main(['--commit-msg-file', _file(tmp_path, text)]) == 0


@pytest.mark.parametrize('text', ['', '\n\n', '# only a comment\n'])
def test_an_EMPTY_message_is_an_abort_not_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    """Git aborts an empty commit itself; refusing it would only add noise (commitizen's ``--allow-abort``)."""
    monkeypatch.chdir(tmp_path)
    assert commitmsg.main(['--commit-msg-file', _file(tmp_path, text)]) == 0
    assert 'empty' in capsys.readouterr().out


def test_planted_an_off_format_file_fails_with_the_refusal_LAST(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The forge merge decision quotes the last line said, so the refusal is that line."""
    monkeypatch.chdir(tmp_path)
    assert commitmsg.main(['--commit-msg-file', _file(tmp_path, 'data(x): y\n')]) == 1
    said = capsys.readouterr()
    assert (said.out + said.err).strip().splitlines()[-1].startswith('[commit-msg] refused')


def test_message_flag_judges_one_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert commitmsg.main(['--message', 'feat: x']) == 0
    assert commitmsg.main(['--message', 'data(x): y']) == 1


_GIT = shutil.which('git') or 'git'


def _git(root: Path, *args: str) -> str:
    return subprocess.run([_GIT, *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def test_a_rev_range_judges_every_commit_and_names_the_bad_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(tmp_path, 'init', '-q')
    _git(tmp_path, 'config', 'user.email', 't@t')
    _git(tmp_path, 'config', 'user.name', 't')
    _git(tmp_path, 'commit', '-q', '--allow-empty', '-m', 'chore: seed')
    first = _git(tmp_path, 'rev-parse', 'HEAD')
    _git(tmp_path, 'commit', '-q', '--allow-empty', '-m', 'feat: good')
    monkeypatch.chdir(tmp_path)
    assert commitmsg.main(['--rev-range', f'{first}..HEAD']) == 0
    _git(tmp_path, 'commit', '-q', '--allow-empty', '-m', 'data(x): bad')
    bad = _git(tmp_path, 'rev-parse', 'HEAD')
    capsys.readouterr()
    assert commitmsg.main(['--rev-range', f'{first}..HEAD']) == 1
    assert bad[:12] in capsys.readouterr().out
