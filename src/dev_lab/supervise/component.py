"""What a component is, what it is handed, and how the registry finds it.

A component measures one thing and optionally knows how to act on it. That is the whole contract,
and the reason it is worth stating precisely is that the predecessor stated it implicitly in three
places at once:

* an action a component implements in Python was reached by ``hasattr`` on an undeclared method, so
  the interface existed only in the dispatcher's head -- and this kit bans reflection outright;
* that method was called with ``global_cfg={}`` -- an EMPTY mapping, not the real config -- so a
  component written against the documented signature silently read nothing;
* components were discovered by walking a directory and instantiating every ``Component`` subclass
  found, so what ran depended on which files happened to be present.

Here a check is handed ONE context object, an implemented action is declared in a table by name,
and discovery reads an explicit ``COMPONENTS`` list. Nothing is found by looking for it.
"""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from dev_lab.supervise.verdict import OPERATORS, Action, CheckResult, Condition, RemedyStep

if TYPE_CHECKING:
    from dev_lab.supervise.process.base import ProcessManager

__all__ = [
    'ActionContext',
    'CheckContext',
    'Component',
    'Handler',
    'Registry',
    'load_components',
]


@dataclass
class CheckContext:
    """Everything a check is handed.

    Attributes:
        config: this component's own section, ``components.<name>``.
        shared: the whole merged configuration, for a check that needs a cycle setting.
        state: this component's OWN slice of the state, mutable and already scoped. A component
            cannot reach another's, which is the whole point: the predecessor handed every check
            the entire state mapping, so a counter's owner was a matter of convention.
        project: the target's directory, so a check resolves a relative path against it rather
            than against whatever directory the supervisor happened to start in.
        manager: how to run a command. A probe that shells out needs somewhere to do it, and the
            ceiling that comes with it.
        timeline: the framework's own bookkeeping -- when the last cycle ran, when it was last
            quiet -- as a READ-ONLY mapping. A probe that must judge whether the supervisor itself
            is alive needs to read this and has no business writing it, which is why it is not
            handed the state it lives in.

    """

    config: Mapping[str, Any]
    shared: Mapping[str, Any]
    state: MutableMapping[str, Any]
    project: Path
    manager: ProcessManager
    timeline: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class ActionContext:
    """Everything an implemented action is handed.

    Separate from :class:`CheckContext` because acting needs two things a check does not: the
    process manager, and the registry, so a step can run another declared action.

    Attributes:
        config: this component's own section.
        shared: the whole merged configuration. Present and REAL -- unlike the predecessor, where
            the acting path received an empty mapping here and a component reading it got nothing.
        project: the target's directory.
        manager: how to reach the service's process.
        registry: the registry, so an action may resolve another action by name.
        state: this component's OWN slice of the state, mutable and already scoped, exactly as a
            check is handed. An action that deploys has to record what it verified and what failed,
            and the slice is the only place it may do that.

    """

    config: Mapping[str, Any]
    shared: Mapping[str, Any]
    project: Path
    manager: ProcessManager
    registry: Registry
    state: MutableMapping[str, Any] = field(default_factory=dict)


#: An action a component implements in Python. Returns True on success; False lets the remedy
#: engine retry or escalate rather than treating the step as done.
Handler = Callable[[ActionContext], bool]


class Component(ABC):
    """One thing that gets measured, and optionally acted upon.

    Attributes:
        name: the registry key and the config key. Must be non-empty.
        description: one line, for a report.

    """

    name: str = ''
    description: str = ''

    @abstractmethod
    def check(self, ctx: CheckContext) -> CheckResult:
        """Measure, and report what was found.

        Args:
            ctx: this component's config, its own state slice, and the target directory.

        Returns:
            The metrics read, the anomalies found, and any completions.

        """
        ...

    def remedies(self) -> Mapping[str, Sequence[RemedyStep]]:
        """Return the default remedy chain per anomaly kind.

        A chain declared here is a DEFAULT: the config's own ``remedies`` section overrides it, and
        that precedence is stated in one place (the registry) rather than being a merge order a
        reader has to reconstruct.

        Returns:
            Anomaly kind to ordered steps. Empty when this component declares no chain.

        """
        return {}

    def actions(self) -> Mapping[str, Action]:
        """Return the actions this component offers.

        Returns:
            Action name to its declaration. An action with no ``command`` must also appear in
            :meth:`handlers`, and the registry refuses one that does not.

        """
        return {}

    def handlers(self) -> Mapping[str, Handler]:
        """Return the actions this component implements in Python.

        This is the declared replacement for the predecessor's ``hasattr`` probe: an action that
        runs Python says so here.

        Returns:
            Action name to the callable that performs it.

        """
        return {}


