"""One cycle end to end: measure, act, say -- and the three ways it refuses to do any of them."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import pytest
from _box_fake import boxed_as_run
from lab_commons.box import Refused, hold
from lab_commons.compute.model import Demand

from dev_lab.supervise.alert import Notifier
from dev_lab.supervise.component import ActionContext, CheckContext, Component, Handler, Registry
from dev_lab.supervise.loop import UNCONFIGURED, CycleResult, run_cycle
from dev_lab.supervise.process import SystemdProcessManager
from dev_lab.supervise.process.base import Ran
from dev_lab.supervise.process.systemd import ceiling_gb
from dev_lab.supervise.state import StateStore
from dev_lab.supervise.verdict import Action, Anomaly, CheckResult, Condition, RemedyStep, Severity

_CLOCK = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
_PROJECT = Path('/srv/target')


class _Probe(Component):
    """Reports whatever it was constructed with."""

    name = 'probe'
    description = 'a probe'
    anomalies: ClassVar[list[Anomaly]] = []
    metrics: ClassVar[dict[str, float]] = {}

    def check(self, ctx: CheckContext) -> CheckResult:
        """Return the canned result."""
        return CheckResult(metrics=dict(self.metrics), anomalies=list(self.anomalies))


class _Broken(Component):
    """Raises instead of reporting, which is a component a cycle must survive."""

    name = 'broken'
    description = 'a component that raises'

    def check(self, ctx: CheckContext) -> CheckResult:
        """Fail."""
        message = 'the probe itself is broken'
        raise RuntimeError(message)


class _Hanging(Component):
    """Never answers."""

    name = 'hanging'
    description = 'a component that hangs'

    def check(self, ctx: CheckContext) -> CheckResult:
        """Sleep past any reasonable wall."""
        time.sleep(5)
        return CheckResult()


class _Deployer(Component):
    """Declares one action it implements, and one chain reaching it."""

    name = 'deployer'
    description = 'a component that acts'

    def check(self, ctx: CheckContext) -> CheckResult:
        """Report one anomaly for the chain to act on."""
        ctx.state['seen_by_check'] = True
        return CheckResult(anomalies=[Anomaly(kind='stale', severity=Severity.CRITICAL, message='stale build')])

    def actions(self) -> dict[str, Action]:
        """Declare an implemented action and a command action."""
        return {
            'refresh': Action(description='implemented'),
            'shout': Action(description='a command', command='echo hi'),
        }

    def handlers(self) -> dict[str, Handler]:
        """Implement one of them."""

        def refresh(action_ctx: ActionContext) -> bool:
            _Deployer.calls.append('refresh')
            _Deployer.seen_config = dict(action_ctx.config)
            _Deployer.action_state = action_ctx.state
            return True

        return {'refresh': refresh}

    def remedies(self) -> dict[str, list[RemedyStep]]:
        """Reach the implemented action for the anomaly this component reports."""
        return {'stale': [RemedyStep(action='refresh')]}

    calls: ClassVar[list[str]] = []
    seen_config: ClassVar[dict[str, Any]] = {}
    check_state: ClassVar[dict[str, Any]] = {}
    action_state: ClassVar[dict[str, Any]] = {}


class _Reply:
    """A canned HTTP reply."""

    status = 200

    def read(self, amt: int | None = None) -> bytes:
        """Return the body."""
        return b'ok'


class _Connection:
    """Records nothing and answers 200."""

    def request(self, method: str, path: str, body: bytes, headers: dict[str, str]) -> None:
        """Accept the request, and do nothing with it."""

    def getresponse(self) -> _Reply:
        """Return the canned reply."""
        return _Reply()

    def close(self) -> None:
        """Close, which for a fake is nothing at all."""


class _Transport:
    """A transport that remembers what it was asked for."""

    def __init__(self) -> None:
        self.hosts: list[tuple[str, float]] = []
        self.schemes: list[str] = []

    def __call__(self, scheme: str, host: str, timeout: float) -> _Connection:
        self.schemes.append(scheme)
        self.hosts.append((host, timeout))
        return _Connection()


def _manager(seen: list[tuple[list[str], int, str | None]]) -> SystemdProcessManager:
    def run(argv: list[str], timeout: int, cwd: str | None) -> Ran:
        seen.append((argv, timeout, cwd))
        return boxed_as_run(argv, Ran(code=0, out='done'))

    return SystemdProcessManager(runner=run)


def _registry(*components: Component) -> Registry:
    registry = Registry()
    for component in components:
        registry.register(component)
    return registry


def _config(**cycle: object) -> dict[str, Any]:
    base: dict[str, Any] = {'interval': 300, 'check_timeout': 30}
    base.update(cycle)
    # A CONFIGURED SUPERVISOR DECLARES WHAT IT WATCHES, which is also what makes the
    # `unconfigured` refusal meaningful: a config with no sections at all is now the
    # thing that refusal is about, and this harness describes the ordinary case.
    return {
        'target': {'name': 'unit-test'},
        'cycle': base,
        'alerts': {},
        'components': {'probe': {}, 'deployer': {}, 'broken': {}, 'hanging': {}},
    }


@pytest.fixture(autouse=True)
def _clean_components() -> None:
    """Each test sees only the canned state it set, not the previous test's."""
    _Probe.anomalies = []
    _Probe.metrics = {}
    _Deployer.calls = []
    _Deployer.seen_config = {}
    _Deployer.check_state = {}
    _Deployer.action_state = {}


