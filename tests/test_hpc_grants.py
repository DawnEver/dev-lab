"""``lab_commons.hpc`` grants, shared-account allocation and the remote verdict -- against the recorded cluster.

Usage per workstation is never stored: it is read back from the ``--comment`` tag every job carries, so
these tests feed the probe's ``@@@ shared`` section the way ``squeue -o "%C %k"`` prints it.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from lab_commons.config import CONFIG_ENV
from lab_commons.hpc import run as run_module
from lab_commons.hpc.config import Config, Cost, JobSpec, Limits, Policy
from lab_commons.hpc.grants import Grant, Machine, load_grants
from lab_commons.hpc.plan import allocate, headroom, make_plan
from lab_commons.hpc.pytest_item import junit_key, parse_junit
from lab_commons.hpc.run import Unreachable, failover_runner, render_script
from lab_commons.hpc.slurm import PROBE_COMMAND, parse_snapshot, parse_usage, probe_command
from lab_commons.hpc.verdict import (
    VerdictSpec,
    build_script,
    collect_command,
    fetch_script,
    group_items,
    parse_collection_errors,
    parse_ids,
    remote_verdict,
)

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
workstation = "ws-a"
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
    machine = load_grants()
    assert machine.workstation == 'ws-a'
    assert machine.comment == 'lc:ws=ws-a'
    assert [g.account for g in machine.grants] == [('me', 'acct-free'), ('me', 'x')]
    assert machine.grants[0].targets == ('me@login2', 'me@login1'), 'hosts keep their order'
    assert machine.grants[0].name == 'me@login2 (acct-free)'
    assert machine.grants[0].cluster().partitions == ('shortq',)
    assert machine.grants[0].cluster().account == 'acct-free'
    assert machine.grants[1].priority == 2
    assert not machine.grants[0].same_cluster(machine.grants[1])


def _grant(**extra: object) -> str:
    keys = {'hosts': '["h"]', 'cpus': '1', **extra}
    return 'workstation = "w"\n[[grant]]\nuser = "u"\nslurm_account = "s"\n' + ''.join(
        f'{k} = {v}\n' for k, v in keys.items()
    )


@pytest.mark.parametrize(
    ('table', 'match'),
    [
        ({}, r'no \[hpc\] table'),
        (_grant() + '[[grant]]\nuser = "u"\nhosts = ["g"]\nslurm_account = "s"\ncpus = 2\n', 'granted twice'),
        (_grant(cpus='0'), 'share must be positive'),
        (_grant(key='"x"'), 'unknown keys'),
        (_grant(account='"u@h"'), 'unknown keys'),
        (_grant(hosts='[]'), 'at least one login host'),
        (_grant().replace('"w"', '""'), 'workstation'),
        ('workstation = "w"\n', r'no \[\[hpc\.grant\]\]'),
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

    monkeypatch.setattr(run_module, '_completed', fake)
    grant = Grant(user='me', hosts=('h1', 'h2'), slurm_account='a', cpus=1)
    assert run_module.runner_for(grant)('true', None) == 'ok'
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
    assert plan.partition == 'shortq'


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


def test_an_untagged_plan_carries_no_comment(tmp_path: Path) -> None:
    plan = make_plan(10, Cost(seconds=60), _snap(), cluster=GRANT.cluster(), policy=Policy(), limits=Limits())
    assert '--comment' not in render_script(plan, Config(source=tmp_path / 'h.toml'), '~/r')


# -- the item runner -------------------------------------------------------------------------------------


def test_junit_keys_follow_pytests_mangling() -> None:
    assert junit_key('tests/unit/test_a.py::TestB::test_c[x-1]') == ('tests.unit.test_a.TestB', 'test_c[x-1]')
    assert junit_key('tests/test_a.py::test_d') == ('tests.test_a', 'test_d')


def test_junit_outcomes_and_a_missing_id() -> None:
    junit = (
        '<testsuites><testsuite>'
        '<testcase classname="t.test_a" name="ok"/>'
        '<testcase classname="t.test_a" name="bad"><failure/></testcase>'
        '<testcase classname="t.test_a" name="bad"><error/></testcase>'
        '<testcase classname="t.test_a" name="skip"><skipped type="pytest.skip"/></testcase>'
        '<testcase classname="t.test_a" name="xf"><skipped type="pytest.xfail"/></testcase>'
        '</testsuite></testsuites>'
    )
    ids = [f't/test_a.py::{n}' for n in ('ok', 'bad', 'skip', 'xf', 'gone')]
    assert parse_junit(junit, ids) == {
        ids[0]: 'passed',
        ids[1]: 'failed',
        ids[2]: 'skipped',
        ids[3]: 'xfailed',
        ids[4]: 'missing',
    }


def test_the_item_runner_is_standalone() -> None:
    """It is shipped as text and imported beside an arbitrary lab_commons -- it must import none."""
    source = (Path(__file__).parents[1] / 'src' / 'lab_commons' / 'hpc' / 'pytest_item.py').read_text(encoding='utf-8')
    assert 'lab_commons' not in ''.join(line for line in source.splitlines() if line.startswith(('import', 'from')))


# -- the remote verdict ----------------------------------------------------------------------------------


def test_a_verdict_is_bound_to_a_full_sha() -> None:
    with pytest.raises(ValueError, match='40-hex'):
        VerdictSpec(sha='99d207471a', repo_url='https://x', install='true')


def test_every_path_stays_under_ci() -> None:
    spec = VerdictSpec(
        sha=SHA,
        repo_url='https://g/r.git',
        install='uv pip install -e .',
        python='3.13',
        select='not slow',
        not_covered='win',
    )
    for script in (fetch_script(spec), build_script(spec), collect_command(spec, covered_only=True)):
        for word in script.replace(';', ' ').replace('=', ' ').split():
            if '$HOME' in word or word.startswith('~'):
                assert word.startswith(('"$HOME"/ci', '~/ci', '"$HOME/ci/bin')), word
    assert '--python 3.13' in build_script(spec)
    assert '.lab-ci-installed' in build_script(spec), 'the venv is reused once installed'
    assert "-m '(not slow) and not (win)'" in collect_command(spec, covered_only=True)
    assert "-m '(not slow)'" in collect_command(spec), 'pytest keeps one -m: select and not_covered are joined'


def test_ids_are_read_from_collect_only_and_grouped_by_file() -> None:
    text = 'tests/a.py::t1\ntests/a.py::t2[x]\ntests/b.py::C::t3\n\n3 tests collected in 0.1s\n'
    ids = parse_ids(text)
    assert ids == ['tests/a.py::t1', 'tests/a.py::t2[x]', 'tests/b.py::C::t3']
    items = group_items(ids)
    assert [i['ids'] for i in items] == [ids[:2], ids[2:]]
    assert items[1]['junit'] == '.lab-ci/junit/1.xml'


class FakeAda:
    """A runner answering the verdict flow; items 0 and 2 return, item 1's shard dies."""

    def __init__(self, *, have: bool = True) -> None:
        """*have*: whether the cache already holds the commit."""
        self.have = have
        self.calls: list[tuple[str, str | None]] = []

    def __call__(self, command: str, stdin: str | None = None) -> str:  # noqa: C901, PLR0911 -- one answer per verb
        self.calls.append((command, stdin))
        if command.startswith('echo "@@@ nodes"'):
            return IDLE + '@@@ shared\n8 lc:ws=other\n'
        if 'cat-file' in command:
            return 'have\n' if self.have else 'missing\n'
        if '@@@ facts' in command:
            return '@@@ facts\nplatform=linux-x86_64/glibc2.28\npython=3.13.1\n'
        if '--collect-only' in command:
            win = 'tests/w.py::t\n' if 'not (win)' not in command else ''
            return f'tests/a.py::t1\ntests/a.py::t2\n{win}tests/b.py::t3\ntests/c.py::t4\n'
        if 'sbatch' in command:
            return '4242\n'
        if 'sacct' in command:
            return '4242_0|COMPLETED\n4242_1|FAILED\n4242_2|COMPLETED\n'
        if 'results/*.json' in command:
            manifest = json.loads(next(s for c, s in self.calls if 'manifest.json' in c) or '')
            lines = []
            for shard, (start, stop) in enumerate(manifest['shards']):
                if shard == 1:
                    continue
                results = []
                for index in range(start, stop):
                    ids = manifest['items'][index]['ids']
                    results.append({'index': index, 'ok': True, 'value': {'outcomes': dict.fromkeys(ids, 'passed')}})
                lines.append(json.dumps({'shard': shard, 'results': results}))
            return '\n'.join(lines) + '\n'
        return ''


