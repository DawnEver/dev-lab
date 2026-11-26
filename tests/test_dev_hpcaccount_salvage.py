"""``hpcaccount salvage`` / ``salvage-fetch``: an account's own git work brought home before the account is cleaned.

User ruling 2026-11-25: an account is cleaned completely, and no door brought its unpushed commits and uncommitted
changes home. Real temporary repos stand in for the account and its fixed lines run in a real POSIX shell with that
home as ``$HOME``. Each salvaged kind has its planted control beside it: a pushed-only checkout carries no bundle
while one commit ahead does; a clean checkout carries no diff while a dirty one does; an ignored file and one over
the carried limit are not carried while a small untracked file is; a dry run writes nothing; a checkout git cannot
read, and a bundle whose origin names no remote of the target repo, are refused by name.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from dev_lab.dev.hpcaccount import inventory, salvage, salvagefetch, salvageread
from dev_lab.dev.hpcaccount.fleet import Target

_SH = shutil.which('sh')
_GIT = shutil.which('git')
_ENV = {
    'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@x', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@x',
    'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
}  # fmt: skip
#: The carried limit these tests use: ``big.bin`` is over it, ``notes.md`` under.
LIMIT = 64


def _git(repo: Path, *args: str) -> str:
    assert _GIT is not None, 'no git on PATH'
    env = {**os.environ, **_ENV}
    done = subprocess.run(
        [_GIT, '-C', str(repo), *args], check=True, capture_output=True, text=True, encoding='utf-8', env=env
    )
    return done.stdout


def _commit(repo: Path, name: str, text: str, message: str) -> str:
    (repo / name).write_text(text, encoding='utf-8', newline='\n')
    _git(repo, 'add', name)
    _git(repo, 'commit', '-q', '-m', message)
    return _git(repo, 'rev-parse', 'HEAD').strip()


def _runner(home: Path):  # noqa: ANN202 -- a Runner
    """The account's Runner: the fixed line in a real POSIX shell with *home* as ``$HOME``."""
    assert _SH is not None, 'no sh on PATH: every runner (Linux, Git for Windows) carries one'
    env = {**os.environ, **_ENV, 'HOME': home.as_posix()}

    def run(command: str, _stdin: str | None = None) -> str:
        done = subprocess.run([_SH, '-c', command], capture_output=True, env=env, check=False)
        assert done.returncode == 0, done.stderr.decode('utf-8', 'replace')
        return done.stdout.decode('utf-8', 'replace')

    return run


@pytest.fixture
def account(tmp_path: Path) -> SimpleNamespace:
    """A home whose ``src`` holds one checkout of each kind, all cloned from one origin."""
    home, origin = tmp_path / 'home', tmp_path / 'origin.git'
    _git(tmp_path, 'init', '--bare', '-q', '-b', 'main', str(origin))
    shas = {}
    for name in ('pushed', 'ahead', 'dirty', 'loose', 'detached'):
        repo = home / 'src' / name
        repo.mkdir(parents=True)
        _git(repo, 'init', '-q', '-b', 'main')
        (repo / '.gitignore').write_text('out/\n', encoding='utf-8', newline='\n')
        _git(repo, 'add', '.gitignore')
        _commit(repo, 'a.txt', f'{name}\n', 'one')
        _git(repo, 'remote', 'add', 'origin', origin.as_posix())
        _git(repo, 'push', '-q', 'origin', f'main:{name}', *(['main:main'] if name == 'pushed' else []))
        _git(repo, 'fetch', '-q', 'origin')
    src = home / 'src'
    shas['ahead'] = _commit(src / 'ahead', 'b.txt', 'b\n', 'not on any remote')
    (src / 'dirty' / 'a.txt').write_text('changed\n', encoding='utf-8', newline='\n')
    (src / 'dirty' / 'staged.txt').write_text('staged\n', encoding='utf-8', newline='\n')
    _git(src / 'dirty', 'add', 'staged.txt')
    (src / 'loose' / 'notes.md').write_text('a note\n', encoding='utf-8', newline='\n')
    (src / 'loose' / 'big.bin').write_bytes(b'0' * (LIMIT + 1))
    (src / 'loose' / 'out').mkdir()
    (src / 'loose' / 'out' / 'result.csv').write_text('ignored\n', encoding='utf-8', newline='\n')
    (src / 'pushed' / 'out').mkdir()
    (src / 'pushed' / 'out' / 'result.csv').write_text('ignored\n', encoding='utf-8', newline='\n')
    _git(src / 'detached', 'checkout', '-q', '--detach')
    shas['detached'] = _commit(src / 'detached', 'c.txt', 'c\n', 'on a detached HEAD only')
    return SimpleNamespace(home=home, origin=origin, shas=shas, out=tmp_path / 'out', tmp=tmp_path)


