"""The process-manager seam: what a manager would execute, and what it refuses to pretend."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from _box_fake import ended, record
from lab_commons.box import Refused

from dev_lab.supervise.notify import NOTIFY_SOCKET
from dev_lab.supervise.process import MANAGERS, SystemdProcessManager, manager_for, subprocess_runner
from dev_lab.supervise.process.base import Ran
from dev_lab.supervise.process.systemd import CAPPED_CPU, CAPPED_QUEUE_S, OUTPUT_CAP, Runner, ceiling_gb


def _recorder(calls: list[tuple[list[str], int, str | None]], code: int = 0) -> Runner:
    """Return a runner that records what it was asked to run instead of running it."""

    def run(argv: list[str], timeout: int, cwd: str | None) -> Ran:
        calls.append((argv, timeout, cwd))
        return Ran(code=code, out='active')

    return run


def test_a_manager_is_looked_up_by_the_name_a_config_uses() -> None:
    """The table is explicit, so a name that is not in it is a refusal rather than a guess."""
    manager = manager_for('systemd')
    assert isinstance(manager, SystemdProcessManager)
    assert manager.name == 'systemd'


def test_an_unknown_manager_name_names_what_does_exist() -> None:
    """A refusal that does not say what would have worked sends a reader to the docs."""
    with pytest.raises(ValueError, match='systemd'):
        manager_for('supervisord')


def test_the_table_holds_the_builtin() -> None:
    """Guards against the table silently losing its only entry."""
    assert set(MANAGERS) == {'systemd'}


def test_is_active_reads_the_exit_status() -> None:
    """`systemctl is-active` answers in its status, not in its text."""
    calls: list[tuple[list[str], int, str | None]] = []
    manager = SystemdProcessManager(runner=_recorder(calls, code=0))
    assert manager.is_active('webapp') is True
    assert calls[0][0] == ['systemctl', 'is-active', 'webapp']
    assert SystemdProcessManager(runner=_recorder(calls, code=3)).is_active('webapp') is False


@pytest.mark.parametrize('verb', ['start', 'stop', 'restart'])
def test_lifecycle_verbs_are_one_command_each(verb: str) -> None:
    """Hosting the process is the manager's job, so the supervisor only names the verb."""
    calls: list[tuple[list[str], int, str | None]] = []
    manager = SystemdProcessManager(runner=_recorder(calls))
    if verb == 'start':
        result = manager.start('webapp')
    elif verb == 'stop':
        result = manager.stop('webapp')
    else:
        result = manager.restart('webapp')
    assert result.ok
    assert calls[0][0] == ['systemctl', verb, 'webapp']


def test_a_capped_run_is_a_box_claim_carrying_its_ceiling_and_its_wall() -> None:
    """The ceiling is the reason this method exists; the box enforces it and the timeout as the wall."""
    calls: list[tuple[list[str], int, str | None]] = []
    manager = SystemdProcessManager(runner=_recorder(calls))
    manager.run_capped(['python', '-c', 'import x'], memory_max='600M', timeout=120)
    argv, allowed, _cwd = calls[0]
    assert argv[1:4] == ['-m', 'lab_commons.box', 'run']
    assert argv[argv.index('--mem-gb') + 1] == f'{600 / 1024:g}'
    assert argv[argv.index('--wall') + 1] == '120'
    assert argv[argv.index('--cpu') + 1] == str(CAPPED_CPU)
    assert argv[argv.index('--') + 1 :] == ['python', '-c', 'import x']
    assert allowed > 120 + CAPPED_QUEUE_S, 'the wrapper must outlive the wait and the wall it hands to the box'


def _boxing(what: object, ran: Ran) -> SystemdProcessManager:
    """A manager whose box records *what* (``None``: the box crashed) and whose runner answers *ran*."""

    def run(argv: list[str], _timeout: int, _cwd: str | None) -> Ran:
        record(argv, what)
        return ran

    return SystemdProcessManager(runner=run)


@pytest.mark.parametrize(
    ('what', 'said'),
    [(Refused('cpu: wants 1 of 0'), 'box refused'), (ended(-9, 'memory'), 'box killed'), (None, 'box crashed')],
)
def test_a_capped_run_the_box_ended_is_a_failure_naming_why(what: object, said: str) -> None:
    ran = _boxing(what, Ran(code=0, out='x')).run_capped(['true'], memory_max='600M', timeout=5)
    assert ran.code == -1
    assert said in ran.err


