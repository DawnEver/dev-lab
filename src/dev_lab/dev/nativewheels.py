"""``[tool.dev_lab.wheels]``: an OPT-IN workflow building a repo's native (maturin) wheels, one per OS, from its trunk.

WHO IT IS FOR (user ruling, dev-lab #981): a family repo builds its Rust extension from source; an EXTERNAL user
installs a prebuilt wheel. A repo that declares the table renders :data:`WORKFLOW`; one that does not renders
nothing. Declared, read and refused here; :mod:`dev_lab.dev.ciworkflows` places what :func:`workflow` returns.

THE DECLARATION (:data:`SHAPE`): ``targets`` (each a key of :data:`TARGETS`: OS and machine, so the runner, the Rust
target and the manylinux flag have one source), ``python`` (the interpreters each wheel is tested on, ``"3.X"``) and
``abi3`` are required. ABI3 IS THE FAMILY'S WAY (user ruling D19): ``abi3 = "3.X"`` is the minimum Python the
wheel's ``cp3X-abi3`` tag targets, so ONE wheel per target is built on that interpreter and tested on every
``python``; the extension crate enables pyo3's matching ``abi3-py3X`` feature, and a build whose wheel is not
``cp3X-abi3`` fails naming both. ``abi3 = false`` is the option for a crate that cannot be abi3: one wheel per
(target, version). Never defaulted: the floor is a fact of the crate, so it is declared.
``manylinux`` is the Linux wheel's platform policy (:data:`MANYLINUX`, whose images carry the newest interpreters).
``release`` names the GitHub Release the trunk's wheels are attached to, replaced whole on every trunk build;
without it the wheels are the run's artifacts only (the family publishes to GitHub Releases, never PyPI: D19). The
import the wheel test runs is ``[tool.maturin] module-name``, never typed twice. Every wheel carries GitHub's build
provenance attestation (D19), verifiable with ``gh attestation verify <wheel> --repo <owner>/<repo>``.

THE TRIGGER IS THE TRUNK (``[tool.dev_lab.integrator] trunk``): a push to it, or a dispatch. A push the job token
makes starts no workflow, and the family's promote job pushes the trunk with it, so :func:`dispatched` adds the
dispatch of :data:`WORKFLOW` to that job, after the promote step. A release is published from the trunk only; a
dispatch on another branch builds and tests.

JOBS: ``build`` (a matrix cell per wheel: maturin through ``PyO3/maturin-action``, attested, uploaded as one
artifact),
``test`` (a cell per target and version, on a fresh runner with no checkout: the wheel installed with its
dependencies, then the extension imported) and ``release`` (when declared, after every test passed).
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from typing import Any, Final, cast

from dev_lab.dev.family import declared_table
from dev_lab.dev.lanepolicy import FAMILY_INTEGRATION, Policy, policy_from

__all__ = [
    'MANYLINUX',
    'SHAPE',
    'TABLE',
    'TARGETS',
    'WORKFLOW',
    'Target',
    'Wheels',
    'declared',
    'dispatched',
    'workflow',
]

#: The ``[tool.dev_lab.<TABLE>]`` a repo opts in with.
TABLE: Final = 'wheels'
#: The workflow file the declaration renders.
WORKFLOW: Final = 'wheels.yml'
#: The Linux platform policy when none is declared: the maintained manylinux images carry the newest interpreters.
MANYLINUX: Final = '2_28'


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
    f'version), optionally manylinux = "<policy, {MANYLINUX} when omitted>", '
    'release = "<the GitHub Release tag the trunk\'s wheels are attached to>"'
)

_KEYS: Final = frozenset({'targets', 'python', 'abi3', 'manylinux', 'release'})
_VERSION: Final = re.compile(r'3\.\d+')
_TAG: Final = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*')
_POLICY: Final = re.compile(r'[A-Za-z0-9_]+')
_MODULE: Final = re.compile(r'[A-Za-z_]\w*(\.[A-Za-z_]\w*)*')


#: GitHub's build provenance attestation (D19): the ``actions/attest`` wrapper naming the build-provenance predicate.
_ATTEST: Final = 'actions/attest-build-provenance@v4'
#: What the attestation needs beyond reading the tree: the OIDC token Sigstore certifies, and its two stores.
_ATTESTS: Final = {'contents': 'read', 'id-token': 'write', 'attestations': 'write', 'artifact-metadata': 'write'}


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
    release: str = ''


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


def _malformed(table: dict[str, Any]) -> str:
    """Why *table* is refused; ``''`` when it has :data:`SHAPE`."""
    targets, python, abi3 = _strings(table.get('targets')), _strings(table.get('python')), table.get('abi3')
    release, manylinux = table.get('release', 'x'), table.get('manylinux', MANYLINUX)
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
        'release is not a tag name (letters, digits, ., _, -)': (
            not isinstance(release, str) or not _TAG.fullmatch(release)
        ),
    }
    if why := next((why for why, bad in wrong.items() if bad), ''):
        return why
    if isinstance(abi3, str) and _minor(abi3) > min(map(_minor, python)):
        return f'abi3 = "{abi3}" is above the oldest python, on which its {_tag(abi3)}-abi3 wheel does not install'
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
    return Wheels(
        targets=tuple(_strings(table['targets'])),
        python=tuple(sorted(_strings(table['python']), key=_minor)),
        module=module,
        trunk=_trunk(text, origin),
        abi3=abi3 if isinstance(abi3, str) else '',
        manylinux=str(table.get('manylinux', MANYLINUX)),
        release=str(table.get('release', '')),
    )


def _trunk(text: str, origin: str) -> str:
    """The trunk pyproject *text* declares; the family's when it declares no ``[tool.dev_lab.integrator]``."""
    if not declared_table(tomllib.loads(text), 'integrator', {}):
        return Policy(FAMILY_INTEGRATION).trunk
    return policy_from(text, origin).trunk