def test_the_verdict_records_outcomes_and_never_passes_what_it_did_not_run() -> None:
    ada = FakeAda()
    machine = Machine(workstation='ws-a', grants=(GRANT,))
    record = remote_verdict(
        VerdictSpec(sha=SHA, repo_url='https://g/r.git', install='true', not_covered='win'),
        machine,
        lambda _g: ada,
        cost=Cost(seconds=600),
        policy=Policy(shard_minutes_min=1, shard_minutes_max=15),
        sleep=lambda _s: None,
        stamp='t0',
    )
    assert record['sha'] == SHA
    assert record['platform'] == 'linux-x86_64/glibc2.28'
    assert record['cluster'] == 'login.example'
    assert record['python'] == '3.13.1'
    assert record['plan']['comment'] == 'lc:ws=ws-a'
    assert record['plan']['job_id'] == '4242'
    outcomes = record['outcomes']
    assert outcomes['tests/w.py::t'] == 'not-covered'
    assert outcomes['tests/a.py::t1'] == 'passed'
    assert outcomes['tests/b.py::t3'] == 'lost', 'a dead shard is not a pass'
    assert outcomes['tests/c.py::t4'] == 'passed'
    script = next(s for c, s in ada.calls if c.endswith('job.sh') and 'cat >' in c) or ''
    assert '#SBATCH --comment=lc:ws=ws-a' in script
    assert 'cd "$HOME"/ci/trees/' + SHA in script
    assert 'lab_ci_pytest_item' in (next(s for c, s in ada.calls if 'manifest.json' in c) or '')


