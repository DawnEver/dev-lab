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
from pathlib import Path
from types import ModuleType

import pytest

from lab_commons.config import CONFIG_ENV
from lab_commons.hpc import __main__ as cli
from lab_commons.hpc import outstanding
from lab_commons.hpc.builds import Builds
from lab_commons.hpc.cluster import Unreachable
from lab_commons.hpc.config import Cost, Limits, Policy
from lab_commons.hpc.grants import Grant, Machine
from lab_commons.hpc.measured import Measured
from lab_commons.hpc.plan import make_plan
from lab_commons.hpc.progress import parse_queue, where
from lab_commons.hpc.pytest_item import canonical, outcome_of, read_stream
from lab_commons.hpc.records import read_record, read_streams, record_name, write_record
from lab_commons.hpc.run import RETRIES, gather_run, submit_run
from lab_commons.hpc.shell import (
    BUILD_LOG,
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
GRANT = Grant(user='me', hosts=('login.example',), slurm_account='acct-free', cpus=64, partitions=('shortq', 'defq'))
SHA = 'a' * 40
SOURCE = Path(__file__).parents[1] / 'src' / 'lab_commons' / 'hpc' / 'pytest_item.py'


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
    assert outcomes[next(n for n in ids if n.endswith('test_setup_error'))] == 'error'
    assert sum(o == 'passed' for o in outcomes.values()) == 9
    assert result['done']['done'] == 1
    assert result['done']['wall'] > 0


def test_a_pytest_that_dies_mid_item_closes_the_stream_and_names_only_the_rest_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _item_runner(tmp_path, monkeypatch)
    body = 'import os\n\ndef test_a():\n    pass\n\ndef test_b():\n    os._exit(3)\n\ndef test_c():\n    pass\n'
    ids = _tree(tmp_path, body)
    result = runner.run({'ids': ids, 'stream': '.lab-ci/t/0.jsonl'})
    assert result['outcomes'] == {ids[0]: 'passed'}
    assert result['done']['done'] == 3, 'it closed, so b and c are missing -- re-running would crash again'


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
    ) -> None:
        """*have*: the cache holds the commit; *oom*: round 0 is OUT_OF_MEMORY; *active*: sacct polls RUNNING."""
        self.have, self.dies, self.kills, self.oom = have, dies, kills, oom
        self.build_fails, self.lacking, self.active = build_fails, lacking, active
        self.env = env
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
            return self.queue
        if 'state.json' in command:
            return self.state
        if command.startswith('for c in'):
            return ''.join(f'@@@ missing {c}\n' for c in self.lacking)
        if command.startswith('echo "@@@ nodes"'):
            return IDLE + '@@@ shared\n8 lc:ws=other\n'
        if 'cat-file' in command:
            return 'have\n' if self.have else 'missing\n'
        if '@@@ facts' in command and self.build_fails:
            return '@@@ build-failed exit 101\nerror: could not find `cargo`\n'
        if '@@@ facts' in command:
            return f'@@@ time env=12s\n@@@ facts\nplatform=linux-x86_64/glibc2.28\npython=3.13.1\nenv={self.env}\n'
        if '--collect-only' in command or 'lab_ci_collect.py --cache' in command:
            if '(win)' in command:
                return 'tests/w.py::t\n'
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
            state = 'OUT_OF_MEMORY' if self.oom and len(self.manifests) == 1 else 'TIMEOUT'
            return '\n'.join(f'1_{i}|{state if i == 0 else "COMPLETED"}' for i in range(9)) + '\n'
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
            out += [json.dumps({'id': n, 'outcome': 'passed', 's': 1.0}) for n in ran]
            if not killed:
                out.append(json.dumps({'done': 0, 'wall': 5.0 + len(ran), 'peak_mb': 2048.0}))
        return '\n'.join(out) + '\n'


MACHINE = Machine(workstation='ws-a', grants=(GRANT,))
COST, POLICY = Cost(seconds=600), Policy(shard_minutes_min=1, shard_minutes_max=15)


def _submit(fake: FakeRunCluster, **kw: object) -> str:
    spec = RunSpec(sha=SHA, repo_url='https://g/r.git', install='true', table={'win': ('windows',)})
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
    assert record['prep'] == {'env': 12, 'collect': 3}, 'prep time is measurable from the record'
    assert record['handed'] == {'tests/w.py::t': ['windows']}, 'handed names the platforms that CAN run it'
    assert (record['platform'], record['system'], record['cluster'], record['python']) == (
        'linux',
        'linux-x86_64/glibc2.28',
        'login.example',
        '3.13.1',
    ), 'platform is the part it is; system is the box it ran on'
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
    spec = RunSpec(sha=SHA, repo_url='u', install='false; true', needs=('cargo',))
    script = build_script(spec)
    assert "bash -eo pipefail -c 'uv venv" in script, 'a failing first install line cannot be masked by the next'
    assert '[ -x "$E/bin/python" ]' in script
    assert f'E="$HOME"/ci/trees/{SHA}/.venv' in script, 'undeclared: the tree keeps its own venv'
    assert BUILD_LOG in script
    assert 'git uv cargo' in needs_script(spec)