def _tag(version: str) -> str:
    """The CPython tag of a ``3.X`` *version*: ``cp3X``."""
    return 'cp' + version.replace('.', '')


def _artifact(target: str, python: str, abi3: str) -> str:
    """The artifact holding the wheel of *target* that interpreter *python* installs (*abi3*: its floor, if any)."""
    return f'wheel-{target}-{_tag(abi3) + "-abi3" if abi3 else _tag(python)}'


def _builds(wheels: Wheels) -> list[dict[str, str]]:
    """One matrix cell per wheel: each target on the abi3 floor, or each (target, version) without abi3."""
    pythons = (wheels.abi3,) if wheels.abi3 else wheels.python
    return [
        {
            'target': name,
            'python': python,
            'runner': TARGETS[name].runner,
            'rust': TARGETS[name].rust,
            'manylinux': wheels.manylinux if TARGETS[name].linux else '',
            # A manylinux container holds every interpreter by version; elsewhere setup-python's is on PATH.
            'interpreter': f'python{python}' if TARGETS[name].linux else 'python',
            'artifact': _artifact(name, python, wheels.abi3),
        }
        for name in wheels.targets
        for python in pythons
    ]


def _tests(wheels: Wheels) -> list[dict[str, str]]:
    """One matrix cell per target and version: the wheel that version installs, on the target's runner."""
    return [
        {
            'target': name,
            'python': python,
            'runner': TARGETS[name].runner,
            'artifact': _artifact(name, python, wheels.abi3),
        }
        for name in wheels.targets
        for python in wheels.python
    ]


