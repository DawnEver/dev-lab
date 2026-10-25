"""The component contract, and the two implicit ones the predecessor stated only in its dispatcher."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dev_lab.supervise.component import (
    ActionContext,
    CheckContext,
    Component,
    Registry,
    load_components,
)
from dev_lab.supervise.components import COMPONENTS
from dev_lab.supervise.process import manager_for
from dev_lab.supervise.verdict import Action, Anomaly, CheckResult, RemedyStep, Severity


class _Unnamed(Component):
    """A component that never said what it answers to."""

    description = 'anonymous'

    def check(self, ctx: CheckContext) -> CheckResult:
        """Return nothing, because this class exists only to be refused."""
        return CheckResult()


class _Probe(Component):
    """A component that reports one anomaly and remembers what it was handed."""

    name = 'probe'
    description = 'a probe'

    def __init__(self) -> None:
        self.seen: CheckContext | None = None

    def check(self, ctx: CheckContext) -> CheckResult:
        """Record the context and report one anomaly."""
        self.seen = ctx
        return CheckResult(anomalies=[Anomaly(kind='broken', severity=Severity.WARNING, message='broken')])


class _Acting(_Probe):
    """A component that implements an action in Python rather than as a command."""

    name = 'acting'

    def actions(self) -> dict[str, Action]:
        """Declare one action with no command, because Python performs it."""
        return {'deploy': Action(description='validate then activate')}

    def handlers(self) -> dict[str, Any]:
        """Declare the implementation matching the action above."""

        def deploy(_ctx: ActionContext) -> bool:
            return True

        return {'deploy': deploy}


class _Undeclared(_Probe):
    """A component that implements something it never declared."""

    name = 'undeclared'

    def handlers(self) -> dict[str, Any]:
        """Declare a handler with no matching action -- the registry must refuse this."""

        def sneaky(_ctx: ActionContext) -> bool:
            return True

        return {'sneaky': sneaky}


def _registry(*components: Component) -> Registry:
    registry = Registry()
    for component in components:
        registry.register(component)
    return registry


def shipped() -> list[Component]:
    """Return the shipped roster as fresh instances, so one test cannot reconfigure another."""
    return [type(component)() for component in COMPONENTS]


def test_a_component_must_declare_a_name() -> None:
    """An unnamed component could not be configured or reached, so it is not registered."""
    with pytest.raises(ValueError, match='declares no name'):
        _registry(_Unnamed())


def test_two_components_may_not_share_a_name() -> None:
    """A config cannot say which of two it meant, so neither may win silently."""
    with pytest.raises(ValueError, match='both answer to'):
        _registry(_Probe(), _Probe())


def test_an_implemented_action_must_be_declared() -> None:
    """THE FIX for the predecessor's hasattr probe: the interface is stated, not discovered."""
    with pytest.raises(ValueError, match='sneaky'):
        _registry(_Undeclared())


def test_an_implemented_action_is_found_by_the_name_it_declared() -> None:
    """A declared action resolves to both its declaration and its implementation."""
    registry = _registry(_Acting())
    assert registry.action('deploy') is not None
    handler = registry.handler('deploy')
    assert handler is not None
    assert handler.__name__ == 'deploy'


def test_a_command_action_has_no_handler() -> None:
    """Nothing to implement is the ordinary case, and must read as such rather than as missing."""
    registry = _registry(_Probe())
    assert registry.action('restart') is None
    assert registry.handler('restart') is None


def test_components_are_enabled_unless_their_own_section_disables_them() -> None:
    """Default-on: a target that installed a supervisor wants its probes running."""
    registry = _registry(_Probe())
    assert [c.name for c in registry.enabled()] == ['probe']
    registry.configure({'probe': {'enabled': False}})
    assert registry.enabled() == []


def test_a_component_section_reaches_its_own_component() -> None:
    """A section the component is not registered under is not handed to it."""
    registry = _registry(_Probe())
    registry.configure({'probe': {'threshold': 5}, 'other': {'threshold': 9}})
    assert registry.config_for('probe') == {'threshold': 5}
    assert registry.config_for('other') == {}


def test_a_check_is_handed_its_own_state_slice_and_nothing_else() -> None:
    """THE OTHER FIX: one component cannot write another's counters, because it is not given them."""
    state: dict[str, Any] = {'components': {'probe': {'peak': 3.0}, 'other': {'peak': 9.0}}}
    probe = _Probe()
    ctx = CheckContext(
        config={},
        shared={},
        state=state['components']['probe'],
        project=Path(),
        manager=manager_for('systemd'),
    )
    ctx.state['peak'] = 11.0
    probe.check(ctx)
    assert state['components']['probe']['peak'] == 11.0
    assert state['components']['other']['peak'] == 9.0


