"""STUCK-RUN-CANCEL: only this sha's forge tasks, busy at full CPU with no result past the bound, are cancelled."""

from __future__ import annotations

import pytest
from lab_commons.hpc.grants import Grant

from dev_lab.dev.forgestuck import Task, cancel_stuck, judge, parse_duration

SHA = 'a' * 40
OTHER = 'b' * 40
HOUR = 3600.0
_GRANT = Grant(user='u', hosts=('login.example',), slurm_account='acct')


def _task(name: str = f'run-{SHA[:12]}-linux', *, cpu: float = 1.0, idle_s: float = 3 * HOUR) -> Task:
    return Task('7_1', name, elapsed_s=4 * HOUR, cpus=2, cpu_s=cpu * 4 * HOUR * 2, idle_s=idle_s)


def test_a_busy_silent_forge_task_is_stuck() -> None:
    assert judge(_task(), SHA, bound_s=HOUR) == ''


@pytest.mark.parametrize(
    ('task', 'why'),
    [
        (_task('my-solve'), 'not a forge task'),
        (_task(f'run-{OTHER[:12]}-linux'), 'not a forge task'),
        (_task(cpu=0.2), 'CPU'),
        (_task(idle_s=0.5 * HOUR), 'a result line'),
    ],
)
def test_a_planted_out_of_bound_task_is_refused(task: Task, why: str) -> None:
    assert why in judge(task, SHA, bound_s=HOUR)


def test_slurm_durations() -> None:
    assert parse_duration('1-02:00:00') == 26 * HOUR
    assert parse_duration('05:30') == 330
    assert parse_duration('01:00:00') == HOUR


class _Shell:
    """A fake account: one stuck task of SHA, one healthy task of SHA, and a foreign job."""

    def __init__(self) -> None:
        self.cancelled: list[str] = []

    def __call__(self, command: str, stdin: str | None = None) -> str:
        del stdin
        if command.startswith('date'):
            return (
                f'100000\n1_1|run-{SHA[:12]}-linux|04:00:00|1\n1_2|run-{SHA[:12]}-linux|04:00:00|1\n'
                '9|someone-else|04:00:00|1\n'
            )
        if command.startswith('sstat'):
            healthy = "'1_2'" in command or ' 1_2 ' in command
            return '01:00:00\n99000\n' if healthy else '04:00:00\n80000\n'
        if command.startswith('scancel'):
            self.cancelled += command.split()[1:]
            return ''
        raise AssertionError(command)


def test_only_the_stuck_task_is_cancelled_and_the_healthy_one_is_reported() -> None:
    shell, said = _Shell(), []
    code = cancel_stuck(
        SHA, [_GRANT], lambda _g: shell, bound_s=HOUR, say=said.append, run_dir=lambda *_: lambda _p: '/r'
    )
    assert shell.cancelled == ['1_1']
    assert code == 1, 'a healthy task of the sha was left alone and said so'
    assert any('1_2' in line and 'healthy' in line for line in said)
    assert not any('someone-else' in line for line in shell.cancelled)


def test_a_short_sha_is_refused_before_any_read() -> None:
    said: list[str] = []
    assert cancel_stuck(SHA[:12], [_GRANT], lambda _g: pytest.fail('read'), bound_s=HOUR, say=said.append) == 2
