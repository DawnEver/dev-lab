"""``lab_commons.hpc`` grants, shared-account allocation and the remote run -- against the recorded cluster.

Usage per session is never stored: it is read back from the ``--comment`` tag every job carries, so
these tests feed the probe's ``@@@ shared`` section the way ``squeue -r -o "%C|%m|%D|%k|%j"`` prints it.
"""

from __future__ import annotations

import tomllib
from dataclasses import replace
from pathlib import Path

import pytest
from lab_commons.config import CONFIG_ENV
from lab_commons.hpc import __main__ as cli
from lab_commons.hpc import cluster as cluster_module
from lab_commons.hpc.builds import Builds
from lab_commons.hpc.cluster import Unreachable, failover_runner, render_script
from lab_commons.hpc.config import Config, Cost, JobSpec, Limits, Policy
from lab_commons.hpc.grants import Grant, Machine, Session, load_grants
from lab_commons.hpc.needsets import Vocabulary
from lab_commons.hpc.plan import allocate, headroom, make_plan
from lab_commons.hpc.shell import (
    RunSpec,
    build_script,
    collect_command,
    fetch_script,
    group_items,
    parse_collection_errors,
    parse_ids,
)
from lab_commons.hpc.slurm import PROBE_COMMAND, Held, parse_snapshot, parse_usage, probe_command

FIXTURE = (Path(__file__).parent / '_hpc_fixtures' / 'cluster-2026-10-08.txt').read_text(encoding='utf-8')
IDLE = FIXTURE.split('@@@ running')[0] + '@@@ running\n'
GRANT = Grant(user='me', hosts=('login.example',), slurm_account='acct-free', partitions=('shortq', 'defq'))
SHA = 'a' * 40
WIDE = Session(name='ws-a', tasks=1000, cpus=10000, mem_gb=100000)


def _snap(shared: str = '', running: str = '') -> object:
    """*shared* is ``<cpus> <comment>`` per task, each written as one 1 GB one-node ``squeue -r`` row."""
    tasks = (line.partition(' ') for line in shared.splitlines())
    rows = ''.join(f'{cpus}|1G|1|{comment}\n' for cpus, _, comment in tasks)
    return parse_snapshot(IDLE + running + '@@@ shared\n' + rows, 'acct-free')


# -- the grants table -------------------------------------------------------------------------------------


def _table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    path = tmp_path / 'config.toml'
    path.write_text(text, encoding='utf-8')
    monkeypatch.setenv(CONFIG_ENV, str(path))


def test_a_machine_holds_several_grants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _table(
        tmp_path,
        monkeypatch,
        """
[hpc]
[[hpc.grant]]
user = "me"
hosts = ["login2", "login1"]
slurm_account = "acct-free"
partitions = ["shortq"]
[[hpc.grant]]
user = "me"
hosts = ["other"]
slurm_account = "x"
priority = 2
""",
    )
    monkeypatch.setenv('LC_HPC_SESSION', 'ws-a')
    machine = load_grants()
    assert machine.session == Session(name='ws-a'), 'no machine file holds a share: it is derived'
    assert machine.comment == 'lc:session=ws-a'
    assert [g.account for g in machine.grants] == [('me', 'acct-free'), ('me', 'x')]
    assert machine.grants[0].targets == ('me@login2', 'me@login1'), 'hosts keep their order'
    assert machine.grants[0].name == 'me@login2 (acct-free)'
    assert machine.grants[0].cluster().partitions == ('shortq',)
    assert machine.grants[1].priority == 2
    assert not machine.grants[0].same_cluster(machine.grants[1])


def _grant(**extra: object) -> str:
    keys = {'hosts': '["h"]', **extra}
    return '[[grant]]\nuser = "u"\nslurm_account = "s"\n' + ''.join(f'{k} = {v}\n' for k, v in keys.items())