@dataclass
class Registry:
    """What is registered, what is enabled, and how a name resolves.

    Attributes:
        components: the registered components, in the order they were added.

    """

    components: dict[str, Component] = field(default_factory=dict)
    _configs: dict[str, Mapping[str, Any]] = field(default_factory=dict, repr=False)
    _remedy_overrides: dict[str, list[RemedyStep]] = field(default_factory=dict, repr=False)

    def register(self, component: Component, config: Mapping[str, Any] | None = None) -> None:
        """Add a component under its declared name.

        Args:
            component: the component to add.
            config: its configuration section, when the caller has one.

        Raises:
            ValueError: the component declares no name, which would make it unreachable, or the
                name is already taken -- two components answering one name is a config that cannot
                say which it meant.

        """
        if not component.name:
            msg = f'{type(component).__name__} declares no name, so nothing could configure or reach it'
            raise ValueError(msg)
        if component.name in self.components:
            msg = f'two components both answer to {component.name!r}'
            raise ValueError(msg)
        undeclared = sorted(set(component.handlers()) - set(component.actions()))
        if undeclared:
            msg = (
                f'{component.name} implements {undeclared} but declares no such action; '
                'an implemented action must be declared in actions() so a remedy can name it'
            )
            raise ValueError(msg)
        self.components[component.name] = component
        self._configs[component.name] = config if config is not None else {}

    def get(self, name: str) -> Component | None:
        """Return the component registered under *name*.

        Args:
            name: the component's name.

        Returns:
            The component, or None when nothing answers to that name.

        """
        return self.components.get(name)

    def configure(self, sections: Mapping[str, Any]) -> None:
        """Attach per-component configuration sections.

        Args:
            sections: the configuration's ``components`` table. A section naming no registered
                component is ignored -- a target may carry the section for a component it has
                since removed, and refusing to start over that helps nobody.

        """
        for name, section in sections.items():
            if name in self.components and isinstance(section, Mapping):
                self._configs[name] = section

    def set_remedies(self, table: Mapping[str, object]) -> None:
        """Attach the configuration's remedy overrides.

        A SEPARATE METHOD rather than another key smuggled into the component sections: the
        override table is keyed by anomaly KIND while a component section is keyed by component
        NAME, so one mapping could not hold both without a magic key -- and a magic key is what the
        first draft of this did, which silently dropped every override because the section filter
        did not recognise it.

        Args:
            table: anomaly kind to a list of step tables.

        Raises:
            ValueError: a step names no action.

        """
        for kind, chain in table.items():
            if isinstance(chain, list):
                self._remedy_overrides[kind] = [_step(item) for item in chain]

    def config_for(self, name: str) -> Mapping[str, Any]:
        """Return a component's configuration section.

        Args:
            name: the component's name.

        Returns:
            The section, or an empty mapping when it has none.

        """
        return self._configs.get(name, {})

    def enabled(self) -> list[Component]:
        """Return the components that should run, in registration order.

        A component is enabled unless its own section says ``enabled = false``. Default-on is
        deliberate: a target that installed a supervisor wants its probes running, and an explicit
        disable is one line, whereas default-off makes every new check silently inert until someone
        notices it is not reporting.

        Returns:
            The enabled components.

        """
        return [
            component for name, component in self.components.items() if self._configs.get(name, {}).get('enabled', True)
        ]

    def remedies(self, kind: str) -> list[RemedyStep]:
        """Return the remedy chain for an anomaly kind.

        Args:
            kind: the anomaly's type.

        Returns:
            The chain, from the config when it declares one and from the component otherwise. A
            kind nothing declares returns an EMPTY chain, and that is a statement rather than a
            gap: no remedy is declared for it.

            THE FALLBACK USED TO BE A SINGLE ``log`` STEP, and it was a phantom. The intent was
            that an unhandled anomaly be recorded rather than silently dropped -- but no component
            declares an action named ``log``, so the step could never run. It did not record the
            anomaly; the anomaly records itself, in the state and in the report either way. What
            the step produced was a failed attempt against an action nothing implements, once per
            anomaly per cycle: a reading that something was tried, which is worse than a reading
            that nothing was. An empty chain is what the code actually does, so it is what the
            code now says.

        """
        override = self._remedy_overrides.get(kind)
        if override is not None:
            return list(override)
        for component in self.components.values():
            chain = component.remedies().get(kind)
            if chain:
                return list(chain)
        return []

    def owner(self, kind: str) -> str:
        """Return the name of the component that declares a remedy chain for *kind*.

        The acting path needs it to hand an action ITS OWN component's configuration, which is
        what :class:`ActionContext` documents ``config`` to be. Passing the whole components table
        instead left every acting component reading an empty mapping -- the deploy component built
        an empty plan from it and refused every release, naming six settings that were present all
        along.

        Args:
            kind: the anomaly's type.

        Returns:
            The component's name, or an empty string when the chain came from a configuration
            override rather than from a component.

        """
        for name, component in self.components.items():
            if component.remedies().get(kind):
                return name
        # A CHAIN THE CONFIGURATION DECLARED STILL BELONGS TO WHOEVER IMPLEMENTS ITS FIRST ACTION.
        # `Registry.remedies` consults `_remedy_overrides` before any component, so a kind
        # reachable only through a `[remedies]` table has no declaring component -- and returning
        # '' for it handed the action an empty configuration and the shared state slice, which is
        # the two halves of the defects this session already found twice. The action's own
        # declaration is the next-best answer and the right one: a component that implements an
        # action is the component whose section and slice it should be reading.
        for step in self.remedies(kind):
            for name, component in self.components.items():
                if step.action in component.actions():
                    return name
        return ''

    def action(self, name: str) -> Action | None:
        """Return a declared action by name.

        Args:
            name: the action's name.

        Returns:
            The action, or None when nothing declares it.

        """
        for component in self.components.values():
            found = component.actions().get(name)
            if found is not None:
                return found
        return None

    def handler(self, name: str) -> Handler | None:
        """Return the Python implementation of an action, when one is declared.

        Args:
            name: the action's name.

        Returns:
            The callable, or None when the action is a command rather than an implementation.

        """
        for component in self.components.values():
            found = component.handlers().get(name)
            if found is not None:
                return found
        return None