def test_a_commit_off_the_remote_without_a_bundle_is_refused() -> None:
    with pytest.raises(RuntimeError, match=r'not on https://g/r\.git'):
        remote_verdict(
            VerdictSpec(sha=SHA, repo_url='https://g/r.git', install='true'),
            Machine(workstation='w', grants=(GRANT,)),
            lambda _g: FakeAda(have=False),
            cost=Cost(),
            policy=Policy(),
        )


def test_a_file_that_fails_to_collect_is_an_error_outcome_not_an_aborted_run() -> None:
    """One unimportable file must not hide the rest of the tree: it is recorded, the run goes on."""
    spec = VerdictSpec(sha='a' * 40, repo_url='https://g/r.git', install='true')
    assert '--continue-on-collection-errors' in collect_command(spec)
    text = (
        'tests/a.py::t1\n'
        'ERROR tests/b.py - ImportError: no module named x\n'
        'ERROR tests/c.py::C::t - fixture\n'
        'ERROR tests/d.py\n'
        '!!!!! Interrupted: 3 errors during collection !!!!!\n'
    )
    assert parse_collection_errors(text) == ['tests/b.py', 'tests/c.py::C::t', 'tests/d.py']
    assert parse_ids(text) == ['tests/a.py::t1'], 'an ERROR line is not a collected id'


def test_a_network_drop_while_waiting_is_ridden_out_not_fatal() -> None:
    """The jobs survive a VPN drop; the watcher must too (measured 2026-10-09: one abort killed a verdict)."""
    from lab_commons.hpc import verdict as verdict_module

    answers = iter(['drop', 'drop', '7.0|RUNNING\n7.1|COMPLETED\n', '7.0|COMPLETED\n7.1|COMPLETED\n'])

    def run(command: str, stdin: str | None) -> str:
        del command, stdin
        answer = next(answers)
        if answer == 'drop':
            msg = 'no login host answered'
            raise Unreachable(msg)
        return answer

    slept: list[float] = []
    states = verdict_module._wait(run, '7', 2, 30.0, slept.append)
    assert set(states.values()) == {'COMPLETED'}
    assert len(slept) == 3


def test_a_long_outage_names_where_the_results_wait() -> None:
    from lab_commons.hpc import verdict as verdict_module

    def run(command: str, stdin: str | None) -> str:
        del command, stdin
        msg = 'no login host answered'
        raise Unreachable(msg)

    with pytest.raises(Unreachable, match=r'job 7.*still on the cluster'):
        verdict_module._wait(run, '7', 2, 3600.0, lambda _s: None)
