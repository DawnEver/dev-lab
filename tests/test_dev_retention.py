"""Storage retention: only what the policy proves unreferenced is deleted, each deletion logged; quota prunes harder."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from _forge_fake import git_out, run_git

from lab_commons.dev import retention
from lab_commons.dev.diskusage import Usage, parse_mmlsquota
from lab_commons.dev.retention import (
    Plan,
    Policy,
    apply,
    carry_sources,
    cluster_plan,
    load_policy,
    serve_pass,
    workstation_plan,
)

NOW = datetime(2026, 10, 13, 12, tzinfo=UTC)
OLD = NOW - timedelta(days=10)
YOUNG = NOW - timedelta(hours=1)


def _touch(path: Path, when: datetime, size: int = 10) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(b'x' * size)
    os.utime(path, (when.timestamp(), when.timestamp()))
    return path


def _dir(path: Path, when: datetime, size: int = 10) -> Path:
    _touch(path / 'f', when, size)
    os.utime(path, (when.timestamp(), when.timestamp()))
    return path


def _run(
    home: Path, sha: str, env: str, when: datetime, *, done: bool = True, repo: str = 'r', native: str = 'n4'
) -> None:
    builds = {'env': env, 'native': native}
    state = {'sha': sha, 'repo': repo, 'env': 'hash', 'builds': builds, **({'record': {}} if done else {})}
    path = home / 'ci' / 'runs' / sha / 'state.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding='utf-8')
    _touch(path, when)
    _dir(home / 'ci' / 'trees' / sha, when)


def _doomed(plan: Plan) -> dict[str, str]:
    return {d.path.name: d.rule for d in plan.doomed}


@pytest.fixture
def home(tmp_path: Path) -> Path:
    # five finished runs of this repo; SOURCES names the three a live tip carries from
    for i, sha in enumerate(['a1', 'a2', 'a3', 'a4', 'a5']):
        _run(tmp_path, sha, 'e1', OLD + timedelta(hours=i))
    _run(tmp_path, 'b1', 'e2', OLD - timedelta(days=5), repo='other', native='n3')  # another repo's to judge
    _run(tmp_path, 'f1', 'e1', OLD - timedelta(days=1), done=False)  # in flight: no record, live file
    _run(tmp_path, 'g1', 'e1', NOW - timedelta(days=30), done=False)  # abandoned: no record, no live file
    _dir(tmp_path / 'ci' / 'trees' / 'orphan', OLD)
    _dir(tmp_path / 'ci' / 'trees' / 'building', YOUNG)
    for key in ('e1', 'e2', 'e3'):
        _dir(tmp_path / 'ci' / 'envs' / key, OLD)
        _touch(tmp_path / 'ci' / 'envs' / f'{key}.log', OLD)
    _dir(tmp_path / 'ci' / 'envs' / 'e4', YOUNG)
    for i in range(5):
        _dir(tmp_path / 'ci' / 'native' / f'n{i}', OLD + timedelta(hours=i))
    _touch(tmp_path / 'ci' / 'packs' / 'a1.pack', OLD)
    _touch(tmp_path / 'ci' / 'packs' / 'f1.pack', OLD)
    _touch(tmp_path / 'slurm-1.out', OLD)
    _touch(tmp_path / 'slurm-2.out', YOUNG)
    _touch(tmp_path / '.cache' / 'lab-forge-r.log', OLD, size=3 * 1024 * 1024)
    _touch(tmp_path / '.cache' / 'lab-forge-s.log', OLD, size=10)
    return tmp_path


POLICY = Policy(log_max_mb=1, uv_prune=False)
SOURCES = {'a3', 'a4', 'a5'}


def _plan(home: Path) -> Plan:
    return cluster_plan(home, POLICY, now=NOW, live={'f1'}, repo='r', sources=SOURCES)


def test_cluster_plan_deletes_only_the_unreferenced(home: Path) -> None:
    plan = _plan(home)
    assert _doomed(plan) == {
        'a1': 'run-not-a-carry-source',
        'a2': 'run-not-a-carry-source',
        'g1': 'run-abandoned',
        'orphan': 'tree-unreferenced',
        'e3': 'env-unreferenced',
        'e3.log': 'env-unreferenced',
        'n0': 'native-unreferenced',
        'n1': 'native-unreferenced',
        'n2': 'native-unreferenced',
        'a1.pack': 'pack-not-in-flight',
        'slurm-1.out': 'slurm-out-finished',
        'lab-forge-r.log': 'log-over-size',
    }
    trees = {d.path.parent.name for d in plan.doomed if d.rule.startswith('run-')}
    assert trees == {'runs', 'trees'}, 'a run goes with its tree'


def test_a_cargo_target_goes_when_no_kept_run_names_its_native_key(home: Path) -> None:
    """``cargo-target/<native key>`` follows its key; the retired shared target's dirs name no key."""
    targets = home / 'ci' / 'cargo-target'
    for name in ('n3', 'n4', 'n9', 'release'):
        _dir(targets / name, OLD)
    _touch(targets / 'n9.lock', OLD)
    _dir(targets / 'n8', YOUNG)
    doomed = {d.path.name: d.rule for d in _plan(home).doomed if d.path.parent == targets}
    assert doomed == {'n9': 'cargo-unreferenced', 'n9.lock': 'cargo-unreferenced', 'release': 'cargo-unreferenced'}