def _reach(monkeypatch: pytest.MonkeyPatch, home: Path) -> dict[str, object]:
    grant = SimpleNamespace(user='u1')
    monkeypatch.setattr(salvage, 'reached_machine', lambda _users: SimpleNamespace(grants=[grant]))
    monkeypatch.setattr(salvage, 'declared_target', lambda _g, _shell: Target('login1', '/scratch/u1/lab'))
    run = _runner(home)
    return {'connect': lambda _g: run, 'pin': lambda _g, _host: run}


def _salvaged(monkeypatch: pytest.MonkeyPatch, account: SimpleNamespace, said: list[str], *, apply: bool) -> int:
    reach = _reach(monkeypatch, account.home)
    return salvage.salvage('u1', 'src', apply=apply, out=account.out, carried=LIMIT, say=said.append, **reach)


def _manifest(account: SimpleNamespace) -> dict:
    return json.loads((account.out / 'u1' / 'src' / salvage.MANIFEST).read_text(encoding='utf-8'))


def _plan(account: SimpleNamespace) -> salvageread.Plan:
    return salvageread.parse(_runner(account.home)(salvageread.plan_command('src')))


def test_the_salvage_counts_what_the_inventory_counts() -> None:
    """ONE definition of "on no remote" and of "a checkout under a path": the inventory's."""
    for line in (inventory.command('src'), salvageread.plan_command('src'), salvageread.data_command('src/a', 1)):
        assert inventory.UNPUSHED in line
    for line in (inventory.command('src'), salvageread.plan_command('src')):
        assert inventory.FOUND in line


@pytest.mark.parametrize('line', [salvageread.plan_command('src'), salvageread.data_command('src/a b', 1)])
def test_the_lines_only_read(line: str) -> None:
    for verb in ('rm ', 'mv ', 'git push', 'git fetch', 'git gc', 'git checkout', 'git reset', 'git stash ', 'tee '):
        assert verb not in line, verb
    assert '--no-optional-locks diff' in line, 'a diff never refreshes (writes) the index'
    for redirect in ('2>/dev/null', '2>&1', '>/dev/null', '>&3', '>&4', '4>&1', '3>&1', '"$(wc -c < "$f")"'):
        line = line.replace(redirect, '')
    assert '>' not in line.replace('"<\\t', '').replace('">\\t', ''), 'nothing is redirected into a file'


@pytest.mark.parametrize('path', ['', '..', '../etc', '/etc', 'a b', 'x/$(rm -rf ~)', 'a;b'])
def test_a_path_that_is_not_the_home_or_its_names_is_refused(path: str) -> None:
    with pytest.raises(ValueError, match=r'^look: '):
        salvage.salvage_path(path)
    assert salvage.salvage_path('.') == '.'


def test_the_plan_finds_every_checkout_and_a_worktree_deeper_than_the_search(account: SimpleNamespace) -> None:
    ahead = account.home / 'src' / 'ahead'
    _git(ahead, 'worktree', 'add', '-q', '-b', 'wt-branch', str(ahead / '.claude' / 'worktrees' / 'wt'))
    _git(ahead, 'worktree', 'add', '-q', '--detach', str(ahead / '.git' / 'relock' / 'r'), 'HEAD~1')
    assert len(PurePosixPath('ahead/.claude/worktrees/wt/.git').parts) > inventory.DEPTH, 'find alone cannot reach it'
    found = {c.path: c for c in _plan(account).checkouts}
    assert set(found) == {f'src/{n}' for n in ('pushed', 'ahead', 'dirty', 'loose', 'detached')} | {
        'src/ahead/.claude/worktrees/wt'
    }, 'a worktree inside a git directory is a tool scratch tree, never a checkout'
    assert found['src/ahead/.claude/worktrees/wt'].common == found['src/ahead'].common, 'one shared git directory'


def test_a_pushed_only_checkout_carries_an_empty_bundle_and_says_so(
    monkeypatch: pytest.MonkeyPatch, account: SimpleNamespace
) -> None:
    said: list[str] = []
    assert _salvaged(monkeypatch, account, said, apply=True) == 0, said
    assert not (account.out / 'u1' / 'src' / 'pushed' / salvage.FILES['bundle']).exists()
    assert 'salvage: src/pushed: nothing of its own: nothing written' in said
    assert any(row.startswith('    bundle empty: every commit is on a remote') for row in said)
    assert (account.out / 'u1' / 'src' / 'ahead' / salvage.FILES['bundle']).is_file(), 'the planted control'


