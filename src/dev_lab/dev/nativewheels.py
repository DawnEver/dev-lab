"""``[tool.dev_lab.wheels]``: an OPT-IN workflow building a repo's native (maturin) wheels and sdist from its trunk.

WHO IT IS FOR (user ruling, dev-lab #981): a family repo builds its Rust extension from source; an EXTERNAL user
installs a prebuilt wheel, or builds the sdist with Rust. A repo that declares the table renders :data:`WORKFLOW`;
one that does not renders nothing. Declared, read and refused here; :mod:`dev_lab.dev.nativewheeljobs` renders
the jobs (and their trigger) and :mod:`dev_lab.dev.ciworkflows` places them.

THE DECLARATION (:data:`SHAPE`): ``targets`` (each a key of :data:`TARGETS`: OS and machine, so the runner, the Rust
target and the manylinux flag have one source), ``python`` (the interpreters each wheel is tested on, ``"3.X"``) and
``abi3`` are required. ABI3 IS THE FAMILY'S WAY (user ruling D19): ``abi3 = "3.X"`` is the minimum Python the
wheel's ``cp3X-abi3`` tag targets, so ONE wheel per target is built on that interpreter and tested on every
``python``; the extension crate enables pyo3's matching ``abi3-py3X`` feature, and a build whose wheel is not
``cp3X-abi3`` fails naming both. ``abi3 = false`` is the option for a crate that cannot be abi3: one wheel per
(target, version). Never defaulted: the floor is a fact of the crate, so it is declared.
``manylinux`` is the Linux wheel's platform policy (:data:`MANYLINUX`, whose images carry the newest interpreters).
The import every test runs is ``[tool.maturin] module-name``, never typed twice.

RELEASES (user ruling D34; GitHub Releases only, never PyPI: D19) are the optional ``release`` table: ``versioned =
true`` publishes ``v<version>`` once per package version, ``rolling = "<tag>"`` a PRERELEASE recreated at every
trunk build, so GitHub never shows it as the latest. The version is the one maturin writes into the sdist's
``PKG-INFO``: the repo's single declared source (a Cargo workspace, or the pyproject) is read by maturin alone. A
versioned release is never overwritten: a re-run on its own commit leaves it as it is, and a trunk build of an
already released version from ANOTHER commit is refused naming both commits, unless ``existing = "keep"`` (one of
:data:`EXISTING`) declares that such a build leaves the release as it is. Without ``release`` the wheels and the
sdist are the run's artifacts only. Releases are published from the trunk (``[tool.dev_lab.integrator] trunk``)
only.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from typing import Any, Final, cast

from dev_lab.dev.family import declared_table
from dev_lab.dev.lanepolicy import FAMILY_INTEGRATION, Policy, policy_from

__all__ = [
    'EXISTING',
    'MANYLINUX',
    'SHAPE',
    'TABLE',
    'TARGETS',
    'WORKFLOW',
    'Target',
    'Wheels',
    'declared',
]

#: The ``[tool.dev_lab.<TABLE>]`` a repo opts in with.
TABLE: Final = 'wheels'
#: The workflow file the declaration renders.
WORKFLOW: Final = 'wheels.yml'
#: The Linux platform policy when none is declared: the maintained manylinux images carry the newest interpreters.
MANYLINUX: Final = '2_28'
#: What a trunk build does when its ``v<version>`` is released from another commit: fail naming both commits (the
#: first, the default), or leave the release as it is.
EXISTING: Final = ('refuse', 'keep')


@dataclass(frozen=True)
class Target:
    """One wheel platform: the hosted runner that builds and tests it, and maturin's Rust target."""

    runner: str
    rust: str

    @property
    def linux(self) -> bool:
        """Whether maturin builds it in a manylinux container: there the interpreter is the image's, by version."""
        return '-linux-' in self.rust


