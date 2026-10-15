"""``lab_commons.hpc`` remote run: streamed outcomes, retried kills and measured plans.

Every number in a docstring here was measured on a real cluster for one downstream run
(2026-10-09): 26233 passed, 13751 lost, 8786 missing. The item runner is exercised by
REALLY running pytest on ids built to be awkward, because the defect behind ``missing`` was a mismatch
between the id pytest collects and the id it reports -- a fake cannot reproduce that.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import ClassVar

import pytest

from lab_commons.compute import learned
from lab_commons.compute.learned import OOM_GROWTH, Measured
from lab_commons.config import CONFIG_ENV
from lab_commons.dev.forgestatus import Status
from lab_commons.dev.platformparts import part_of, parts_of
from lab_commons.hpc import __main__ as cli
from lab_commons.hpc import cluster as cluster_module
from lab_commons.hpc.builds import Builds, cargo_target
from lab_commons.hpc.cluster import Unreachable
from lab_commons.hpc.config import Cost, Limits, Policy
from lab_commons.hpc.grants import Grant, Machine
from lab_commons.hpc.needsets import BASE, Vocabulary
from lab_commons.hpc.phases import describe, phases
from lab_commons.hpc.plan import Plan, balance, make_plan
from lab_commons.hpc.progress import parse_queue, where
from lab_commons.hpc.pytest_item import canonical, item_argv, outcome_of, read_stream
from lab_commons.hpc.records import (
    files_made,
    fold,
    held_outcomes,
    read_record,
    read_streams,
    record_name,
    run_shas,
    write_record,
)
from lab_commons.hpc.run import RETRIES, build_run, gather_run, submit_run
from lab_commons.hpc.shell import (
    FULL,
    INCREMENTAL,
    PREP_LOG,
    TIME,
    RunSpec,
    build_script,
    collect_command,
    needs_script,
    parse_ids,
    parse_times,
)
from lab_commons.hpc.slurm import parse_snapshot
from lab_commons.hpc.watch import PENDING

FIXTURE = (Path(__file__).parent / '_hpc_fixtures' / 'cluster-2026-10-08.txt').read_text(encoding='utf-8')
IDLE = FIXTURE.split('@@@ running')[0] + '@@@ running\n'
GRANT = Grant(user='me', hosts=('login.example',), slurm_account='acct-free', partitions=('shortq', 'defq'))
SHA = 'a' * 40
SOURCE = Path(__file__).parents[1] / 'src' / 'lab_commons' / 'hpc' / 'pytest_item.py'


@pytest.fixture(autouse=True)
def _machine_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every gather learns beside the machine file: never this box's own."""
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'machine' / 'config.toml'))


def test_the_item_runner_is_standalone() -> None:
    """It is shipped as text and imported beside an arbitrary lab_commons -- it must import none."""
    source = SOURCE.read_text(encoding='utf-8')
    assert 'lab_commons' not in ''.join(line for line in source.splitlines() if line.startswith(('import', 'from')))


# -- the stream ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('when', 'outcome', 'xfail', 'expected'),
    [
        ('setup', 'passed', False, None),
        ('call', 'passed', False, 'passed'),
        ('call', 'failed', False, 'failed'),
        ('setup', 'failed', False, 'error'),
        ('teardown', 'failed', False, 'error'),
        ('setup', 'skipped', False, 'skipped'),
        ('call', 'skipped', True, 'xfailed'),
    ],
)
def test_a_phase_decides_only_what_it_can(when: str, outcome: str, *, xfail: bool, expected: str | None) -> None:
    assert outcome_of(when, outcome, xfail=xfail) == expected


def test_the_xdist_group_suffix_is_stripped_only_back_to_a_collected_id() -> None:
    """``--dist loadgroup`` turned ``t`` into ``t@group_0``; 8786 ran tests read as missing."""
    expected = {'tests/a.py::t[x@y]', 'tests/a.py::u'}
    assert canonical('tests/a.py::u@group_0', expected) == 'tests/a.py::u'
    assert canonical('tests/a.py::t[x@y]', expected) == 'tests/a.py::t[x@y]', 'an @ inside the id is the id'
    assert canonical('tests/a.py::v@g', expected) == 'tests/a.py::v@g', 'nothing collected: left alone'


def test_an_unclosed_stream_is_unfinished_and_keeps_what_it_finished() -> None:
    text = (
        '{"id": "t.py::a", "outcome": "passed", "s": 1.5}\n'
        '{"id": "t.py::b", "outcome": "passed", "s": 0.5}\n'
        '{"id": "t.py::b", "outcome": "error", "s": 0.25}\n'
        '{"id": "t.py::c", "outc'
    )
    folded = read_stream(text, ['t.py::a', 't.py::b', 't.py::c'])
    assert folded['done'] is None
    assert folded['outcomes'] == {'t.py::a': 'passed', 't.py::b': 'error'}
    assert folded['seconds'] == {'t.py::a': 1.5, 't.py::b': 0.75}


def test_streams_are_read_back_per_item_in_one_command() -> None:
    calls = []

    def run(command: str, stdin: str | None) -> str:
        calls.append((command, stdin))
        return '@@@ 0.jsonl\n{"a": 1}\n@@@ 12.jsonl\n{"b": 2}\n{"c": 3}\n'

    assert read_streams(run, '"$HOME"/ci/x') == {0: '{"a": 1}', 12: '{"b": 2}\n{"c": 3}'}
    assert len(calls) == 1


# -- the item runner, for real ---------------------------------------------------------------------------

_TRICKY = """
import os
import pytest

@pytest.mark.parametrize('v', ['a[b]', 'x::y', 'p/q', 'ünï', '-neg', 'a-b', 'sp ace', 'at@sign'])
def test_param(v):
    assert v

@pytest.mark.grouped
@pytest.mark.parametrize('n', [1, -1])
def test_grouped(n):
    assert n > 0

class TestKind:
    @pytest.mark.xfail(reason='known')
    def test_xfail(self):
        raise AssertionError

    @pytest.mark.skip(reason='not here')
    def test_skip(self):
        pass

@pytest.fixture
def broken():
    raise RuntimeError('setup')

def test_setup_error(broken):
    pass
"""

#: What xdist's ``--dist loadgroup`` does to a grouped test's id inside a worker.
_LOADGROUP = """
def pytest_collection_modifyitems(items):
    for item in items:
        if item.get_closest_marker('grouped'):
            item._nodeid = item.nodeid + '@group_0'
"""


def _item_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The runner as the cluster has it: ``lab_ci_pytest_item.py`` on PYTHONPATH, imported by that name."""
    shipped = tmp_path / 'bin' / 'lab_ci_pytest_item.py'
    shipped.parent.mkdir()
    shipped.write_text(SOURCE.read_text(encoding='utf-8'), encoding='utf-8')
    monkeypatch.setenv('PYTHONPATH', str(shipped.parent))
    monkeypatch.chdir(tmp_path)
    spec = importlib.util.spec_from_file_location('lab_ci_pytest_item', shipped)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tree(tmp_path: Path, body: str) -> list[str]:
    (tmp_path / 'pytest.ini').write_text('[pytest]\nmarkers =\n    grouped: x\n', encoding='utf-8')
    (tmp_path / 'conftest.py').write_text(_LOADGROUP, encoding='utf-8')
    test = tmp_path / 'tests' / 'sub dir' / 'test_tricky.py'
    test.parent.mkdir(parents=True)
    test.write_text(body, encoding='utf-8')
    collected = subprocess.run(
        [sys.executable, '-m', 'pytest', '--collect-only', '-q', '-p', 'no:cacheprovider'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        cwd=tmp_path,
    )
    return parse_ids(collected.stdout)


def test_every_awkward_id_that_ran_is_reported_under_its_collected_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Brackets, '::', '/', unicode, a leading '-', a space and an '@' in params, and a loadgroup suffix."""
    runner = _item_runner(tmp_path, monkeypatch)
    ids = _tree(tmp_path, _TRICKY)
    assert len(ids) == 13
    result = runner.run({'ids': ids, 'stream': '.lab-ci/t/0.jsonl'})
    outcomes = result['outcomes']
    assert set(outcomes) == set(ids), result['tail']
    grouped = sorted(n for n in ids if 'test_grouped' in n)
    assert [outcomes[n] for n in grouped] == ['failed', 'passed']
    assert outcomes[next(n for n in ids if n.endswith('test_xfail'))] == 'xfailed'
    assert outcomes[next(n for n in ids if n.endswith('test_skip'))] == 'skipped'
    assert result['whys'][next(n for n in ids if n.endswith('test_skip'))] == 'not here', 'a skip keeps its reason'
    assert result['whys'][next(n for n in ids if n.endswith('test_xfail'))] == 'known', 'an xfail keeps its reason'
    assert outcomes[next(n for n in ids if n.endswith('test_setup_error'))] == 'error'
    assert sum(o == 'passed' for o in outcomes.values()) == 9
    assert result['done']['done'] == 1
    assert result['done']['wall'] > 0


