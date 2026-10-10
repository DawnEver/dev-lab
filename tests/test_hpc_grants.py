"""``lab_commons.hpc`` grants, shared-account allocation and the remote run -- against the recorded cluster.

Usage per workstation is never stored: it is read back from the ``--comment`` tag every job carries, so
these tests feed the probe's ``@@@ shared`` section the way ``squeue -o "%C %k"`` prints it.
"""

from __future__ import annotations

import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from lab_commons.config import CONFIG_ENV
from lab_commons.hpc import __main__ as cli
from lab_commons.hpc import cluster as cluster_module
from lab_commons.hpc.cluster import Unreachable, failover_runner, render_script
from lab_commons.hpc.config import Config, Cost, JobSpec, Limits, Policy
from lab_commons.hpc.grants import Grant, Machine, load_grants
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
from lab_commons.hpc.slurm import PROBE_COMMAND, parse_snapshot, parse_usage, probe_command

FIXTURE = (Path(__file__).parent / '_hpc_fixtures' / 'cluster-2026-10-08.txt').read_text(encoding='utf-8')
IDLE = FIXTURE.split('@@@ running')[0] + '@@@ running\n'
GRANT = Grant(user='me', hosts=('login.example',), slurm_account='acct-free', cpus=64, partitions=('shortq', 'defq'))
SHA = 'a' * 40


def _snap(shared: str = '') -> object:
    return parse_snapshot(IDLE + '@@@ shared\n' + shared, 'acct-free')


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
cpus = 64
partitions = ["shortq"]
[[hpc.grant]]
user = "me"
hosts = ["other"]
slurm_account = "x"
cpus = 8
priority = 2
""",
    )
    monkeypatch.setenv('HARNESS_MACHINE', 'ws-a')
    machine = load_grants()
    assert machine.workstation == 'ws-a'
    assert machine.comment == 'lc:ws=ws-a'
    assert [g.account for g in machine.grants] == [('me', 'acct-free'), ('me', 'x')]
    assert machine.grants[0].targets == ('me@login2', 'me@login1'), 'hosts keep their order'
    assert machine.grants[0].name == 'me@login2 (acct-free)'
    assert machine.grants[0].cluster().partitions == ('shortq',)
    assert machine.grants[1].priority == 2
    assert not machine.grants[0].same_cluster(machine.grants[1])


def _grant(**extra: object) -> str:
    keys = {'hosts': '["h"]', 'cpus': '1', **extra}
    return '[[grant]]\nuser = "u"\nslurm_account = "s"\n' + ''.join(f'{k} = {v}\n' for k, v in keys.items())


@pytest.mark.parametrize(
    ('table', 'match'),
    [
        ({}, r'no \[hpc\] table'),
        (_grant() + '[[grant]]\nuser = "u"\nhosts = ["g"]\nslurm_account = "s"\ncpus = 2\n', 'granted twice'),
        (_grant(cpus='0'), 'share must be positive'),
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
    grant = Grant(user='me', hosts=('h1', 'h2'), slurm_account='a', cpus=1)
    assert cluster_module.runner_for(grant)('true', None) == 'ok'
    assert [a[-2] for a in seen] == ['me@h1', 'me@h2']
    assert 'BatchMode=yes' in seen[0]
    assert any(a.startswith('ConnectTimeout=') for a in seen[0])


# -- live usage is read, never stored --------------------------------------------------------------------


def test_usage_is_summed_per_workstation_tag() -> None:
    usage = parse_usage('16 lc:ws=ws-a\n8 lc:ws=ws-b\n4 lc:ws=ws-a\n2 (null)\n1 \n')
    assert usage == {'ws-a': 20, 'ws-b': 8, '': 3}


def test_the_usage_question_rides_the_one_probe_and_stays_about_the_caller() -> None:
    assert probe_command() == PROBE_COMMAND
    command = probe_command('acct-free')
    assert command.startswith(PROBE_COMMAND)
    assert 'squeue -h --me -A acct-free -o "%C %k"' in command


def test_headroom_is_the_share_less_what_others_and_i_hold() -> None:
    assert headroom(_snap(), 64, 'ws-a') == 64
    assert headroom(_snap('16 lc:ws=ws-a\n'), 64, 'ws-a') == 48
    # 96 quota, another box holds 48: min(64, 96-48) - 0
    assert headroom(_snap('48 lc:ws=ws-b\n'), 64, 'ws-a') == 48
    assert headroom(_snap('48 lc:ws=ws-b\n24 lc:ws=ws-a\n'), 64, 'ws-a') == 24
    assert headroom(_snap('90 (null)\n'), 64, 'ws-a') == 6, 'an untagged job is someone else'
    assert headroom(_snap('70 lc:ws=ws-a\n'), 64, 'ws-a') == 0


# -- allocation ------------------------------------------------------------------------------------------


def test_the_plan_is_capped_by_headroom_and_tagged() -> None:
    grant, plan = allocate(
        500, Cost(seconds=60), [(GRANT, _snap('16 lc:ws=ws-a\n'))], workstation='ws-a', policy=Policy()
    )
    assert grant is GRANT
    assert plan.throttle == 48
    assert plan.comment == 'lc:ws=ws-a'
    assert plan.account == 'acct-free'
    assert plan.partitions[0] == 'shortq'


def test_the_grant_that_finishes_first_wins() -> None:
    small = Grant(user='me', hosts=('a',), slurm_account='acct-free', cpus=8)
    big = Grant(user='me', hosts=('b',), slurm_account='acct-free', cpus=64)
    grant, _ = allocate(500, Cost(seconds=60), [(small, _snap()), (big, _snap())], workstation='w', policy=Policy())
    assert grant is big


def test_a_tie_goes_to_priority() -> None:
    low = Grant(user='me', hosts=('a',), slurm_account='acct-free', cpus=64)
    high = Grant(user='me', hosts=('b',), slurm_account='acct-free', cpus=64, priority=1)
    grant, _ = allocate(10, Cost(seconds=60), [(low, _snap()), (high, _snap())], workstation='w', policy=Policy())
    assert grant is high


def test_no_headroom_anywhere_names_every_account() -> None:
    other = Grant(user='me', hosts=('b',), slurm_account='acct-free', cpus=4)
    with pytest.raises(ValueError, match=r'me@login\.example') as refused:
        allocate(
            10, Cost(cpus=8), [(GRANT, _snap('96 lc:ws=ws-b\n')), (other, _snap())], workstation='ws-a', policy=Policy()
        )
    assert 'me@b' in str(refused.value)
    assert 'ws-b=96' in str(refused.value)


def test_the_script_carries_the_workstation_comment(tmp_path: Path) -> None:
    _, plan = allocate(10, Cost(seconds=60), [(GRANT, _snap())], workstation='ws-a', policy=Policy())
    script = render_script(plan, Config(job=JobSpec(name='j'), source=tmp_path / 'h.toml'), '~/r')
    assert '#SBATCH --comment=lc:ws=ws-a\n' in script
    assert '#SBATCH --output=logs/%A_%a.out\n' in script, 'Slurm never expands ~; the run dir is the submit dir'


def test_a_grants_setup_runs_first_in_every_task(tmp_path: Path) -> None:
    """A real cluster's compute nodes have no git until a module is loaded (2026-10-09: 126 tests errored on it)."""
    loaded = replace(GRANT, setup=('module load git/2.42.0',))
    _, plan = allocate(10, Cost(seconds=60), [(loaded, _snap())], workstation='ws-a', policy=Policy())
    config = Config(job=JobSpec(name='j', setup=('source .venv/bin/activate',)), source=tmp_path / 'h.toml')
    lines = render_script(plan, config, '~/r').splitlines()
    assert lines.index('module load git/2.42.0') < lines.index('source .venv/bin/activate')


