"""STUCK-RUN-CANCEL: only this sha's forge tasks, busy at full CPU, silent past their MEASURED limit, are cancelled."""

from __future__ import annotations

import json

import pytest
from lab_commons.hpc.grants import Grant

from dev_lab.dev.forgestuck import Limit, Task, cancel_stuck, judge, limit_of, parse_duration, remote_path

SHA = 'a' * 40
OTHER = 'b' * 40
HOUR = 3600.0
_GRANT = Grant(user='u', hosts=('login.example',), slurm_account='acct')
_LIMIT = Limit(HOUR, 'planted')


def _task(name: str = f'run-{SHA[:12]}-linux', *, cpu: float = 1.0, idle_s: float = 3 * HOUR) -> Task:
    return Task('7_1', name, elapsed_s=4 * HOUR, cpus=2, cpu_s=cpu * 4 * HOUR * 2, idle_s=idle_s, limit=_LIMIT)


def test_a_busy_silent_forge_task_is_stuck() -> None:
    assert judge(_task(), SHA) == ''


@pytest.mark.parametrize(
    ('task', 'why'),
    [
        (_task('my-solve'), 'not a forge task'),
        (_task(f'run-{OTHER[:12]}-linux'), 'not a forge task'),
        (_task(cpu=0.2), 'CPU'),
        (_task(idle_s=0.5 * HOUR), 'a test line'),
    ],
)
def test_a_planted_out_of_bound_task_is_refused(task: Task, why: str) -> None:
    assert why in judge(task, SHA)


def test_the_limit_is_the_measured_wall_and_the_bound_only_floors_an_unmeasured_test() -> None:
    durations = {'t::a': 600.0, 't::b': 1200.0}
    measured = limit_of(['t::a', 't::b'], durations, factor=3, bound_s=HOUR)
    assert measured.seconds == 3600.0
    assert 'unmeasured' not in measured.basis
    short = limit_of(['t::a'], durations, factor=2, bound_s=HOUR)
    assert short.seconds == 1200.0, 'the bound does not lift a fully measured shard'
    unpriced = limit_of(['t::a', 't::new'], durations, factor=2, bound_s=HOUR)
    assert unpriced.seconds == HOUR
    assert '1 test(s) unmeasured, fallback bound 60 min' in unpriced.basis


def test_slurm_durations() -> None:
    assert parse_duration('1-02:00:00') == 26 * HOUR
    assert parse_duration('05:30') == 330
    assert parse_duration('01:00:00') == HOUR


_MANIFEST = {
    'shards': [[0, 1], [1, 2], [2, 3]],
    'items': [
        {'ids': ['t::x'], 'stream': '.lab-ci/r.jsonl'},
        {'ids': ['t::slow'], 'stream': '.lab-ci/r1.jsonl'},
        {'ids': ['t::fast'], 'stream': '.lab-ci/r2.jsonl'},
    ],
}


class _Shell:
    """A fake account: shard 1 (a slow test) and shard 2 (a fast one), equally silent; and a foreign job.

    *sstat* is what ``sstat`` prints for every task; *fresh* makes the re-read before a cancel see a new line.
    """

    def __init__(self, *, sstat: str = '00:30.000\n04:00:00\n', fresh: bool = False, job: str = '1') -> None:
        self.cancelled: list[str] = []
        self.sstat, self.fresh, self.job = sstat, fresh, job

    def __call__(self, command: str, stdin: str | None = None) -> str:
        del stdin
        if 'squeue' in command:
            return (
                f'100000\n{self.job}_1|run-{SHA[:12]}-linux|04:00:00|1\n{self.job}_2|run-{SHA[:12]}-linux|04:00:00|1\n'
                '9|someone-else|04:00:00|1\n'
            )
        if command.startswith('cat '):
            return json.dumps(_MANIFEST)
        if command.startswith('sstat'):
            return f'{self.sstat}--stream--\n90000\n'  # silent 10000 s
        if command.startswith('date'):
            return '100000\n99990\n' if self.fresh else '100000\n90000\n'
        if command.startswith('scancel'):
            self.cancelled += command.split()[1:]
            return ''
        raise AssertionError(command)


