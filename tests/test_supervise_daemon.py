"""The loop: it does not overlap itself, it skips rather than fails, and it stops when asked."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from lab_commons.box import hold
from lab_commons.compute.model import Demand

from dev_lab.supervise import daemon
from dev_lab.supervise.cli import build_registry
from dev_lab.supervise.component import CheckContext, Component, Registry
from dev_lab.supervise.daemon import MIN_INTERVAL, Loop, serve
from dev_lab.supervise.loop import CycleResult
from dev_lab.supervise.process import SystemdProcessManager
from dev_lab.supervise.process.base import Ran
from dev_lab.supervise.state import StateStore
from dev_lab.supervise.verdict import Anomaly, CheckResult, Severity

_CLOCK = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
_PROJECT = Path('/srv/target')


class _Probe(Component):
    """Reports nothing, or one anomaly, depending on how it was built."""

    name = 'probe'
    description = 'a probe'

    def __init__(self, *, broken: bool = False) -> None:
        self.broken = broken
        self.runs = 0

    def check(self, ctx: CheckContext) -> CheckResult:
        """Count the call and report."""
        self.runs += 1
        if self.broken:
            return CheckResult(anomalies=[Anomaly(kind='down', severity=Severity.WARNING, message='down')])
        return CheckResult()


def _manager() -> SystemdProcessManager:
    def run(_argv: list[str], _timeout: int, _cwd: str | None) -> Ran:
        return Ran(code=0)

    return SystemdProcessManager(runner=run)


def _loop(tmp_path: Path, probe: Component) -> Loop:
    registry = Registry()
    registry.register(probe)
    config = {
        'target': {'name': 'unit-test'},
        'cycle': {'interval': 300, 'check_timeout': 30},
        'alerts': {},
        'components': {probe.name: {}},
    }
    return Loop(
        registry=registry,
        store=StateStore(tmp_path / 'state.json'),
        config=config,
        project=_PROJECT,
        manager=_manager(),
    )


def test_the_interval_is_floored_so_a_typo_cannot_make_a_busy_loop(tmp_path: Path) -> None:
    """An interval of one second is a supervisor competing with the service it supervises."""
    loop = _loop(tmp_path, _Probe())
    loop.config['cycle']['interval'] = 1
    assert loop.interval() == MIN_INTERVAL


def test_one_cycle_runs_the_checks(tmp_path: Path) -> None:
    """The loop's unit of work is the cycle, and it is the same one the CLI runs."""
    probe = _Probe()
    result = _loop(tmp_path, probe).once(_CLOCK)
    assert result is not None
    assert result.status == 'healthy'
    assert probe.runs == 1


def test_a_cycle_that_finds_the_seat_taken_skips_rather_than_fails(tmp_path: Path) -> None:
    """A refusal is not a fault, and no work is done here either.

    The other cycle is the one doing the work, which is why the seat is taken before measuring.
    """
    probe = _Probe()
    loop = _loop(tmp_path, probe)
    with hold(Demand({'supervise_unit_test': 1, 'cpu': 0, 'mem_gb': 0.0}), 60, 'another cycle', 0.0, key='k'):
        assert loop.once(_CLOCK) is None
    assert probe.runs == 0, 'the seat is taken before any work, so no check should have run'


def test_serve_once_runs_one_cycle_and_returns(tmp_path: Path) -> None:
    """A host driven by a systemd timer wants one cycle per invocation, not a daemon."""
    probe = _Probe()
    seen: list[CycleResult] = []
    code = serve(_loop(tmp_path, probe), once=True, on_cycle=lambda result, _at: seen.append(result))
    assert probe.runs == 1
    assert len(seen) == 1
    assert code == 0


def test_a_daemon_flushes_what_it_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """THE REGRESSION. A buffered log from a process that never exits is not a log.

    `emit` does not flush by default, which is right for a command that exits: the interpreter
    flushes on the way out. A supervisor does not exit, and its stdout is a pipe to the journal,
    so the default is BLOCK buffering -- one short line every few minutes leaves an 8 KB buffer
    days away from filling.

    Measured on the host: every `supervise:` line in the journal appeared in the same second as a
    restart, because the restart was the only thing that flushed it. The cycle times read off
    those lines were the times of the restarts, and a healthy daemon looked exactly like one that
    had never run.
    """
    flushed: list[bool] = []
    real = daemon.emit

    def _record(text: object = '', *, err: bool = False, flush: bool = False) -> None:
        flushed.append(flush)
        real(text, err=err, flush=flush)

    monkeypatch.setattr(daemon, 'emit', _record)
    serve(_loop(tmp_path, _Probe()), once=True)
    # NOT `== [True]`, WHICH PINNED THE COUNT AND NOT THE PROPERTY. The daemon now says whether the
    # manager is watching before it runs its first cycle, so a count would have to be edited every
    # time it gains a line -- and the count was never the point. What must hold is that NO line the
    # daemon writes goes out unflushed, however many there are.
    assert flushed, 'the daemon wrote nothing at all, so this proves nothing'
    assert all(flushed), 'the daemon logged without flushing'