def test_every_round_runs_as_the_user_whose_home_holds_the_built_tree() -> None:
    """Measured 2026-10-09: built as one user, submitted as another on the same cluster -- no venv there."""
    other = Grant(user='you', hosts=GRANT.hosts, slurm_account='acct-free', cpus=640, partitions=GRANT.partitions)
    mine, theirs = FakeRunCluster(dies=frozenset({'tests/b.py'})), FakeRunCluster()
    machine = Machine(workstation='ws-a', grants=(GRANT, other))
    connect = {GRANT.account: mine, other.account: theirs}

    spec = RunSpec(sha=SHA, repo_url='https://g/r.git', install='true')
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
    spec = RunSpec(sha=SHA, repo_url='u', install='true', only=frozenset({'tests/b.py::t4'}))
    submit_run(spec, MACHINE, lambda _g: fake, cost=COST, policy=POLICY, stamp='t0')
    assert [i['ids'] for i in fake.manifests[0]['items']] == [['tests/b.py::t4']]
    assert RunSpec(sha=SHA, repo_url='u', install='true', only=frozenset({'x'})).scope == INCREMENTAL
    assert RunSpec(sha=SHA, repo_url='u', install='true').scope == FULL


def test_every_round_adds_its_job_to_the_record() -> None:
    record = _run(FakeRunCluster(dies=frozenset({'tests/b.py'})))
    assert record['job_ids'] == ['4243', '4244'], 'a retry round is part of the same run'


def test_a_venv_that_cannot_name_its_env_refuses_the_run() -> None:
    """A run without its env hash cannot be carried as a base (P2); it is refused before any job."""
    fake = FakeRunCluster(env='')
    with pytest.raises(RuntimeError, match='env hash'):
        _submit(fake)
    assert not fake.manifests


def test_the_record_is_named_for_its_sha_platform_and_request_and_round_trips_gzipped(tmp_path: Path) -> None:
    record = _run(FakeRunCluster())
    assert record_name(record) == f'run-{SHA}-linux-t0.json.gz'
    path = write_record(record, tmp_path / 'runs')
    assert path == tmp_path / 'runs' / record_name(record)
    assert read_record(path) == record


def test_declared_inputs_share_one_env_and_native_build_and_put_the_source_on_pythonpath() -> None:
    builds = Builds(('uv.lock',), ('src',), ('rust',), 'make', env_key='e1', native_key='n1')
    script = build_script(RunSpec(sha=SHA, repo_url='u', install='uv sync', builds=builds))
    assert 'export E="$HOME"/ci/envs/e1' in script
    assert 'export N="$HOME"/ci/native/n1' in script
    assert 'flock 9' in script, 'two runs building one key wait for each other'
    assert f'$HOME/ci/trees/{SHA}/src:$HOME/ci/native/n1:$HOME/ci/bin' in script
    assert '.venv' not in script, 'no per-sha venv when the inputs are declared'


def test_a_commit_off_the_remote_without_a_pack_source_is_refused() -> None:
    with pytest.raises(RuntimeError, match=r'not on https://g/r\.git'):
        submit_run(
            RunSpec(sha=SHA, repo_url='https://g/r.git', install='true'),
            Machine(workstation='w', grants=(GRANT,)),
            lambda _g: FakeRunCluster(have=False),
            cost=Cost(),
            policy=Policy(),
        )


def test_env_and_native_builds_share_persistent_caches_and_cargo_is_locked() -> None:
    builds = Builds(('uv.lock',), ('src',), ('rust',), 'make', env_key='e1', native_key='n1')
    script = build_script(RunSpec(sha=SHA, repo_url='u', install='uv sync', builds=builds))
    assert ' UV_CACHE_DIR="$HOME"/ci/uv-cache' in script, 'one uv cache across every env key'
    assert 'export CARGO_TARGET_DIR="$HOME"/ci/cargo-target' in script, 'a rust edit compiles only changed crates'
    assert 'flock 8' in script, 'two native keys building at once take turns on the shared target'


def test_prep_steps_are_timed_into_the_tree_log_and_the_record() -> None:
    builds = Builds(('uv.lock',), ('src',), ('rust',), 'make', env_key='e1', native_key='n1')
    spec = RunSpec(sha=SHA, repo_url='u', install='uv sync', builds=builds, collect='tests')
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


