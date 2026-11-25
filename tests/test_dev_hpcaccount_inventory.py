"""``hpcaccount look --account <user> inventory <path>``: what a directory holds before it is archived or cleaned.

User ruling 2026-11-25: an account is cleaned completely, results of record archived first. A directory may go
without an archive only when every checkout in it is PROVEN pushed -- so the read must be able to say NOT PUSHED:
the planted controls below are a dirty tree, a commit on no remote, a stash, a checkout with no remote and a git
that could not answer.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev.hpcaccount import inventory, look

_SH = shutil.which('sh')
_GIT = shutil.which('git')


def _git(repo: Path, *args: str) -> str:
    env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@x', 'GIT_COMMITTER_NAME': 't',
           'GIT_COMMITTER_EMAIL': 't@x', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}  # fmt: skip
    assert _GIT is not None, 'no git on PATH'
    done = subprocess.run(
        [_GIT, '-C', str(repo), *args], check=True, capture_output=True, text=True, encoding='utf-8', env=env
    )
    return done.stdout


def _read(home: Path, path: str) -> str:
    """Run the inventory's fixed line in a real POSIX shell with *home* as ``$HOME``."""
    assert _SH is not None, 'no sh on PATH: every runner (Linux, Git for Windows) carries one'
    env = {**os.environ, 'HOME': home.as_posix(), 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}
    line = inventory.command(path)
    done = subprocess.run([_SH, '-c', line], capture_output=True, text=True, encoding='utf-8', env=env, check=False)
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """A home whose ``work`` holds a pushed checkout, an unpushed one, a remote-less one and plain data."""
    home = tmp_path / 'home'
    origin = tmp_path / 'origin.git'
    work = home / 'work'
    (work / 'data' / 'deep').mkdir(parents=True)
    (work / 'data' / 'deep' / 'result.csv').write_text('1,2\n', encoding='utf-8')
    (work / '.hidden').write_text('x', encoding='utf-8')
    _git(tmp_path, 'init', '--bare', '-q', str(origin))
    for name in ('pushed', 'ahead', 'local'):
        repo = work / 'src' / name
        repo.mkdir(parents=True)
        _git(repo, 'init', '-q', '-b', 'main')
        (repo / 'a.txt').write_text(name, encoding='utf-8')
        (repo / '.gitignore').write_text('out/\n', encoding='utf-8')
        _git(repo, 'add', '.')
        _git(repo, 'commit', '-q', '-m', 'one')
        if name != 'local':
            _git(repo, 'remote', 'add', 'origin', origin.as_posix())
            _git(repo, 'push', '-q', 'origin', f'main:{name}')
    (work / 'src' / 'pushed' / 'out').mkdir()
    (work / 'src' / 'pushed' / 'out' / 'big.bin').write_bytes(b'0' * 10)
    ahead = work / 'src' / 'ahead'
    (ahead / 'b.txt').write_text('b', encoding='utf-8')
    _git(ahead, 'add', '.')
    _git(ahead, 'commit', '-q', '-m', 'not on any remote')
    (ahead / 'a.txt').write_text('dirty', encoding='utf-8')
    return home


@pytest.mark.parametrize('path', ['', '../etc', '/etc', 'a/../../b', 'a b', 'x/$(rm -rf ~)', 'a;b'])
def test_a_path_that_is_not_home_relative_names_is_refused(path: str) -> None:
    with pytest.raises(ValueError, match=r'^look: '):
        look.command_of('inventory', path, '/root')


def test_inventory_is_a_read_of_look_and_takes_a_path() -> None:
    assert 'inventory' in look.READS
    assert look.command_of('inventory', 'work/src', '/root') == inventory.command('work/src')
    with pytest.raises(ValueError, match='takes exactly one'):
        look.command_of('inventory', '', '/root')