def test_a_pytest_that_dies_mid_item_names_the_test_it_was_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _item_runner(tmp_path, monkeypatch)
    body = 'import os\n\ndef test_a():\n    pass\n\ndef test_b():\n    os._exit(3)\n\ndef test_c():\n    pass\n'
    ids = _tree(tmp_path, body)
    result = runner.run({'ids': ids, 'stream': '.lab-ci/t/0.jsonl'})
    assert result['outcomes'] == {ids[0]: 'passed'}
    assert result['done']['done'] == 3
    assert result['started'] == ids[1], 'the plugin streams a START line, so the in-flight id is known'


def test_a_clean_exit_mid_item_fails_the_in_flight_id_and_requeues_only_the_ids_after_it() -> None:
    items = [{'ids': ['t.py::a', 't.py::b', 't.py::c', 't.py::d']}]
    streams = {
        0: '{"start": "t.py::a"}\n{"id": "t.py::a", "outcome": "passed", "s": 0}\n'
        '{"start": "t.py::b"}\n{"done": 1, "wall": 2.0, "peak_mb": null}\n'
    }
    outcomes: dict[str, str] = {}
    reasons: dict[str, str] = {}
    pending, killed, _ = fold(items, streams, outcomes, Measured.of({}), reasons, shards=[(0, 1)], walls=[60.0])
    assert outcomes == {'t.py::a': 'passed', 't.py::b': 'failed'}, 'nothing is missing when the in-flight id is known'
    assert 'exited 1' in reasons['t.py::b']
    assert sorted(node for part in pending for node in part) == ['t.py::c', 't.py::d']
    assert not killed


def test_the_scope_timeout_reaches_the_pytest_argv() -> None:
    files = ['tests/test_a.py']
    with_ceiling = item_argv({'ids': [], 'timeout_s': 3000}, files)
    assert with_ceiling[with_ceiling.index('--timeout') + 1] == '3000'
    assert with_ceiling[-1] == 'tests/test_a.py'
    assert '--timeout' not in item_argv({'ids': []}, files), 'undeclared: the repo default stands'


# -- the measured plan -----------------------------------------------------------------------------------