@pytest.mark.parametrize(
    ('table', 'match'),
    [
        ({}, r'no \[hpc\] table'),
        (_grant() + '[[grant]]\nuser = "u"\nhosts = ["g"]\nslurm_account = "s"\n', 'granted twice'),
        (_grant(cpus='64'), r'\[\[hpc\.grant\]\] cpus is retired.*admission fits'),
        (_grant(key='"x"'), 'unknown keys'),
        (_grant(account='"u@h"'), 'unknown keys'),
        (_grant(hosts='[]'), 'at least one login host'),
        ({'grant': []}, r'no \[\[hpc\.grant\]\]'),
    ],
)
def test_a_bad_grants_table_is_refused_by_name(table: str | dict, match: str) -> None:
    raw = table if isinstance(table, dict) else tomllib.loads(table)
    with pytest.raises(ValueError, match=match):
        load_grants(raw)


def test_no_machine_file_refuses_by_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'absent.toml'))
    with pytest.raises(ValueError, match=r'absent\.toml \[hpc\]: no \[hpc\] table'):
        load_grants()


# -- login-host failover ---------------------------------------------------------------------------------


class _Host:
    def __init__(self, target: str, *, up: bool) -> None:
        self.target, self.up, self.commands = target, up, []

    def __call__(self, command: str, stdin: str | None = None) -> str:
        self.commands.append(command)
        if not self.up:
            msg = f'ssh could not reach {self.target}'
            raise Unreachable(msg)
        return f'{self.target}:{command}'


def test_an_unreachable_first_host_fails_over_and_the_second_stays_chosen() -> None:
    down, up = _Host('me@h1', up=False), _Host('me@h2', up=True)
    run = failover_runner([(down.target, down), (up.target, up)])
    assert run('hostname', None) == 'me@h2:hostname'
    assert run('squeue', None) == 'me@h2:squeue'
    assert down.commands == ['hostname'], 'a host that did not answer is not asked again'


def test_no_host_answering_names_every_host() -> None:
    run = failover_runner([('me@h1', _Host('me@h1', up=False)), ('me@h2', _Host('me@h2', up=False))])
    with pytest.raises(Unreachable, match=r'me@h1.*me@h2'):
        run('true', None)


def test_a_failing_command_is_not_a_failover() -> None:
    def broken(_command: str, _stdin: str | None = None) -> str:
        msg = 'ssh exited 1: sbatch: error'
        raise RuntimeError(msg)

    second = _Host('me@h2', up=True)
    run = failover_runner([('me@h1', broken), ('me@h2', second)])
    with pytest.raises(RuntimeError, match='sbatch'):
        run('sbatch x', None)
    assert second.commands == []


def test_runner_for_tries_the_grants_targets_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def fake(argv: list[str], _stdin: object = None, _timeout: float = 0) -> str:
        seen.append(argv)
        if argv[-2] == 'me@h1':
            msg = 'ssh could not reach me@h1'
            raise Unreachable(msg)
        return 'ok'

    monkeypatch.setattr(cluster_module, '_completed', fake)
    grant = Grant(user='me', hosts=('h1', 'h2'), slurm_account='a')
    assert cluster_module.runner_for(grant)('true', None) == 'ok'
    assert [a[-2] for a in seen] == ['me@h1', 'me@h2']
    assert 'BatchMode=yes' in seen[0]
    assert any(a.startswith('ConnectTimeout=') for a in seen[0])


# -- live usage is read, never stored --------------------------------------------------------------------


def test_usage_is_tasks_cpus_and_memory_summed_per_session_tag() -> None:
    usage = parse_usage(
        '16|64G|1|lc:session=ws-a\n8|2G|1|lc:session=ws-b\n4|1G|2|lc:session=ws-a\n2|1G|1|(null)\n1|500M|1|\n'
    )
    assert usage == {
        'ws-a': Held(tasks=2, cpus=20, mem_mb=66 * 1024),
        'ws-b': Held(tasks=1, cpus=8, mem_mb=2048),
        '': Held(tasks=2, cpus=3, mem_mb=1524),
    }
    # Planted control: the retired workstation tag is no session's, so it is counted untagged.
    assert parse_usage('8|1G|1|lc:ws=ws-a\n') == {'': Held(tasks=1, cpus=8, mem_mb=1024)}


def test_the_usage_question_rides_the_one_probe_counts_every_pending_task_and_stays_about_the_caller() -> None:
    assert probe_command() == PROBE_COMMAND
    command = probe_command('acct-free')
    assert command.startswith(PROBE_COMMAND)
    assert 'squeue -h --me -r -t PENDING,RUNNING -A acct-free -o "%C|%m|%D|%k|%j"' in command