def test_an_action_context_carries_the_real_shared_config() -> None:
    """The predecessor passed an EMPTY mapping here, so a component reading it silently got nothing."""
    shared = {'cycle': {'interval': 300}}
    ctx = ActionContext(
        config={'a': 1},
        shared=shared,
        project=Path(),
        manager=manager_for('systemd'),
        registry=_registry(_Acting()),
    )
    assert ctx.shared['cycle']['interval'] == 300
    assert ctx.config == {'a': 1}


def test_a_kind_with_no_declared_chain_gets_no_chain() -> None:
    """THE REGRESSION. The fallback named an action no component implements, so it never ran.

    It was written to record an unhandled anomaly rather than drop it -- but the anomaly is
    recorded either way, in the state and in the report. What the phantom step produced instead
    was one failed attempt per anomaly per cycle, against an action nothing declares: a reading
    that something was tried, when nothing was.
    """
    assert _registry(_Probe()).remedies('nothing-declares-this') == []


def test_no_shipped_remedy_names_an_action_nobody_declares() -> None:
    """THE CLASS OF DEFECT, not the instance.

    The phantom fallback was one step naming an action no component implements. A chain that
    cannot be resolved is reported as a failed attempt on EVERY cycle, so the class is worth a
    check rather than the one instance: it turns a typo into a permanent alarm. Read over the
    shipped roster, which is where a default remedy would be written.
    """
    roster = shipped()
    declared = {name for component in roster for name in component.actions()}
    for component in roster:
        for kind, chain in component.remedies().items():
            for step in chain:
                assert step.action in declared, f'{component.name}.{kind} names undeclared {step.action!r}'


def test_a_component_declared_chain_is_used() -> None:
    """A component that knows how to act on its own anomaly says so, and is believed."""

    class _Chained(_Probe):
        name = 'chained'

        def remedies(self) -> dict[str, list[RemedyStep]]:
            """Declare one chain."""
            return {'broken': [RemedyStep(action='restart')]}

    assert [step.action for step in _registry(_Chained()).remedies('broken')] == ['restart']


def test_a_configured_chain_overrides_the_component_default() -> None:
    """Config wins over the component, and the precedence is stated in ONE place."""

    class _Chained(_Probe):
        name = 'chained'

        def remedies(self) -> dict[str, list[RemedyStep]]:
            """Declare one chain, which the config will override."""
            return {'broken': [RemedyStep(action='restart')]}

    registry = _registry(_Chained())
    registry.set_remedies({'broken': [{'action': 'deploy', 'escalate_after': 2}]})
    chain = registry.remedies('broken')
    assert [step.action for step in chain] == ['deploy']
    assert chain[0].escalate_after == 2


def test_a_configured_step_naming_no_action_is_refused() -> None:
    """A chain step that does nothing is a remedy that reads as attempted and never ran."""
    registry = _registry(_Probe())
    with pytest.raises(ValueError, match='names no action'):
        registry.set_remedies({'broken': [{'on': 'critical'}]})


def test_a_project_module_declares_its_components(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A module contributes what it STATES in COMPONENTS, not whatever a directory walk found."""
    module = tmp_path / 'project_components.py'
    module.write_text(
        'from dev_lab.supervise.component import Component\n'
        'from dev_lab.supervise.verdict import CheckResult\n'
        '\n'
        'class Mine(Component):\n'
        "    name = 'mine'\n"
        '    def check(self, ctx):\n'
        '        return CheckResult()\n'
        '\n'
        'COMPONENTS = [Mine()]\n',
        encoding='utf-8',
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    loaded = load_components('project_components')
    assert [component.name for component in loaded] == ['mine']


def test_a_module_declaring_nothing_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Silently loading nothing would look like a project whose checks all passed."""
    module = tmp_path / 'silent_module.py'
    module.write_text('X = 1\n', encoding='utf-8')
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(ValueError, match='COMPONENTS'):
        load_components('silent_module')


def test_a_module_listing_a_non_component_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo in the list must not be dropped quietly."""
    module = tmp_path / 'wrong_module.py'
    module.write_text("COMPONENTS = ['not a component']\n", encoding='utf-8')
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(TypeError, match='not a Component'):
        load_components('wrong_module')