def test_an_unpushed_commit_lands_and_fetches_into_a_matched_repo(
    monkeypatch: pytest.MonkeyPatch, account: SimpleNamespace
) -> None:
    assert _salvaged(monkeypatch, account, [], apply=True) == 0
    entry = next(c for c in _manifest(account)['checkouts'] if c['path'] == 'src/ahead')
    assert entry['unpushed'] == '1'
    assert any(account.shas['ahead'] in head for head in entry['files']['commits.bundle']['holds'])
    local = account.tmp / 'local'
    _git(account.tmp, 'clone', '-q', account.origin.as_posix(), str(local))
    head, status = _git(local, 'rev-parse', 'HEAD'), _git(local, 'status', '--porcelain')
    said: list[str] = []
    monkeypatch.chdir(account.out)
    checkout = Path('u1', 'src', 'ahead')  # relative, as typed: git reads the bundle from inside the repo
    assert salvagefetch.fetch(checkout, local, apply=True, say=said.append) == 0, said
    assert _git(local, 'rev-parse', 'salvage/u1/src/ahead/main').strip() == account.shas['ahead']
    assert (_git(local, 'rev-parse', 'HEAD'), _git(local, 'status', '--porcelain')) == (head, status), 'untouched'
    again: list[str] = []
    assert salvagefetch.fetch(checkout, local, apply=True, say=again.append) == 0, again
    skipped = [line for line in again if 'skipped -- refs/heads/salvage/u1/src/ahead/' in line]
    assert len(skipped) == len(again) - 1, 'held work is not landed twice'
    assert again[-1].endswith('already holds all of it'), again


def test_a_dirty_tracked_file_lands_in_the_diff(monkeypatch: pytest.MonkeyPatch, account: SimpleNamespace) -> None:
    assert _salvaged(monkeypatch, account, [], apply=True) == 0
    diff = (account.out / 'u1' / 'src' / 'dirty' / salvage.FILES['diff']).read_text(encoding='utf-8')
    assert '+changed' in diff, 'the unstaged change'
    assert '+staged' in diff, 'the staged new file'
    clone = account.tmp / 'replay'
    _git(account.tmp, 'clone', '-q', '-b', 'dirty', account.origin.as_posix(), str(clone))
    _git(clone, 'apply', '--check', str(account.out / 'u1' / 'src' / 'dirty' / salvage.FILES['diff']))
    assert not (account.out / 'u1' / 'src' / 'ahead' / salvage.FILES['diff']).exists(), 'a clean tree has no diff'


def test_an_untracked_file_lands_and_a_large_or_ignored_one_does_not(
    monkeypatch: pytest.MonkeyPatch, account: SimpleNamespace
) -> None:
    said: list[str] = []
    assert _salvaged(monkeypatch, account, said, apply=True) == 0
    tar = (account.out / 'u1' / 'src' / 'loose' / salvage.FILES['untracked']).read_bytes()
    with tarfile.open(fileobj=io.BytesIO(tar)) as held:
        assert {m.name.removeprefix('./') for m in held.getmembers()} == {'notes.md'}
        assert held.extractfile('./notes.md').read() == b'a note\n'  # type: ignore[union-attr]
    entry = next(c for c in _manifest(account)['checkouts'] if c['path'] == 'src/loose')
    assert entry['untracked_listed'] == [{'path': 'big.bin', 'bytes': LIMIT + 1}], 'listed by name and size'
    assert f'    listed only (over {LIMIT}B): big.bin {LIMIT + 1}B' in said
    assert not (account.out / 'u1' / 'src' / 'pushed' / salvage.FILES['untracked']).exists(), 'ignored stays'


def test_a_detached_head_with_unpushed_commits_lands(monkeypatch: pytest.MonkeyPatch, account: SimpleNamespace) -> None:
    assert _salvaged(monkeypatch, account, [], apply=True) == 0
    entry = next(c for c in _manifest(account)['checkouts'] if c['path'] == 'src/detached')
    assert entry['branch'] == ''
    assert entry['head'] == account.shas['detached']
    assert f'{account.shas["detached"]} HEAD' in entry['files']['commits.bundle']['holds']
    local = account.tmp / 'local'
    _git(account.tmp, 'clone', '-q', account.origin.as_posix(), str(local))
    checkout = account.out / 'u1' / 'src' / 'detached'
    assert salvagefetch.fetch(checkout, local, apply=True, say=[].append) == 0
    assert _git(local, 'rev-parse', 'salvage/u1/src/detached/HEAD').strip() == account.shas['detached']