def test_headroom_is_the_quota_less_every_job_held_with_no_share_carved_out() -> None:
    assert headroom(_snap()) == 96
    assert headroom(_snap('16 lc:session=ws-a\n')) == 80
    assert headroom(_snap('48 lc:session=ws-b\n24 lc:session=ws-a\n')) == 24, 'every box holds against the quota alike'
    assert headroom(_snap('90 (null)\n')) == 6, 'an untagged job counts too'
    assert headroom(_snap('100 lc:session=ws-a\n')) == 0


# -- allocation ------------------------------------------------------------------------------------------


def test_the_plan_is_capped_by_headroom_and_tagged() -> None:
    grant, plan = allocate(
        500, Cost(seconds=60), [(GRANT, _snap('16 lc:session=ws-a\n'))], session=WIDE, policy=Policy()
    )
    assert grant is GRANT
    assert plan.throttle == len(plan.shards) <= 80, 'the headroom caps the wave; one wave, all running'
    assert plan.comment == 'lc:session=ws-a'
    assert plan.account == 'acct-free'
    assert plan.partitions[0] == 'shortq'


def test_the_grant_that_finishes_first_wins() -> None:
    small = Grant(user='me', hosts=('a',), slurm_account='acct-free')
    big = Grant(user='me', hosts=('b',), slurm_account='acct-free')
    busy, idle = _snap('88 lc:session=x\n'), _snap()
    grant, _ = allocate(500, Cost(seconds=60), [(small, busy), (big, idle)], session=None, policy=Policy())
    assert grant is big


def test_a_tie_goes_to_priority() -> None:
    low = Grant(user='me', hosts=('a',), slurm_account='acct-free')
    high = Grant(user='me', hosts=('b',), slurm_account='acct-free', priority=1)
    grant, _ = allocate(10, Cost(seconds=60), [(low, _snap()), (high, _snap())], session=None, policy=Policy())
    assert grant is high


def test_no_headroom_anywhere_names_every_account() -> None:
    other = Grant(user='me', hosts=('b',), slurm_account='acct-free')
    with pytest.raises(ValueError, match=r'me@login\.example') as refused:
        allocate(
            10,
            Cost(cpus=8),
            [(GRANT, _snap('96 lc:session=ws-b\n')), (other, _snap('90 (null)\n'))],
            session=WIDE,
            policy=Policy(),
        )
    assert 'me@b' in str(refused.value)
    assert 'ws-b=96' in str(refused.value)


def test_the_script_carries_the_session_comment(tmp_path: Path) -> None:
    _, plan = allocate(10, Cost(seconds=60), [(GRANT, _snap())], session=WIDE, policy=Policy())
    script = render_script(plan, Config(job=JobSpec(name='j'), source=tmp_path / 'h.toml'), '~/r')
    assert '#SBATCH --comment=lc:session=ws-a\n' in script
    assert '#SBATCH --output=/dev/null\n' in script, 'a task writes no per-task file on the shared home'


def test_a_grants_setup_runs_first_in_every_task(tmp_path: Path) -> None:
    """A real cluster's compute nodes have no git until a module is loaded (2026-10-09: 126 tests errored on it)."""
    loaded = replace(GRANT, setup=('module load git/2.42.0',))
    _, plan = allocate(10, Cost(seconds=60), [(loaded, _snap())], session=WIDE, policy=Policy())
    config = Config(job=JobSpec(name='j', setup=('source .venv/bin/activate',)), source=tmp_path / 'h.toml')
    lines = render_script(plan, config, '~/r').splitlines()
    assert lines.index('module load git/2.42.0') < lines.index('source .venv/bin/activate')


def test_the_grant_table_reads_setup() -> None:
    table = {'grant': [{**_GRANT_ROW, 'setup': ['module load git']}]}
    assert load_grants(table).grants[0].setup == ('module load git',)


_GRANT_ROW = {'user': 'me', 'hosts': ['h'], 'slurm_account': 'a'}