def test_shards_are_cut_by_measured_time_and_the_wall_is_the_slowest() -> None:
    """A flat 120 s per file planned 129-min shards that ran 1h25-2h07; 23 of 99 hit the limit."""
    seconds = [600.0] * 6 + [3000.0] + [60.0] * 20
    plan = make_plan(
        len(seconds),
        Cost(seconds=120),
        parse_snapshot(IDLE),
        cluster=GRANT.cluster(),
        policy=Policy(shard_minutes_min=20, shard_minutes_max=60, safety=1.5),
        limits=Limits(),
        seconds=seconds,
    )
    padded = [s * 1.5 for s in seconds]
    sums = [sum(padded[a:b]) for a, b in plan.shards]
    assert plan.minutes == max(1, -(-int(max(sums)) // 60))
    assert all(s <= 60 * 60 or b - a == 1 for s, (a, b) in zip(sums, plan.shards, strict=True))
    assert (6, 7) in plan.shards, 'the 75-min item sits alone rather than dragging neighbours over the window'


def test_measured_estimates_fall_back_only_for_files_never_measured() -> None:
    measured = Measured.of({'durations': {'a.py::x': 2.0, 'a.py::y': 4.0}, 'overheads': {'a.py': 10.0}})
    seconds, unmeasured = measured.estimate([['a.py::x', 'a.py::y', 'a.py::z'], ['b.py::t']], Cost(seconds=120))
    assert seconds == [10.0 + 2.0 + 4.0 + 3.0, 120.0]
    assert unmeasured == ['b.py']


def test_memory_is_the_worst_measured_peak_with_margin() -> None:
    """3 shards were OOM-killed at 6 GB; the completed ones peaked at 5.15 GB."""
    measured = Measured(peaks_mb={'a.py': 5274.0, 'b.py': 900.0})
    worst = measured.mem_gb([['a.py::t'], ['b.py::t']], Cost(mem_gb=6), Policy(safety=1.5))
    # floor: abs=0.0 -- the same float product on both sides, so only the relative 1e-12 rounding is allowed
    assert worst == pytest.approx(5274.0 * 1.5 / 1024, rel=1e-12, abs=0.0)
    assert measured.mem_gb([['a.py::t'], ['c.py::t']], Cost(mem_gb=9), Policy(safety=1.5)) == 9, 'unmeasured: cost'


def test_a_measured_peak_raises_the_memory_and_never_lowers_it_under_the_declared_cost() -> None:
    """Ada 2026-10-12: a 150 MB peak priced 225M, OOM; 429M, OOM; 598M passed -- 16 OOMs in a day.

    The peak is the pytest child's; the task's cgroup also holds the item runner, so the declared cost
    is the floor a measurement may only raise.
    """
    measured = Measured(peaks_mb={'a.py': 150.0})
    assert measured.mem_gb([['a.py::t']], Cost(mem_gb=1), Policy(safety=1.5)) == 1
    assert measured.mem_gb([['a.py::t']], Cost(mem_gb=0.1), Policy(safety=1.5)) == pytest.approx(
        150.0 * 1.5 / 1024, rel=1e-12, abs=0.0
    ), 'PLANTED CONTROL: over the floor the peak decides'


def test_a_peak_read_at_a_kill_is_a_floor_grown_like_a_retry_and_never_lowers_a_known_peak() -> None:
    """Ada 2026-10-13: 24 children OOM-killed at 1 GB read peaks of ~1120 MB -- the limit, not the need.

    Kept as measured, the next run asks 1.5x the limit and dies again; the retry after an OOM asks
    OOM_GROWTH x, and so does the record.
    """
    killed = {'seconds': {}, 'done': {'done': -9, 'wall': 30.0, 'peak_mb': 1120.0}}
    measured = Measured()
    measured.learn(['a.py::t'], killed)
    assert measured.peaks_mb == {'a.py': 1120.0 * OOM_GROWTH}
    known = Measured(peaks_mb={'a.py': 3493.0})
    known.learn(['a.py::t'], killed)
    assert known.peaks_mb == {'a.py': 3493.0}, 'a kill at a lower limit says nothing new'
    finished = {'seconds': {'a.py::t': 1.0}, 'done': {'done': 0, 'wall': 30.0, 'peak_mb': 700.0}}
    known.learn(['a.py::t'], finished)
    assert known.peaks_mb == {'a.py': 700.0}, 'PLANTED CONTROL: a finished item is measured, newer wins'


# -- the run flow ------------------------------------------------------------------------------------


class FakeRunCluster:
    """A cluster answering the run flow; an item of a file in *dies* is killed in its first *kills* rounds.

    A killed item streams the first half of its ids (rounded down) and never closes.
    """

    def __init__(
        self,
        *,
        have: bool = True,
        dies: frozenset[str] = frozenset(),
        kills: int = 1,
        oom: bool = False,
        build_fails: bool = False,
        lacking: tuple[str, ...] = (),
        active: int = 0,
        env: str = 'e0ffee0123456789',
        collected: str | None = None,
        hog: str = '',
        mem_ceiling: str = '360G',
    ) -> None:
        """*have*: the cache holds the commit; *oom*: round 0 is OUT_OF_MEMORY; *active*: sacct polls RUNNING.

        *hog*: an id whose item is OOM-killed in every round it runs in; *mem_ceiling*: the account's quota
        memory; *closed* (set later): every grant refuses the next round.
        """
        self.have, self.dies, self.kills, self.oom = have, dies, kills, oom
        self.hog, self.mem_ceiling, self.closed = hog, mem_ceiling, False
        self.build_fails, self.lacking, self.active = build_fails, lacking, active
        self.env, self.collected = env, collected
        self.state = ''
        self.queue = ''
        self.calls: list[tuple[str, str | None]] = []
        self.manifests: list[dict] = []
        self.scripts: list[str] = []

    def __call__(self, command: str, stdin: str | None = None) -> str:  # noqa: C901, PLR0911, PLR0912 -- one answer per verb
        self.calls.append((command, stdin))
        if command.endswith('state.json') and 'cat >' in command:
            self.state = stdin or ''
            return ''
        if 'squeue -h -r -j' in command:
            if isinstance(self.queue, Exception):
                raise self.queue
            return self.queue
        if 'state.json' in command:
            return self.state
        if command.startswith('for c in'):
            return ''.join(f'@@@ missing {c}\n' for c in self.lacking)
        if command.startswith('echo "@@@ nodes"'):
            quota = 'cpu=0' if self.closed else 'cpu=96'
            probed = IDLE.replace('|free|cpu=96,', f'|free|{quota},').replace('mem=360G', f'mem={self.mem_ceiling}')
            return probed + '@@@ shared\n8 lc:ws=other\n'
        if 'cat-file' in command:
            return 'have\n' if self.have else 'missing\n'
        if '@@@ facts' in command and self.build_fails:
            return '@@@ build-failed exit 101\nerror: could not find `cargo`\n'
        if '@@@ facts' in command:
            return f'@@@ time env=12s\n@@@ facts\nplatform=linux-x86_64/glibc2.28\npython=3.13.1\nenv={self.env}\n'
        if '--collect-only' in command or 'lab_ci_collect.py --cache' in command:
            if '(win)' in command:
                return 'tests/w.py::t\n'
            if self.collected is not None:
                return self.collected
            return (
                '@@@ time collect=3s\n'
                'tests/a.py::t1\ntests/a.py::t2\ntests/w.py::t\ntests/b.py::t3\ntests/b.py::t4\ntests/b.py::t5\n'
            )
        if command.endswith('manifest.json'):
            self.manifests.append(json.loads(stdin or ''))
        if command.endswith('job.sh') and 'cat >' in command:
            self.scripts.append(stdin or '')
        if 'sbatch' in command:
            return f'{4242 + len(self.manifests)}\n'
        if 'sacct' in command and self.active:
            self.active -= 1
            return '\n'.join(f'1_{i}|RUNNING' for i in range(9)) + '\n'
        if 'sacct' in command:
            state = 'OUT_OF_MEMORY' if (self.oom and len(self.manifests) == 1) or self.hog else 'TIMEOUT'
            hour = 1 + len(self.manifests)
            rows = (
                f'1_{i}|{state if i == 0 else "COMPLETED"}|2026-10-11T0{hour}:00:00|2026-10-11T0{hour}:01:00'
                f'|2026-10-11T0{hour}:{2 + i:02d}:00|{60 + 60 * i}|1'
                for i in range(9)
            )
            return '\n'.join(rows) + '\n'
        if '*.jsonl' in command:
            return self._streams()
        return ''

    def _streams(self) -> str:
        out = []
        dying = len(self.manifests) <= self.kills
        for index, item in enumerate(self.manifests[-1]['items']):
            killed = dying and item['ids'][0].split('::')[0] in self.dies
            ran = item['ids'][: len(item['ids']) // 2] if killed else item['ids']
            out.append(f'@@@ {index}.jsonl')
            if self.hog in item['ids']:
                ran = item['ids'][: item['ids'].index(self.hog)]
                out += [json.dumps({'id': n, 'outcome': 'passed', 's': 1.0}) for n in ran]
                out.append(json.dumps({'done': -9, 'wall': 5.0, 'peak_mb': 1024.0}))
                continue
            out += [json.dumps({'id': n, 'outcome': 'passed', 's': 1.0}) for n in ran]
            if not killed:
                out.append(json.dumps({'done': 0, 'wall': 5.0 + len(ran), 'peak_mb': 2048.0}))
        return '\n'.join(out) + '\n'


MACHINE = Machine(workstation='ws-a', grants=(GRANT,))
COST, POLICY = Cost(seconds=600), Policy(shard_minutes_min=1, shard_minutes_max=15)


def _submit(fake: FakeRunCluster, **kw: object) -> str:
    spec = RunSpec(
        sha=SHA,
        repo_url='https://g/r.git',
        builds=Builds(install='true', env_key='k1'),
        vocabulary=Vocabulary(('win',)),
    )
    return submit_run(spec, MACHINE, lambda _g: fake, cost=COST, policy=POLICY, stamp='t0', **kw)


def _gather(fake: FakeRunCluster) -> dict | None:
    return gather_run(SHA, MACHINE, lambda _g: fake, cost=COST, policy=POLICY)


def _run(fake: FakeRunCluster, **kw: object) -> dict:
    """Submit, then gather until the record comes back -- each gather one short call, as a caller makes them."""
    _submit(fake, **kw)
    for _ in range(2 + RETRIES):
        record = _gather(fake)
        if record is not None:
            return record
    pytest.fail('the gathers never returned a record')


def test_the_run_records_outcomes_and_never_passes_what_it_did_not_run() -> None:
    fake = FakeRunCluster()
    record = _run(fake)
    assert record['sha'] == SHA
    assert {k: v for k, v in record['prep'].items() if k != 'ship'} == {'env': 12, 'collect': 3}, 'prep is measurable'
    assert record['prep']['ship'] >= 0, 'so is the fetch/pack'
    assert record['handed'] == {'tests/w.py::t': 'win'}, 'handed names the part each id belongs to'
    assert (record['platform'], record['system'], record['cluster'], record['python']) == (
        BASE,
        'linux-x86_64/glibc2.28',
        'login.example',
        '3.13.1',
    ), 'platform is the part it is (its need-set); system is the box it ran on'
    assert (record['scope'], record['req'], record['env']) == ('full', 't0', 'e0ffee0123456789')
    assert (record['account'], record['job_ids']) == ('acct-free', ['4243'])
    assert record['plan']['comment'] == 'lc:ws=ws-a'
    assert record['plan']['job_id'] == '4243'
    assert record['plan']['unmeasured'] == ['tests/a.py', 'tests/b.py']
    assert record['outcomes']['tests/w.py::t'] == 'not-covered'
    assert set(record['outcomes'].values()) == {'passed', 'not-covered'}
    assert record['reasons'] == {}, 'a green run carries no reasons'
    assert record['overheads'] == {'tests/a.py': 5.0, 'tests/b.py': 5.0}
    assert record['peaks_mb'] == {'tests/a.py': 2048.0, 'tests/b.py': 2048.0}
    assert '#SBATCH --comment=lc:ws=ws-a' in fake.scripts[0]
    assert 'cd "$HOME"/ci/trees/' + SHA in fake.scripts[0]
    assert 'lab_ci_pytest_item' in json.dumps(fake.manifests[0])


def test_a_killed_shard_reruns_only_its_unfinished_ids_split_in_halves() -> None:
    fake = FakeRunCluster(dies=frozenset({'tests/b.py'}))
    record = _run(fake)
    assert len(fake.manifests) == 2
    assert [i['ids'] for i in fake.manifests[1]['items']] == [['tests/b.py::t4'], ['tests/b.py::t5']]
    assert all(record['outcomes'][f'tests/b.py::t{n}'] == 'passed' for n in (3, 4, 5))
    assert len(record['rounds']) == 2


def test_what_is_still_unfinished_after_the_retries_is_lost() -> None:
    record = _run(FakeRunCluster(dies=frozenset({'tests/b.py'}), kills=1 + RETRIES))
    assert len(record['rounds']) == 1 + RETRIES
    assert record['outcomes']['tests/b.py::t3'] == 'passed', 'what a killed shard finished is kept'
    assert [record['outcomes'][f'tests/b.py::t{n}'] for n in (4, 5)] == ['lost', 'lost']


def test_an_out_of_memory_round_doubles_the_memory_of_the_next() -> None:
    record = _run(FakeRunCluster(dies=frozenset({'tests/b.py'}), oom=True))
    first, second = record['rounds']
    assert second['mem_mb'] == 2 * first['mem_mb']


def test_an_oom_item_is_bisected_at_the_grantable_ceiling_and_its_lone_hog_fails_by_id() -> None:
    """Ada 2026-10-14: an item OOM-killed at 62.7 GB was re-asked at 366.77 GB of a 360 GB quota and never ran again."""
    fake = FakeRunCluster(hog='tests/b.py::t4', mem_ceiling='4G')
    record = _run(fake)
    assert [r['mem_mb'] for r in record['rounds']] == [1024, 4096], 'the grown ask is held to the quota'
    assert [i['ids'] for i in fake.manifests[1]['items']] == [['tests/b.py::t4'], ['tests/b.py::t5']]
    assert record['outcomes']['tests/b.py::t4'] == 'failed', 'the hog alone at the ceiling is its own failure'
    why = 'OUT_OF_MEMORY alone at 4096 MB, the most any grant gives (peak 1024 MB)'
    assert record['reasons']['tests/b.py::t4'] == why
    assert [record['outcomes'][f'tests/b.py::t{n}'] for n in (3, 5)] == ['passed', 'passed'], 'its mates got results'


def test_an_oom_item_under_the_ceiling_is_retried_not_failed() -> None:
    """PLANTED CONTROL: a lone id killed BELOW the ceiling is not yet proven a hog -- it is re-asked bigger."""
    fake = FakeRunCluster(hog='tests/b.py::t4', mem_ceiling='360G')
    _submit(fake)
    _gather(fake)
    assert _gather(fake) is None, 'still bisecting/growing, not settled'
    assert 'tests/b.py::t4' not in json.loads(fake.state)['outcomes']


def test_a_round_no_grant_can_take_settles_as_an_error_naming_why() -> None:
    """Ada 2026-10-14: 'cannot advance: no grant can take this work' repeated for hours, and no verdict came."""
    fake = FakeRunCluster(dies=frozenset({'tests/b.py'}))
    _submit(fake)
    fake.closed = True
    record = _gather(fake)
    assert record is not None, 'an unplaceable round settles the run in the same gather'
    assert [record['outcomes'][f'tests/b.py::t{n}'] for n in (4, 5)] == ['error', 'error']
    assert record['reasons']['tests/b.py::t4'].startswith('could not be placed: no grant can take this work')
    assert record['outcomes']['tests/b.py::t3'] == 'passed', 'PLANTED CONTROL: what ran keeps its result'
    assert len(fake.manifests) == 1, 'nothing was submitted'


def test_every_folded_round_teaches_its_repo_not_only_the_record() -> None:
    """A run superseded before its record has still measured what it ran.

    Ada 2026-10-13: no downstream run of the day reached its record, so none was learned, and every
    round 0 planned all ~4670 files blind at 1 GB.
    """
    _submit(FakeRunCluster(dies=frozenset({'tests/b.py'})))
    assert learned.learned('https://g/r.git') == {}, 'PLANTED CONTROL: nothing folded, nothing learned'
    fake = FakeRunCluster(dies=frozenset({'tests/b.py'}))
    _submit(fake)
    assert _gather(fake) is None, 'round 0 folded and its unfinished ids re-submitted: no record yet'
    taught = learned.learned('https://g/r.git')
    assert taught['peaks_mb'].keys() >= {'tests/a.py'}, 'what round 0 measured is history already'


def test_history_prices_the_plan_and_names_nothing_unmeasured() -> None:
    history = {
        'durations': {f'tests/{f}.py::t{n}': 30.0 for f, n in (('a', 1), ('a', 2), ('b', 3), ('b', 4), ('b', 5))},
        'overheads': {'tests/a.py': 20.0, 'tests/b.py': 20.0},
        'peaks_mb': {'tests/a.py': 1000.0, 'tests/b.py': 3000.0},
    }
    record = _run(FakeRunCluster(), history=history)
    assert record['plan']['unmeasured'] == []
    assert record['plan']['mem_mb'] == -(-3000 * 1.5 // 1)


def test_submit_returns_with_the_state_on_the_cluster_and_gather_reports_pending_while_jobs_run() -> None:
    fake = FakeRunCluster(active=2)
    assert _submit(fake)['sha'] == SHA
    assert json.loads(fake.state)['current']['job_id'] == '4243', 'the run state lives on the cluster'
    assert fake.active == 2, 'submit polls no job state'
    assert _gather(fake) is None
    assert _gather(fake) is None
    record = _gather(fake)
    assert record is not None
    assert set(record['outcomes'].values()) == {'passed', 'not-covered'}
    assert _gather(fake) == record, 'a finished run answers its record again'


def test_a_retry_round_is_submitted_by_a_gather_and_returns_pending() -> None:
    fake = FakeRunCluster(dies=frozenset({'tests/b.py'}))
    _submit(fake)
    assert _gather(fake) is None, 'the unfinished ids went out as round 1'
    assert len(fake.manifests) == 2


def test_a_gather_through_an_outage_raises_unreachable_and_loses_nothing() -> None:
    fake = FakeRunCluster()
    _submit(fake)

    def down(_command: str, _stdin: str | None = None) -> str:
        msg = 'ssh: connect to host login.example port 22: timed out'
        raise Unreachable(msg)

    with pytest.raises(Unreachable, match='keep running'):
        gather_run(SHA, MACHINE, lambda _g: down, cost=COST, policy=POLICY)
    assert _gather(fake) is not None


def test_a_failed_build_stops_the_run_and_quotes_the_kept_log() -> None:
    """Measured 2026-10-09: an install that failed (no cargo) still submitted 276 shards that all died."""
    fake = FakeRunCluster(build_fails=True)
    with pytest.raises(
        RuntimeError, match=r'(?s)build for a{12} failed .*nothing was submitted.*could not find `cargo`'
    ):
        _submit(fake)
    assert not fake.manifests, 'nothing was submitted'


def test_a_missing_prerequisite_is_named_before_anything_is_fetched() -> None:
    fake = FakeRunCluster(lacking=('cargo',))
    with pytest.raises(RuntimeError, match='lacks cargo'):
        _submit(fake)
    assert not any('cat-file' in c for c, _ in fake.calls)


def test_the_build_runs_in_its_own_errexit_shell_and_checks_the_venv() -> None:
    spec = RunSpec(sha=SHA, repo_url='u', builds=Builds(install='false; true', needs=('cargo',), env_key='k1'))
    script = build_script(spec)
    assert "bash -eo pipefail -c 'uv venv" in script, 'a failing first install line cannot be masked by the next'
    assert '[ -x "$E/bin/python" ]' in script
    assert 'E="$HOME"/ci/envs/k1' in script, 'every env lives under its key'
    assert '"$HOME"/ci/envs/k1.log' in script, 'the build log sits beside the env it builds'
    assert 'git uv cargo' in needs_script(spec)


def test_every_round_runs_as_the_user_whose_home_holds_the_built_tree() -> None:
    """Measured 2026-10-09: built as one user, submitted as another on the same cluster -- no venv there."""
    other = Grant(user='you', hosts=GRANT.hosts, slurm_account='acct-free', partitions=GRANT.partitions)
    mine, theirs = FakeRunCluster(dies=frozenset({'tests/b.py'})), FakeRunCluster()
    machine = Machine(workstation='ws-a', grants=(GRANT, other))
    connect = {GRANT.account: mine, other.account: theirs}

    spec = RunSpec(sha=SHA, repo_url='https://g/r.git', builds=Builds(install='true', env_key='k1'))
    submit_run(spec, machine, lambda g: connect[g.account], cost=COST, policy=POLICY, stamp='t0')
    builder = mine if any('@@@ facts' in c for c, _ in mine.calls) else theirs
    for _ in range(2 + RETRIES):
        if gather_run(SHA, machine, lambda g: connect[g.account], cost=COST, policy=POLICY) is not None:
            break
    bystander = theirs if builder is mine else mine
    assert builder.manifests, 'the rounds ran where the tree was built'
    assert not bystander.manifests, 'no round went to another user on the same cluster'


def test_only_runs_the_ids_the_caller_selected() -> None:
    fake = FakeRunCluster()
    spec = RunSpec(
        sha=SHA, repo_url='u', builds=Builds(install='true', env_key='k1'), only=frozenset({'tests/b.py::t4'})
    )
    submit_run(spec, MACHINE, lambda _g: fake, cost=COST, policy=POLICY, stamp='t0')
    assert [i['ids'] for i in fake.manifests[0]['items']] == [['tests/b.py::t4']]
    assert (
        RunSpec(sha=SHA, repo_url='u', builds=Builds(install='true', env_key='k1'), only=frozenset({'x'})).scope
        == INCREMENTAL
    )
    assert RunSpec(sha=SHA, repo_url='u', builds=Builds(install='true', env_key='k1')).scope == FULL


def test_every_round_adds_its_job_to_the_record() -> None:
    record = _run(FakeRunCluster(dies=frozenset({'tests/b.py'})))
    assert record['job_ids'] == ['4243', '4244'], 'a retry round is part of the same run'


def test_an_empty_collection_refuses_carrying_the_collectors_own_error() -> None:
    """PLANTED, a consumer 2026-10-10: the import error that emptied the collection is in the refusal."""
    said = 'ImportError while loading conftest tests/conftest.py\nE   ModuleNotFoundError: No module named thing\n'
    fake = FakeRunCluster(collected='@@@ time collect=1s\n' + said)
    with pytest.raises(RuntimeError, match='an empty run is not a pass') as refused:
        _submit(fake)
    assert 'ModuleNotFoundError: No module named thing' in str(refused.value)
    assert '[tool.lab_commons.hpc] install' in str(refused.value), 'the refusal names the remedy'
    assert not fake.manifests


def test_a_venv_that_cannot_name_its_env_refuses_the_run() -> None:
    """A run without its env hash cannot be carried as a base (P2); it is refused before any job."""
    fake = FakeRunCluster(env='')
    with pytest.raises(RuntimeError, match='env hash'):
        _submit(fake)
    assert not fake.manifests


def test_the_record_is_named_for_its_sha_part_and_request_and_round_trips_gzipped(tmp_path: Path) -> None:
    record = _run(FakeRunCluster())
    assert record_name(record) == f'run-{SHA}-base-t0.json.gz'
    path = write_record(record, tmp_path / 'runs')
    assert path == tmp_path / 'runs' / record_name(record)
    assert read_record(path) == record


def test_declared_inputs_share_one_env_and_native_build_and_put_the_source_on_pythonpath() -> None:
    builds = Builds(('uv.lock',), ('src',), ('rust',), 'make', 'uv sync', env_key='e1', native_key='n1')
    script = build_script(RunSpec(sha=SHA, repo_url='u', builds=builds))
    assert 'export E="$HOME"/ci/envs/e1' in script
    assert 'export N="$HOME"/ci/native/n1' in script
    assert 'flock 9' in script, 'two runs building one key wait for each other'
    assert f'$HOME/ci/trees/{SHA}/src:$HOME/ci/native/n1:$HOME/ci/bin' in script
    assert '.venv' not in script, 'no per-sha venv when the inputs are declared'


def test_a_commit_off_the_remote_without_a_pack_source_is_refused() -> None:
    with pytest.raises(RuntimeError, match=r'not on https://g/r\.git'):
        submit_run(
            RunSpec(sha=SHA, repo_url='https://g/r.git', builds=Builds(install='true', env_key='k1')),
            Machine(workstation='w', grants=(GRANT,)),
            lambda _g: FakeRunCluster(have=False),
            cost=Cost(),
            policy=Policy(),
        )


def test_env_and_native_builds_share_persistent_caches_and_cargo_is_locked() -> None:
    builds = Builds(('uv.lock',), ('src',), ('rust',), 'make', 'uv sync', env_key='e1', native_key='n1')
    script = build_script(RunSpec(sha=SHA, repo_url='u', builds=builds))
    assert ' UV_CACHE_DIR="$HOME"/ci/uv-cache' in script, 'one uv cache across every env key'
    assert ' UV_LINK_MODE=hardlink' in script, 'an env shares its inodes with the cache: files are a quota'
    assert 'export CARGO_TARGET_DIR="$HOME"/ci/cargo-target/n1\n' in script, "the target is the native key's own"
    assert 'flock 8' in script, 'two runs building one native key take turns on its target'
    other = build_script(RunSpec(sha=SHA, repo_url='u', builds=replace(builds, native_key='n2')))
    assert 'CARGO_TARGET_DIR="$HOME"/ci/cargo-target/n2\n' in other
    assert 'CARGO_TARGET_DIR="$HOME"/ci/cargo-target\n' not in script, 'PLANTED CONTROL: no account-wide target'


def test_a_cargo_target_is_shared_only_by_identical_native_inputs() -> None:
    """Cargo's freshness is mtime-based: a target shared across different sources reuses stale artifacts."""
    assert cargo_target('n1') == cargo_target('n1')
    assert cargo_target('n1') != cargo_target('n2')
    with pytest.raises(ValueError, match='native key'):
        cargo_target('')


def test_prep_steps_are_timed_into_the_tree_log_and_the_record() -> None:
    builds = Builds(('uv.lock',), ('src',), ('rust',), 'make', 'uv sync', env_key='e1', native_key='n1')
    spec = RunSpec(sha=SHA, repo_url='u', builds=builds, collect='tests')
    for script, step in (
        (build_script(spec), 'env'),
        (build_script(spec), 'native'),
        (collect_command(spec), 'collect'),
    ):
        assert f'{TIME} {step}=' in script
        assert PREP_LOG in script
    assert parse_times(f'x\n{TIME} env=12s\n{TIME} collect=3s\nt.py::a\n') == {'env': 12, 'collect': 3}


class _RedCluster(FakeRunCluster):
    """Every ``tests/a.py`` id fails with a reason; the rest pass."""

    def _streams(self) -> str:
        out = []
        for raw in super()._streams().splitlines():
            line = json.loads(raw) if raw.startswith('{') else {}
            if line.get('id', '').startswith('tests/a.py'):
                line = {**line, 'outcome': 'failed', 'why': f'AssertionError: {line["id"]}'}
            out.append(json.dumps(line) if line else raw)
        return '\n'.join(out) + '\n'


def test_the_record_names_why_each_red_failed() -> None:
    """A 3000-red run triages from the record: every failed/error id carries its crash line, nothing else does."""
    record = _run(_RedCluster())
    red = {n for n, o in record['outcomes'].items() if o == 'failed'}
    assert red
    assert record['reasons'] == {n: f'AssertionError: {n}' for n in red}


def test_a_multi_file_item_pays_each_files_overhead_and_its_memory_reads_every_file() -> None:
    """A file's overhead is its own (imports, module fixtures); an item holding two pays both."""
    measured = Measured(
        durations={'a.py::x': 2.0, 'b.py::y': 3.0},
        overheads={'a.py': 7.0, 'b.py': 8.0},
        peaks_mb={'a.py': 100.0, 'b.py': 4096.0},
    )
    seconds, unmeasured = measured.estimate([['a.py::x', 'b.py::y'], ['a.py::x', 'c.py::t']], Cost(seconds=120))
    assert seconds == [7.0 + 8.0 + 2.0 + 3.0, 7.0 + 2.0 + 120.0], 'the overheads add: a 600 s file is not hidden'
    assert unmeasured == ['c.py']
    assert measured.mem_gb([['a.py::x', 'b.py::y']], Cost(mem_gb=1), Policy(safety=1.0)) == 4.0


def test_whole_files_are_packed_into_items_up_to_the_budget() -> None:
    measured = Measured(
        durations={'a.py::x': 10.0, 'a.py::y': 10.0, 'b.py::z': 15.0, 'c.py::t': 50.0, 'd.py::u': 5.0},
        overheads={'a.py': 3.0, 'b.py': 3.0, 'c.py': 3.0, 'd.py': 3.0},
    )
    files = [['a.py::x', 'a.py::y'], ['b.py::z'], ['c.py::t'], ['d.py::u']]
    items = measured.pack(files, Cost(seconds=120), budget=45.0)
    assert items == [['a.py::x', 'a.py::y', 'b.py::z'], ['c.py::t'], ['d.py::u']], (
        'a file is never split; one over budget sits alone; the next does not join it'
    )
    assert measured.pack([['e.py::t'], ['f.py::t']], Cost(seconds=120), budget=45.0) == [['e.py::t'], ['f.py::t']]


def test_a_multi_file_item_shares_its_overhead_and_teaches_its_peak_to_every_file() -> None:
    measured = Measured()
    folded = {'seconds': {'a.py::x': 2.0, 'b.py::y': 3.0}, 'done': {'wall': 12.0, 'peak_mb': 900.0}}
    measured.learn(['a.py::x', 'b.py::y'], folded)
    assert measured.overheads == {'a.py': 3.5, 'b.py': 3.5}, 'the shares sum back to the 7 s measured'
    assert measured.estimate([['a.py::x', 'b.py::y']], Cost())[0] == [12.0], 'the same item is priced at its wall'
    assert measured.peaks_mb == {'a.py': 900.0, 'b.py': 900.0}


# -- an id that dies is priced from its death ------------------------------------------------------------


def test_an_id_killed_mid_run_is_floored_at_the_time_it_was_given_not_its_files_mean() -> None:
    """Measured 2026-10-10: a file's costly id kept dying and was re-priced from its cheap survivors."""
    measured = Measured(durations={'a.py::cheap': 1.0}, overheads={'a.py': 10.0})
    folded = {'outcomes': {'a.py::cheap': 'passed'}, 'seconds': {'a.py::cheap': 1.0}, 'done': None}
    measured.killed(['a.py::cheap', 'a.py::slow', 'a.py::after'], folded, spent=600.0)
    assert measured.floors == {'a.py::slow': 589.0}, 'the interrupted id; the one after it never started'
    seconds, _ = measured.estimate([['a.py::slow', 'a.py::after']], Cost())
    assert seconds == [10.0 + 589.0 + 1.0], 'the slow id at its floor, not the 1 s mean of the survivors'
    measured.learn(['a.py::slow'], {'seconds': {'a.py::slow': 700.0}, 'done': None})
    assert measured.floors == {}, 'once it finishes, its duration is known and the floor goes'
    assert Measured.of(measured.record()).durations['a.py::slow'] == 700.0


def test_a_floor_survives_the_record_and_prices_a_file_with_nothing_else_measured() -> None:
    measured = Measured(floors={'a.py::slow': 900.0})
    again = Measured.of(measured.record())
    assert again.estimate([['a.py::slow']], Cost(seconds=60))[0] == [900.0]


def test_fold_charges_a_killed_item_what_its_shard_wall_had_left() -> None:
    """Items in a shard run back to back: the unclosed one was killed after the wall minus its predecessors."""
    items = [{'ids': ['a.py::x']}, {'ids': ['b.py::fast', 'b.py::slow']}, {'ids': ['c.py::never']}]
    streams = {
        0: json.dumps({'id': 'a.py::x', 'outcome': 'passed', 's': 50.0})
        + '\n'
        + json.dumps({'done': 0, 'wall': 100.0, 'peak_mb': 1.0}),
        1: json.dumps({'id': 'b.py::fast', 'outcome': 'passed', 's': 20.0}),
    }
    measured, outcomes = Measured(), {}
    pending, killed, busy = fold(items, streams, outcomes, measured, {}, shards=[(0, 3)], walls=[1000.0])
    assert not killed
    assert busy == 100.0, 'only the closed item reports its wall'
    assert pending == [['b.py::slow'], ['c.py::never']]
    assert measured.floors == {'b.py::slow': 880.0}, '1000 s wall - 100 s item 0 - 20 s finished'
    assert 'c.py::never' not in measured.floors, 'an item after the kill never started'


def test_a_file_whose_costly_id_dies_is_replanned_with_more_wall_than_it_died_at() -> None:
    """No TIMEOUT state here (the round is OUT_OF_MEMORY), so only the floor can lengthen the retry."""
    record = _run(FakeRunCluster(dies=frozenset({'tests/b.py'}), oom=True))
    _, second = record['rounds']
    assert record['floors'] == {}, 'the retry finished it, so its floor gave way to its duration'
    assert second['minutes'] * 60 >= 60.0, 'the retry is never sized shorter than the 60 s sacct says it died at'


def test_a_timeout_round_asks_the_next_for_twice_the_minutes() -> None:
    record = _run(FakeRunCluster(dies=frozenset({'tests/b.py'})))
    first, second = record['rounds']
    assert second['minutes'] >= 2 * first['minutes']
    assert second['mem_mb'] == first['mem_mb'], 'a timeout is not a memory problem'


def test_a_retry_wall_is_held_to_a_partition_that_allows_it() -> None:
    snap = parse_snapshot(IDLE)

    def plan(min_minutes: float) -> Plan:
        return make_plan(
            4,
            Cost(seconds=60),
            snap,
            cluster=GRANT.cluster(),
            policy=Policy(),
            limits=Limits(),
            min_minutes=min_minutes,
        )

    assert plan(0).partitions == ('shortq', 'defq')
    assert plan(0).minutes < 60
    asked = plan(5 * 60)
    assert asked.minutes == 5 * 60, 'the retry gets the minutes it asked for'
    beyond = plan(3 * 24 * 60)
    assert beyond.minutes == 2 * 24 * 60, "held to the longest ceiling on offer: the free QOS's two days"
    assert beyond.partitions == ('defq',), 'only a partition whose ceiling holds the wall is named'


def test_round_zero_packs_measured_files_into_one_item() -> None:
    history = {
        'durations': {f'tests/{f}.py::t{n}': 1.0 for f, n in (('a', 1), ('a', 2), ('b', 3), ('b', 4), ('b', 5))},
        'overheads': {'tests/a.py': 7.0, 'tests/b.py': 7.0},
    }
    fake = FakeRunCluster()
    _submit(fake, history=history)
    assert [len(i['ids']) for i in fake.manifests[0]['items']] == [5], 'two files, one start-up'


# -- where a run is, and when it stalls ------------------------------------------------------------------


def _queue(minutes: int, partitions: str, *, pending: int = 3, running: int = 1) -> str:
    rows = [f'RUNNING|None|{partitions}|2026-10-10T09:00:00'] * running
    rows += [f'PENDING|Priority|{partitions}|2026-10-10T09:00:00'] * pending
    return f'2026-10-10T{9 + minutes // 60:02d}:{minutes % 60:02d}:00\n' + '\n'.join(rows) + '\n'


def test_the_queue_says_pending_running_why_and_for_how_long() -> None:
    assert parse_queue(_queue(45, 'shortq,defq')) == (3, 1, ('Priority',), ('shortq', 'defq'), 45.0)
    assert parse_queue('') == (0, 0, (), (), 0.0)


def test_where_counts_queued_running_and_done_then_finished() -> None:
    fake = FakeRunCluster()
    _submit(fake)
    fake.queue = _queue(5, 'shortq,defq', pending=0, running=0)
    shards = json.loads(fake.state)['current']['shards']
    progress = where(SHA, MACHINE, lambda _g: fake, policy=POLICY)
    assert (progress.pending, progress.running, progress.done, progress.stall) == (0, 0, shards, '')
    assert _gather(fake) is not None
    assert where(SHA, MACHINE, lambda _g: fake, policy=POLICY).finished


def test_a_pend_past_the_threshold_beside_an_unnamed_idle_partition_names_the_requeue() -> None:
    fake = FakeRunCluster()
    _submit(fake)
    fake.queue = _queue(45, 'shortq')
    progress = where(SHA, MACHINE, lambda _g: fake, policy=POLICY)
    assert progress.pending == 3
    assert f'scontrol update JobId={progress.job_id} Partition=shortq,defq' in progress.stall
    assert 'defq on' in progress.stall


def test_a_stall_on_every_declared_partition_quotes_slurms_reason_not_capacity() -> None:
    fake = FakeRunCluster()
    _submit(fake)
    fake.queue = _queue(45, 'shortq,defq')
    stall = where(SHA, MACHINE, lambda _g: fake, policy=POLICY).stall
    assert 'already names every declared partition' in stall
    assert 'Priority' in stall
    assert 'scontrol' not in stall


def test_a_pend_under_the_threshold_is_no_stall() -> None:
    """Planted control: the same queue 10 minutes in is just a queue."""
    fake = FakeRunCluster()
    _submit(fake)
    fake.queue = _queue(10, 'shortq')
    assert where(SHA, MACHINE, lambda _g: fake, policy=POLICY).stall == ''


# -- gather and gather --wait share one path, on this login node's shell ---------------------------------


def _gather_cli(fake: FakeRunCluster, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[object, list]:

    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'machine' / 'config.toml'))
    monkeypatch.setattr(cli, 'load_grants', lambda: MACHINE)
    monkeypatch.setattr(cli, 'submitter', lambda: lambda _g: fake)  # gather: this login node's shell
    slept: list[float] = []
    monkeypatch.setattr(cli, '_sleep', slept.append)
    _submit(fake)
    return cli, slept


def test_gather_wait_polls_until_the_run_has_its_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:

    fake = FakeRunCluster(active=2)
    fake.queue = _queue(3, 'shortq,defq', pending=2, running=2)
    cli, slept = _gather_cli(fake, tmp_path, monkeypatch)
    assert cli.main(['run', 'gather', '--sha', SHA, '--wait', '-o', str(tmp_path / 'out')]) == 0
    assert 'queued 2 for 3 min (Priority) on shortq,defq; running 2 of' in ''.join(capsys.readouterr())
    assert len(slept) == 2, 'two polls saw it running, the third gathered it'
    assert len(list((tmp_path / 'out').iterdir())) == 1


def test_gather_without_wait_says_where_the_run_is_and_exits_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeRunCluster(active=1)
    fake.queue = _queue(3, 'shortq,defq', pending=1, running=0)
    cli, slept = _gather_cli(fake, tmp_path, monkeypatch)
    assert cli.main(['run', 'gather', '--sha', SHA, '-o', str(tmp_path / 'out')]) == PENDING
    assert 'queued 1 for 3 min' in ''.join(capsys.readouterr())
    assert slept == []
    assert cli.main(['run', 'gather', '--sha', SHA, '--wait', '-o', str(tmp_path / 'out')]) == 0


def test_a_job_id_slurm_has_forgotten_is_a_finished_run_for_gather(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PLANTED CONTROL, 2026-10-11: squeue forgets a finished job and refuses its id; that is DONE, not a crash."""
    fake = FakeRunCluster(active=1)
    fake.queue = RuntimeError('ssh exited 1: slurm_load_jobs error: Invalid job id specified')
    cli, _ = _gather_cli(fake, tmp_path, monkeypatch)
    assert cli.main(['run', 'gather', '--sha', SHA, '--wait', '-o', str(tmp_path / 'out')]) == 0
    assert len(list((tmp_path / 'out').iterdir())) == 1


def test_any_other_squeue_failure_still_raises() -> None:
    """The other half of the control: only the forgotten-id refusal reads as finished."""
    fake = FakeRunCluster()
    _submit(fake)
    fake.queue = RuntimeError('ssh exited 1: slurm_load_jobs error: Unable to contact slurm controller')
    with pytest.raises(RuntimeError, match='Unable to contact'):
        where(SHA, MACHINE, lambda _g: fake, policy=POLICY)


def test_a_red_record_makes_gather_exit_nonzero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Planted control beside the green gather: same path, failing ids, exit 1."""
    cli, _ = _gather_cli(_RedCluster(), tmp_path, monkeypatch)
    assert cli.main(['run', 'gather', '--sha', SHA, '-o', str(tmp_path / 'out')]) == 1


# -- efficiency: measured phases, carried measurements, balanced shards (census 2026-10-11) ----------------


def test_a_kill_is_charged_the_seconds_slurm_says_the_shard_ran_not_its_planned_wall() -> None:
    """Measured 2026-10-11: a shard killed after 7 s was charged its 216-min plan; one id got a 12960 s floor."""
    items = [{'ids': ['a.py::dies', 'a.py::after']}]
    measured = Measured()
    fold(items, {}, {}, measured, {}, shards=[(0, 1)], walls=[7.0])
    assert measured.floors == {'a.py::dies': 7.0}
    planted = Measured()
    fold(items, {}, {}, planted, {}, shards=[(0, 1)], walls=[12960.0])
    assert planted.floors == {'a.py::dies': 12960.0}, 'PLANTED CONTROL: the wall given is the wall charged'


def test_every_round_keeps_slurms_clock_and_the_record_breaks_its_wall_down() -> None:
    record = _run(FakeRunCluster(dies=frozenset({'tests/b.py'})))
    first, second = (r['clock'] for r in record['rounds'])
    assert first['queue_s'] == 60.0, 'median start minus submit'
    assert first['core_s'] == sum(60 + 60 * i for i in range(9))
    assert first['tail_s'] == 540.0 - 300.0, 'the longest task minus the median'
    assert record['prep']['ship'] >= 0
    breakdown = phases(record)
    assert breakdown['retry_s'] == second['wall_s'] + (second['submit'] - first['end'])
    assert breakdown['utilisation'] == pytest.approx(
        (first['busy_s'] + second['busy_s']) / (first['core_s'] + second['core_s']), rel=1e-12, abs=0.0
    )
    assert describe(breakdown).startswith('phases: wall ')
    assert describe(phases({'prep': {'env': 60}})) == 'phases: prep 1.0 min, no round finished yet'


def test_lpt_refills_the_same_shards_so_the_heavy_items_are_not_neighbours() -> None:
    seconds = [100.0, 90.0, 80.0, 1.0, 1.0, 1.0]
    order, shards = balance(seconds, ((0, 3), (3, 6)))
    loads = [sum(seconds[order[i]] for i in range(a, b)) for a, b in shards]
    assert len(shards) == 2
    assert max(loads) == 170.0, 'LPT: 100 with the three 1 s items, 90 + 80 beside it'
    assert sorted(order) == list(range(6)), 'a permutation: no item lost or doubled'
    balanced = [10.0, 10.0, 10.0, 10.0]
    assert balance(balanced, ((0, 2), (2, 4))) == ([0, 1, 2, 3], ((0, 2), (2, 4))), (
        'PLANTED CONTROL: a refill no faster than the input keeps the input'
    )


def test_a_gathered_record_plans_the_next_submit_of_its_repo_and_no_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Measured 2026-10-11: --history was optional, nobody passed it, and 4441 of 4441 files planned blind."""
    fake = FakeRunCluster()
    cli, _ = _gather_cli(fake, tmp_path, monkeypatch)
    assert cli.main(['run', 'gather', '--sha', SHA, '-o', str(tmp_path / 'out')]) == 0
    assert learned.learned('https://g/r.git')['durations'], 'the record taught its repository'
    assert learned.learned('https://g/other.git') == {}, 'PLANTED CONTROL: another repository learned nothing'
    state = _submit(FakeRunCluster(), history=learned.learned('https://g/r.git'))
    assert state['rounds'][0]['unmeasured'] == []
    assert _submit(FakeRunCluster())['rounds'][0]['unmeasured'] == ['tests/a.py', 'tests/b.py']


def test_a_runs_file_cost_is_one_count_of_its_tree_run_and_env_and_unread_is_unmeasured() -> None:
    """The home's FILE quota is a supply (user ruling 2026-10-14): a run's file cost is learned like its memory."""
    asked: list[str] = []

    def home(command: str, _stdin: object) -> str:
        asked.append(command)
        return '12345\n'

    state = {'sha': SHA, 'builds': {'env': 'e1', 'native': 'n1'}}
    assert files_made(home, state) == 12345.0
    assert asked == [f'find "$HOME"/ci/trees/{SHA} "$HOME"/ci/runs/{SHA} "$HOME"/ci/envs/e1 -xdev 2>/dev/null | wc -l']
    assert files_made(lambda *_a: '', state) == 0.0, 'PLANTED CONTROL: unread is 0, the prior prices it'


def test_history_is_no_flag_and_its_spelling_is_refused_with_the_remedy(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(['run', 'submit', '--sha', SHA, '--repo-url', 'u', '--scope', 'full', '--history', 'r.json.gz'])
    assert 'lab_commons.compute.learned' in capsys.readouterr().err


def test_a_workstation_never_submits_or_gathers_over_ssh(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """PLANTED CONTROL: the same step on a box with sbatch reaches the local shell (and fails there, not here)."""
    monkeypatch.setattr(cli, 'load_grants', lambda: MACHINE)
    monkeypatch.setattr(cluster_module.shutil, 'which', lambda _name: None)
    assert cli.main(['run', 'gather', '--sha', SHA, '-o', 'out']) == 2
    assert 'no sbatch' in capsys.readouterr().err
    reached: list[str] = []

    def shell(command: str, _stdin: str | None = None, **_kw: object) -> str:
        reached.append(command)
        msg = 'no state here'
        raise RuntimeError(msg)

    monkeypatch.setattr(cluster_module.shutil, 'which', lambda _name: '/usr/bin/sbatch')
    monkeypatch.setattr(cluster_module, 'local_runner', shell)
    assert cli.main(['run', 'gather', '--sha', SHA, '-o', 'out']) == 1, 'it ran here, and here had no run'
    assert reached, 'on a cluster the step runs in this login node shell'


def test_every_item_carries_the_timeout_its_scope_declares() -> None:
    timeouts = {'incremental': 300, 'full': 3000}
    builds = Builds(install='true', env_key='k1', timeout_s=timeouts)
    full, incremental = FakeRunCluster(), FakeRunCluster()
    submit_run(RunSpec(sha=SHA, repo_url='u', builds=builds), MACHINE, lambda _g: full, cost=COST, policy=POLICY)
    narrowed = RunSpec(sha=SHA, repo_url='u', builds=builds, only=frozenset({'tests/b.py::t4'}))
    submit_run(narrowed, MACHINE, lambda _g: incremental, cost=COST, policy=POLICY)
    assert {i['timeout_s'] for i in full.manifests[0]['items']} == {3000}
    assert {i['timeout_s'] for i in incremental.manifests[0]['items']} == {300}


def test_the_run_state_names_the_build_directories_it_runs_in() -> None:
    """Retention ties ``~/ci/envs/<key>`` and ``~/ci/native/<key>`` to a run only through these keys."""
    builds = Builds(install='true', env_key='k1', native_key='n1')
    state = submit_run(
        RunSpec(sha=SHA, repo_url='u', builds=builds), MACHINE, lambda _g: FakeRunCluster(), cost=COST, policy=POLICY
    )
    assert state['builds'] == {'env': 'k1', 'native': 'n1'}


class _AdaRounds(FakeRunCluster):
    """sacct answers PER JOB ID, as Ada did for 18f128d on 2026-10-12: r0 and r1 OUT_OF_MEMORY, r2 COMPLETED."""

    STATES: ClassVar[dict[str, str]] = {'4243': 'OUT_OF_MEMORY', '4244': 'OUT_OF_MEMORY', '4245': 'COMPLETED'}

    def __call__(self, command: str, stdin: str | None = None) -> str:
        if command.startswith('sacct '):
            self.calls.append((command, stdin))
            job = command.split(' -j ')[1].split(maxsplit=1)[0]
            row = f'{self.STATES[job]}|2026-10-12T16:25:27|2026-10-12T16:25:39|2026-10-12T16:26:08|29|1'
            return ''.join(f'{job}_{i}|{row}\n' for i in range(9))
        return super().__call__(command, stdin)


def test_two_out_of_memory_rounds_then_a_completed_one_is_gathered_from_the_latest_job() -> None:
    """THE ADA RUN OF 2026-10-12: the record comes from r2, and only the CURRENT round's job is ever asked about.

    sacct, never squeue, decides a round: a job squeue has forgotten is finished, not running.
    """
    fake = _AdaRounds(dies=frozenset({'tests/b.py'}), kills=2)
    record = _run(fake)
    assert record['job_ids'] == ['4243', '4244', '4245']
    first, second, third = record['rounds']
    assert (second['mem_mb'], third['mem_mb']) == (2 * first['mem_mb'], 4 * first['mem_mb'])
    assert all(record['outcomes'][f'tests/b.py::t{n}'] == 'passed' for n in (3, 4, 5)), 'r2 results gathered'
    asked = [c.split(' -j ')[1].split()[0] for c, _ in fake.calls if c.startswith('sacct ')]
    assert asked == ['4243', '4244', '4245'], 'each gather asks sacct about the current round only'
    assert not any(' -j ' in c for c, _ in fake.calls if 'squeue' in c), 'squeue decides no job in a gather'


def test_build_prepares_the_tree_and_its_env_and_submits_nothing() -> None:
    """``run build`` is ``run submit`` up to the facts, so a job-mode entry can run in the built tree (2026-10-13)."""
    fake = FakeRunCluster()
    spec = RunSpec(sha=SHA, repo_url='u', builds=Builds(install='true', env_key='k1'))
    built = build_run(spec, fake, 'login.example')
    assert built['env'] == fake.env
    assert 'env' in built['prep'], 'the prep wall times come back with the facts'
    assert not fake.manifests, 'nothing was submitted'
    assert not fake.state, 'no run state: a build is not a run'
    assert not any('--collect-only' in c or 'lab_ci_collect.py --cache' in c for c, _ in fake.calls), 'no collection'


def _build_cli(monkeypatch: pytest.MonkeyPatch, fake: FakeRunCluster) -> None:
    monkeypatch.setattr(cli, 'load_grants', lambda: MACHINE)
    monkeypatch.setattr(cli, 'submitter', lambda: lambda _g: fake)
    monkeypatch.setattr(cli, 'builds_at', lambda *_a, **_k: Builds(install='true', env_key='k1'))


def test_run_build_names_the_workdir_and_setup_a_job_file_reuses(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeRunCluster()
    _build_cli(monkeypatch, fake)
    assert cli.main(['run', 'build', '--sha', SHA, '--repo-url', 'u']) == 0
    out = capsys.readouterr().out
    assert f'workdir = "~/ci/trees/{SHA}"' in out
    assert 'setup = [". .lab-ci/env.sh"]' in out
    assert not fake.manifests


def test_a_failed_run_build_is_inconclusive(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _build_cli(monkeypatch, FakeRunCluster(build_fails=True))
    assert cli.main(['run', 'build', '--sha', SHA, '--repo-url', 'u']) == 3
    assert 'could not find `cargo`' in capsys.readouterr().err


# -- carried outcomes (lab_commons.dev.forgecarry) ------------------------------------------------------

A_SHA = 'a' * 40


def test_carried_ids_are_never_submitted_and_the_record_names_their_origin() -> None:
    fake, envs = FakeRunCluster(), []

    def carry(env: str) -> dict[str, tuple[str, str, str]]:
        envs.append(env)
        return {
            'tests/a.py::t1': ('passed', A_SHA, A_SHA),
            'tests/a.py::t2': ('failed', A_SHA, A_SHA),
            'x::y': ('passed', A_SHA, A_SHA),
        }

    record = _run(fake, carry=carry)
    assert envs == ['e0ffee0123456789'], 'the carry is asked for the env the build reported'
    submitted = {node for item in fake.manifests[0]['items'] for node in item['ids']}
    assert submitted == {'tests/b.py::t3', 'tests/b.py::t4', 'tests/b.py::t5'}
    assert record['carried'] == {'tests/a.py::t1': A_SHA, 'tests/a.py::t2': A_SHA}, 'an id not collected is not taken'
    assert record['outcomes']['tests/a.py::t2'] == 'failed', 'a carried red stays red'
    assert record['scope'] == FULL, 'a carried run is still the full suite'
    part = part_of(record)
    assert (part.ran, part.kept, part.result) == (3, {A_SHA[:12]: 2}, 'FAIL'), 'carried is never counted as run'
    assert part.description().endswith(f'kept={A_SHA[:12]}:2')
    assert parts_of([Status(f'tests/{part.platform}', 'failure', part.description(), '')])[0][part.platform] == part


def test_a_run_whose_every_id_is_carried_writes_its_record_without_a_job() -> None:
    fake = FakeRunCluster()
    ids = ['tests/a.py::t1', 'tests/a.py::t2', 'tests/b.py::t3', 'tests/b.py::t4', 'tests/b.py::t5']
    state = _submit(fake, carry=lambda _env: dict.fromkeys(ids, ('passed', A_SHA, A_SHA)))
    assert not fake.manifests, 'nothing was submitted'
    assert state['rounds'] == []
    assert _gather(fake) == state['record']
    assert part_of(state['record']).ran == 0


def test_a_superseded_run_holds_its_folded_rounds_and_every_id_its_last_round_streamed() -> None:
    fake = FakeRunCluster(dies=frozenset({'tests/b.py'}), kills=5)
    state = _submit(fake)
    held = held_outcomes(json.loads(fake.state), fake)
    assert held == {
        'tests/a.py::t1': ('passed', SHA),
        'tests/a.py::t2': ('passed', SHA),
        'tests/b.py::t3': ('passed', SHA),
    }, 'the killed item kept what it streamed; the handed id is not an outcome'
    assert state['sha'] == SHA
    assert run_shas(MACHINE, {GRANT.account: lambda _c, _s: f'/h/ci/runs/{SHA}/state.json\n'}) == [SHA]