def _cancel(shell: _Shell, said: list[str], durations: dict[str, float] | None = None) -> int:
    durations = {'t::slow': 5000.0, 't::fast': 60.0} if durations is None else durations
    return cancel_stuck(
        SHA,
        [_GRANT],
        lambda _g: shell,
        limit=lambda ids: limit_of(ids, durations, factor=3, bound_s=HOUR),
        say=said.append,
        round_of=lambda *_: lambda _p: ('/r', frozenset({'1'})),
    )


def test_only_the_task_silent_past_its_measured_wall_is_cancelled() -> None:
    shell, said = _Shell(), []
    code = _cancel(shell, said)
    assert shell.cancelled == ['1_2'], 'the fast test is overdue; the slow one is within 3 x its wall'
    assert code == 1
    assert any('1_1' in line and 'healthy' in line for line in said)
    assert 'someone-else' not in ' '.join(shell.cancelled)


def test_a_task_of_an_earlier_round_is_refused_though_its_name_matches() -> None:
    """PLANTED CONTROL for the test above: the same silent tasks under a job id this round never submitted."""
    shell, said = _Shell(job='7'), []
    assert _cancel(shell, said) == 1
    assert shell.cancelled == []
    assert any('not one the current round submitted' in line for line in said)


def test_the_cpu_time_is_the_largest_step_parsed_not_text_sorted() -> None:
    """``9:59.000`` sorts after ``1-02:00:00`` as text; parsed, the day-long step is the task's load."""
    shell, said = _Shell(sstat='1-02:00:00\n09:59.000\n'), []
    _cancel(shell, said)
    assert shell.cancelled == ['1_2']


def test_a_task_sstat_cannot_measure_is_refused() -> None:
    shell, said = _Shell(sstat=''), []
    _cancel(shell, said)
    assert shell.cancelled == []
    assert any('sstat reported no CPU time' in line for line in said)


def test_a_line_written_while_it_was_judged_spares_the_task() -> None:
    shell, said = _Shell(fresh=True), []
    assert _cancel(shell, said) == 1
    assert shell.cancelled == []
    assert any('arrived while it was being judged' in line for line in said)


def test_a_failing_grant_is_reported_and_the_next_is_still_judged() -> None:
    shell, said = _Shell(), []
    broken = Grant(user='v', hosts=('down.example',), slurm_account='acct')

    def connect(grant: Grant) -> _Shell:
        if grant is broken:
            msg = 'ssh: unreachable'
            raise OSError(msg)
        return shell

    code = cancel_stuck(
        SHA,
        [broken, _GRANT],
        connect,
        limit=lambda ids: limit_of(ids, {'t::slow': 5000.0, 't::fast': 60.0}, factor=3, bound_s=HOUR),
        say=said.append,
        round_of=lambda *_: lambda _p: ('/r', frozenset({'1'})),
    )
    assert code == 2
    assert shell.cancelled == ['1_2']
    assert any('unreachable' in line for line in said)


def test_a_short_sha_is_refused_before_any_read() -> None:
    def never(_g: Grant) -> None:
        pytest.fail('read')

    assert cancel_stuck(SHA[:12], [_GRANT], never, limit=lambda _i: _LIMIT, say=lambda _l: None) == 2


def test_a_home_relative_run_dir_keeps_its_home_and_quotes_the_rest() -> None:
    """A run dir recorded as ``~/ci/...``: quoted whole it reached the shell as ``'~/ci/...'`` (live 2026-10-26)."""
    assert remote_path('~/ci/trees/abc/.lab-hpc/run-1') == '"$HOME"/ci/trees/abc/.lab-hpc/run-1'
    assert remote_path("~/ci/it's here") == '"$HOME"/' + "'ci/it'\"'\"'s here'"
    assert remote_path('/gpfs01/home/u/ci/run 1') == "'/gpfs01/home/u/ci/run 1'"
    assert remote_path('~user/ci') == "'~user/ci'"
