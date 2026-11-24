"""TYPED-VALUES-ARE-SHOWN, the family half: no tracked code in any family repo reads a typed value hidden."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import ask
from dev_lab.dev.famtests import alwayson, hiddenintake

_GIT = shutil.which('git') or 'git'

#: Every hidden-intake form, PLANTED by language. Spelled in pieces so this file is not itself a hit.
_GP = 'getpass' + '.getpass'
_PLANTED: dict[str, str] = {
    'a.py': f'import getpass\nsecret = {_GP}("token: ")\n',
    'b.py': 'import msvcrt\nch = msvcrt.' + 'getwch()\n',
    'c.sh': 'read ' + '-rs TOKEN\n',
    'd.sh': 'stty ' + '-echo\n',
    'e.ps1': '$t = Read-Host "token" -' + 'AsSecureString\n',
    'f.ps1': '$k = [Console]::' + 'ReadKey(' + '$true)\n',
    'g.js': "readlineSync.question('token', { " + 'hideEcho' + 'Back: true })\n',
}
#: Near-misses that must stay clean: the harmless getpass call, a plain read, a visible prompt.
_HARMLESS: dict[str, str] = {
    'h.py': 'import getpass\nwho = getpass.getuser()\nvalue = input("token: ")\n',
    'i.sh': 'read -r LINE\nread -p "name: " NAME\n',
    'j.ps1': '$n = Read-Host "name"\n',
}


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    def git(*argv: str) -> None:
        subprocess.run([_GIT, '-C', str(tmp_path), *argv], check=True, capture_output=True)

    git('init', '-q')
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding='utf-8')
    git('add', '.')
    return tmp_path


def test_every_planted_hidden_form_is_named_by_file_and_line(tmp_path: Path) -> None:
    root = _repo(tmp_path, {**_PLANTED, **_HARMLESS})
    hits = hiddenintake.hits(root)
    assert sorted(path for path, _line in hits) == sorted(_PLANTED)
    with pytest.raises(AssertionError, match=ask.RULE_ID) as refused:
        hiddenintake.check(root)
    assert 'a.py:2' in str(refused.value)
    assert 'dev_lab.dev.ask' in str(refused.value)


def test_the_harmless_near_misses_and_the_exempt_trees_are_clean(tmp_path: Path) -> None:
    """PLANTED CONTROL's other side: the visible forms, and hidden forms under attic/ and memory, pass."""
    (tmp_path / 'attic').mkdir()
    (tmp_path / '.claude' / 'memory').mkdir(parents=True)
    root = _repo(tmp_path, {**_HARMLESS, 'attic/old.py': _PLANTED['a.py'], '.claude/memory/x.py': _PLANTED['a.py']})
    assert hiddenintake.hits(root) == ()
    hiddenintake.check(root)


def test_an_empty_corpus_is_refused_rather_than_read_as_clean(tmp_path: Path) -> None:
    subprocess.run([_GIT, '-C', str(tmp_path), 'init', '-q'], check=True, capture_output=True)
    with pytest.raises(AssertionError, match='no file'):
        hiddenintake.check(tmp_path)


def test_the_row_is_always_on_in_every_repo_installing_dev_lab() -> None:
    assert alwayson.rows()[ask.RULE_ID] is hiddenintake.check


def test_this_repo_reads_no_typed_value_hidden() -> None:
    hiddenintake.check(Path(__file__).resolve().parents[1])
