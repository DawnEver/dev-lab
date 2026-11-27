"""``hpcaccount salvage``: an account's own git work landed as git objects before the account is cleaned.

User ruling 2026-11-25: an account is cleaned completely, and no door brought its unpushed commits and uncommitted
changes home. User ruling A, 2026-11-27 (#1039): they land as ``salvage/<yyyymmdd>-<name>`` branches of a local
repo, and ``output/`` keeps only a JSON record. Real temporary repos stand in for the account and its fixed lines run
in a real POSIX shell with that home as ``$HOME``. Each salvaged kind has its planted control beside it: a
pushed-only checkout lands no branch while one commit ahead does; a clean checkout lands no worktree commit while a
dirty one does; an ignored file and one over the carried limit are not carried while a small untracked file is; a
dry run writes nothing; a checkout git cannot read, and an origin naming no remote of the target repo, are refused
by name; nothing but one ``.json`` record lands under the output.
"""

from __future__ import annotations

import inspect
import json
import os
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest
from lab_commons.hpc.cluster import Runner

from dev_lab.dev.datedlog import FAMILY_KINDS
from dev_lab.dev.hpcaccount import inventory, salvage, salvageread
from dev_lab.dev.hpcaccount.fleet import Target
from dev_lab.dev.layout import BACKUP_SUFFIXES

_SH = shutil.which('sh')
_GIT = shutil.which('git')
_ENV = {
    'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@x', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@x',
    'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
}  # fmt: skip
#: The carried limit these tests use: ``big.bin`` is over it, ``notes.md`` under.
LIMIT = 64
DAY = '20261127'


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


def _runner(home: Path) -> Runner:
    """The account's Runner: the fixed line in a real POSIX shell with *home* as ``$HOME``."""
    assert _SH is not None, 'no sh on PATH: every runner (Linux, Git for Windows) carries one'
    sh, env = _SH, {**os.environ, **_ENV, 'HOME': home.as_posix()}

    def run(command: str, _stdin: str | None = None) -> str:
        done = subprocess.run([sh, '-c', command], capture_output=True, env=env, check=False)
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
    local = tmp_path / 'local'
    _git(tmp_path, 'clone', '-q', origin.as_posix(), str(local))
    return SimpleNamespace(home=home, origin=origin, shas=shas, out=tmp_path / 'out', tmp=tmp_path, local=local)


def _reach(monkeypatch: pytest.MonkeyPatch, home: Path) -> Runner:
    """The one account reached and pinned: every connect and pin answers *home*'s Runner."""
    grant = SimpleNamespace(user='u1')
    monkeypatch.setattr(salvage, 'reached_machine', lambda _users: SimpleNamespace(grants=[grant]))
    monkeypatch.setattr(salvage, 'declared_target', lambda _g, _shell: Target('login1', '/scratch/u1/lab'))
    return _runner(home)


def _salvaged(
    monkeypatch: pytest.MonkeyPatch, account: SimpleNamespace, said: list[str], *, apply: bool, repo: Path | None = None
) -> int:
    run = _reach(monkeypatch, account.home)
    return salvage.salvage(
        'u1', 'src', apply=apply, repo=repo or account.local, reason='account u1 cleaned (test)', out=account.out,
        carried=LIMIT, day=DAY, say=said.append, connect=lambda _g: run, pin=lambda _g, _host: run,
    )  # fmt: skip


def _record(account: SimpleNamespace) -> dict:
    (written,) = account.out.glob('*.json')
    return salvage.read_record(written)


def _entry(account: SimpleNamespace, name: str) -> dict:
    return next(c for c in _record(account)['checkouts'] if c['path'] == f'src/{name}')


def _branch(name: str, ref: str) -> str:
    return salvage.branch_name(DAY, 'u1', f'src/{name}', ref)


