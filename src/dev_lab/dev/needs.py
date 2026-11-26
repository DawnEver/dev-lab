"""ONE NEED REGISTRY -- a test declares what it needs, the scheduler routes by it, a host that lacks it FAILS it.

User ruling 2026-11-24 (T2). A test names its needs on the function, typed by KIND::

    from dev_lab.dev.needs import needs

    @needs('jmag', 'os:windows', 'extra:plot', 'data:meas')
    def test_...

The registry is :data:`KINDS`, family-wide, and each kind reads its names from ONE source:

* ``<tool>`` (bare) -- a tool the family can probe: :data:`lab_commons.compute.toolchecks.CHECKS`.
* ``os:<name>`` -- :data:`lab_commons.compute.probe.OS_NAMES` values.
* ``extra:<name>`` -- the repo's ``[project.optional-dependencies]``.
* ``data:<store>`` -- the repo's ``[tool.dev_lab.needs] data = {<store> = "<ENV naming its root>"}``.

A need IS a resource marker (:attr:`Need.marker`: the tool name, the OS name, ``extra_<name>``,
``data_<store>``), so the existing need-set routing applies unchanged: the marker must be declared in
``[tool.lab_commons.tests] resources``, a test's part is its need-set (:mod:`lab_commons.hpc.needsets`), and
only a host whose capability covers that part produces it (:func:`lab_commons.compute.admission.admit`).
An unregistered need, or one whose marker the repo does not declare (its test would land in ``base`` and run
everywhere), is refused BY NAME at collection.

A SELECTED TEST WHOSE NEED IS MISSING FAILS, NEVER SKIPS. Routing put it here, so the host declared the need
present; a probe that disagrees is a host defect, and a skip would turn it into a silent green. The failure
names the need and the probe's reading (:meth:`Host.missing`).
"""

from __future__ import annotations

import os
import re
import sys
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cache
from importlib import metadata
from pathlib import Path
from typing import Final

import pytest
from lab_commons.compute.probe import OS_NAMES
from lab_commons.compute.toolchecks import CHECKS

__all__ = [
    'KINDS',
    'MARK',
    'Host',
    'Need',
    'UnregisteredNeed',
    'judge',
    'needs',
    'of_item',
    'parse',
    'refuse_unregistered',
]

#: The pytest mark carrying a test's needs as spelled, beside the resource markers they imply.
MARK: Final = 'needs'
#: The kinds a need may name; a bare name is a ``tool``.
KINDS: Final = ('tool', 'os', 'extra', 'data')
_RESOURCES: Final = '[tool.lab_commons.tests] resources'
_DATA: Final = '[tool.dev_lab.needs] data'
#: A requirement's distribution name: the leading identifier, before extras, versions, URLs or markers.
_DIST: Final = re.compile(r'\s*([A-Za-z0-9][A-Za-z0-9._-]*)')


class UnregisteredNeed(ValueError):
    """A need the registry does not hold, or whose marker the repo does not declare -- named, with its door."""


@dataclass(frozen=True)
class Need:
    """One need: its *kind*, its *name*, as *spelled* on the test."""

    kind: str
    name: str

    @property
    def spelled(self) -> str:
        """The spelling a test writes: bare for a tool, ``<kind>:<name>`` otherwise."""
        return self.name if self.kind == 'tool' else f'{self.kind}:{self.name}'

    @property
    def marker(self) -> str:
        """The resource marker this need IS (:data:`lab_commons.box.machine.RESOURCE_NAME` spelling)."""
        name = self.name.lower().replace('-', '_').replace('.', '_')
        return name if self.kind in {'tool', 'os'} else f'{self.kind}_{name}'


def _split(spelled: str) -> Need:
    kind, sep, name = spelled.partition(':')
    return Need(kind, name) if sep else Need('tool', spelled)


def _manifest(root: Path) -> dict[str, object]:
    path = root / 'pyproject.toml'
    return tomllib.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


def _table(manifest: Mapping[str, object], *keys: str) -> dict[str, object]:
    value: object = manifest
    for key in keys:
        value = value.get(key, {}) if isinstance(value, Mapping) else {}
    return dict(value) if isinstance(value, Mapping) else {}


def _registered(kind: str, root: Path) -> frozenset[str]:
    manifest = _manifest(root)
    if kind == 'tool':
        return frozenset(CHECKS)
    if kind == 'os':
        return frozenset(OS_NAMES.values())
    if kind == 'extra':
        return frozenset(_table(manifest, 'project', 'optional-dependencies'))
    return frozenset(_table(manifest, 'tool', 'dev_lab', 'needs', 'data'))


