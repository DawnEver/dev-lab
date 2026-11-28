"""The jobs of the native ``wheels.yml`` a :class:`Wheels` declaration renders (:mod:`dev_lab.dev.nativewheels`).

``build`` (a matrix cell per wheel: one per system with abi3, one per system and Python without; refused when not
abi3 as declared, smoke-imported, attested, uploaded), ``test`` (only with a declared ``python`` list: each wheel
installed and imported on every listed interpreter, on its system's runner), ``test-sdist`` (a maturin repo with a
Linux system: a fresh Linux runner, no checkout, the family Rust toolchain installs the sdist and imports it), then
``publish``: the rolling prerelease on the trunk, ``v<version>`` once per sdist version when ``versioned``, and a
pushed ``v*`` tag's own release. Declared and refused in :mod:`dev_lab.dev.nativewheels`; rendered here. PURE.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from dev_lab.dev.pythontoolchain import VERSION
from dev_lab.dev.rusttoolchain import CHANNEL

__all__ = ['RUNNERS', 'Wheels', 'jobs']

#: Each declarable system and the GitHub runner building and testing its wheels natively.
RUNNERS: Final = {
    'linux': 'ubuntu-latest',
    'linux-arm64': 'ubuntu-24.04-arm',
    'windows': 'windows-latest',
    'windows-arm64': 'windows-11-arm',
    'macos': 'macos-latest',
}
#: GitHub's build provenance attestation, and what it needs beyond reading the tree: the OIDC token Sigstore
#: certifies and the attestation store.
_ATTEST: Final = 'actions/attest-build-provenance@v4'
_ATTESTS: Final = {'contents': 'read', 'id-token': 'write', 'attestations': 'write'}
_ABI3_CHECK: Final = (
    'for wheel in dist/*.whl; do case "$wheel" in *abi3*) ;; *) echo "::error::$wheel is not abi3 -- '
    'one wheel per OS needs pyo3 abi3 at the requires-python floor, or declare abi3 = false '
    '([tool.dev_lab.native], #981)"; exit 1;; esac; done'
)
_RUN: Final = '$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID'
#: What a versioned release does when ``v<version>`` is released from another commit, by ``existing``.
_ELSEWHERE: Final = {
    'refuse': 'echo "::error::$tag is released from $at, and this trunk build $GITHUB_SHA carries the same version '
    '$version: bump the version where the repo declares it, or declare [tool.dev_lab.native] existing = '
    '\\"keep\\""; exit 1',
    'keep': 'echo "::notice::$tag is released from $at; existing = \\"keep\\" leaves it as it is"; exit 0',
}
_VERSIONED: Final = """\
version=$(tar -xzOf dist/*.tar.gz --wildcards '*/PKG-INFO' | sed -n 's/^Version: //p' | head -n1)
if [ -z "$version" ]; then echo "::error::the sdist's PKG-INFO carries no Version"; exit 1; fi
tag="v$version"
at=$(gh api "repos/$GITHUB_REPOSITORY/commits/$tag" --jq .sha 2>/dev/null) || at=""
if [ -n "$at" ] && [ "$at" != "$GITHUB_SHA" ]; then {elsewhere}; fi
if gh release view "$tag" >/dev/null 2>&1; then
  echo "::notice::$tag is released from this commit already; its assets are never overwritten"; exit 0
fi
gh release create "$tag" dist/* --target "$GITHUB_SHA" --latest --title "$tag" \\
  --notes "Wheels and sdist of version $version, built from $GITHUB_SHA by {run}."
"""


@dataclass(frozen=True)
class Wheels:
    """A ``[tool.dev_lab.native]`` wheels declaration, every option resolved to its value."""

    systems: tuple[str, ...]
    module: str
    maturin: bool
    #: The interpreters each wheel is tested on; ``()``: the family Python's smoke import only.
    python: tuple[str, ...]
    #: One wheel per system (pyo3 abi3), or one per system and Python version.
    abi3: bool
    #: The Linux platform policy: ``auto`` or a ``2_X`` glibc floor.
    manylinux: str
    #: The prerelease tag recreated at every trunk build.
    rolling: str
    #: Publish ``v<version>`` (the sdist's PKG-INFO version) once per version from the trunk.
    versioned: bool
    #: What a trunk build does when its ``v<version>`` is released from another commit: refuse or keep.
    existing: str
    #: The branch releases are published from (``[tool.dev_lab.integrator] trunk``).
    trunk: str

    @property
    def sdist_system(self) -> str:
        """The system whose build cell makes the one sdist: the first Linux one, for maturin; ``''``: none."""
        return next((name for name in self.systems if name.startswith('linux')), '') if self.maturin else ''


def _tag(version: str) -> str:
    return 'cp' + version.replace('.', '')


def _artifact(wheels: Wheels, system: str, python: str) -> str:
    return f'wheels-{RUNNERS[system]}' if wheels.abi3 else f'wheels-{RUNNERS[system]}-{_tag(python)}'


def _cells(wheels: Wheels) -> list[dict[str, Any]]:
    """One build cell per wheel; the sdist cell is the sdist system's first."""
    pythons = (VERSION,) if wheels.abi3 else wheels.python or (VERSION,)
    return [
        {
            'os': RUNNERS[name],
            'python': python,
            'artifact': _artifact(wheels, name, python),
            'sdist': name == wheels.sdist_system and python == pythons[0],
        }
        for name in wheels.systems
        for python in pythons
    ]


def _build(wheels: Wheels) -> dict[str, Any]:
    """The matrix job: build each wheel natively, refuse non-abi3 when abi3, smoke-import, attest, upload."""
    if wheels.maturin:
        args = '--release --out dist' + ('' if wheels.abi3 else ' --interpreter ${{ matrix.python }}')
        built = [
            {
                'uses': 'PyO3/maturin-action@v1',
                'with': {'command': 'build', 'args': args, 'manylinux': wheels.manylinux},
            },
            {
                'if': '${{ matrix.sdist }}',
                'uses': 'PyO3/maturin-action@v1',
                'with': {'command': 'sdist', 'args': '--out dist'},
            },
        ]
    else:
        env: dict[str, str] = {} if wheels.abi3 else {'CIBW_BUILD': '${{ matrix.cibw }}'}
        if wheels.manylinux != 'auto':
            image = f'manylinux_{wheels.manylinux}'
            env |= {'CIBW_MANYLINUX_X86_64_IMAGE': image, 'CIBW_MANYLINUX_AARCH64_IMAGE': image}
        built = [{'uses': 'pypa/cibuildwheel@v2.22', 'with': {'output-dir': 'dist'}, **({'env': env} if env else {})}]
    smoke = (
        'python -m venv .smoke && py=.smoke/bin/python && { [ -x "$py" ] || py=.smoke/Scripts/python.exe; } && '
        f'"$py" -m pip install dist/*.whl && "$py" -c "import {wheels.module}"'
    )
    cells = _cells(wheels)
    if not wheels.maturin and not wheels.abi3:
        cells = [{**cell, 'cibw': f'{_tag(cell["python"])}-*'} for cell in cells]
    checks = (
        [] if not wheels.abi3 else [{'name': 'Refuse a wheel that is not abi3', 'shell': 'bash', 'run': _ABI3_CHECK}]
    )
    return {
        'strategy': {'fail-fast': False, 'matrix': {'include': cells}},
        'runs-on': '${{ matrix.os }}',
        'permissions': _ATTESTS,
        'steps': [
            {'uses': 'actions/checkout@v4'},
            {'uses': 'actions/setup-python@v5', 'with': {'python-version': '${{ matrix.python }}'}},
            *built,
            *checks,
            {'name': 'Smoke-import the wheel in a clean venv', 'shell': 'bash', 'run': smoke},
            {
                'name': 'Attest the build provenance of what was built',
                'uses': _ATTEST,
                'with': {'subject-path': 'dist/*'},
            },
            {'uses': 'actions/upload-artifact@v4', 'with': {'name': '${{ matrix.artifact }}', 'path': 'dist/*'}},
        ],
    }


def _installed(module: str, artifact: str, what: str, files: str) -> list[dict[str, Any]]:
    return [
        {'uses': 'actions/download-artifact@v4', 'with': {'name': artifact, 'path': 'dist'}},
        {'name': f'Install the {what}', 'shell': 'bash', 'run': f'python -m pip install dist/{files}'},
        {'name': 'Import the extension', 'shell': 'bash', 'run': f'python -c "import {module}"'},
    ]


def _test(wheels: Wheels) -> dict[str, Any]:
    """Each wheel installed (never from the source tree) and imported on every declared Python."""
    cells = [
        {'os': RUNNERS[name], 'python': python, 'artifact': _artifact(wheels, name, python)}
        for name in wheels.systems
        for python in wheels.python
    ]
    return {
        'needs': 'build',
        'runs-on': '${{ matrix.os }}',
        'strategy': {'fail-fast': False, 'matrix': {'include': cells}},
        'steps': [
            {'uses': 'actions/setup-python@v5', 'with': {'python-version': '${{ matrix.python }}'}},
            *_installed(wheels.module, '${{ matrix.artifact }}', 'wheel', '*.whl'),
        ],
    }


def _test_sdist(wheels: Wheels) -> dict[str, Any]:
    """The sdist installed on a fresh Linux runner with the family Rust toolchain, then its extension imported."""
    sdist = next(cell for cell in _cells(wheels) if cell['sdist'])
    return {
        'needs': 'build',
        'runs-on': 'ubuntu-latest',
        'steps': [
            {'uses': 'actions/setup-python@v5', 'with': {'python-version': VERSION}},
            {
                'name': f'Install the family Rust toolchain {CHANNEL}',
                'shell': 'bash',
                'run': f'rustup toolchain install {CHANNEL} --profile minimal\nrustup default {CHANNEL}',
            },
            *_installed(wheels.module, sdist['artifact'], 'sdist', '*.tar.gz'),
        ],
    }


def _publish(wheels: Wheels, needs: list[str]) -> dict[str, Any]:
    """After *needs*: the rolling prerelease and ``v<version>`` (if versioned) on the trunk, a tag's own release."""
    trunk = f"github.ref == 'refs/heads/{wheels.trunk}'"
    rolling = (
        f'gh release delete {wheels.rolling} --yes --cleanup-tag || true\n'
        f'gh release create {wheels.rolling} dist/* --prerelease --target "$GITHUB_SHA" '
        f'--title "{wheels.rolling}" --notes "Wheels built from {wheels.trunk} at $GITHUB_SHA."'
    )
    versioned = [
        {
            'name': 'Publish v<version> unless it is released',
            'if': trunk,
            'shell': 'bash',
            'run': _VERSIONED.format(elsewhere=_ELSEWHERE[wheels.existing], run=_RUN),
        }
    ]
    return {
        'needs': needs,
        'runs-on': 'ubuntu-latest',
        'permissions': {'contents': 'write'},
        'env': {'GH_TOKEN': '${{ github.token }}', 'GH_REPO': '${{ github.repository }}'},
        'steps': [
            {'uses': 'actions/download-artifact@v4', 'with': {'path': 'dist', 'merge-multiple': True}},
            *(versioned if wheels.versioned else []),
            {'name': f'Replace the rolling {wheels.rolling} prerelease', 'if': trunk, 'run': rolling},
            {
                'name': 'Publish the tag release',
                'if': "startsWith(github.ref, 'refs/tags/')",
                'run': 'gh release create "$GITHUB_REF_NAME" dist/* --verify-tag --title "$GITHUB_REF_NAME"',
            },
        ],
    }


def jobs(wheels: Wheels) -> dict[str, Any]:
    """Every job of the wheels workflow *wheels* declares, in run order. PURE."""
    tests = {
        **({'test': _test(wheels)} if wheels.python else {}),
        **({'test-sdist': _test_sdist(wheels)} if wheels.sdist_system else {}),
    }
    return {'build': _build(wheels), **tests, 'publish': _publish(wheels, ['build', *tests])}
