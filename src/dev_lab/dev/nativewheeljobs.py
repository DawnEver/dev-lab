"""The native-wheels workflow's jobs and trigger, rendered from a checked :class:`~dev_lab.dev.nativewheels.Wheels`.

What a repo declares, and what each release means, is :mod:`dev_lab.dev.nativewheels`; this module only renders it.
Split from it along that seam (MODULE-SIZE-ALARM).

THE TRIGGER IS THE TRUNK: a push to it, or a dispatch. A push the job token makes starts no workflow, and the
family's promote job pushes the trunk with it, so :func:`dispatched` adds the dispatch of
:data:`~dev_lab.dev.nativewheels.WORKFLOW` to that job, after the promote step. A dispatch on another branch builds
and tests.

JOBS: ``build`` (a matrix cell per wheel: maturin through ``PyO3/maturin-action``, attested, uploaded as one
artifact), ``sdist`` (``maturin sdist``, attested; the version it carries is the job's output), ``test`` (a cell per
target and version, on a fresh runner with no checkout: the wheel installed with its dependencies, then the
extension imported), ``test-sdist`` (a fresh Linux runner with the family's pinned Rust toolchain,
:data:`~dev_lab.dev.rusttoolchain.CHANNEL`: the sdist built, installed and imported), then, on the trunk once every
test passed, ``release`` (``v<version>``) and ``prerelease`` (the rolling tag) as declared. Every wheel and the sdist
carry GitHub's build provenance attestation (D19): ``gh attestation verify <file> --repo <owner>/<repo>``.
"""

from __future__ import annotations

from typing import Any, Final

from dev_lab.dev.nativewheels import TARGETS, WORKFLOW, Wheels
from dev_lab.dev.rusttoolchain import CHANNEL

__all__ = ['dispatched', 'workflow']

#: GitHub's build provenance attestation (D19): the ``actions/attest`` wrapper naming the build-provenance predicate.
_ATTEST: Final = 'actions/attest-build-provenance@v4'
#: What the attestation needs beyond reading the tree: the OIDC token Sigstore certifies, and its two stores.
_ATTESTS: Final = {'contents': 'read', 'id-token': 'write', 'attestations': 'write', 'artifact-metadata': 'write'}


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