def test_a_multi_file_item_pays_one_start_up_and_its_memory_reads_every_file() -> None:
    """4316 one-file items paid 9.5 h of start-up for 6.0 h of tests (measured 2026-10-10)."""
    measured = Measured(
        durations={'a.py::x': 2.0, 'b.py::y': 3.0},
        overheads={'a.py': 7.0, 'b.py': 8.0},
        peaks_mb={'a.py': 100.0, 'b.py': 4096.0},
    )
    seconds, unmeasured = measured.estimate([['a.py::x', 'b.py::y'], ['a.py::x', 'c.py::t']], Cost(seconds=120))
    assert seconds == [8.0 + 2.0 + 3.0, 7.0 + 2.0 + 120.0], 'one start-up: the worst of the files'
    assert unmeasured == ['c.py']
    assert measured.mem_gb([['a.py::x', 'b.py::y']], Cost(mem_gb=1), Policy(safety=1.0)) == 4.0


def test_whole_files_are_packed_into_items_up_to_the_budget() -> None:
    measured = Measured(
        durations={'a.py::x': 10.0, 'a.py::y': 10.0, 'b.py::z': 15.0, 'c.py::t': 50.0, 'd.py::u': 5.0},
        overheads={'a.py': 7.0, 'b.py': 7.0, 'c.py': 7.0, 'd.py': 7.0},
    )
    files = [['a.py::x', 'a.py::y'], ['b.py::z'], ['c.py::t'], ['d.py::u']]
    items = measured.pack(files, Cost(seconds=120), budget=45.0)
    assert items == [['a.py::x', 'a.py::y', 'b.py::z'], ['c.py::t'], ['d.py::u']], (
        'a file is never split; one over budget sits alone; the next does not join it'
    )
    assert measured.pack([['e.py::t'], ['f.py::t']], Cost(seconds=120), budget=45.0) == [['e.py::t'], ['f.py::t']]


def test_a_multi_file_item_teaches_its_overhead_and_peak_to_every_file() -> None:
    measured = Measured()
    folded = {'seconds': {'a.py::x': 2.0, 'b.py::y': 3.0}, 'done': {'wall': 12.0, 'peak_mb': 900.0}}
    measured.learn(['a.py::x', 'b.py::y'], folded)
    assert measured.overheads == {'a.py': 7.0, 'b.py': 7.0}
    assert measured.peaks_mb == {'a.py': 900.0, 'b.py': 900.0}


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


# -- one list of outstanding runs; watch and gather --wait share one path --------------------------------


def _outstanding_cli(fake: FakeRunCluster, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[object, list]:

    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'machine' / 'config.toml'))
    monkeypatch.setattr(cli, 'load_grants', lambda: MACHINE)
    monkeypatch.setattr(cli, 'runner_for', lambda _g, *_a: fake)
    slept: list[float] = []
    monkeypatch.setattr(cli, '_sleep', slept.append)
    state = _submit(fake)
    outstanding.add(SHA, repo='https://g/r.git', grant=state['rounds'][0]['grant'], job_ids=['4243'])
    return cli, slept


def test_watch_blocks_until_every_outstanding_run_has_its_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:

    fake = FakeRunCluster(active=2)
    fake.queue = _queue(3, 'shortq,defq', pending=2, running=2)
    cli, slept = _outstanding_cli(fake, tmp_path, monkeypatch)
    assert cli.main(['run', 'status']) == 0
    assert 'queued 2 for 3 min (Priority) on shortq,defq; running 2 of' in ''.join(capsys.readouterr())
    assert cli.main(['run', 'watch', '-o', str(tmp_path / 'out')]) == 0
    assert len(slept) == 2, 'two polls saw it running, the third gathered it'
    assert len(list((tmp_path / 'out').iterdir())) == 1
    assert outstanding.outstanding() == []
    assert cli.main(['run', 'watch', '-o', str(tmp_path / 'out')]) == 0, 'nothing outstanding is nothing to wait for'


def test_gather_without_wait_says_where_the_run_is_and_exits_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeRunCluster(active=1)
    fake.queue = _queue(3, 'shortq,defq', pending=1, running=0)
    cli, slept = _outstanding_cli(fake, tmp_path, monkeypatch)
    assert cli.main(['run', 'gather', '--sha', SHA, '-o', str(tmp_path / 'out')]) == PENDING
    assert 'queued 1 for 3 min' in ''.join(capsys.readouterr())
    assert slept == []
    assert cli.main(['run', 'gather', '--sha', SHA, '--wait', '-o', str(tmp_path / 'out')]) == 0


def test_a_red_record_makes_watch_exit_nonzero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Planted control beside the green watch: same path, failing ids, exit 1."""
    cli, _ = _outstanding_cli(_RedCluster(), tmp_path, monkeypatch)
    assert cli.main(['run', 'watch', '-o', str(tmp_path / 'out')]) == 1