def test_harder_is_this_repos_carry_sources_oldest_first_never_in_flight(home: Path) -> None:
    plan = _plan(home)
    harder = [d.path.name for d in plan.harder if d.path.parent.name == 'runs']
    assert harder == ['a3', 'a4', 'a5'], "f1 is in flight, b1 is another repo's"


def test_a_kept_run_naming_no_builds_blocks_the_env_and_native_rules(home: Path) -> None:
    """An older run state names no build keys: an unprovable reference is a reference."""
    state = home / 'ci' / 'runs' / 'a5' / 'state.json'
    state.write_text(json.dumps({'sha': 'a5', 'repo': 'r', 'record': {}}), encoding='utf-8')
    _touch(state, OLD + timedelta(hours=4))
    rules = set(_doomed(_plan(home)).values())
    assert not {'env-unreferenced', 'native-unreferenced'} & rules
    assert 'run-not-a-carry-source' in rules, 'PLANTED CONTROL: the run rules still decide'


def test_carry_sources_are_the_carrys_own_nearest_runs_per_tip(tmp_path: Path) -> None:
    """A linear history c0..c5 with runs at c0..c4: tip c5 reads c4 c3 c2; c0 c1 are nobody's source."""
    run_git(tmp_path, 'init', '-q')
    shas = []
    for i in range(6):
        run_git(tmp_path, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', f'c{i}')
        shas.append(git_out(tmp_path, 'rev-parse', 'HEAD'))
    runs = shas[:5]
    assert carry_sources(tmp_path, runs, [shas[5]]) == set(shas[2:5])
    assert carry_sources(tmp_path, runs, [shas[3]]) == set(shas[0:4]), "a tip that ran is its own child's source"


def test_apply_logs_every_deletion_and_dry_run_deletes_nothing(home: Path) -> None:
    plan = _plan(home)
    lines: list[str] = []
    apply(plan, POLICY, usage=None, dry_run=True, say=lines.append, run=_no_run)
    assert (home / 'ci' / 'runs' / 'a1').exists()
    assert all(json.loads(line)['dry_run'] for line in lines)
    done = apply(plan, POLICY, usage=None, dry_run=False, say=lines.append, run=_no_run)
    assert not (home / 'ci' / 'runs' / 'a1').exists()
    assert (home / 'ci' / 'runs' / 'a3').exists()
    assert (home / 'ci' / 'runs' / 'f1').exists()
    assert (home / '.cache' / 'lab-forge-r.log.1').exists()
    row = json.loads(lines[-1])
    assert {'path', 'bytes', 'rule'} <= row.keys()
    assert done.freed_bytes > 0
    assert done.over is False


def test_the_cli_is_a_dry_run_reporting_paths_bytes_and_files_per_rule(home: Path, monkeypatch) -> None:
    """Ada's binding ceiling is the FILE quota: the dry run says what goes per rule and where files would land."""
    said: list[str] = []
    quota = Usage(used=10 * 10**9, limit=1000 * 10**9, files=960_000, files_limit=2_000_000)
    monkeypatch.setattr(retention, '_plan_for', lambda *_a, **_k: _plan(home))
    monkeypatch.setattr(retention, 'read_usage', lambda *_a, **_k: quota)
    monkeypatch.setattr(retention, '_live_shas', set)
    monkeypatch.setattr(retention, 'section', lambda _name: {'log_max_mb': 1, 'uv_prune': False})
    monkeypatch.setattr(retention, 'emit', said.append)
    assert retention.main(['--cluster']) == 0
    assert (home / 'ci' / 'runs' / 'a1').exists(), 'without --apply nothing is touched'
    summary = [line for line in said if line.startswith('[retention]')]
    assert '[retention] would delete run-not-a-carry-source: 4 paths, 0.0 MB, 8 files' in summary
    assert any(line.startswith('[retention] would delete 15 paths') for line in summary), summary
    assert any('files 960000/2000000 (48.0%) -> ' in line for line in summary), summary
    said.clear()
    assert retention.main(['--cluster', '--apply']) == 0
    assert not (home / 'ci' / 'runs' / 'a1').exists(), 'PLANTED CONTROL: --apply deletes'
    assert any(line.startswith('[retention] deleted run-not-a-carry-source') for line in said), said


def test_quota_pressure_prunes_harder_until_target_and_reports_still_over(home: Path) -> None:
    plan = _plan(home)
    near = Usage(used=95 * 10**9, limit=100 * 10**9, files=None, files_limit=None)
    done = apply(plan, POLICY, usage=near, dry_run=False, say=lambda _: None, run=_no_run)
    assert not (home / 'ci' / 'runs' / 'a3').exists(), 'pressure removed the oldest carry source'
    assert (home / 'ci' / 'runs' / 'f1').exists()
    assert done.over, 'a few bytes freed cannot bring 95% under the pressure line'


def test_mmlsquota_is_read_for_blocks_and_files() -> None:
    text = (
        '                         Block Limits                                               |     File Limits\n'
        'Filesystem Fileset    type             KB      quota      limit   in_doubt    grace |    files   quota    '
        'limit in_doubt    grace  Remarks\n'
        'dss2fs01   HOME       USR        10261120 1048576000 1101004800    1643488     none |   516915 2000000  '
        '2020000      340     none \n'
    )
    usage = parse_mmlsquota(text)
    assert usage == Usage(used=10261120 * 1024, limit=1048576000 * 1024, files=516915, files_limit=2000000)
    assert usage.fraction() == pytest.approx(516915 / 2000000, abs=0.0)  # exact integers; files are the nearer ceiling
    assert parse_mmlsquota('no quota') is None


def test_workstation_plan_removes_stale_forge_trees_only(tmp_path: Path) -> None:
    checkout = tmp_path / 'repo'
    _dir(checkout / '.claude' / 'worktrees' / 'forge-aaaaaaaaaaaa', OLD)
    _dir(checkout / '.claude' / 'worktrees' / 'forge-bbbbbbbbbbbb', YOUNG)
    _dir(checkout / '.claude' / 'worktrees' / 'storage-retention', OLD)
    plan = workstation_plan([checkout], POLICY, now=NOW)
    assert _doomed(plan) == {'forge-aaaaaaaaaaaa': 'forge-tree-stale'}
    calls: list[list[str]] = []
    apply(plan, POLICY, usage=None, dry_run=False, say=lambda _: None, run=lambda argv, **_: calls.append(argv))
    assert not (checkout / '.claude' / 'worktrees' / 'forge-aaaaaaaaaaaa').exists()
    assert calls[-1][-2:] == ['worktree', 'prune'], 'git forgets the removed worktree'


def test_policy_is_data_and_an_unknown_key_is_refused() -> None:
    assert load_policy({'abandon_days': 5}).abandon_days == 5
    assert load_policy({}) == Policy()
    with pytest.raises(ValueError, match='carry_keep'):
        load_policy({'carry_keep': 5})  # retired: the carry's own selection decides


def test_serve_pass_runs_once_per_interval(home: Path, tmp_path: Path) -> None:
    state = tmp_path / 'state' / 'forge-retention.json'
    kwargs = {
        'cluster': True, 'home': home, 'state': state, 'table': {'uv_prune': False},
        'usage': lambda: None, 'live': lambda: {'f1'}, 'say': lambda _: None, 'run': _no_run,
        'planner': lambda _root, policy, **kw: cluster_plan(
            kw['home'], policy, now=kw['now'], live=kw['live'], repo='r', sources=SOURCES
        ),
    }  # fmt: skip
    assert serve_pass(Path(), now=NOW, **kwargs) is not None
    assert not (home / 'ci' / 'runs' / 'a1').exists()
    assert serve_pass(Path(), now=NOW + timedelta(hours=1), **kwargs) is None, 'not due again within the hour'


def _no_run(*_: object, **__: object) -> None:
    return None