def workflow(wheels: Wheels) -> dict[str, Any]:
    """The ``wheels.yml`` workflow *wheels* renders: build, test, and release when one is declared. PURE."""
    build_steps: list[dict[str, Any]] = [
        {'uses': 'actions/checkout@v4'},
        {'uses': 'actions/setup-python@v5', 'with': {'python-version': '${{ matrix.python }}'}},
        {
            'name': 'Build the wheel',
            'uses': 'PyO3/maturin-action@v1',
            'with': {
                'target': '${{ matrix.rust }}',
                'manylinux': '${{ matrix.manylinux }}',
                'args': '--release --out dist --interpreter ${{ matrix.interpreter }}',
            },
        },
    ]
    if wheels.abi3:
        tag, feature = f'{_tag(wheels.abi3)}-abi3', f'abi3-py{wheels.abi3.replace(".", "")}'
        build_steps.append(
            {
                'name': f'The wheel is {tag}',
                'shell': 'bash',
                'run': f"ls dist/*-{tag}-*.whl || {{ echo 'no {tag} wheel: [tool.dev_lab.wheels] abi3 = "
                f'"{wheels.abi3}" needs the extension crate to enable the pyo3 feature {feature}\'; exit 1; }}',
            }
        )
    build_steps += [
        {'name': 'Attest the build provenance of the wheel', 'uses': _ATTEST, 'with': {'subject-path': 'dist/*.whl'}},
        {
            'uses': 'actions/upload-artifact@v4',
            'with': {'name': '${{ matrix.artifact }}', 'path': 'dist/*.whl', 'if-no-files-found': 'error'},
        },
    ]
    jobs: dict[str, Any] = {
        'build': {
            'name': 'build ${{ matrix.target }} (${{ matrix.python }})',
            'runs-on': '${{ matrix.runner }}',
            'permissions': _ATTESTS,
            'strategy': {'fail-fast': False, 'matrix': {'include': _builds(wheels)}},
            'steps': build_steps,
        },
        'test': {
            'name': 'test ${{ matrix.target }} (${{ matrix.python }})',
            'needs': 'build',
            'runs-on': '${{ matrix.runner }}',
            'strategy': {'fail-fast': False, 'matrix': {'include': _tests(wheels)}},
            'steps': [
                {'uses': 'actions/setup-python@v5', 'with': {'python-version': '${{ matrix.python }}'}},
                {'uses': 'actions/download-artifact@v4', 'with': {'name': '${{ matrix.artifact }}', 'path': 'dist'}},
                {'name': 'Install the wheel', 'shell': 'bash', 'run': 'python -m pip install dist/*.whl'},
                {'name': 'Import the extension', 'shell': 'bash', 'run': f'python -c "import {wheels.module}"'},
            ],
        },
    }
    if wheels.release:
        jobs['release'] = {
            'needs': 'test',
            'if': f"${{{{ github.ref == 'refs/heads/{wheels.trunk}' }}}}",
            'runs-on': 'ubuntu-latest',
            'permissions': {'contents': 'write'},
            'env': {'GH_TOKEN': '${{ github.token }}', 'RELEASE': wheels.release},
            'steps': [
                {
                    'uses': 'actions/download-artifact@v4',
                    'with': {'pattern': 'wheel-*', 'path': 'dist', 'merge-multiple': True},
                },
                {
                    'name': "Replace the release with this commit's wheels",
                    'run': 'gh release delete "$RELEASE" --repo "$GITHUB_REPOSITORY" --yes --cleanup-tag || true\n'
                    'gh release create "$RELEASE" dist/*.whl --repo "$GITHUB_REPOSITORY" --target "$GITHUB_SHA" '
                    '--title "Native wheels ($RELEASE)" --notes "The native wheels of $GITHUB_SHA, built and tested '
                    'by $GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID."',
                },
            ],
        }
    return {
        'name': 'Native wheels',
        'on': {'push': {'branches': [wheels.trunk]}, 'workflow_dispatch': {}},
        'concurrency': {'group': 'wheels-${{ github.ref }}', 'cancel-in-progress': False},
        'permissions': {'contents': 'read'},
        'jobs': jobs,
    }


#: What the promote step runs (``ci_base.toml``): the dispatch follows the step that runs it.
_PROMOTES: Final = 'dev_lab.dev.integrate promote'


def dispatched(ci: dict[str, Any], trunk: str) -> dict[str, Any]:
    """*ci* with its promote job dispatching :data:`WORKFLOW` on *trunk* once the promote step passed. PURE.

    The job token's push of the trunk starts no workflow, so the job starts it. A *ci* with no promote job (the
    role is on a host, whose push starts the workflow itself) is returned as is.
    """
    promote = ci.get('jobs', {}).get('promote')
    if promote is None:
        return ci
    at = next(i for i, step in enumerate(promote['steps']) if _PROMOTES in step.get('run', '')) + 1
    step = {
        'name': f'Build the native wheels of the promoted {trunk}',
        'run': f'gh workflow run {WORKFLOW} --repo "$GITHUB_REPOSITORY" --ref {trunk}',
        'env': {'GH_TOKEN': '${{ github.token }}'},
    }
    job = {
        **promote,
        'permissions': {**promote.get('permissions', {}), 'actions': 'write'},
        'steps': [*promote['steps'][:at], step, *promote['steps'][at:]],
    }
    return {**ci, 'jobs': {**ci['jobs'], 'promote': job}}