def test_an_untagged_plan_carries_no_comment(tmp_path: Path) -> None:
    plan = make_plan(10, Cost(seconds=60), _snap(), cluster=GRANT.cluster(), policy=Policy(), limits=Limits())
    assert '--comment' not in render_script(plan, Config(source=tmp_path / 'h.toml'), '~/r')


# -- the remote run ----------------------------------------------------------------------------------


def test_a_run_is_bound_to_a_full_sha() -> None:
    with pytest.raises(ValueError, match='40-hex'):
        RunSpec(sha='99d207471a', repo_url='https://x', builds=Builds(install='true', env_key='k1'))


def test_every_path_stays_under_ci() -> None:
    spec = RunSpec(
        sha=SHA,
        repo_url='https://g/r.git',
        builds=Builds(install='uv pip install -e .', env_key='k1'),
        python='3.13',
        select='not slow',
        vocabulary=Vocabulary(('win',)),
    )
    for script in (fetch_script(spec), build_script(spec), collect_command(spec, also='win')):
        for word in script.replace(';', ' ').replace('=', ' ').split():
            if '$HOME' in word or word.startswith('~'):
                assert word.startswith(('"$HOME"/ci', '~/ci', '"$HOME/ci/', '\\"$HOME/ci/', '$HOME/ci/')), word
    assert '--python 3.13' in build_script(spec)
    assert '.lab-ci-installed' in build_script(spec), 'the venv is reused once installed'
    assert "-m '(not slow) and (win)'" in collect_command(spec, also='win')
    assert "-m '(not slow)'" in collect_command(spec), (
        'pytest keeps one -m: select and the platform expression are joined'
    )


def test_ids_are_read_from_collect_only_and_grouped_by_file() -> None:
    text = 'tests/a.py::t1\ntests/a.py::t2[x]\ntests/b.py::C::t3\n\n3 tests collected in 0.1s\n'
    ids = parse_ids(text)
    assert ids == ['tests/a.py::t1', 'tests/a.py::t2[x]', 'tests/b.py::C::t3']
    assert group_items(ids) == [ids[:2], ids[2:]]


def test_a_file_that_fails_to_collect_is_an_error_outcome_not_an_aborted_run() -> None:
    """One unimportable file must not hide the rest of the tree: it is recorded, the run goes on."""
    spec = RunSpec(sha='a' * 40, repo_url='https://g/r.git', builds=Builds(install='true', env_key='k1'))
    assert '--continue-on-collection-errors' in collect_command(replace(spec, collect='-x tests')), 'the plain path'
    collector = Path(cluster_module.__file__).with_name('collect.py')  # lab-commons' installed hpc package
    assert '--continue-on-collection-errors' in collector.read_text(encoding='utf-8'), 'the per-file collector'
    text = (
        'tests/a.py::t1\n'
        'ERROR tests/b.py - ImportError: no module named x\n'
        'ERROR tests/c.py::C::t - fixture\n'
        'ERROR tests/d.py\n'
        '!!!!! Interrupted: 3 errors during collection !!!!!\n'
    )
    assert parse_collection_errors(text) == ['tests/b.py', 'tests/c.py::C::t', 'tests/d.py']
    assert parse_ids(text) == ['tests/a.py::t1'], 'an ERROR line is not a collected id'


# -- the session is the job's owner; its share is never a machine-file fact ----------------------------------


def test_the_session_is_lc_hpc_session_and_tags_every_job(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('LC_HPC_SESSION', 'G')
    machine = load_grants(tomllib.loads(_grant()))
    assert machine.comment == 'lc:session=G'
    assert machine.session == Session(name='G')


def test_without_lc_hpc_session_no_job_is_tagged_or_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('LC_HPC_SESSION', raising=False)
    machine = load_grants(tomllib.loads(_grant()))
    assert machine.session is None
    assert machine.comment == ''
    _, plan = allocate(10, Cost(seconds=60), [(GRANT, _snap('40 lc:session=G\n'))], session=None, policy=Policy())
    assert plan.comment == ''
    assert headroom(_snap('40 lc:session=G\n')) == 56, 'every job on the account holds against its quota'


def test_a_bad_session_name_is_refused_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('LC_HPC_SESSION', 'a b')
    with pytest.raises(ValueError, match='LC_HPC_SESSION'):
        load_grants(tomllib.loads(_grant()))


def test_a_leftover_session_table_is_refused_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """User ruling 2026-10-17: an allocation between sessions is temporary and never lives in a machine file."""
    monkeypatch.setenv('LC_HPC_SESSION', 'G')
    leftover = _grant() + '[session.G]\ntasks = 1\ncpus = 1\nmem_gb = 1\n'
    with pytest.raises(ValueError, match=r'\[hpc\] session is retired.*lab_commons\.hpc allocate'):
        load_grants(tomllib.loads(leftover))
    # Planted control: the same file without the table loads.
    load_grants(tomllib.loads(_grant()))


def test_the_retired_workstation_key_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match=r'\[hpc\] workstation is retired.*LC_HPC_SESSION.*delete the line'):
        load_grants(tomllib.loads('workstation = "w"\n' + _grant()))