def _run(registry: Registry, tmp_path: Path, config: dict[str, Any] | None = None, **kwargs: object) -> CycleResult:
    manager = kwargs.pop('manager', _manager([]))
    return run_cycle(
        registry,
        StateStore(tmp_path / 'state.json'),
        config or _config(),
        _PROJECT,
        manager,
        clock=_CLOCK,
        **kwargs,
    )


def test_a_config_with_no_component_sections_is_not_healthy(tmp_path: Path) -> None:
    """THE REGRESSION, and the guard against it had NO TEST AT ALL, which is why it was dead code.

    `Registry.enabled()` is default-ON for every registered component, so the arm refusing a run
    with nothing enabled was reachable only by a config that explicitly disabled all eight -- an
    arrangement nobody writes. What actually happens is a config with NO sections: a missing file,
    an empty one, or a header typed with the wrong name. Eight components then run with nothing to
    check, each reports clean because there is nothing for it to find wrong, and the cycle comes
    back HEALTHY over a supervisor watching nothing at all.
    """
    config = _config()
    config['components'] = {}
    result = _run(_registry(_Probe()), tmp_path, config)
    assert result.status != 'healthy'
    assert [one.kind for one in result.anomalies] == [UNCONFIGURED]


def test_a_config_that_disables_every_component_is_not_healthy(tmp_path: Path) -> None:
    """The arrangement the guard always covered: sections that all say `enabled = false`."""
    config = _config()
    config['components'] = {'probe': {'enabled': False}}
    result = _run(_registry(_Probe()), tmp_path, config)
    assert result.status != 'healthy'
    assert [one.kind for one in result.anomalies] == [UNCONFIGURED]


def test_a_quiet_cycle_is_healthy_and_records_when(tmp_path: Path) -> None:
    """The clean case: nothing wrong, counters dropped, and the moment written down."""
    result = _run(_registry(_Probe()), tmp_path)
    assert result.status == 'healthy'
    assert result.anomalies == []
    assert result.state['last_quiet'] == _CLOCK.isoformat()
    assert (tmp_path / 'state.json').is_file()


def test_a_quiet_cycle_clears_a_counter_a_previous_one_raised(tmp_path: Path) -> None:
    """A condition that cleared must stop counting, or escalation fires on a healthy target."""
    store = StateStore(tmp_path / 'state.json')
    _Probe.anomalies = [Anomaly(kind='bad', severity=Severity.WARNING, message='bad')]
    run_cycle(_registry(_Probe()), store, _config(), _PROJECT, _manager([]), clock=_CLOCK)
    assert store.read()['anomalies'] != {}
    _Probe.anomalies = []
    run_cycle(_registry(_Probe()), store, _config(), _PROJECT, _manager([]), clock=_CLOCK)
    assert store.read()['anomalies'] == {}


def test_one_source_clearing_does_not_wait_for_every_other_to_clear(tmp_path: Path) -> None:
    """THE REGRESSION. Clearing was all-or-nothing, so a fixed fault stayed on the books.

    The counters were cleared only when a cycle came back with NO anomalies at all. One live
    condition therefore kept every dead one alive: a source whose fault had been repaired still
    carried its frozen count and its last alert time, indefinitely, and its escalation clock kept
    ticking against a healthy component. Measured on the real host before this was fixed -- a
    health probe that had been silently broken by the transport defect still held an entry an
    hour after the repair, because two unrelated anomalies were still firing.
    """
    store = StateStore(tmp_path / 'state.json')
    _Probe.anomalies = [Anomaly(kind='bad', severity=Severity.WARNING, message='bad')]
    registry = _registry(_Probe(), _Deployer())
    run_cycle(registry, store, _config(), _PROJECT, _manager([]), clock=_CLOCK)
    assert set(store.read()['anomalies']) == {'probe.bad', 'deployer.stale'}

    _Probe.anomalies = []
    run_cycle(registry, store, _config(), _PROJECT, _manager([]), clock=_CLOCK)
    assert set(store.read()['anomalies']) == {'deployer.stale'}