def test_the_manifest_holds_each_file_sha256(monkeypatch: pytest.MonkeyPatch, account: SimpleNamespace) -> None:
    assert _salvaged(monkeypatch, account, [], apply=True) == 0
    record = _manifest(account)
    assert (record['account'], record['path'], record['carried_max_bytes']) == ('u1', 'src', LIMIT)
    checked = 0
    for entry in record['checkouts']:
        assert entry['origin'] == account.origin.as_posix()
        for name, held in entry.get('files', {}).items():
            data = (account.out / 'u1' / entry['path'] / name).read_bytes()
            assert (len(data), hashlib.sha256(data).hexdigest()) == (held['bytes'], held['sha256'])
            checked += 1
    assert checked >= 4, 'ahead and detached bundles, the dirty diff, the loose tar'


def test_without_apply_nothing_is_written(monkeypatch: pytest.MonkeyPatch, account: SimpleNamespace) -> None:
    said: list[str] = []
    assert _salvaged(monkeypatch, account, said, apply=False) == 0
    assert not account.out.exists()
    assert said[-1].startswith('salvage: dry run -- nothing written')
    assert any(row.startswith('  src/ahead: origin ') for row in said), 'the plan names each checkout'


def test_a_checkout_git_cannot_read_is_refused_by_name_and_the_rest_still_land(
    monkeypatch: pytest.MonkeyPatch, account: SimpleNamespace
) -> None:
    severed = account.home / 'src' / 'severed'
    severed.mkdir()
    (severed / '.git').write_text('gitdir: /nowhere/.git/worktrees/severed\n', encoding='utf-8', newline='\n')
    said: list[str] = []
    assert _salvaged(monkeypatch, account, said, apply=True) == 2
    refusal = next(line for line in said if line.startswith('  src/severed: REFUSED -- git cannot read it'))
    assert 'look --account u1 inventory src/severed' in refusal, 'the refusal names its door'
    assert {r['path'] for r in _manifest(account)['refused']} == {'src/severed'}
    assert (account.out / 'u1' / 'src' / 'ahead' / salvage.FILES['bundle']).is_file()


def test_an_unmatched_checkout_is_refused_by_name_and_nothing_is_fetched(
    monkeypatch: pytest.MonkeyPatch, account: SimpleNamespace
) -> None:
    assert _salvaged(monkeypatch, account, [], apply=True) == 0
    other = account.tmp / 'other'
    _git(account.tmp, 'clone', '-q', account.origin.as_posix(), str(other))
    _git(other, 'remote', 'set-url', 'origin', 'https://forge.example/team/another-repo.git')
    refs = _git(other, 'for-each-ref')
    said: list[str] = []
    assert salvagefetch.fetch(account.out / 'u1' / 'src' / 'ahead', other, apply=True, say=said.append) == 2
    assert said[0].startswith('salvage-fetch: refused -- src/ahead (origin '), said
    assert "repository 'origin'" in said[0]
    assert 'another-repo' in said[0], 'the refusal names the remotes it compared'
    assert _git(other, 'for-each-ref') == refs


@pytest.mark.parametrize(('url', 'name'), [
    ('https://forge.example/Owner/alpha-lab.git', 'alpha-lab'),
    ('https://mirror.example/Team/Alpha-Lab', 'alpha-lab'),
    ('forge.example:Owner/beta-lab.git', 'beta-lab'),
    ('/srv/repos/beta-lab/', 'beta-lab'),
])  # fmt: skip
def test_the_match_rule_is_the_repository_name(url: str, name: str) -> None:
    assert salvagefetch.repository_name(url) == name


def test_each_bundle_ref_lands_on_a_salvage_branch_git_accepts(tmp_path: Path) -> None:
    landed = {
        ('src/a', 'refs/heads/feat/x'): 'salvage/u1/src/a/feat/x',
        ('src/a', 'refs/r2/solid'): 'salvage/u1/src/a/r2/solid',
        ('src/a', 'worktrees/wt/HEAD'): 'salvage/u1/src/a/worktrees/wt/HEAD',
        ('src/a/.claude/worktrees/w', 'HEAD'): 'salvage/u1/src/a/claude/worktrees/w/HEAD',
    }
    for (checkout, ref), branch in landed.items():
        assert salvagefetch.branch_of('u1', checkout, ref) == branch
        _git(tmp_path, 'check-ref-format', '--branch', branch)
    with pytest.raises(subprocess.CalledProcessError):
        _git(tmp_path, 'check-ref-format', '--branch', 'salvage/u1/src/a/.claude/HEAD')  # the planted control