# -- every declared partition is asked for; the grant with the most room builds ---------------------------


def test_sbatch_asks_for_every_declared_partition_that_admits_the_shard(tmp_path: Path) -> None:
    """Array 7660516 went to ``shortq`` alone and pended for hours while ``defq`` had idle nodes."""
    _, plan = allocate(500, Cost(seconds=60), [(GRANT, _snap())], session=WIDE, policy=Policy())
    assert plan.partitions == ('shortq', 'defq')
    script = render_script(plan, Config(job=JobSpec(workdir=str(tmp_path))), '~/r')
    assert '#SBATCH --partition=shortq,defq\n' in script


def test_a_partition_whose_ceiling_breaks_the_shard_is_left_out() -> None:
    """Planted control: a 30 h shard exceeds ``shortq``'s ceiling, so the list must shrink to ``defq``."""
    _, plan = allocate(1, Cost(seconds=20 * 3600), [(GRANT, _snap())], session=WIDE, policy=Policy())
    assert plan.partitions == ('defq',)


def test_a_partition_needing_another_qos_is_not_merged_into_one_submission() -> None:
    """One ``sbatch`` carries one ``--qos``; ``devq`` needs ``dev``, the others the default."""
    grant = replace(GRANT, partitions=('devq', 'shortq', 'defq'), qos={'devq': 'dev'})
    _, plan = allocate(3, Cost(seconds=60), [(grant, _snap())], session=WIDE, policy=Policy())
    assert plan.partitions == ('devq',)
    assert plan.qos == 'dev'


def test_on_an_even_makespan_the_grant_with_more_headroom_wins_wherever_it_is_listed() -> None:
    first = Grant(user='u1', hosts=('login.example',), slurm_account='acct-free')
    second = Grant(user='u2', hosts=('login.example',), slurm_account='acct-free')
    busy, idle = _snap('60 lc:session=ws-a\n'), _snap()
    grant, _ = allocate(1, Cost(seconds=60), [(first, busy), (second, idle)], session=WIDE, policy=Policy())
    assert grant is second
    # Planted control: equal room falls back to the file order.
    grant, _ = allocate(1, Cost(seconds=60), [(first, idle), (second, idle)], session=WIDE, policy=Policy())
    assert grant is first


# -- a job-file verb reads its job file, never a guessed one in the cwd ---------------------------------


def _cli_on_machine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> object:

    monkeypatch.chdir(tmp_path)  # no hpc.toml here
    monkeypatch.setattr(cli, 'load_grants', lambda: Machine(session=WIDE, grants=(GRANT,)))
    monkeypatch.setattr(cli, 'runner_for', lambda _g, *_a: None)
    return cli