def parse(spelled: str, *, root: Path) -> Need:
    """The :class:`Need` *spelled* names in the repo at *root*.

    Raises:
        UnregisteredNeed: an unknown kind, a name its kind's source does not hold, or a marker the repo's
            ``[tool.lab_commons.tests] resources`` does not declare -- each named, with where to declare it.

    """
    need = _split(spelled)
    if need.kind not in KINDS:
        msg = f'need {spelled!r}: kind {need.kind!r} is not registered; the kinds are {list(KINDS)} (dev_lab.dev.needs)'
        raise UnregisteredNeed(msg)
    known = _registered(need.kind, root)
    if need.name not in known:
        source = {
            'tool': 'lab_commons.compute.toolchecks.CHECKS',
            'os': 'lab_commons.compute.probe.OS_NAMES',
            'extra': '[project.optional-dependencies]',
            'data': _DATA,
        }[need.kind]
        msg = f'need {spelled!r}: {need.name!r} is not a registered {need.kind} ({source}: {sorted(known)})'
        raise UnregisteredNeed(msg)
    resources = _table(_manifest(root), 'tool', 'lab_commons', 'tests').get('resources', [])
    if need.marker not in (resources if isinstance(resources, list) else []):
        msg = (
            f'need {spelled!r}: its marker {need.marker!r} is not in {_RESOURCES}, so its test would run on '
            f'every host; add it there'
        )
        raise UnregisteredNeed(msg)
    return need


def needs[F](*spelled: str) -> Callable[[F], F]:
    """The decorator: the :data:`MARK` carrying *spelled*, plus the resource marker each need IS.

    Applying the markers here keeps the need-set selection (``-m``) a pure function of the test's own
    declaration; validation waits for collection, where the repo root is known.
    """
    marks = [getattr(pytest.mark, MARK)(*spelled), *(getattr(pytest.mark, _split(one).marker) for one in spelled)]

    def apply(target: F) -> F:
        for mark in marks:
            target = mark(target)
        return target

    return apply


def of_item(item: pytest.Item, *, root: Path) -> tuple[Need, ...]:
    """Every need *item* declares, parsed (:func:`parse` raises on an unregistered one)."""
    return tuple(parse(str(one), root=root) for mark in item.iter_markers(MARK) for one in mark.args)


def _tool_present(tool: str) -> bool:
    from lab_commons.compute.presence import declared_versions, probe  # noqa: PLC0415 -- probed only when needed

    return probe(tool, CHECKS[tool], declared_versions(Path.cwd()).get(tool), now=datetime.now(UTC)).present


def _installed(dist: str) -> bool:
    try:
        metadata.distribution(dist)
    except metadata.PackageNotFoundError:
        return False
    return True


@dataclass(frozen=True)
class Host:
    """What THIS host has, every reader injectable so a control plants both answers."""

    system: str
    tool: Callable[[str], bool]
    installed: Callable[[str], bool]
    environ: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def this(cls) -> Host:
        """The running host: its OS, the tool probe (cached per process), installed distributions, environment."""
        return cls(OS_NAMES.get(sys.platform, sys.platform), cache(_tool_present), _installed, os.environ)

    def missing(self, need: Need, *, root: Path) -> str | None:
        """``None`` when *need* is present here, else why it is missing -- the reading, named."""
        if need.kind == 'os':
            return None if need.name == self.system else f'os {need.name} wanted, this host runs {self.system}'
        if need.kind == 'tool':
            return None if self.tool(need.name) else f'tool {need.name} not present (lab_commons.compute.presence)'
        manifest = _manifest(root)
        if need.kind == 'extra':
            rows = _table(manifest, 'project', 'optional-dependencies').get(need.name, [])
            dists = [m.group(1) for row in (rows if isinstance(rows, list) else []) if (m := _DIST.match(str(row)))]
            if lacking := [dist for dist in dists if not self.installed(dist)]:
                return f'extra {need.name} lacks {lacking}: python -m dev_lab.dev.dep --sync --extra {need.name}'
            return None
        variable = str(_table(manifest, 'tool', 'dev_lab', 'needs', 'data')[need.name])
        where = self.environ.get(variable, '')
        if not where or not Path(where).is_dir():
            return f'data store {need.name}: {variable}={where!r} is not a directory'
        return None


def judge(item: pytest.Item, *, root: Path, host: Host) -> None:
    """Fail *item* naming every need of it missing on *host* -- never a skip."""
    if lacking := [
        f'{need.spelled} ({why})' for need in of_item(item, root=root) if (why := host.missing(need, root=root))
    ]:
        pytest.fail(f'need {", ".join(lacking)} -- missing on this host, which was routed this test', pytrace=False)


def refuse_unregistered(items: list[pytest.Item], *, root: Path) -> None:
    """Refuse the session when any collected test declares an unregistered need, naming each."""
    refused = []
    for item in items:
        try:
            of_item(item, root=root)
        except UnregisteredNeed as why:
            refused.append(f'{item.nodeid}: {why}')
    if refused:
        raise pytest.UsageError('\n'.join(refused))