#: Every target a repo may declare, by name. Each runs natively on its runner, so its wheel is tested where it built.
TARGETS: Final = {
    'linux-x86_64': Target('ubuntu-latest', 'x86_64-unknown-linux-gnu'),
    'linux-aarch64': Target('ubuntu-24.04-arm', 'aarch64-unknown-linux-gnu'),
    'windows-x86_64': Target('windows-latest', 'x86_64-pc-windows-msvc'),
    'windows-arm64': Target('windows-11-arm', 'aarch64-pc-windows-msvc'),
    'macos-arm64': Target('macos-latest', 'aarch64-apple-darwin'),
    'macos-x86_64': Target('macos-15-intel', 'x86_64-apple-darwin'),
    'macos-universal2': Target('macos-latest', 'universal2-apple-darwin'),
}

#: The one shape of the table, said in every refusal.
SHAPE: Final = (
    f'[tool.dev_lab.{TABLE}] targets = [<one or more of {sorted(TARGETS)}>], python = ["3.X", ...], '
    'abi3 = "3.X" (the minimum Python of the cp3X-abi3 tag, at most the oldest python) or false (one wheel per '
    f'version), optionally manylinux = "<policy, {MANYLINUX} when omitted>" and release = {{ rolling = "<the '
    'prerelease tag recreated at every trunk build, not v<digit>...>", versioned = <true: v<version> published '
    f'once per version>, existing = <with versioned, one of {list(EXISTING)}: what a trunk build of a version '
    f'released from another commit does, "{EXISTING[0]}" when omitted> }} (rolling, versioned or both)'
)

_KEYS: Final = frozenset({'targets', 'python', 'abi3', 'manylinux', 'release'})
_RELEASE_KEYS: Final = frozenset({'rolling', 'versioned', 'existing'})
_VERSION: Final = re.compile(r'3\.\d+')
_TAG: Final = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*')
#: The tags a versioned release owns: a rolling tag among them would be taken for a version.
_VERSIONED_TAG: Final = re.compile(r'v\d.*')
_POLICY: Final = re.compile(r'[A-Za-z0-9_]+')
_MODULE: Final = re.compile(r'[A-Za-z_]\w*(\.[A-Za-z_]\w*)*')


@dataclass(frozen=True)
class Wheels:
    """A repo's wheels declaration, checked: what :func:`workflow` renders."""

    targets: tuple[str, ...]
    python: tuple[str, ...]
    module: str
    trunk: str
    #: The minimum Python of the ``cp3X-abi3`` tag; ``''``: one wheel per version.
    abi3: str = ''
    manylinux: str = MANYLINUX
    #: The prerelease tag recreated at every trunk build; ``''``: none.
    rolling: str = ''
    #: Whether ``v<version>`` is published once per package version.
    versioned: bool = False
    #: With :attr:`versioned`, one of :data:`EXISTING`.
    existing: str = EXISTING[0]


def _minor(version: str) -> int:
    """The minor of a ``3.X`` *version*: what orders two of them."""
    return int(version.split('.')[1])


def _strings(value: object) -> list[str]:
    """*value* when it is a non-empty list of distinct strings, else ``[]``."""
    if not isinstance(value, list):
        return []
    items = cast('list[object]', value)
    strings = [one for one in items if isinstance(one, str)]
    return strings if strings and len(strings) == len(items) == len(set(strings)) else []


def _release_malformed(value: object) -> str:
    """Why the ``release`` *value* is refused; ``''`` when it has its part of :data:`SHAPE`."""
    if not isinstance(value, dict):
        return 'release is not a table'
    release = cast('dict[str, Any]', value)
    rolling, versioned = release.get('rolling', ''), release.get('versioned', False)
    named = isinstance(rolling, str) and bool(_TAG.fullmatch(rolling))
    wrong = {
        f'release has unknown key(s) {sorted(set(release) - _RELEASE_KEYS)}': not set(release) <= _RELEASE_KEYS,
        'release.rolling is not a tag name (letters, digits, ., _, -)': 'rolling' in release and not named,
        f'release.rolling = {rolling!r} is a v<digit> tag, which the versioned release owns': named
        and bool(_VERSIONED_TAG.fullmatch(rolling)),
        'release.versioned is not true or false': not isinstance(versioned, bool),
        f'release.existing is not one of {list(EXISTING)}': release.get('existing', EXISTING[0]) not in EXISTING,
        'release.existing is declared without versioned = true': 'existing' in release and versioned is not True,
        'release declares neither rolling nor versioned = true': not rolling and versioned is not True,
    }
    return next((why for why, bad in wrong.items() if bad), '')


