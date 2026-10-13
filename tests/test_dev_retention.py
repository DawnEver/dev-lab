"""Storage retention: only what the policy proves unreferenced is deleted, each deletion logged; quota prunes harder."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lab_commons.dev.retention import (
    Policy,
    Usage,
    apply,
    cluster_plan,
    load_policy,
    parse_mmlsquota,
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


def _run(home: Path, sha: str, env: str, when: datetime, *, done: bool = True, repo: str = 'r') -> None:
    state = {'sha': sha, 'repo': repo, 'env': env, **({'record': {}} if done else {})}
    path = home / 'ci' / 'runs' / sha / 'state.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding='utf-8')
    _touch(path, when)
    _dir(home / 'ci' / 'trees' / sha, when)


def _doomed(plan: object) -> dict[str, str]:
    return {d.path.name: d.rule for d in plan.doomed}  # type: ignore[attr-defined]


@pytest.fixture
def home(tmp_path: Path) -> Path:
    # env e1: five finished runs, oldest first -> the 3 newest are carry sources
    for i, sha in enumerate(['a1', 'a2', 'a3', 'a4', 'a5']):
        _run(tmp_path, sha, 'e1', OLD + timedelta(hours=i))
    _run(tmp_path, 'b1', 'e2', OLD - timedelta(days=5))  # the only run of e2: its env's carry source
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


def test_cluster_plan_deletes_only_the_unreferenced(home: Path) -> None:
    plan = cluster_plan(home, POLICY, now=NOW, live={'f1'})
    assert _doomed(plan) == {
        'a1': 'run-beyond-carry',
        'a2': 'run-beyond-carry',
        'g1': 'run-abandoned',
        'orphan': 'tree-unreferenced',
        'e3': 'env-unreferenced',
        'e3.log': 'env-unreferenced',
        'n0': 'native-beyond-keep',
        'n1': 'native-beyond-keep',
        'a1.pack': 'pack-not-in-flight',
        'slurm-1.out': 'slurm-out-finished',
        'lab-forge-r.log': 'log-over-size',
    }
    trees = {d.path.parent.name for d in plan.doomed if d.rule.startswith('run-')}
    assert trees == {'runs', 'trees'}, 'a run goes with its tree'


def test_harder_is_oldest_first_and_never_in_flight_nor_the_newest_per_env(home: Path) -> None:
    plan = cluster_plan(home, POLICY, now=NOW, live={'f1'})
    harder = [d.path.name for d in plan.harder if d.path.parent.name == 'runs']
    assert harder == ['a3', 'a4'], 'b1 and a5 are the newest of their env, f1 is in flight'


def test_apply_logs_every_deletion_and_dry_run_deletes_nothing(home: Path) -> None:
    plan = cluster_plan(home, POLICY, now=NOW, live={'f1'})
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


def test_quota_pressure_prunes_harder_until_target_and_reports_still_over(home: Path) -> None:
    plan = cluster_plan(home, POLICY, now=NOW, live={'f1'})
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
    assert usage.fraction() == pytest.approx(516915 / 2000000)  # files are the nearer ceiling here
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
    assert load_policy({'carry_keep': 5}).carry_keep == 5
    assert load_policy({}) == Policy()
    with pytest.raises(ValueError, match='carry_kept'):
        load_policy({'carry_kept': 5})


def test_serve_pass_runs_once_per_interval(home: Path, tmp_path: Path) -> None:
    state = tmp_path / 'state' / 'forge-retention.json'
    kwargs = {
        'cluster': True, 'home': home, 'state': state, 'table': {'uv_prune': False},
        'usage': lambda: None, 'live': lambda: {'f1'}, 'say': lambda _: None, 'run': _no_run,
    }  # fmt: skip
    assert serve_pass(Path(), now=NOW, **kwargs) is not None
    assert not (home / 'ci' / 'runs' / 'a1').exists()
    assert serve_pass(Path(), now=NOW + timedelta(hours=1), **kwargs) is None, 'not due again within the hour'


def _no_run(*_: object, **__: object) -> None:
    return None