def test_an_anomaly_is_stamped_with_its_component(tmp_path: Path) -> None:
    """The stamped source is the key every other rule is keyed by."""
    _Probe.anomalies = [Anomaly(kind='bad', severity=Severity.WARNING, message='bad')]
    result = _run(_registry(_Probe()), tmp_path)
    assert result.status == 'degraded'
    assert result.anomalies[0].source == 'probe.bad'


def test_a_component_that_raises_becomes_a_critical_anomaly(tmp_path: Path) -> None:
    """A probe that cannot run is worse than one reporting a problem: nothing is watching."""
    result = _run(_registry(_Broken()), tmp_path)
    assert result.status == 'degraded'
    assert result.anomalies[0].kind == 'check_failed'
    assert result.anomalies[0].severity is Severity.CRITICAL
    assert 'RuntimeError' in result.anomalies[0].message


def test_a_component_that_never_answers_is_bounded_by_the_wall(tmp_path: Path) -> None:
    """THE BUG THIS TEST FOUND: a `with` pool joins its thread on exit, so the wall bounded nothing."""
    started = time.monotonic()
    result = _run(_registry(_Hanging()), tmp_path, config=_config(check_timeout=1))
    elapsed = time.monotonic() - started
    assert result.anomalies[0].kind == 'check_failed'
    assert 'did not answer' in result.anomalies[0].message
    assert elapsed < 4, f'the cycle waited {elapsed:.1f}s for a check it had already given up on'


def test_an_implemented_action_runs(tmp_path: Path) -> None:
    """A component that acts in Python says so, and the chain reaches it."""
    result = _run(_registry(_Deployer()), tmp_path)
    assert _Deployer.calls == ['refresh']
    assert [attempt.action for attempt in result.attempts] == ['refresh']
    assert result.attempts[0].ok is True


def test_an_action_shares_the_state_slice_its_own_check_reads(tmp_path: Path) -> None:
    """THE REGRESSION, and it silently disabled the circuit breaker.

    A check is handed `state['components'][component]`; an action was handed a SHARED
    `state['components']['actions']`. So the deploy component read its deployment history out of one
    dict and wrote the snapshot into another: `check` never saw a verified release, `no_verified_release`
    warned forever against a target that had deployed successfully, and -- the costly half --
    `failure_streak` counted failures that had been recorded somewhere it never looked, so a release
    could fail without limit and the escalation the operator asked for could never fire.

    One component, one slice. A chain declared by a configuration override has no owning component
    and keeps the shared slice, which is what having no owner means.
    """
    _run(_registry(_Deployer()), tmp_path)
    assert _Deployer.action_state.get('seen_by_check') is True, 'the action cannot see what the check wrote'


def test_an_action_is_handed_its_own_component_s_config(tmp_path: Path) -> None:
    """THE REGRESSION, and it made every deployment refuse itself.

    `ActionContext` documents `config` as "this component's own section", and the acting path
    passed the WHOLE components table instead. A component that read its section out of it found
    an empty mapping, so the deploy component built an empty plan and refused every release with
    "the deploy plan is incomplete, missing: repositories, unit, health, install, run, probe" --
    naming six settings that were present in the file the whole time.
    """
    config = _config()
    config['components'] = {'deployer': {'token': 'x'}}
    _run(_registry(_Deployer()), tmp_path, config)
    assert _Deployer.seen_config == {'token': 'x'}


def test_a_command_action_runs_under_a_ceiling(tmp_path: Path) -> None:
    """Every remedy command is capped, so a reinstall cannot take the host down while we watch."""
    seen: list[tuple[list[str], int, str | None]] = []

    class _Cmd(_Deployer):
        def remedies(self) -> dict[str, list[RemedyStep]]:
            """Reach the command action instead."""
            return {'stale': [RemedyStep(action='shout')]}

    result = _run(_registry(_Cmd()), tmp_path, manager=_manager(seen))
    assert result.attempts[0].ok is True
    argv = seen[0][0]
    assert argv[1:4] == ['-m', 'lab_commons.box', 'run']
    assert argv[argv.index('--mem-gb') + 1] == f'{ceiling_gb("400M"):g}'
    assert argv[-4:] == ['--', 'sh', '-c', 'echo hi']