def test_a_path_is_one_segment_no_checkout_name_can_spell() -> None:
    assert [salvage.segment(p) for p in ('.', 'src', 'src/ahead/.claude/worktrees/wt')] == [
        '~',
        'src',
        'src+ahead+.claude+worktrees+wt',
    ]
    assert len({salvage.segment(p) for p in ('a/b', 'a.b', 'a_b', 'a-b')}) == 4, 'distinct paths stay distinct'


def test_only_a_json_record_lands_under_the_output(monkeypatch: pytest.MonkeyPatch, account: SimpleNamespace) -> None:
    """OUTPUT-HOLDS-NO-CODE / NO-BACKUP-COPIES: the work is branches; the dated kind holds one record, declared."""
    assert _salvaged(monkeypatch, account, [], apply=True) == 0
    written = [f.relative_to(account.out) for f in account.out.rglob('*') if f.is_file()]
    assert len(written) == 1, written
    assert len(written[0].parts) == 1, 'the record sits in the kind directory itself'
    assert written[0].suffix in FAMILY_KINDS[salvage.KIND]['.'], 'the record is a declared format'
    assert FAMILY_KINDS[salvage.KIND] == {'.': frozenset({'.json'})}, 'the kind admits no sub-tree, no bundle'
    assert not BACKUP_SUFFIXES & {f.suffix for f in account.out.rglob('*')}


def _plan(account: SimpleNamespace) -> salvageread.Plan:
    return salvageread.parse(_runner(account.home)(salvageread.plan_command('src'), None))


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


def test_a_pushed_only_checkout_lands_no_branch_and_says_so(
    monkeypatch: pytest.MonkeyPatch, account: SimpleNamespace
) -> None:
    said: list[str] = []
    assert _salvaged(monkeypatch, account, said, apply=True) == 0, said
    assert _entry(account, 'pushed')['branches'] == []
    assert 'salvage: src/pushed: nothing of its own: nothing landed' in said
    assert any(row.startswith('    bundle empty: every commit is on a remote') for row in said)
    assert _entry(account, 'ahead')['branches'], 'the planted control'


def test_an_unpushed_commit_lands_on_a_derived_branch_and_nothing_else_moves(
    monkeypatch: pytest.MonkeyPatch, account: SimpleNamespace
) -> None:
    local = account.local
    head, status = _git(local, 'rev-parse', 'HEAD'), _git(local, 'status', '--porcelain')
    said: list[str] = []
    assert _salvaged(monkeypatch, account, said, apply=True) == 0, said
    branch = _branch('ahead', 'refs/heads/main')
    assert branch == f'salvage/{DAY}-u1-src+ahead-main'
    assert _git(local, 'rev-parse', branch).strip() == account.shas['ahead']
    held = {'branch': branch, 'sha': account.shas['ahead'], 'from': 'refs/heads/main'}
    assert held in _entry(account, 'ahead')['branches']
    assert (_git(local, 'rev-parse', 'HEAD'), _git(local, 'status', '--porcelain')) == (head, status), 'untouched'
    push = next(line for line in said if line.startswith('salvage: push them: '))
    assert 'dev_lab.dev.netverb -- git -C' in push, 'the caller pushes through the network door'
    assert branch in push
    again: list[str] = []
    assert _salvaged(monkeypatch, account, again, apply=True) == 2, 'an existing worktree branch is never moved'
    skipped = [line for line in again if line.startswith('salvage: src/ahead: ') and ' skipped -- ' in line]
    assert skipped, 'held work is not landed twice'
    assert all('refs/heads/salvage/' in line for line in skipped), skipped
    assert any('src/dirty REFUSED' in line and 'never moved' in line for line in again), again


