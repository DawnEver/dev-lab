"""The deployment sequence: prove before activating, and never leave the target down."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest
from lab_commons.outcomes import Status

from dev_lab.supervise import deploy as deploy_module
from dev_lab.supervise.alert import Transport
from dev_lab.supervise.component import ActionContext, CheckContext, Registry
from dev_lab.supervise.components.deploy import Deploy, _settle
from dev_lab.supervise.deploy import PhaseResult, Plan, activate, fetch, preflight, probe, verify
from dev_lab.supervise.deploy import deploy as run_deploy
from dev_lab.supervise.process.base import Ran
from dev_lab.supervise.release import Snapshot, failure_streak, history, record_success
from dev_lab.supervise.verdict import Severity

_PROJECT = Path('/srv/target')


class _Reply:
    """A canned HTTP reply."""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body

    def read(self, amt: int | None = None) -> bytes:
        """Return the body."""
        return self._body.encode('utf-8')


class _Scripted:
    """A process manager that answers from a table keyed by a fragment of the command.

    Records every command it was asked to run, so a test can assert what a phase DID as well as
    what it concluded -- which is the only way to catch a phase that reports success without
    having done anything.
    """

    def __init__(self, responses: dict[str, Ran] | None = None, reply: tuple[int, str] = (200, '{}')) -> None:
        self.responses = responses or {}
        self.reply = reply
        self.ran: list[str] = []
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.restarts: list[str] = []

    def _answer(self, argv: list[str]) -> Ran:
        key = ' '.join(argv)
        self.ran.append(key)
        for fragment, ran in self.responses.items():
            if fragment in key:
                return ran
        return Ran(code=0, out='')

    def is_active(self, unit: str) -> bool:
        """Report every unit as active."""
        return True

    def start(self, unit: str) -> Ran:
        """Record a start."""
        return Ran(code=0)

    def stop(self, unit: str) -> Ran:
        """Record a stop."""
        return Ran(code=0)

    def restart(self, unit: str) -> Ran:
        """Record a restart."""
        self.restarts.append(unit)
        return self.responses.get('restart', Ran(code=0))

    def run_capped(self, argv: list[str], *, memory_max: str, timeout: int, cwd: str | None = None) -> Ran:
        """Record and answer a command."""
        return self._answer(argv)

    def start_capped(
        self,
        argv: list[str],
        *,
        memory_max: str,
        name: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> Ran:
        """Record a detached start."""
        self.started.append(' '.join(argv))
        return self.responses.get('start_capped', Ran(code=0))

    def stop_unit(self, name: str) -> Ran:
        """Record a stop by name."""
        self.stopped.append(name)
        return Ran(code=0)


def _transport(status: int = 200, body: str = '{"status": "healthy", "commit": "abc12345"}') -> Transport:
    """Return a transport answering with one canned reply."""

    class _Connection:
        def __init__(self) -> None:
            self.sent: list[str] = []

        def request(self, method: str, url: str, headers: dict[str, str] | None = None) -> None:
            self.sent.append(url)

        def getresponse(self) -> _Reply:
            return _Reply(status, body)

        def close(self) -> None:
            return None

    def make(_scheme: str, _host: str, _timeout: float) -> _Connection:
        return _Connection()

    return make


def _plan(**overrides: object) -> Plan:
    base: dict[str, Any] = {
        'repositories': {'main': '/srv/target'},
        'main': 'main',
        'unit': 'webapp',
        'health': 'https://x/health/',
        'health_timeout': 1,
        'install': 'make install-web',
        'run': '{python} -m app --port {port}',
        'probe': ['http://127.0.0.1:{port}/health/'],
        'ceiling': '600M',
        'keep': 3,
        'tolerance': 3,
    }
    base.update(overrides)
    return Plan.from_config(base, _PROJECT)


def _plan_config(**overrides: object) -> dict[str, Any]:
    """The component configuration a complete plan is read from."""
    config: dict[str, Any] = {
        'repositories': {'main': '/srv/target'},
        'main': 'main',
        'unit': 'webapp',
        'health': 'https://x/health/',
        'install': 'make install-web',
        'run': '{python} -m app --port {port}',
        'probe': ['http://127.0.0.1:{port}/health/'],
    }
    config.update(overrides)
    return config


def _ctx(manager: _Scripted, config: dict[str, Any] | None = None) -> ActionContext:
    return ActionContext(
        config=config if config is not None else {},
        shared={'cycle': {}},
        project=_PROJECT,
        manager=manager,
        registry=Registry(),
    )


def test_a_failed_fetch_is_not_a_release_to_deploy() -> None:
    """A fetch that did not happen says nothing about the remote -- least of all 'no change'."""
    manager = _Scripted({'fetch': Ran(code=1, err='offline')})
    outcome = fetch(_plan(), _ctx(manager))
    assert outcome.ok is False
    assert 'fetch failed' in outcome.detail


def test_a_fetch_reads_every_repository() -> None:
    """One repository left behind is a release that is half-applied by construction."""
    manager = _Scripted({'rev-parse': Ran(code=0, out='abc123\n')})
    outcome = fetch(_plan(repositories={'main': '/a', 'lib': '/b'}), _ctx(manager))
    assert outcome.ok is True
    assert outcome.commits == {'main': 'abc123', 'lib': 'abc123'}


def test_a_probe_refuses_a_candidate_that_answers_the_wrong_status() -> None:
    """The candidate gate is the whole reason a bad release can be caught without an outage."""
    assert probe(['http://x/'], _transport(500, '{}')).ok is False


def test_a_probe_refuses_a_candidate_that_answers_but_not_with_json() -> None:
    """A 200 saying nothing is not a 200 saying the right thing."""
    assert probe(['http://x/'], _transport(200, 'not json')).ok is False


def test_a_proven_candidate_is_started_and_stopped_on_its_own_port() -> None:
    """Nothing here touches the live target, which is what makes the gate worth having."""
    manager = _Scripted()
    outcome = preflight(
        _plan(install='true', probe=[]),
        _ctx(manager),
        {'main': 'abc123'},
        transport=_transport(),
        port=7002,
    )
    assert outcome.ok is True
    assert any('--port 7002' in one for one in manager.started), manager.started
    assert manager.stopped == ['lab-supervise-candidate']


def test_a_candidate_that_will_not_install_is_refused_before_anything_is_started() -> None:
    """The build failing is the cheapest possible discovery, and it must not reach the target."""
    manager = _Scripted({'make install-web': Ran(code=2, err='no such target')})
    outcome = preflight(_plan(), _ctx(manager), {'main': 'abc123'}, transport=_transport(), port=7002)
    assert outcome.ok is False
    assert 'installing the candidate failed' in outcome.detail
    assert manager.started == []
    assert manager.restarts == []


def test_the_candidate_gets_an_environment_before_it_is_installed() -> None:
    """THE REGRESSION, and it survived a rehearsal that had quietly done this step by hand.

    `preflight` starts the candidate with `{candidate}/.venv/bin/python` and never created that
    venv. On the host this was written for, `make install-web` is `uv pip install -e ".[web]"`,
    which refuses to run without one -- so EVERY release was refused with "No virtual environment
    found", and the rehearsal passed only because the venv had been built by hand first.
    """
    manager = _Scripted()
    outcome = preflight(
        _plan(venv='uv venv --python 3.12', install='true', probe=[]),
        _ctx(manager),
        {'main': 'abc123'},
        transport=_transport(),
        port=7002,
    )
    assert outcome.ok is True
    built = next(index for index, one in enumerate(manager.ran) if 'uv venv' in one)
    installed = next(index for index, one in enumerate(manager.ran) if one.endswith('true'))
    assert built < installed, manager.ran


def test_a_candidate_whose_environment_will_not_build_is_refused() -> None:
    """No environment means no install and no run, so it is refused where nothing is touched yet."""
    manager = _Scripted({'uv venv': Ran(code=1, err='no interpreter')})
    outcome = preflight(
        _plan(venv='uv venv --python 3.12'), _ctx(manager), {'main': 'abc123'}, transport=_transport(), port=7002
    )
    assert outcome.ok is False
    assert 'environment' in outcome.detail
    assert manager.started == []


def test_activation_provisions_the_host_between_the_install_and_the_restart() -> None:
    """THE DEPLOYMENT'S OWN DEFINITION IS PART OF THE RELEASE, SO IT HAS TO ARRIVE WITH IT.

    The units were installed by hand at cutover, which is the same divergence this deployment was
    rebuilt to remove: the units that ran were not necessarily the units in the commit. A unit
    change in the repository silently did nothing until somebody noticed.

    Order matters twice over. Provisioning runs AFTER the fast-forward so it installs the release's
    own unit files, and BEFORE the restart so the service comes back under the new definition.
    """
    manager = _Scripted()
    plan = _plan(install='true', provision='install -m 644 deploy/x.service /etc/systemd/system/')
    assert activate(plan, _ctx(manager), {'main': 'abc123'}).ok is True
    steps = [index for index, one in enumerate(manager.ran) if one.endswith('true') or 'install -m 644' in one]
    assert len(steps) == 2, manager.ran
    assert 'install -m 644' in manager.ran[steps[1]], 'provisioning ran before the install'
    assert manager.restarts == ['webapp']


def test_a_candidate_is_never_provisioned() -> None:
    """A CANDIDATE MUST NOT TOUCH THE HOST'S SYSTEMD.

    It is a build in a scratch directory being asked whether it can start. Installing its unit
    files, or anything else it ships, would let a release that is about to be refused change the
    machine that refused it.
    """
    manager = _Scripted()
    plan = _plan(install='true', probe=[], provision='install -m 644 deploy/x.service /etc/systemd/system/')
    preflight(plan, _ctx(manager), {'main': 'abc123'}, transport=_transport(), port=7002)
    assert not any('install -m 644' in one for one in manager.ran), manager.ran


def test_a_plan_with_no_environment_step_still_installs() -> None:
    """The step is optional: a target whose install makes its own environment is unchanged."""
    manager = _Scripted()
    outcome = preflight(
        _plan(install='true', probe=[]), _ctx(manager), {'main': 'abc123'}, transport=_transport(), port=7002
    )
    assert outcome.ok is True


def test_activation_fast_forwards_then_installs_then_restarts() -> None:
    """Three steps, in that order: a restart before the install serves the old environment."""
    manager = _Scripted()
    assert activate(_plan(), _ctx(manager), {'main': 'abc123'}).ok is True
    assert manager.restarts == ['webapp']
    assert any('make install-web' in one for one in manager.ran)


def test_a_diverged_repository_stops_activation() -> None:
    """A fast-forward that did not fast-forward must not be followed by a restart."""
    manager = _Scripted({'merge-base': Ran(code=1, err='not an ancestor')})
    outcome = activate(_plan(), _ctx(manager), {'main': 'abc123'})
    assert outcome.ok is False
    assert 'not abc123' in outcome.detail
    assert manager.restarts == []


def test_verification_insists_the_target_reports_the_release() -> None:
    """Up and serving the RIGHT commit are different facts, and only one of them is a deploy."""
    right = verify(
        _plan(), {'main': 'abc12345'}, transport=_transport(200, '{"status": "healthy", "commit": "abc12345"}')
    )
    assert right.ok is True
    wrong = verify(
        _plan(), {'main': 'abc12345'}, transport=_transport(200, '{"status": "healthy", "commit": "99999999"}')
    )
    assert wrong.ok is False
    assert 'expected abc12345' in wrong.detail


def test_verification_refuses_a_target_that_reports_itself_unhealthy() -> None:
    """A 200 is not health; the payload is."""
    assert verify(_plan(), {'main': 'abc'}, transport=_transport(200, '{"status": "degraded"}')).ok is False


def test_the_deploy_component_is_off_when_no_repository_is_configured() -> None:
    """An unconfigured deploy component is off, not broken -- and must not convict anything."""
    ctx = CheckContext(config={}, shared={}, state={}, project=_PROJECT, manager=_Scripted(), timeline={})
    result = Deploy().check(ctx)
    assert result.anomalies == []


def test_a_first_deployment_says_it_has_nowhere_to_roll_back_to() -> None:
    """The honest warning: the first release is the one that cannot be undone."""
    ctx = CheckContext(
        config={'repositories': {'main': '/srv/target'}},
        shared={},
        state={},
        project=_PROJECT,
        manager=_Scripted({'rev-parse': Ran(code=0, out='abc123\n')}),
        timeline={},
    )
    anomalies = Deploy().check(ctx).anomalies
    assert [one.kind for one in anomalies] == ['no_verified_release']
    assert anomalies[0].severity is Severity.WARNING


def _ctx_with(manager: _Scripted) -> CheckContext:
    """A check context with no verified release and one repository."""
    return CheckContext(
        config={'repositories': {'main': '/srv/target'}},
        shared={},
        state={},
        project=_PROJECT,
        manager=manager,
        timeline={},
    )


def test_a_target_that_has_never_deployed_can_still_see_a_release() -> None:
    """THE REGRESSION, and it deadlocked the first deployment of the host this was written for.

    A snapshot is written by a successful deploy; a deploy runs only on `release_available`; and
    `check` RETURNED as soon as it found no snapshot, so `release_available` was never reached. A
    target that had never deployed could therefore never deploy, and warned on every cycle while a
    pushed release waited. The warning is about ROLLBACK -- there is no floor if this fails -- and
    it is not a reason to refuse the only action that can create one.
    """
    manager = _Scripted({'origin/main': Ran(code=0, out='new12345\n'), 'HEAD': Ran(code=0, out='old12345\n')})
    kinds = [one.kind for one in Deploy().check(_ctx_with(manager)).anomalies]
    assert 'release_available' in kinds
    assert 'no_verified_release' in kinds, 'the rollback warning must survive the fix'


def test_a_target_already_running_the_remote_offers_nothing_to_deploy() -> None:
    """With no snapshot the baseline is WHAT IS RUNNING, or every cycle would redeploy the same commit."""
    manager = _Scripted({'origin/main': Ran(code=0, out='same1234\n'), 'HEAD': Ran(code=0, out='same1234\n')})
    kinds = [one.kind for one in Deploy().check(_ctx_with(manager)).anomalies]
    assert 'release_available' not in kinds
    assert 'no_verified_release' in kinds


def test_an_unreadable_checkout_is_not_a_release_to_deploy() -> None:
    """A baseline that cannot be read says nothing about the remote, so nothing may be concluded."""
    manager = _Scripted({'origin/main': Ran(code=0, out='new12345\n'), 'HEAD': Ran(code=1, err='not a git repository')})
    kinds = [one.kind for one in Deploy().check(_ctx_with(manager)).anomalies]
    assert 'release_available' not in kinds


def test_a_release_that_keeps_failing_escalates_rather_than_repeating() -> None:
    """THE CIRCUIT BREAKER IS NOT A BLACKLIST: it is retried, and the alert says how many times."""
    state: dict[str, Any] = {}
    record_success(state, Snapshot(main='old', libs='', at='t'))
    manager = _Scripted({'rev-parse': Ran(code=0, out='new12345\n')})
    ctx = CheckContext(
        config={'repositories': {'main': '/srv/target'}, 'tolerance': 2},
        shared={},
        state=state,
        project=_PROJECT,
        manager=manager,
        timeline={},
    )
    component = Deploy()
    assert [one.kind for one in component.check(ctx).anomalies] == ['release_available']
    state.setdefault('release_failures', []).extend([{'key': 'new12345|'}, {'key': 'new12345|'}])
    kinds = [one.kind for one in component.check(ctx).anomalies]
    assert 'release_failing' in kinds


def test_a_successful_deploy_records_what_it_verified() -> None:
    """Without this there is nothing to roll back to, which is how a second failure has no floor."""
    state: dict[str, Any] = {}
    manager = _Scripted({'rev-parse': Ran(code=0, out='abc12345\n')})
    ctx = _ctx(manager, _plan_config())
    ctx.state = state
    settled = Deploy(transport=_transport())._deploy(ctx)
    assert settled is True
    assert history(state)[-1].main == 'abc12345'


def test_an_incomplete_plan_is_refused_rather_than_run() -> None:
    """A plan with nothing in it would pass every phase and report deploying nothing at all."""
    outcome = run_deploy(
        _plan(install='', run='', probe=[], health='', unit=''),
        _ctx(_Scripted()),
        None,
        transport=_transport(),
        port=7002,
    )
    assert outcome.ok is False
    assert 'incomplete' in outcome.detail


def test_a_rolled_back_release_is_counted_as_a_failure_of_the_release_it_tried() -> None:
    """THE REGRESSION, and it killed the circuit breaker through the rollback door.

    When a release comes up wrong and the rollback works, the outcome's `commits` are the OLD
    release -- so `_settle` took the success branch, and `record_success` CLEARS the failure
    record. The release that failed was therefore never counted at all, and every earlier count
    was wiped with it. A release could fail on every cycle forever and `release_failing` -- the
    escalation that says "this has now failed five times" while still retrying -- could never fire.

    `PhaseResult.tried` exists for exactly this and says so in its own docstring: "recording the old
    release as the failure would make the circuit breaker count the wrong thing and never reach
    its threshold." The intent was written down and never read.
    """
    state: dict[str, Any] = {}
    ctx = _ctx(_Scripted(), _plan_config())
    ctx.state = state
    plan = Plan.from_config(_plan_config(), _PROJECT)
    rolled_back = PhaseResult(ok=True, detail='rolled back', commits={'main': 'old12345'}, tried={'main': 'new12345'})
    assert _settle(ctx, plan, rolled_back) is True, 'the target is serving something verified'
    assert failure_streak(state, Snapshot(main='new12345', libs='', at='')) == 1


def test_a_rollback_does_not_re_add_the_release_it_restored() -> None:
    """A RESTORED RELEASE IS NOT A NEWLY VERIFIED ONE.

    The release rolled back TO was already in the history -- it is where `previous` came from --
    so re-recording it would move it to the end for no reason and restamp it as verified now.
    """
    state: dict[str, Any] = {}
    record_success(state, Snapshot(main='old12345', libs='', at='2026-01-01T00:00:00+00:00'))
    ctx = _ctx(_Scripted(), _plan_config())
    ctx.state = state
    plan = Plan.from_config(_plan_config(), _PROJECT)
    rolled_back = PhaseResult(ok=True, detail='rolled back', commits={'main': 'old12345'}, tried={'main': 'new12345'})
    _settle(ctx, plan, rolled_back)
    assert [one.at for one in history(state)] == ['2026-01-01T00:00:00+00:00']


def test_a_deploy_that_fails_records_the_release_it_tried() -> None:
    """Recording the OLD release would make the breaker count the wrong thing forever."""
    state: dict[str, Any] = {}
    manager = _Scripted({'rev-parse': Ran(code=0, out='abc12345\n'), 'make install-web': Ran(code=2, err='broken')})
    ctx = _ctx(manager, _plan_config())
    ctx.state = state
    assert Deploy(transport=_transport())._deploy(ctx) is False
    assert state['release_failures'][-1]['key'].startswith('abc12345')


def test_a_failure_with_no_release_to_blame_records_no_release_failure() -> None:
    """THE REGRESSION, and it was found as `"key": "|"` in a host's live state file.

    A fetch that fails has no commit set to attribute anything to. The sequence passed an empty
    mapping to `_settle` anyway, which built a snapshot out of it -- `main=''`, `libs=''`, key
    `'|'` -- and recorded a failure of that. So the state accumulated failures of a release that
    does not exist, `failure_streak` never counted them against anything real, and a reader
    opening the file saw a release they could not name.
    """
    state: dict[str, Any] = {}
    manager = _Scripted({'fetch': Ran(code=1, err='offline')})
    ctx = _ctx(manager, _plan_config())
    ctx.state = state
    assert Deploy(transport=_transport())._deploy(ctx) is False
    assert 'release_failures' not in state, state.get('release_failures')


def test_an_unreadable_remote_is_reported_rather_than_called_no_release() -> None:
    """THE SECOND REGRESSION, and this one made a deployment blind for an hour.

    `_remote` returns None when a fetch fails, and the check read that exactly like "the remote
    holds nothing new". When the daemon's git could not reach the repository at all -- it had no
    `HOME`, so the ownership exemption was unreadable -- every cycle reported no release to deploy,
    the anomaly list stayed empty, and a target running stale code looked identical to an
    up-to-date one. The supervisor cannot supervise through an unreadable remote, and that fact
    belongs in the anomaly list rather than in the gap between two `None`s.
    """
    manager = _Scripted({'fetch': Ran(code=1, err='offline')})
    kinds = [one.kind for one in Deploy().check(_ctx_with(manager)).anomalies]
    assert 'remote_unreadable' in kinds


def test_a_readable_remote_says_nothing_about_being_readable() -> None:
    """The refusal is for a remote that could not be read, not for every check."""
    manager = _Scripted({'origin/main': Ran(code=0, out='same1234\n'), 'HEAD': Ran(code=0, out='same1234\n')})
    kinds = [one.kind for one in Deploy().check(_ctx_with(manager)).anomalies]
    assert 'remote_unreadable' not in kinds


def test_a_phase_result_reads_in_the_one_status_vocabulary() -> None:
    """Plan A1.6: a deploy phase speaks lab_commons.outcomes; a failure is RETRYABLE (the breaker counts it)."""
    assert PhaseResult(ok=True).status is Status.OK
    assert PhaseResult(ok=False, detail='x').status is Status.ERROR


def test_the_generic_name_is_gone_from_deploy() -> None:
    assert 'PhaseResult' in deploy_module.__all__
    with pytest.raises(AttributeError):
        _ = importlib.import_module(deploy_module.__name__).Outcome
