"""NATIVE WHEELS ARE OPT-IN (#981): one wheel per declared OS, built from ``main`` on GitHub, for EXTERNAL users.

A repo with a native extension declares the systems in its ``pyproject.toml`` -- the single source::

    [tool.dev_lab.native]
    wheels = ["linux", "windows", "macos"]

and :mod:`dev_lab.dev.ciworkflows` renders :data:`WORKFLOW` beside the base workflows. A repo without the
declaration renders nothing. Family repos keep depending on each other by ``git+https://`` (built from source with
the pinned toolchain); these wheels are for consumers outside the family.

* Trigger: each push to ``main``, a version tag (``v*``), and ``workflow_dispatch``.
* Build: per the repo's ``[build-system] build-backend`` -- ``maturin`` builds with ``PyO3/maturin-action`` (the
  toolchain from the repo's ``rust-toolchain.toml``), any other backend with ``pypa/cibuildwheel``. One wheel per
  OS across Python versions means pyo3 ``abi3``: a built wheel that is not ``abi3`` fails the job by name.
* Smoke: each wheel installs into a clean venv and imports the extension (``[tool.maturin] module-name``, else the
  project name as a module).
* Publish: the wheels and the sdist go to the rolling prerelease :data:`ROLLING` (replaced on each push to
  ``main``) and, on a tag, to that tag's release. PyPI stays out of scope until a repo asks.

GitHub only: Gitea runners carry no macOS or Windows host, so a Gitea repo declaring wheels is refused by name.
"""

from __future__ import annotations

import tomllib
from typing import Any, Final, cast

from dev_lab.dev.family import declared_table

__all__ = ['ROLLING', 'RUNNERS', 'WORKFLOW', 'wheels_workflow']

#: The workflow file a declaring repo renders.
WORKFLOW: Final = 'wheels.yml'
#: The rolling prerelease every push to ``main`` replaces.
ROLLING: Final = 'main-latest'
#: Each declarable system and the GitHub runner building its one wheel (manylinux x86_64, Windows x64, macOS arm64).
RUNNERS: Final = {'linux': 'ubuntu-latest', 'windows': 'windows-latest', 'macos': 'macos-latest'}

_ABI3_CHECK: Final = (
    'for wheel in dist/*.whl; do case "$wheel" in *abi3*) ;; *) echo "::error::$wheel is not abi3 -- '
    'one wheel per OS needs pyo3 abi3 at the requires-python floor ([tool.dev_lab.native], #981)"; exit 1;; '
    'esac; done'
)


def wheels_workflow(text: str, origin: str) -> dict[str, Any] | None:
    """The wheels workflow pyproject *text* declares, or ``None`` with no ``[tool.dev_lab.native] wheels``. PURE.

    Raises:
        TypeError: ``wheels`` is not a list.
        ValueError: ``wheels`` is not a non-empty list of :data:`RUNNERS` keys; *origin* names the text.

    """
    data = tomllib.loads(text)
    systems = declared_table(data, 'native', {}).get('wheels')
    if systems is None:
        return None
    if not isinstance(systems, list):
        msg = f'{origin}: [tool.dev_lab.native] wheels must be a list of systems from {sorted(RUNNERS)}'
        raise TypeError(msg)
    systems = [str(name) for name in cast('list[object]', systems)]
    if not systems:
        msg = f'{origin}: [tool.dev_lab.native] wheels names no system -- name some of {sorted(RUNNERS)} or drop it'
        raise ValueError(msg)
    if unknown := [name for name in systems if name not in RUNNERS]:
        msg = f'{origin}: [tool.dev_lab.native] wheels names {unknown}; the systems are {sorted(RUNNERS)}'
        raise ValueError(msg)
    maturin = data.get('build-system', {}).get('build-backend') == 'maturin'
    module = data.get('tool', {}).get('maturin', {}).get('module-name') or data['project']['name'].replace('-', '_')
    return {
        'name': 'Wheels',
        'on': {'push': {'branches': ['main'], 'tags': ['v*']}, 'workflow_dispatch': {}},
        'permissions': {'contents': 'read'},
        'jobs': {'build': _build(systems, module, maturin=maturin), 'publish': _publish()},
    }


def _build(systems: list[str], module: str, *, maturin: bool) -> dict[str, Any]:
    """The matrix job: build one wheel on each system's runner, refuse a non-abi3 wheel, smoke-import it, upload."""
    if maturin:
        built = [
            {
                'uses': 'PyO3/maturin-action@v1',
                'with': {'command': 'build', 'args': '--release --out dist', 'manylinux': 'auto'},
            },
            {
                'if': "runner.os == 'Linux'",
                'uses': 'PyO3/maturin-action@v1',
                'with': {'command': 'sdist', 'args': '--out dist'},
            },
        ]
    else:
        built = [{'uses': 'pypa/cibuildwheel@v2.22', 'with': {'output-dir': 'dist'}}]
    smoke = (
        'python -m venv .smoke && py=.smoke/bin/python && { [ -x "$py" ] || py=.smoke/Scripts/python.exe; } && '
        f'"$py" -m pip install dist/*.whl && "$py" -c "import {module}"'
    )
    return {
        'strategy': {'fail-fast': False, 'matrix': {'include': [{'os': RUNNERS[name]} for name in systems]}},
        'runs-on': '${{ matrix.os }}',
        'steps': [
            {'uses': 'actions/checkout@v4'},
            {'uses': 'actions/setup-python@v5', 'with': {'python-version': '3.x'}},
            *built,
            {'name': 'Refuse a wheel that is not abi3', 'shell': 'bash', 'run': _ABI3_CHECK},
            {'name': 'Smoke-import the wheel in a clean venv', 'shell': 'bash', 'run': smoke},
            {
                'uses': 'actions/upload-artifact@v4',
                'with': {'name': 'wheels-${{ matrix.os }}', 'path': 'dist/*'},
            },
        ],
    }


def _publish() -> dict[str, Any]:
    """The release job: every artifact to :data:`ROLLING` on ``main``, to the tag's own release on a tag."""
    rolling = (
        f'gh release delete {ROLLING} --yes --cleanup-tag || true\n'
        f'gh release create {ROLLING} dist/* --prerelease --target "$GITHUB_SHA" '
        f'--title "{ROLLING}" --notes "Wheels built from main at $GITHUB_SHA."'
    )
    return {
        'needs': 'build',
        'runs-on': 'ubuntu-latest',
        'permissions': {'contents': 'write'},
        'env': {'GH_TOKEN': '${{ github.token }}', 'GH_REPO': '${{ github.repository }}'},
        'steps': [
            {'uses': 'actions/download-artifact@v4', 'with': {'path': 'dist', 'merge-multiple': True}},
            {
                'name': f'Replace the rolling {ROLLING} prerelease',
                'if': "github.ref == 'refs/heads/main'",
                'run': rolling,
            },
            {
                'name': 'Publish the tag release',
                'if': "startsWith(github.ref, 'refs/tags/')",
                'run': 'gh release create "$GITHUB_REF_NAME" dist/* --verify-tag --title "$GITHUB_REF_NAME"',
            },
        ],
    }