@pytest.mark.parametrize(
    ('argv', 'remedy'),
    [
        (['probe'], 'host card carries its supply'),
        (['run', 'status'], 'shows its progress'),
        (['run', 'watch'], 'forge serve'),
    ],
)
def test_the_ssh_reads_are_retired_and_name_the_forge_as_their_replacement(
    argv: list[str], remedy: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Where a run is and what the cluster can take are read from the forge. PLANTED CONTROL: run gather parses."""
    cli = _cli_on_machine(monkeypatch, tmp_path)
    with pytest.raises(SystemExit):
        cli.main(argv)
    err = capsys.readouterr().err
    assert 'is retired' in err
    assert remedy in err
    assert cli._parser().parse_args(['run', 'gather', '--sha', 'a', '-o', 'o']).step == 'gather'


@pytest.mark.parametrize('verb', ['plan', 'submit', 'status', 'gather', 'retry'])
def test_a_verb_that_reads_a_job_file_refuses_without_one_and_names_the_remedy(
    verb: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = _cli_on_machine(monkeypatch, tmp_path)
    with pytest.raises(SystemExit):
        cli.main([verb])
    assert '-c <job file>' in capsys.readouterr().err


def test_a_named_job_file_that_is_missing_is_refused_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = _cli_on_machine(monkeypatch, tmp_path)
    with pytest.raises(SystemExit):
        cli.main(['status', '-c', 'nope.toml'])
    assert 'nope.toml' in capsys.readouterr().err


# -- the accounts are one pool; a session past its cap queues, never refused -----------------------------

TWO = Session(name='G', tasks=2, cpus=128, mem_gb=600, task_cpus=64, task_mem_gb=300)
OTHER = Grant(user='you', hosts=('login.example',), slurm_account='acct-free')


def test_a_session_is_counted_across_every_account_and_past_its_cap_it_queues() -> None:
    """One task on each account fills a two-task cap: the plan is not refused, it has no room and throttles to 1."""
    one = _snap('8 lc:session=G\n')
    _, plan = allocate(10, Cost(cpus=8, seconds=60), [(GRANT, one), (OTHER, one)], session=TWO, policy=Policy())
    assert plan.room == 0
    assert plan.throttle == 1
    assert plan.comment == 'lc:session=G'
    # Planted control: another session's tasks hold the account, never this session's cap.
    theirs = _snap('8 lc:session=H\n')
    _, plan = allocate(10, Cost(cpus=8, seconds=60), [(GRANT, theirs), (OTHER, theirs)], session=TWO, policy=Policy())
    assert plan.room == 2
    assert plan.throttle == 2


def test_the_session_cap_bounds_cpus_and_memory_as_well_as_tasks() -> None:
    by_cpu = replace(TWO, tasks=100, cpus=64)
    _, plan = allocate(10, Cost(cpus=40, seconds=60), [(GRANT, _snap())], session=by_cpu, policy=Policy())
    assert plan.room == 1, 'the account holds two 40-CPU tasks, a 64-CPU session one'
    by_mem = replace(TWO, tasks=100, mem_gb=300)
    cost = Cost(mem_gb=150, seconds=60)
    _, plan = allocate(10, cost, [(GRANT, _snap()), (OTHER, _snap())], session=by_mem, policy=Policy())
    assert plan.room == 2, 'planted control: nothing held, two 150 GB tasks fit 300 GB'
    held = _snap('1 lc:session=G\n')  # one 1 GB task, on the OTHER account
    _, plan = allocate(10, cost, [(GRANT, _snap()), (OTHER, held)], session=by_mem, policy=Policy())
    assert plan.room == 1, 'the 1 GB held elsewhere leaves 299 GB: one more 150 GB task'


def test_a_task_past_the_sessions_per_task_ceiling_is_refused() -> None:
    with pytest.raises(ValueError, match='per-task ceiling'):
        allocate(1, Cost(cpus=65, seconds=60), [(GRANT, _snap())], session=TWO, policy=Policy())
    # Planted control: at the ceiling it plans.
    allocate(1, Cost(cpus=64, seconds=60), [(GRANT, _snap())], session=TWO, policy=Policy())


def test_the_account_with_group_memory_room_takes_the_job() -> None:
    """AssocGrpMemLimit is the real contention: 352 of 360 GB held leaves no room for a 16 GB task."""
    full = _snap(running='acct-free|8|1|352G|N/A\n')
    pool = [(GRANT, full), (OTHER, _snap())]
    grant, plan = allocate(1, Cost(mem_gb=16, seconds=60), pool, session=None, policy=Policy())
    assert grant is OTHER
    assert plan.room
    # Planted control: with room on both, the file order holds.
    grant, _ = allocate(1, Cost(mem_gb=4, seconds=60), pool, session=None, policy=Policy())
    assert grant is GRANT