def test_a_step_gated_off_is_recorded_as_skipped_not_failed(tmp_path: Path) -> None:
    """A report must tell 'we chose not to' from 'we tried and it did not work'."""

    class _Gated(_Deployer):
        def remedies(self) -> dict[str, list[RemedyStep]]:
            """Gate the only step on a severity this anomaly does not have."""
            return {'stale': [RemedyStep(action='refresh', on='warning')]}

    result = _run(_registry(_Gated()), tmp_path)
    assert result.attempts[0].skipped is True
    assert result.attempts[0].ran is False
    assert _Deployer.calls == []


def test_a_step_whose_condition_is_not_met_is_skipped(tmp_path: Path) -> None:
    """The gate is data, and a condition that does not hold means the step does not run."""

    class _Conditional(_Deployer):
        def remedies(self) -> dict[str, list[RemedyStep]]:
            """Gate the step on a metric this check does not report."""
            return {'stale': [RemedyStep(action='refresh', condition=Condition(metric='commits', op='>', value=0))]}

    result = _run(_registry(_Conditional()), tmp_path)
    assert result.attempts[0].skipped is True
    assert 'condition not met' in result.attempts[0].detail


def test_an_action_nobody_declares_is_reported(tmp_path: Path) -> None:
    """A chain naming an action that does not exist must not look like a step that ran."""

    class _Missing(_Deployer):
        def remedies(self) -> dict[str, list[RemedyStep]]:
            """Name an action no component declares."""
            return {'stale': [RemedyStep(action='nonexistent')]}

    result = _run(_registry(_Missing()), tmp_path)
    assert result.attempts[0].ok is False
    assert 'no action named' in result.attempts[0].detail


def test_dry_run_touches_nothing(tmp_path: Path) -> None:
    """A rehearsal must not perform the act it is rehearsing."""
    seen: list[tuple[list[str], int, str | None]] = []
    result = _run(_registry(_Deployer()), tmp_path, manager=_manager(seen), dry_run=True)
    assert _Deployer.calls == []
    assert seen == []
    assert result.deliveries == []
    assert [attempt.action for attempt in result.attempts] == ['refresh']


def test_a_second_cycle_on_one_target_is_refused_by_its_seat(tmp_path: Path) -> None:
    """THE ONLY LOCK. The kit forbids a pid file or a heartbeat as a second definition of it."""
    seat = Demand({'supervise_unit_test': 1, 'cpu': 0, 'mem_gb': 0.0}), 60
    with hold(*seat, 'another cycle', 0.0, key='k'), pytest.raises(Refused):
        _run(_registry(_Probe()), tmp_path)


def test_a_warranted_notice_reaches_the_channel(tmp_path: Path) -> None:
    """The end of the chain: something was wrong, and a human was told."""
    _Probe.anomalies = [Anomaly(kind='bad', severity=Severity.CRITICAL, message='bad')]
    transport = _Transport()
    config = _config()
    config['alerts'] = {'telegram': {'enabled': True, 'token': 't', 'chat': 'c'}}
    notifier = Notifier(config=config, transport=transport)
    result = _run(_registry(_Probe()), tmp_path, config=config, notifier=notifier)
    assert [delivery.channel for delivery in result.deliveries] == ['telegram']
    assert result.deliveries[0].ok is True
    assert transport.hosts == [('api.telegram.org', 15.0)]


def test_a_condition_that_does_not_hold_holds_the_step(tmp_path: Path) -> None:
    """The gate is data on the step, read against the metrics this cycle measured."""

    class _Conditional(_Deployer):
        def remedies(self) -> dict[str, list[RemedyStep]]:
            """Gate the step on a metric this check does not report."""
            return {'stale': [RemedyStep(action='refresh', condition=Condition(metric='commits', op='>', value=0))]}

    result = _run(_registry(_Conditional()), tmp_path)
    assert result.attempts[0].skipped is True
    assert 'condition not met' in result.attempts[0].detail


def test_the_state_a_cycle_reports_is_the_state_it_wrote(tmp_path: Path) -> None:
    """A caller reading the result must see what a later cycle will read."""
    store = StateStore(tmp_path / 'state.json')
    _Probe.anomalies = [Anomaly(kind='bad', severity=Severity.WARNING, message='bad')]
    result = run_cycle(_registry(_Probe()), store, _config(), _PROJECT, _manager([]), clock=_CLOCK)
    assert result.state == store.read()
    assert result.state['anomalies']['probe.bad']['consecutive'] == 1
