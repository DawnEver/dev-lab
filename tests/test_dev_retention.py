"""Storage retention: a tree or env goes once nothing in flight needs it, every tick, each deletion logged."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
from _forge_fake import git_out, run_git

from lab_commons.dev import retention, retentionplan
from lab_commons.dev.diskusage import Usage, parse_mmlsquota
from lab_commons.dev.retention import apply, serve_pass
from lab_commons.dev.retentionplan import (
    Plan,
    Policy,
    carry_sources,
    cluster_plan,
    in_flight,
    load_policy,
    occupied_shas,
    runs,
    workstation_plan,
)
from lab_commons.hpc.slurm import parse_workdirs

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
    path = home / 'ci' / 'runs' / sha / 'base' / 'state.json'
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
        'a1': 'tree-not-in-flight',  # its state goes too: run-not-a-carry-source (below)
        'a2': 'tree-not-in-flight',
        'a3': 'tree-not-in-flight',
        'a4': 'tree-not-in-flight',
        'a5': 'tree-not-in-flight',
        'b1': 'tree-not-in-flight',
        'g1': 'tree-not-in-flight',
        'orphan': 'tree-not-in-flight',
        'e3': 'env-unreferenced',
        'e3.log': 'env-unreferenced',
        'n0': 'native-unreferenced',
        'n1': 'native-unreferenced',
        'n2': 'native-unreferenced',
        'a1.pack': 'pack-not-in-flight',
        'slurm-1.out': 'slurm-out-finished',
        'lab-forge-r.log': 'log-over-size',
    }
    runs = {d.path.name: d.rule for d in plan.doomed if d.path.parent.name == 'runs'}
    assert runs == {'a1': 'run-not-a-carry-source', 'a2': 'run-not-a-carry-source', 'g1': 'run-abandoned'}
    assert (home / 'ci' / 'runs' / 'a3') not in {d.path for d in plan.doomed}, 'a carry source keeps its STATE'
    kept = {'f1', 'building'}
    assert not {d.path.name for d in plan.doomed if d.path.parent.name == 'trees'} & kept, 'in flight: kept'


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
    assert [d.path.name for d in plan.harder] == ['a3', 'a4', 'a5'], "f1 is in flight, b1 is another repo's"
    assert {d.path.parent.name for d in plan.harder} == {'runs'}, 'their trees already went: not in flight'


def test_an_in_flight_run_naming_no_builds_blocks_the_env_and_native_rules(home: Path) -> None:
    """An older state names no build keys: IN FLIGHT, an unprovable reference is a reference."""
    state = home / 'ci' / 'runs' / 'a5' / 'base' / 'state.json'
    state.write_text(json.dumps({'sha': 'a5', 'repo': 'r'}), encoding='utf-8')
    _touch(state, OLD + timedelta(hours=4))
    rules = {d.rule for d in cluster_plan(home, POLICY, now=NOW, live={'f1', 'a5'}, repo='r', sources=SOURCES).doomed}
    assert not {'env-unreferenced', 'native-unreferenced'} & rules
    assert 'run-not-a-carry-source' in rules, 'PLANTED CONTROL: the run rules still decide'


def test_a_sha_whose_other_part_is_unrecorded_is_an_unrecorded_run(tmp_path: Path) -> None:
    """Every part of a sha has its own state (``runs/<sha>/<part>``); the sha's run ends with its LAST part.

    PLANTED CONTROL: the recorded base part is the newer file, so a newest-wins read would call it done.
    """
    for part, state, when in (('femm', {'sha': 's', 'repo': 'r'}, OLD), ('base', {'sha': 's', 'record': {}}, YOUNG)):
        path = tmp_path / 'runs' / 's' / part / 'state.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(state), encoding='utf-8')
        _touch(path, when)
    [(path, state, when)] = runs(tmp_path)
    assert (path.name, 'record' in state, state['repo'], when) == ('s', False, 'r', YOUNG)


def test_in_flight_is_live_occupied_ungathered_or_being_built(home: Path) -> None:
    """The ONE definition every keep-for-flight rule reads; the abandoned and the gathered are not in it."""
    flying = in_flight(home / 'ci', POLICY, now=NOW, live={'x9'}, occupied={'a2'})
    assert flying == {'x9', 'a2', 'building'}, 'f1 is past abandon_days: only its live run file keeps it'


def test_an_env_is_kept_for_an_in_flight_run_or_its_repos_newest_run_only(home: Path) -> None:
    """A kept carry source's env goes: the carry reads its state, never its env. The newest run's stays."""
    for sha, env in (('a3', 'e8'), ('a4', 'e9')):
        state = home / 'ci' / 'runs' / sha / 'base' / 'state.json'
        data = json.loads(state.read_text(encoding='utf-8'))
        state.write_text(json.dumps({**data, 'builds': {'env': env, 'native': 'n4'}}), encoding='utf-8')
        _touch(state, OLD + timedelta(hours=int(sha[1])))
        _dir(home / 'ci' / 'envs' / env, OLD)
    doomed = _doomed(_plan(home))
    assert doomed['e8'] == doomed['e9'] == 'env-unreferenced', 'not in flight, not the newest'
    assert 'e1' not in doomed, 'PLANTED CONTROL: f1 in flight and a5, the newest of r, name it'
    assert 'e2' not in doomed, "PLANTED CONTROL: the other repo's newest run names it"


def test_a_job_in_a_tree_a_run_built_names_that_runs_builds(home: Path) -> None:
    """Only a job no run state explains blocks the env rules; one in a run's tree is read through its state."""
    plan = cluster_plan(home, POLICY, now=NOW, live={'f1'}, repo='r', sources=SOURCES, occupied={'a3'})
    assert _doomed(plan)['e3'] == 'env-unreferenced'
    assert (home / 'ci' / 'trees' / 'a3') not in {d.path for d in plan.doomed}


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
    assert '[retention] would delete run-not-a-carry-source: 2 paths, 0.0 MB, 6 files' in summary
    assert any(line.startswith('[retention] would delete 19 paths') for line in summary), summary
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
    with pytest.raises(ValueError, match='every serve tick'):
        load_policy({'every' + '_hours': 24})  # retired: a budget read once a day is exceeded between reads