def test_the_grant_table_reads_setup() -> None:
    table = {'grant': [{**_GRANT_ROW, 'setup': ['module load git']}]}
    assert load_grants(table).grants[0].setup == ('module load git',)


_GRANT_ROW = {'user': 'me', 'hosts': ['h'], 'slurm_account': 'a', 'cpus': 4}


def test_an_untagged_plan_carries_no_comment(tmp_path: Path) -> None:
    plan = make_plan(10, Cost(seconds=60), _snap(), cluster=GRANT.cluster(), policy=Policy(), limits=Limits())
    assert '--comment' not in render_script(plan, Config(source=tmp_path / 'h.toml'), '~/r')


# -- the remote run ----------------------------------------------------------------------------------


def test_a_run_is_bound_to_a_full_sha() -> None:
    with pytest.raises(ValueError, match='40-hex'):
        RunSpec(sha='99d207471a', repo_url='https://x', install='true')


def test_every_path_stays_under_ci() -> None:
    spec = RunSpec(
        sha=SHA,
        repo_url='https://g/r.git',
        install='uv pip install -e .',
        python='3.13',
        select='not slow',
        table={'win': ('windows',)},
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
    spec = RunSpec(sha='a' * 40, repo_url='https://g/r.git', install='true')
    assert '--continue-on-collection-errors' in collect_command(replace(spec, collect='-x tests')), 'the plain path'
    collector = Path(__file__).parents[1] / 'src' / 'lab_commons' / 'hpc' / 'collect.py'
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


# -- the workstation is the harness's machine name ------------------------------------------------------


def test_the_workstation_is_harness_machine_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('HARNESS_MACHINE', 'G')
    assert load_grants(tomllib.loads(_grant())).comment == 'lc:ws=G'


def test_without_harness_machine_the_workstation_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('HARNESS_MACHINE', raising=False)
    machine = load_grants(tomllib.loads(_grant()))
    assert machine.workstation is None
    assert machine.comment == ''
    _, plan = allocate(10, Cost(seconds=60), [(GRANT, _snap('40 lc:ws=G\n'))], workstation=None, policy=Policy())
    assert plan.comment == ''
    assert headroom(_snap('40 lc:ws=G\n'), 64, None) == 56, (
        'an unnamed box holds nothing tagged; every tagged job is another box'
    )


def test_a_spaced_harness_machine_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('HARNESS_MACHINE', 'a b')
    with pytest.raises(ValueError, match='HARNESS_MACHINE'):
        load_grants(tomllib.loads(_grant()))


def test_the_retired_workstation_key_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match=r'\[hpc\] workstation is retired.*HARNESS_MACHINE.*delete the line'):
        load_grants(tomllib.loads('workstation = "w"\n' + _grant()))