def _step(item: object) -> RemedyStep:
    """Build a :class:`RemedyStep` from a configuration table.

    Args:
        item: a table naming at least an ``action``.

    Returns:
        The step.

    Raises:
        ValueError: the table names no action, which would be a chain step that does nothing.

    """
    if not isinstance(item, Mapping) or not item.get('action'):
        msg = f'a configured remedy step names no action: {item!r}'
        raise ValueError(msg)
    return RemedyStep(
        action=str(item['action']),
        on=item.get('on', 'always'),
        condition=_condition(item.get('condition')),
        max_attempts=int(item.get('max_attempts', 1)),
        escalate_after=item.get('escalate_after'),
    )


def _condition(declared: object) -> Condition | None:
    """Build a gate from a configuration table.

    Args:
        declared: the step's ``condition`` table, or None when it declares no gate.

    Returns:
        The condition, or None.

    Raises:
        ValueError: the table names no metric, or an operator this build does not know.

    """
    if declared is None:
        return None
    if not isinstance(declared, Mapping) or not declared.get('metric'):
        msg = f'a remedy condition names no metric: {declared!r}'
        raise ValueError(msg)
    condition = Condition(
        metric=str(declared['metric']),
        op=str(declared.get('op', '>')),
        value=float(declared.get('value', 0.0)),
    )
    if condition.op not in OPERATORS:
        msg = f'{condition.op!r} is not a comparison; this build knows {sorted(OPERATORS)}'
        raise ValueError(msg)
    return condition


class _ComponentModule(Protocol):
    """The single declaration a project module contributes to supervision."""

    COMPONENTS: list[Component] | None


def load_components(dotted: str) -> list[Component]:
    """Import a project's component module and take its declared components.

    The module names them::

        COMPONENTS = [WdgHealth, WdgDeploy]

    Read as a named attribute rather than scanned with ``dir``, so what a module contributes is
    something it states.

    Args:
        dotted: the module's import path.

    Returns:
        The components it declares.

    Raises:
        ValueError: the module declares no ``COMPONENTS`` list.
        TypeError: it declares one, and an entry in it is not a component.

    """
    module = importlib.import_module(dotted)
    try:
        declared = cast(_ComponentModule, module).COMPONENTS
    except AttributeError:
        declared = None
    if declared is None:
        msg = f'{dotted} declares no COMPONENTS list, so there is nothing to load from it'
        raise ValueError(msg)
    built: list[Component] = []
    for entry in declared:
        if not isinstance(entry, Component):
            msg = f'{dotted} lists {entry!r}, which is not a Component'
            raise TypeError(msg)
        built.append(entry)
    return built