@pytest.mark.parametrize('own', [69, 137])
def test_a_capped_command_exiting_a_former_box_sentinel_keeps_its_own_code(own: int) -> None:
    """PLANTED (SR-20261015-002): the box recorded the command's own exit, so its code is the command's."""
    ran = _boxing(ended(own), Ran(code=own, out='x')).run_capped(['true'], memory_max='600M', timeout=5)
    assert (ran.code, ran.out) == (own, 'x')


@pytest.mark.parametrize(('ceiling', 'gb'), [('600M', 600 / 1024), ('2G', 2.0), ('512k', 512 / 1024**2)])
def test_a_ceiling_reads_in_binary_units(ceiling: str, gb: float) -> None:
    assert ceiling_gb(ceiling) == pytest.approx(gb, rel=1e-12, abs=0.0)  # GB; an exact binary fraction


def test_a_ceiling_without_a_unit_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match='K/M/G/T'):
        ceiling_gb('600')


def test_a_failing_command_is_a_ran_not_an_exception() -> None:
    """A refusal is an outcome to report; unwinding would take the cycle down with it."""
    result = subprocess_runner([sys.executable, '-c', 'raise SystemExit(7)'], 30, None)
    assert result.ok is False
    assert result.code == 7


def test_a_command_that_cannot_be_run_reports_rather_than_raises() -> None:
    """A missing binary is the ordinary case on a host that is not the deployment target."""
    result = subprocess_runner(['definitely-not-a-binary-xyz'], 30, None)
    assert result.ok is False
    assert 'could not run' in result.err


def test_a_child_does_not_inherit_the_managers_notify_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """A SUBPROCESS MUST NOT BE ABLE TO SPEAK AS THE SUPERVISOR.

    Every fork goes through `subprocess_runner`, and every one would otherwise inherit
    `$NOTIFY_SOCKET` -- measured on the host the moment the watchdog went live, as notification
    messages arriving from CHILD pids. `NotifyAccess=main` is the only reason those were harmless,
    and widening it to `all` would let a subprocess satisfy the check-in whose whole job is to prove
    the DAEMON is still working. The class goes by removing the variable here, in the one place that
    owns every fork -- rather than by naming an offender the journal cannot name either, since it
    records a pid and the pid is gone before anybody reads it.
    """
    monkeypatch.setenv(NOTIFY_SOCKET, '/run/systemd/notify')
    ran = subprocess_runner(
        [sys.executable, '-c', 'import os; print(os.environ.get("NOTIFY_SOCKET", "absent"))'],
        30,
        None,
    )
    assert ran.ok
    assert ran.out.strip() == 'absent', "a child could have notified on the supervisor's behalf"


def test_a_silent_failure_still_says_something() -> None:
    """A log line reading 'exit 1 with no output' beats an empty one."""
    assert Ran(code=1).detail() == 'exit 1 with no output'


def test_detail_prefers_the_stream_that_explains() -> None:
    """Standard error is where a refusal explains itself, so it is read first."""
    assert Ran(code=1, out='noise', err='the real reason').detail() == 'the real reason'


def test_a_commands_output_is_capped_rather_than_collected(tmp_path: Path) -> None:
    """THE REGRESSION. `capture_output=True` collects a command's whole output into THIS process.

    This process is the supervisor, whose own cgroup is 300M. The command runs inside a scope the
    kernel bounds -- the candidate build under 600M -- so a command that emits half a gigabyte, or
    a compiler reporting ten thousand errors, would blow the SUPERVISOR's ceiling instead and take
    the thing doing the supervising with it. Nothing reads the middle of a build log: `Ran.detail`
    keeps 200 characters for a line, and the numeric probes parse a leading token.
    """
    ran = subprocess_runner(
        [sys.executable, '-c', f'print("x" * {4 * OUTPUT_CAP})'],
        timeout=60,
        cwd=str(tmp_path),
    )
    assert ran.ok
    assert len(ran.out) <= OUTPUT_CAP, 'the caller received more than the cap'


def test_a_command_that_cannot_be_asked_is_not_a_unit_that_is_gone() -> None:
    """`is-active` exits 3 for inactive and 4 for unknown; -1 is this module's "could not run".

    Collapsing all three into False made `stop_unit` report success on a unit it never stopped --
    leaving a candidate's transient unit alive, holding the spare port every later candidate is
    started on.
    """

    def refuses(_argv: list[str], _timeout: int, _cwd: str | None) -> Ran:
        return Ran(code=-1, err='systemctl: command not found')

    stopped = SystemdProcessManager(runner=refuses).stop_unit('lab-supervise-candidate')
    assert stopped.ok is False, 'a unit nobody could ask about was reported stopped'
    assert 'could not ask' in stopped.err