def _malformed(table: dict[str, Any]) -> str:
    """Why *table* is refused; ``''`` when it has :data:`SHAPE`."""
    targets, python, abi3 = _strings(table.get('targets')), _strings(table.get('python')), table.get('abi3')
    manylinux = table.get('manylinux', MANYLINUX)
    wrong = {
        f'unknown key(s) {sorted(set(table) - _KEYS)}': not set(table) <= _KEYS,
        f'targets is not a non-empty list of distinct names from {sorted(TARGETS)}': (
            not targets or not set(targets) <= set(TARGETS)
        ),
        'python is not a non-empty list of distinct "3.X" versions': (
            not python or not all(_VERSION.fullmatch(one) for one in python)
        ),
        'abi3 is neither a "3.X" floor nor false': abi3 is not False
        and not (isinstance(abi3, str) and _VERSION.fullmatch(abi3)),
        'manylinux is not a policy name (letters, digits, _)': (
            not isinstance(manylinux, str) or not _POLICY.fullmatch(manylinux)
        ),
    }
    if why := next((why for why, bad in wrong.items() if bad), ''):
        return why
    if 'release' in table and (why := _release_malformed(table['release'])):
        return why
    if isinstance(abi3, str) and _minor(abi3) > min(map(_minor, python)):
        return f'abi3 = "{abi3}" is above the oldest python, on which its abi3 wheel does not install'
    return ''


def declared(text: str, origin: str) -> Wheels | None:
    """The ``[tool.dev_lab.wheels]`` pyproject *text* declares, checked; ``None`` when it declares none.

    Raises:
        ValueError: the table is malformed, or ``[tool.maturin]`` names no ``module-name`` to import; *origin* names
            the text in the refusal.

    """
    data = tomllib.loads(text)
    value: object = declared_table(data, TABLE)
    if value is None:
        return None
    table = cast('dict[str, Any]', value) if isinstance(value, dict) else None
    why = 'not a table' if table is None else _malformed(table)
    if table is None or why:
        msg = f'{origin}: [tool.dev_lab.{TABLE}] = {value!r}: {why}; write {SHAPE}'
        raise ValueError(msg)
    module: object = data.get('tool', {}).get('maturin', {}).get('module-name')
    if not isinstance(module, str) or not _MODULE.fullmatch(module):
        msg = (
            f'{origin}: [tool.dev_lab.{TABLE}] tests each wheel by importing its extension, and [tool.maturin] '
            f'module-name = {module!r} names none: declare the dotted module maturin builds (e.g. "package._native")'
        )
        raise ValueError(msg)
    abi3: str | bool = table['abi3']
    release = cast('dict[str, Any]', table.get('release', {}))
    return Wheels(
        targets=tuple(_strings(table['targets'])),
        python=tuple(sorted(_strings(table['python']), key=_minor)),
        module=module,
        trunk=_trunk(text, origin),
        abi3=abi3 if isinstance(abi3, str) else '',
        manylinux=str(table.get('manylinux', MANYLINUX)),
        rolling=str(release.get('rolling', '')),
        versioned=release.get('versioned', False) is True,
        existing=str(release.get('existing', EXISTING[0])),
    )


def _trunk(text: str, origin: str) -> str:
    """The trunk pyproject *text* declares; the family's when it declares no ``[tool.dev_lab.integrator]``."""
    if not declared_table(tomllib.loads(text), 'integrator', {}):
        return Policy(FAMILY_INTEGRATION).trunk
    return policy_from(text, origin).trunk