def _build_job(wheels: Wheels) -> dict[str, Any]:
    """One wheel per matrix cell: built, checked abi3 when declared, attested and uploaded."""
    steps: list[dict[str, Any]] = [
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
        steps.append(
            {
                'name': f'The wheel is {tag}',
                'shell': 'bash',
                'run': f"ls dist/*-{tag}-*.whl || {{ echo 'no {tag} wheel: [tool.dev_lab.wheels] abi3 = "
                f'"{wheels.abi3}" needs the extension crate to enable the pyo3 feature {feature}\'; exit 1; }}',
            }
        )
    steps += [
        {'name': 'Attest the build provenance of the wheel', 'uses': _ATTEST, 'with': {'subject-path': 'dist/*.whl'}},
        {
            'uses': 'actions/upload-artifact@v4',
            'with': {'name': '${{ matrix.artifact }}', 'path': 'dist/*.whl', 'if-no-files-found': 'error'},
        },
    ]
    return {
        'name': 'build ${{ matrix.target }} (${{ matrix.python }})',
        'runs-on': '${{ matrix.runner }}',
        'permissions': _ATTESTS,
        'strategy': {'fail-fast': False, 'matrix': {'include': _builds(wheels)}},
        'steps': steps,
    }


#: The job, and its artifact, holding the sdist.
_SDIST: Final = 'sdist'
#: The version the sdist carries: the ``Version`` of the ``PKG-INFO`` maturin wrote at its top directory.
_READ_VERSION: Final = (
    'sdist=$(ls dist/*.tar.gz)\n'
    'version=$(tar -xzOf "$sdist" "$(basename "$sdist" .tar.gz)/PKG-INFO" | sed -n "s/^Version: //p")\n'
    'test -n "$version" || { echo "::error::$sdist carries no Version in its PKG-INFO"; exit 1; }\n'
    'echo "version=$version" >> "$GITHUB_OUTPUT"'
)


def _sdist_job() -> dict[str, Any]:
    """The one sdist, attested and uploaded; the version it carries is the job's output."""
    return {
        'runs-on': 'ubuntu-latest',
        'permissions': _ATTESTS,
        'outputs': {'version': '${{ steps.version.outputs.version }}'},
        'steps': [
            {'uses': 'actions/checkout@v4'},
            {
                'name': 'Build the sdist',
                'uses': 'PyO3/maturin-action@v1',
                'with': {'command': 'sdist', 'args': '--out dist'},
            },
            {'name': 'Read the version the sdist carries', 'id': 'version', 'shell': 'bash', 'run': _READ_VERSION},
            {
                'name': 'Attest the build provenance of the sdist',
                'uses': _ATTEST,
                'with': {'subject-path': 'dist/*.tar.gz'},
            },
            {
                'uses': 'actions/upload-artifact@v4',
                'with': {'name': _SDIST, 'path': 'dist/*.tar.gz', 'if-no-files-found': 'error'},
            },
        ],
    }


def _installed(wheels: Wheels, artifact: str, what: str, files: str) -> list[dict[str, Any]]:
    """Download *artifact*, install its *files* (*what*: a wheel or the sdist) with their dependencies, import."""
    return [
        {'uses': 'actions/download-artifact@v4', 'with': {'name': artifact, 'path': 'dist'}},
        {'name': f'Install the {what}', 'shell': 'bash', 'run': f'python -m pip install dist/{files}'},
        {'name': 'Import the extension', 'shell': 'bash', 'run': f'python -c "import {wheels.module}"'},
    ]


def _test_jobs(wheels: Wheels) -> dict[str, Any]:
    """``test`` (each wheel on each version, on its target's runner) and ``test-sdist`` (built from source)."""
    return {
        'test': {
            'name': 'test ${{ matrix.target }} (${{ matrix.python }})',
            'needs': 'build',
            'runs-on': '${{ matrix.runner }}',
            'strategy': {'fail-fast': False, 'matrix': {'include': _tests(wheels)}},
            'steps': [
                {'uses': 'actions/setup-python@v5', 'with': {'python-version': '${{ matrix.python }}'}},
                *_installed(wheels, '${{ matrix.artifact }}', 'wheel', '*.whl'),
            ],
        },
        'test-sdist': {
            'name': f'test the sdist ({wheels.python[0]})',
            'needs': _SDIST,
            'runs-on': 'ubuntu-latest',
            'steps': [
                {'uses': 'actions/setup-python@v5', 'with': {'python-version': wheels.python[0]}},
                {
                    'name': f'Install the family Rust toolchain {CHANNEL}',
                    'shell': 'bash',
                    'run': f'rustup toolchain install {CHANNEL} --profile minimal\nrustup default {CHANNEL}',
                },
                *_installed(wheels, _SDIST, 'sdist', '*.tar.gz'),
            ],
        },
    }


#: The release jobs' shared pieces: the run that tested what they publish, and the repository flag.
_RUN: Final = '$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID'
_REPO: Final = '--repo "$GITHUB_REPOSITORY"'
_OUTPUT: Final = f'${{{{ needs.{_SDIST}.outputs.version }}}}'


def _publishing(wheels: Wheels, env: dict[str, str], step: dict[str, Any]) -> dict[str, Any]:
    """A job publishing every wheel and the sdist through *step*: on the trunk only, once every test passed."""
    return {
        'needs': [_SDIST, 'test', 'test-sdist'],
        'if': f"${{{{ github.ref == 'refs/heads/{wheels.trunk}' }}}}",
        'runs-on': 'ubuntu-latest',
        'permissions': {'contents': 'write'},
        'env': {'GH_TOKEN': '${{ github.token }}', 'VERSION': _OUTPUT, **env},
        'steps': [
            {
                'uses': 'actions/download-artifact@v4',
                'with': {'pattern': 'wheel-*', 'path': 'dist', 'merge-multiple': True},
            },
            {'uses': 'actions/download-artifact@v4', 'with': {'name': _SDIST, 'path': 'dist'}},
            step,
        ],
    }


#: What a versioned release does when ``v<version>`` is released from another commit, by :data:`EXISTING`.
_ELSEWHERE: Final = {
    'refuse': 'echo "::error::$TAG is released from $at, and this trunk build $GITHUB_SHA carries the same version '
    '$VERSION: bump the version where the repo declares it, or declare [tool.dev_lab.wheels.release] existing = '
    '\\"keep\\""; exit 1',
    'keep': 'echo "::notice::$TAG is released from $at; existing = \\"keep\\" leaves it as it is"; exit 0',
}


def _versioned(wheels: Wheels) -> dict[str, Any]:
    """``v<version>``, created once: a re-run on its commit leaves it, another commit is refused or kept."""
    run = (
        'at=$(gh api "repos/$GITHUB_REPOSITORY/commits/$TAG" --jq .sha 2>/dev/null) || at=""\n'
        f'if [ -n "$at" ] && [ "$at" != "$GITHUB_SHA" ]; then {_ELSEWHERE[wheels.existing]}; fi\n'
        f'if gh release view "$TAG" {_REPO} >/dev/null 2>&1; then\n'
        '  echo "::notice::$TAG is released from this commit already; its assets are never overwritten"; exit 0\n'
        'fi\n'
        f'gh release create "$TAG" dist/* {_REPO} --target "$GITHUB_SHA" --latest --title "$TAG" '
        f'--notes "The native wheels and sdist of version $VERSION, built from $GITHUB_SHA and tested by {_RUN}."'
    )
    step = {'name': 'Publish v<version> unless it is released', 'run': run}
    return _publishing(wheels, {'TAG': f'v{_OUTPUT}'}, step)


def _rolling(wheels: Wheels) -> dict[str, Any]:
    """The rolling prerelease, deleted and created again at the built commit: never the latest release."""
    run = (
        f'if gh release view "$ROLLING" {_REPO} >/dev/null 2>&1; then\n'
        f'  gh release delete "$ROLLING" {_REPO} --yes --cleanup-tag\n'
        'fi\n'
        f'gh release create "$ROLLING" dist/* {_REPO} --target "$GITHUB_SHA" --prerelease '
        '--title "$ROLLING (prerelease of $VERSION)" --notes "The native wheels and sdist of $GITHUB_SHA (version '
        f'$VERSION), built and tested by {_RUN}; recreated at every trunk build."'
    )
    step = {'name': "Replace the prerelease with this commit's wheels and sdist", 'run': run}
    return _publishing(wheels, {'ROLLING': wheels.rolling}, step)


def workflow(wheels: Wheels) -> dict[str, Any]:
    """The ``wheels.yml`` workflow *wheels* renders: build, test, and the declared releases. PURE."""
    jobs: dict[str, Any] = {'build': _build_job(wheels), _SDIST: _sdist_job(), **_test_jobs(wheels)}
    if wheels.versioned:
        jobs['release'] = _versioned(wheels)
    if wheels.rolling:
        jobs['prerelease'] = _rolling(wheels)
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