def test_a_dirty_tracked_change_lands_as_one_commit_on_its_head(
    monkeypatch: pytest.MonkeyPatch, account: SimpleNamespace
) -> None:
    assert _salvaged(monkeypatch, account, [], apply=True) == 0
    branch = _branch('dirty', salvage.WORKTREE)
    local, dirty = account.local, account.home / 'src' / 'dirty'
    assert _git(local, 'rev-parse', f'{branch}^').strip() == _git(dirty, 'rev-parse', 'HEAD').strip()
    assert _git(local, 'show', f'{branch}:a.txt') == 'changed\n', 'the unstaged change'
    assert _git(local, 'show', f'{branch}:staged.txt') == 'staged\n', 'the staged new file'
    assert 'account u1 cleaned (test)' in _git(local, 'log', '-1', '--format=%B', branch), 'the reason rides along'
    assert all(b['from'] != salvage.WORKTREE for b in _entry(account, 'ahead')['branches']), 'a clean tree: none'


def test_an_untracked_file_lands_and_a_large_or_ignored_one_does_not(
    monkeypatch: pytest.MonkeyPatch, account: SimpleNamespace
) -> None:
    said: list[str] = []
    assert _salvaged(monkeypatch, account, said, apply=True) == 0
    branch = _branch('loose', salvage.WORKTREE)
    files = set(_git(account.local, 'ls-tree', '-r', '--name-only', branch).split())
    assert files == {'.gitignore', 'a.txt', 'notes.md'}, 'big.bin is over the limit, out/ is ignored'
    assert _git(account.local, 'show', f'{branch}:notes.md') == 'a note\n'
    assert _entry(account, 'loose')['untracked_listed'] == [{'path': 'big.bin', 'bytes': LIMIT + 1}]
    assert f'    listed only (over {LIMIT}B): big.bin {LIMIT + 1}B' in said
    assert _entry(account, 'pushed')['branches'] == [], 'ignored stays'


def test_a_detached_head_with_unpushed_commits_lands(monkeypatch: pytest.MonkeyPatch, account: SimpleNamespace) -> None:
    assert _salvaged(monkeypatch, account, [], apply=True) == 0
    entry = _entry(account, 'detached')
    assert (entry['branch'], entry['head']) == ('', account.shas['detached'])
    branch = _branch('detached', 'HEAD')
    assert {'branch': branch, 'sha': account.shas['detached'], 'from': 'HEAD'} in entry['branches']
    assert _git(account.local, 'rev-parse', branch).strip() == account.shas['detached']


def test_the_record_round_trips_to_the_branches_it_names(
    monkeypatch: pytest.MonkeyPatch, account: SimpleNamespace
) -> None:
    assert _salvaged(monkeypatch, account, [], apply=True) == 0
    record = _record(account)
    assert (record['account'], record['path'], record['repo']) == ('u1', 'src', str(account.local))
    assert (record['reason'], record['carried_max_bytes']) == ('account u1 cleaned (test)', LIMIT)
    landed = [b for entry in record['checkouts'] for b in entry['branches']]
    assert len(landed) >= 4, 'ahead and detached refs, the dirty and loose worktree commits'
    for entry in record['checkouts']:
        assert entry['origin'] == account.origin.as_posix()
        for held in entry['branches']:
            assert _git(account.local, 'rev-parse', held['branch']).strip() == held['sha'], held
    (written,) = account.out.glob('*.json')
    written.write_text(json.dumps({**record, 'format': 1}), encoding='utf-8')
    with pytest.raises(ValueError, match=r'not a salvage record of format 2 .*--into'):
        salvage.read_record(written)  # the planted control: a pre-#1039 record is refused by name


def test_without_apply_nothing_is_written(monkeypatch: pytest.MonkeyPatch, account: SimpleNamespace) -> None:
    refs = _git(account.local, 'for-each-ref')
    said: list[str] = []
    assert _salvaged(monkeypatch, account, said, apply=False) == 0
    assert not account.out.exists()
    assert _git(account.local, 'for-each-ref') == refs
    assert said[-1].startswith('salvage: dry run -- nothing written')
    assert any(row.startswith('  src/ahead: origin ') for row in said), 'the plan names each checkout'