def test_the_tree_carries_its_submodules_at_their_pinned_commits() -> None:
    spec = RunSpec(sha=SHA, repo_url='https://g/r.git', install='uv sync', python='3.13')
    script = build_script(spec)
    assert 'git submodule update -q --init --recursive' in script, 'a tree without its submodules fails as broken code'
    assert script.index('git submodule update') < script.index(spec.install), 'submodules land before the build'


# -- every declared partition is asked for; the grant with the most room builds ---------------------------


def test_sbatch_asks_for_every_declared_partition_that_admits_the_shard(tmp_path: Path) -> None:
    """Array 7660516 went to ``shortq`` alone and pended for hours while ``defq`` had idle nodes."""
    _, plan = allocate(500, Cost(seconds=60), [(GRANT, _snap())], workstation='ws-a', policy=Policy())
    assert plan.partitions == ('shortq', 'defq')
    script = render_script(plan, Config(job=JobSpec(workdir=str(tmp_path))), '~/r')
    assert '#SBATCH --partition=shortq,defq\n' in script


def test_a_partition_whose_ceiling_breaks_the_shard_is_left_out() -> None:
    """Planted control: a 30 h shard exceeds ``shortq``'s ceiling, so the list must shrink to ``defq``."""
    _, plan = allocate(1, Cost(seconds=20 * 3600), [(GRANT, _snap())], workstation='ws-a', policy=Policy())
    assert plan.partitions == ('defq',)


def test_a_partition_needing_another_qos_is_not_merged_into_one_submission() -> None:
    """One ``sbatch`` carries one ``--qos``; ``devq`` needs ``dev``, the others the default."""
    grant = replace(GRANT, partitions=('devq', 'shortq', 'defq'), qos={'devq': 'dev'})
    _, plan = allocate(3, Cost(seconds=60), [(grant, _snap())], workstation='ws-a', policy=Policy())
    assert plan.partitions == ('devq',)
    assert plan.qos == 'dev'


def test_on_an_even_makespan_the_grant_with_more_headroom_wins_wherever_it_is_listed() -> None:
    first = Grant(user='u1', hosts=('login.example',), slurm_account='acct-free', cpus=96)
    second = Grant(user='u2', hosts=('login.example',), slurm_account='acct-free', cpus=96)
    busy, idle = _snap('60 lc:ws=ws-a\n'), _snap()
    grant, _ = allocate(1, Cost(seconds=60), [(first, busy), (second, idle)], workstation='ws-a', policy=Policy())
    assert grant is second
    # Planted control: equal room falls back to the file order.
    grant, _ = allocate(1, Cost(seconds=60), [(first, idle), (second, idle)], workstation='ws-a', policy=Policy())
    assert grant is first


# -- probe reads the machine, not a job file in the cwd --------------------------------------------------


def _cli_on_machine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> object:

    monkeypatch.chdir(tmp_path)  # no hpc.toml here
    monkeypatch.setattr(cli, 'load_grants', lambda: Machine(workstation='ws-a', grants=(GRANT,)))
    monkeypatch.setattr(cli, 'runner_for', lambda _g, *_a: None)
    monkeypatch.setattr(cli, 'probe', lambda _run, _account: _snap())
    return cli


def test_probe_needs_no_job_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``probe`` crashed with FileNotFoundError on ``./hpc.toml``; the machine config is all it reads."""
    cli = _cli_on_machine(monkeypatch, tmp_path)
    assert cli.main(['probe']) == 0
    out = capsys.readouterr()
    assert 'shortq' in out.out + out.err
    assert 'defq' in out.out + out.err


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