def test_the_line_only_reads() -> None:
    line = inventory.command('work')
    assert '--no-optional-locks' in line, 'git status would refresh (write) the index'
    for verb in ('rm ', 'mv ', 'chmod', 'git push', 'git fetch', 'git gc', 'git checkout', 'git reset', 'tee '):
        assert verb not in line, verb
    redirects = line.replace('2>/dev/null', '').replace('2>&1', '').replace('($1 > m)', '')
    assert '>' not in redirects, 'the only redirections are to /dev/null and stderr into stdout (and one awk compare)'


def test_each_entry_is_counted_with_its_files_bytes_and_newest_change(home: Path) -> None:
    entries = inventory.parse(_read(home, 'work')).entries
    names = {Path(entry.path).name: entry for entry in entries}
    assert set(names) == {'data', 'src', '.hidden'}, 'a dot entry is listed too'
    assert names['data'].files == 3, 'data, deep and result.csv: what a file quota counts'
    assert names['data'].bytes >= len('1,2\n'), 'a directory entry adds its own size, which filesystems differ on'
    assert names['data'].newest >= int((home / 'work' / 'data' / 'deep' / 'result.csv').stat().st_mtime)


def test_a_pushed_checkout_is_proven_and_every_other_kind_is_not(home: Path) -> None:
    checkouts = {Path(c.path).name: c for c in inventory.parse(_read(home, 'work')).checkouts}
    assert set(checkouts) == {'pushed', 'ahead', 'local'}
    assert checkouts['pushed'].reasons() == [], checkouts['pushed']
    assert checkouts['pushed'].ignored == ['out/'], 'what git ignores is listed for a person to judge'
    assert any('1 commit(s) on no remote' in r for r in checkouts['ahead'].reasons())
    assert any('changed' in r for r in checkouts['ahead'].reasons())
    assert 'no remote' in checkouts['local'].reasons()


def test_planted_control_a_stash_and_an_unanswering_git_are_not_pushed() -> None:
    text = 'P\t/h/w\nG\t/h/w/r\nR\torigin\thttps://forge/r.git\nS\t0\nU\tfatal: bad revision HEAD\nT\t1\n'
    (checkout,) = inventory.parse(text).checkouts
    assert 'git could not count unpushed commits: fatal: bad revision HEAD' in checkout.reasons()
    assert '1 stash entr(y/ies)' in checkout.reasons()


def test_rows_name_each_verdict_and_an_absent_path() -> None:
    assert inventory.rows('A\t/h/gone\n') == ['inventory: /h/gone does not exist']
    text = (
        'P\t/h/w\nE\t3\t2048\t1764000000\t/h/w/data\nG\t/h/w/r\nR\torigin\thttps://forge/r.git\nS\t0\n'
        'U\t0\nT\t0\nG\t/h/w/q\nS\t2\ns\t M a.txt\ns\t?? new\nU\t0\nT\t0\n'
    )
    rows = inventory.rows(text)
    assert rows[0].startswith('inventory: /h/w -- 1 entr(y/ies), 3 files')
    assert any(row.endswith('/h/w/data') and '2.0K' in row and '2025-11-24' in row for row in rows)
    assert '  /h/w/r: pushed (origin https://forge/r.git)' in rows
    assert '  /h/w/q: NOT PUSHED -- 2 changed or untracked path(s); no remote' in rows
    assert '     M a.txt' in rows, 'a porcelain line is shown as git printed it'


def test_a_commit_only_a_tag_or_an_own_namespace_holds_is_not_pushed(home: Path) -> None:
    """Measured 2026-11-25: an account's work sat on ``refs/r2/solid`` and a detached HEAD, on no branch."""
    pushed = home / 'work' / 'src' / 'pushed'
    for ref in ('refs/tags/kept', 'refs/r2/solid'):
        sha = _git(pushed, 'commit-tree', 'HEAD^{tree}', '-p', 'HEAD', '-m', f'only {ref} holds this').strip()
        _git(pushed, 'update-ref', ref, sha)
    (checkout,) = (c for c in inventory.parse(_read(home, 'work')).checkouts if Path(c.path).name == 'pushed')
    assert '2 commit(s) on no remote' in checkout.reasons(), checkout