@pytest.mark.parametrize(('repo', 'reason'), [(None, 'why'), (Path('r'), ''), (Path('r'), '   ')])
def test_apply_without_a_repo_or_a_reason_is_refused(
    monkeypatch: pytest.MonkeyPatch, account: SimpleNamespace, repo: Path | None, reason: str
) -> None:
    run = _reach(monkeypatch, account.home)
    said: list[str] = []
    code = salvage.salvage(
        'u1', 'src', apply=True, repo=repo, reason=reason, out=account.out, carried=LIMIT, day=DAY,
        say=said.append, connect=lambda _g: run, pin=lambda _g, _host: run,
    )  # fmt: skip
    assert code == 2
    assert said[-1].startswith('salvage: refused -- --apply needs --into <repo>'), said
    assert not account.out.exists()


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
    assert {r['path'] for r in _record(account)['refused']} == {'src/severed'}
    assert _entry(account, 'ahead')['branches']


def test_an_unmatched_repo_is_refused_by_name_and_nothing_lands(
    monkeypatch: pytest.MonkeyPatch, account: SimpleNamespace
) -> None:
    other = account.tmp / 'other'
    _git(account.tmp, 'clone', '-q', account.origin.as_posix(), str(other))
    _git(other, 'remote', 'set-url', 'origin', 'https://forge.example/team/another-repo.git')
    refs = _git(other, 'for-each-ref')
    said: list[str] = []
    assert _salvaged(monkeypatch, account, said, apply=True, repo=other) == 2
    refusal = next(line for line in said if line.startswith('salvage: u1: src/ahead REFUSED -- src/ahead (origin '))
    assert "repository 'origin'" in refusal
    assert 'another-repo' in refusal, 'the refusal names the remotes it compared'
    assert _git(other, 'for-each-ref') == refs


@pytest.mark.parametrize(('url', 'name'), [
    ('https://forge.example/Owner/alpha-lab.git', 'alpha-lab'),
    ('https://mirror.example/Team/Alpha-Lab', 'alpha-lab'),
    ('forge.example:Owner/beta-lab.git', 'beta-lab'),
    ('/srv/repos/beta-lab/', 'beta-lab'),
])  # fmt: skip
def test_the_match_rule_is_the_repository_name(url: str, name: str) -> None:
    assert salvage.repository_name(url) == name


def test_the_branch_name_is_derived_never_free_text_and_git_accepts_it(tmp_path: Path) -> None:
    landed = {
        ('.', 'refs/heads/main'): f'salvage/{DAY}-u1-home-main',
        ('src/a', 'refs/heads/feat/x'): f'salvage/{DAY}-u1-src+a-feat+x',
        ('src/a', 'refs/r2/solid'): f'salvage/{DAY}-u1-src+a-r2+solid',
        ('src/a', 'worktrees/wt/HEAD'): f'salvage/{DAY}-u1-src+a-worktrees+wt+HEAD',
        ('src/a/.claude/worktrees/w', 'HEAD'): f'salvage/{DAY}-u1-src+a+claude+worktrees+w-HEAD',
        ('src/a', salvage.WORKTREE): f'salvage/{DAY}-u1-src+a-@worktree',
        ('src/a', 'refs/heads/x~1:^?*[ y'): f'salvage/{DAY}-u1-src+a-x-1------y',
    }
    for (checkout, ref), branch in landed.items():
        assert salvage.branch_name(DAY, 'u1', checkout, ref) == branch
        _git(tmp_path, 'check-ref-format', '--branch', branch)
    with pytest.raises(subprocess.CalledProcessError):
        _git(tmp_path, 'check-ref-format', '--branch', f'salvage/{DAY}-u1-src+a-x~1')  # the planted control
    with pytest.raises(ValueError, match='yyyymmdd'):
        salvage.branch_name('2026-11-27', 'u1', 'src/a', 'HEAD')
    typed = {'branch', 'name', 'branch_name', 'ref'} & set(inspect.signature(salvage.salvage).parameters)
    assert not typed, 'no caller types a branch name'