def test_serve_counts_the_cycles_that_found_something_wrong(tmp_path: Path) -> None:
    """The exit status has to carry the answer, because a timer reads nothing else."""
    code = serve(_loop(tmp_path, _Probe(broken=True)), once=True)
    assert code == 1


def test_the_loop_calls_back_once_per_cycle(tmp_path: Path) -> None:
    """The callback is how a journal gets written, and it must fire once per result."""
    seen: list[datetime] = []
    serve(_loop(tmp_path, _Probe()), once=True, on_cycle=lambda _r, at: seen.append(at), clock=lambda: _CLOCK)
    assert seen == [_CLOCK]


def test_a_stop_flag_ends_the_loop_before_it_starts_work(tmp_path: Path) -> None:
    """A signal set between cycles must end the loop rather than run one more."""
    loop = _loop(tmp_path, _Probe())
    loop.stop.set()
    assert list(loop.cycles(lambda: _CLOCK)) == []


def test_the_loop_exits_once_what_it_loaded_has_changed_on_disk(tmp_path: Path) -> None:
    """THE STALE-SUPERVISOR DEFECT, as a control.

    A deployment installs its own units and can upgrade the kit a running supervisor executes from;
    a Python process keeps the modules it imported at startup regardless. Measured on the host on
    2026-10-03: a kit fix was deployed, the daemon kept the old one, and two cycles were recorded
    under the OLD rules before somebody restarted it by hand.

    The remedy is to EXIT, not to restart in place: asking the manager to replace us is a process
    supervised by a process manager behaving correctly, and restarting from inside would kill the
    writer of the state this cycle just produced.
    """
    probe = _Probe()
    loop = _loop(tmp_path, probe)
    # THE FLOOR IS THE POINT OF THE INTERVAL, SO THE TEST PAYS ONE OF THEM: the loop waits between
    # cycles, and a signature that has not moved yet must not shortcut that wait. Five seconds is
    # `MIN_INTERVAL`, which is as cheap as this can honestly be made.
    loop.config['cycle']['interval'] = MIN_INTERVAL
    signatures = iter(['before', 'before', 'after'])
    loop.definition = lambda: next(signatures)

    cycles = list(loop.cycles(lambda: _CLOCK))

    assert len(cycles) == 2, 'the cycle in flight finishes, and the one after it does not start'
    assert probe.runs == 2, 'every cycle that started ran its checks'
    assert loop.stop.is_set(), 'the loop asked to be replaced rather than deciding for the manager'


def test_a_definition_that_has_not_moved_does_not_end_the_loop(tmp_path: Path) -> None:
    """The other side: an unchanged signature must never be a reason to stop.

    Driven one step and then closed rather than drained -- draining would sit in the loop's own
    interval wait, which is the behaviour this test is NOT about.
    """
    loop = _loop(tmp_path, _Probe())
    loop.definition = lambda: 'unchanged'
    steps = loop.cycles(lambda: _CLOCK)
    next(steps)
    assert not loop.stop.is_set()
    steps.close()


def test_a_signature_moves_with_a_named_file_and_not_with_a_missing_one(tmp_path: Path) -> None:
    """A DELETED FILE IS A CHANGE; an unreadable one is not the same as an absent one.

    Reporting a path that cannot be read as nothing would make the one case that most needs a
    replace -- the unit is gone -- the one case that looks like no change at all.
    """
    project = tmp_path
    (project / 'unit.service').write_text('Restart=always\n', encoding='utf-8')
    loaded = daemon.definition_signature(project, ['unit.service'])

    assert daemon.definition_signature(project, ['unit.service']) == loaded, 're-reading is stable'

    (project / 'unit.service').write_text('Restart=on-failure\n', encoding='utf-8')
    assert daemon.definition_signature(project, ['unit.service']) != loaded, 'content moved'

    (project / 'unit.service').unlink()
    gone = daemon.definition_signature(project, ['unit.service'])
    assert gone != loaded, 'a deleted file is a change like any other'
    assert 'FileNotFoundError' in gone, 'the reason travels, so the next reader is not misled'


def test_build_registry_takes_remedies_and_sections_from_the_config() -> None:
    """A target contributes both through the same file, and neither is smuggled through the other."""
    registry = build_registry(
        {
            'components': {'probe': {'enabled': True}},
            'remedies': {'down': [{'action': 'restart'}]},
        }
    )
    assert registry.remedies('down')[0].action == 'restart'


def test_build_registry_refuses_a_chain_that_names_no_action() -> None:
    """Caught while assembling, not in the middle of applying a remedy."""
    with pytest.raises(ValueError, match='names no action'):
        build_registry({'components': {}, 'remedies': {'down': [{'on': 'critical'}]}})