def test_serve_pass_runs_every_tick_and_prunes_only_after_a_deletion(home: Path, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    kwargs = {
        'cluster': True, 'home': home, 'lock': tmp_path / 'state' / 'forge-retention.lock',
        'table': {'uv_prune': False}, 'usage': lambda: None, 'live': lambda: {'f1'}, 'say': lambda _: None,
        'run': lambda argv, **_: calls.append(argv),
        'planner': lambda _root, policy, **kw: cluster_plan(
            kw['home'], policy, now=kw['now'], live=kw['live'], repo='r', sources=SOURCES
        ),
    }  # fmt: skip
    (home / 'ci' / 'cache.git').mkdir()
    assert serve_pass(Path(), now=NOW, **kwargs) is not None
    assert not (home / 'ci' / 'runs' / 'a1').exists()
    assert calls, 'something went: git forgets it'
    calls.clear()
    _run(home, 'a6', 'e1', OLD)
    assert serve_pass(Path(), now=NOW + timedelta(minutes=1), **kwargs) is not None, 'the next tick: no interval'
    assert not (home / 'ci' / 'trees' / 'a6').exists()
    calls.clear()
    assert serve_pass(Path(), now=NOW + timedelta(minutes=2), **kwargs) is not None
    assert calls == [], 'nothing went: no prune runs'


def _no_run(*_: object, **__: object) -> None:
    return None


# ``squeue --me -h -t PENDING,RUNNING -o %Z``: a job-file job submits from its run dir under the tree
SQUEUE = '/gpfs01/home/u/ci/trees/orphan/.lab-hpc/sweep-20261015\n/gpfs01/home/u/ci/trees/a3\n/gpfs01/home/u/scratch\n'


def test_slurm_workdirs_name_the_trees_jobs_occupy() -> None:
    assert parse_workdirs(SQUEUE) == [
        '/gpfs01/home/u/ci/trees/orphan/.lab-hpc/sweep-20261015',
        '/gpfs01/home/u/ci/trees/a3',
        '/gpfs01/home/u/scratch',
    ]
    assert occupied_shas(parse_workdirs(SQUEUE)) == {'orphan', 'a3'}


def test_a_tree_a_slurm_job_runs_in_is_kept_under_every_rule(home: Path) -> None:
    occupied = occupied_shas(parse_workdirs(SQUEUE))
    plan = cluster_plan(home, POLICY, now=NOW, live={'f1'}, repo='r', sources=SOURCES, occupied=occupied)
    doomed = {d.path for d in plan.doomed}
    assert home / 'ci' / 'trees' / 'orphan' not in doomed, 'a job-file job runs in it'
    assert home / 'ci' / 'trees' / 'a1' in doomed, 'PLANTED CONTROL: an unrelated tree still goes'
    assert all(d.path.name != 'a3' for d in plan.harder), 'quota pressure never takes an occupied tree'
    assert not any(d.rule == 'env-unreferenced' for d in plan.doomed), 'the job names no builds: unprovable'
    near = Usage(used=95 * 10**9, limit=100 * 10**9, files=None, files_limit=None)
    apply(plan, POLICY, usage=near, dry_run=False, say=lambda _: None, run=_no_run)
    assert (home / 'ci' / 'trees' / 'a3').exists()
    assert (home / 'ci' / 'trees' / 'orphan').exists()
    assert not (home / 'ci' / 'trees' / 'a4').exists(), 'PLANTED CONTROL: pressure still prunes the rest'


def test_an_unreadable_queue_deletes_no_tree(home: Path) -> None:
    plan = cluster_plan(home, POLICY, now=NOW, live={'f1'}, repo='r', sources=SOURCES, occupied=None)
    near = Usage(used=95 * 10**9, limit=100 * 10**9, files=None, files_limit=None)
    apply(plan, POLICY, usage=near, dry_run=False, say=lambda _: None, run=_no_run)
    trees = home / 'ci' / 'trees'
    assert {t.name for t in trees.iterdir()} >= {'a1', 'a2', 'a3', 'a4', 'a5', 'g1', 'orphan'}
    assert not (home / 'ci' / 'runs' / 'a1').exists(), 'PLANTED CONTROL: the run rules still decide runs'
    assert not any(d.rule.endswith('-unreferenced') or d.rule == 'tree-not-in-flight' for d in plan.doomed)


def test_the_queue_read_fails_closed() -> None:
    def broken(*_: object, **__: object) -> object:
        raise FileNotFoundError(2, 'squeue')

    def answer(code: int, out: str) -> Callable[..., object]:
        return lambda *_, **__: subprocess.CompletedProcess([], code, out, '')

    assert retentionplan.slurm_occupied(run=broken) is None, 'no squeue: unprovable'
    assert retentionplan.slurm_occupied(run=answer(1, '')) is None, 'squeue failed: unprovable'
    assert retentionplan.slurm_occupied(run=answer(0, SQUEUE)) == {'orphan', 'a3'}
    assert retentionplan.slurm_occupied(run=answer(0, '')) == set(), 'an empty queue occupies nothing'


TAG: Final = '20261015-055638-r0'


def _superseded(home: Path, sha: str, env: str, when: datetime, *, streams: datetime, many: bool = False) -> Path:
    """The shape 9 run states in 10 had on the served accounts: no record, a round tag, nobody gathering it.

    *many*: the round streamed in the retired shape, a directory of one file per item (and its id list).
    """
    builds = {'env': env, 'native': 'n4'}
    state = {'sha': sha, 'repo': 'r', 'builds': builds, 'current': {'tag': TAG, 'job_id': '7'}}
    path = home / 'ci' / 'runs' / sha / 'base' / 'state.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding='utf-8')
    _touch(path, when)
    tree = _dir(home / 'ci' / 'trees' / sha, when)
    _touch(tree / '.lab-ci' / 'env.sh', when)
    if many:
        for i in range(3):
            _touch(tree / '.lab-ci' / TAG / f'{i}.jsonl', streams).write_text(f'{{"n": {i}}}\n', encoding='utf-8')
            _touch(tree / '.lab-ci' / TAG / f'{i}.ids.json', streams)
        _dir(tree / '.lab-ci' / TAG, streams)
    else:
        lines = ''.join(f'{{"item": {i}, "n": {i}}}\n' for i in range(3))
        _touch(tree / '.lab-ci' / f'{TAG}.jsonl', streams).write_text(lines, encoding='utf-8')
    for made in (tree / '.lab-ci', tree):
        os.utime(made, (when.timestamp(), when.timestamp()))
    return tree


#: What retention keeps of the three-item round either shape streamed: the one file the reader takes.
_KEPT: Final = f'{{"round": "{TAG}"}}\n' + ''.join(f'{{"item": {i}, "n": {i}}}\n' for i in range(3))


@pytest.mark.parametrize('many', [False, True], ids=['one-file', 'many-file-in-flight'])
def test_a_superseded_run_is_not_in_flight_and_its_streams_outlive_its_tree(home: Path, *, many: bool) -> None:
    """No record is not in flight: a superseded run is never gathered. Its tree goes, its streams and state stay."""
    stale = NOW - timedelta(days=3)
    tree = _superseded(home, 's1', 'e7', stale, streams=stale, many=many)
    _dir(home / 'ci' / 'envs' / 'e7', stale)
    plan = _plan(home)
    assert 's1' not in in_flight(home / 'ci', POLICY, now=NOW, live={'f1'}, occupied=())
    doomed = {d.path: d for d in plan.doomed}
    assert doomed[tree].rule == 'tree-not-in-flight'
    assert doomed[home / 'ci' / 'envs' / 'e7'].rule == 'env-unreferenced', 'envs follow the trees'
    assert home / 'ci' / 'runs' / 's1' not in doomed, 'its state is a carry source, kept until abandon_days'
    apply(plan, POLICY, usage=None, dry_run=False, say=lambda _: None, run=_no_run)
    assert not tree.exists()
    run = home / 'ci' / 'runs' / 's1'
    assert sorted(p.name for p in run.iterdir()) == ['base', 'streams.jsonl'], 'ONE file per kept run'
    assert (run / 'streams.jsonl').read_text(encoding='utf-8') == _KEPT


def test_a_run_kept_in_the_many_file_shape_is_upgraded_to_one_file(home: Path) -> None:
    """``runs/<sha>/streams/<tag>.txt`` is read by the carry while the run is unrecorded: upgraded, not refused."""
    stale = NOW - timedelta(days=3)
    tree = _superseded(home, 's1', 'e7', stale, streams=stale)
    shutil.rmtree(tree)
    old = home / 'ci' / 'runs' / 's1' / 'streams'
    old.mkdir()
    (old / f'{TAG}.txt').write_text(''.join(f'@@@ {i}.jsonl\n{{"n": {i}}}\n' for i in range(3)), encoding='utf-8')
    (old / '20261014-000000-r0.txt').write_text('@@@ 0.jsonl\n{"n": 9}\n', encoding='utf-8')  # an earlier round
    before = sum(1 for p in (home / 'ci' / 'runs' / 's1').rglob('*') if p.is_file())
    apply(_plan(home), POLICY, usage=None, dry_run=False, say=lambda _: None, run=_no_run)
    run = home / 'ci' / 'runs' / 's1'
    assert sorted(p.name for p in run.iterdir()) == ['base', 'streams.jsonl'], 'the old directory is gone'
    assert (run / 'streams.jsonl').read_text(encoding='utf-8') == _KEPT
    after = sum(1 for p in run.rglob('*') if p.is_file())
    assert (before, after) == (3, 2), 'PLANTED CONTROL: the state and one stream file, where three were'


def test_a_round_that_ended_within_min_age_is_still_in_flight(home: Path) -> None:
    """PLANTED CONTROL: the state is days old but a stream was written an hour ago -- the gather is due."""
    _superseded(home, 's2', 'e7', NOW - timedelta(days=3), streams=YOUNG)
    assert 's2' in in_flight(home / 'ci', POLICY, now=NOW, live=(), occupied=())


def test_a_job_file_job_names_the_env_its_env_sh_sources(home: Path) -> None:
    """A tree no run state names (a job-file job) is read through ``.lab-ci/env.sh``, not taken as unprovable."""
    tree = _dir(home / 'ci' / 'trees' / 'j1', OLD)
    _touch(tree / '.lab-ci' / 'env.sh', OLD).write_text(
        'export VIRTUAL_ENV="/h/ci/envs/e3" PATH="/h/ci/envs/e3/bin:$PATH"\n'
        'export PYTHONPATH="/h/ci/trees/j1/src:/h/ci/native/n0:/h/ci/bin${PYTHONPATH:+:$PYTHONPATH}"\n',
        encoding='utf-8',
    )
    plan = cluster_plan(home, POLICY, now=NOW, live={'f1'}, repo='r', sources=SOURCES, occupied={'j1'})
    doomed = _doomed(plan)
    assert 'e3' not in doomed, 'the job sources it'
    assert 'n0' not in doomed, 'and its native build'
    assert doomed['n1'] == 'native-unreferenced', 'PLANTED CONTROL: the env rules still decide the rest'


def test_an_old_recorded_run_naming_no_builds_is_no_reference(home: Path) -> None:
    """Measured: a repo's newest recorded run predated ``builds`` -- not in flight, it references nothing."""
    state = home / 'ci' / 'runs' / 'b1' / 'base' / 'state.json'
    state.write_text(json.dumps({'sha': 'b1', 'repo': 'other', 'record': {}}), encoding='utf-8')
    _touch(state, OLD)
    doomed = _doomed(_plan(home))
    assert doomed['e2'] == 'env-unreferenced', 'only the old run named it, by no key'
    assert 'e1' not in doomed, 'PLANTED CONTROL: the newest run naming builds still keeps its env'


def test_collect_keeps_its_newest_key_files_within_budget_and_nothing_else(home: Path) -> None:
    """``collect/`` is a cache: its newest ``collect_files`` key files stay, a young one always, the rest go."""
    store = home / 'ci' / 'collect'
    for i in range(4):
        _touch(store / f'k{i}.json', OLD + timedelta(hours=i))
    _dir(store / 'perfile', OLD)  # the retired one-file-per-test layout: a directory is never a key
    _touch(store / 'k9.json.123.tmp', OLD)  # a writer that died before its replace
    _touch(store / 'k8.json', YOUNG)  # being written: within min_age, kept beyond the budget
    plan = cluster_plan(home, Policy(collect_files=2, uv_prune=False), now=NOW, live={'f1'}, repo='r', sources=SOURCES)
    doomed = {d.path.name: d.rule for d in plan.doomed if d.path.parent == store}
    over = 'collect-over-budget'
    assert doomed == {'k0.json': over, 'k1.json': over, 'k2.json': over, 'perfile': over, 'k9.json.123.tmp': over}


def test_an_artifact_goes_once_no_job_runs_it_and_it_is_not_the_newest(home: Path) -> None:
    """Phase 5: retention by liveness. A job submits from ``ci/jobs/<sha>/<run>``; its artifact stays."""
    store = home / 'ci' / 'artifacts'
    for n, sha in enumerate(['c1', 'c2', 'c3', 'c4']):
        _touch(store / f'{sha}.tar.gz', OLD + timedelta(hours=n))
    _touch(store / 'c5.tar.gz.part', YOUNG)  # being built
    occupied = occupied_shas(['/gpfs01/home/u/ci/jobs/c2/sweep-20261018-0'])
    assert occupied == {'c2'}
    plan = cluster_plan(home, POLICY, now=NOW, live={'f1'}, repo='r', sources=SOURCES, occupied=occupied)
    gone = {d.path.name for d in plan.doomed if d.rule == 'artifact-not-live'}
    assert gone == {'c1.tar.gz', 'c3.tar.gz'}, 'c2 is run by a job, c4 is the newest done, c5 is being built'


def test_an_unreadable_queue_deletes_no_artifact(home: Path) -> None:
    for n, sha in enumerate(['c1', 'c2']):
        _touch(home / 'ci' / 'artifacts' / f'{sha}.tar.gz', OLD + timedelta(hours=n))
    plan = cluster_plan(home, POLICY, now=NOW, live={'f1'}, repo='r', sources=SOURCES, occupied=None)
    assert not any(d.rule == 'artifact-not-live' for d in plan.doomed)
    plan = cluster_plan(home, POLICY, now=NOW, live={'f1'}, repo='r', sources=SOURCES, occupied=set())
    assert {d.path.name for d in plan.doomed if d.rule == 'artifact-not-live'} == {'c1.tar.gz'}, 'PLANTED CONTROL'
