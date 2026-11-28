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
* Smoke: each wheel installs into a clean venv of the family Python (:data:`dev_lab.dev.pythontoolchain.VERSION`,
  the one interpreter its ``requires-python`` admits) and imports the extension (``[tool.maturin] module-name``, else
  the project name as a module).
* Publish: the wheels and the sdist go to the rolling prerelease :data:`ROLLING` (replaced on each push to
  ``main``) and, on a tag, to that tag's release. PyPI stays out of scope until a repo asks.

GitHub only: Gitea runners carry no macOS or Windows host, so a Gitea repo declaring wheels is refused by name.

VENDORED WHEELS (FAM-16): a third-party package the family pins at a commit that only builds from source (a C
extension: every consumer would need a compiler) is declared once, in the repo that builds family wheels::

    [tool.dev_lab.native.vendor.triangle]
    git = "https://github.com/drufat/triangle"
    rev = "<40-hex commit>"

and renders :data:`VENDOR_WORKFLOW`: ``pypa/cibuildwheel`` builds that commit (submodules included) for the family
Python on every :data:`RUNNERS` system, runs the package's own cibuildwheel test, and publishes to the release
:func:`vendor_release` names. That release is IMMUTABLE: an existing asset is never replaced, since a consumer's lock
pins its hash. A consumer reads it as a uv flat index (``[[tool.uv.index]] format = "flat"``, url
``https://github.com/<owner>/<repo>/releases/expanded_assets/<release>``) and pins the distribution's version.
"""

from __future__ import annotations

import re
import tomllib
from typing import Any, Final, cast

from dev_lab.dev.family import declared_table
from dev_lab.dev.pythontoolchain import VERSION

__all__ = ['ROLLING', 'RUNNERS', 'VENDOR_WORKFLOW', 'WORKFLOW', 'vendor_release', 'vendor_workflow', 'wheels_workflow']

#: The workflow file a declaring repo renders.
WORKFLOW: Final = 'wheels.yml'
#: The rolling prerelease every push to ``main`` replaces.
ROLLING: Final = 'main-latest'
#: Each declarable system and the GitHub runner building its one wheel (manylinux x86_64, Windows x64, macOS arm64).
RUNNERS: Final = {'linux': 'ubuntu-latest', 'windows': 'windows-latest', 'macos': 'macos-latest'}
#: The workflow file a repo declaring ``[tool.dev_lab.native.vendor]`` renders.
VENDOR_WORKFLOW: Final = 'vendor-wheels.yml'
_CIBUILDWHEEL: Final = 'pypa/cibuildwheel@v3.2.1'
_COMMIT: Final = re.compile(r'[0-9a-f]{40}')
_UPLOAD: Final = """\
gh release view "$RELEASE" >/dev/null 2>&1 || gh release create "$RELEASE" --target "$GITHUB_SHA" \\
  --title "$RELEASE" --notes "Wheels of $DIST at $REV, built by GitHub Actions (FAM-16)."
have=$(gh release view "$RELEASE" --json assets --jq '.assets[].name')
for wheel in dist/*.whl; do
  name=$(basename "$wheel")
  if printf '%s\\n' "$have" | grep -qxF "$name"; then echo "kept $name: a published wheel is immutable"
  else gh release upload "$RELEASE" "$wheel"; fi
done
"""

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
            {'uses': 'actions/setup-python@v5', 'with': {'python-version': VERSION}},
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


def vendor_release(dist: str, rev: str) -> str:
    """The release holding the wheels of *dist* built at commit *rev*: one per pin, never rewritten. PURE."""
    return f'vendor-{dist}-{rev[:12]}'


def _vendored(text: str, origin: str) -> dict[str, tuple[str, str]]:
    """Each ``[tool.dev_lab.native.vendor.<dist>]`` row as ``dist -> (git, rev)``; a malformed row is refused."""
    rows = cast('dict[str, dict[str, object]]', declared_table(tomllib.loads(text), 'native', {}).get('vendor', {}))
    out: dict[str, tuple[str, str]] = {}
    for dist, row in rows.items():
        where = f'{origin}: [tool.dev_lab.native.vendor.{dist}]'
        git, rev = row.get('git'), row.get('rev')
        if not isinstance(git, str) or not git.startswith('https://github.com/'):
            msg = f'{where} names no git URL -- set git = "https://github.com/<owner>/<repo>"'
            raise ValueError(msg)
        if not isinstance(rev, str) or not _COMMIT.fullmatch(rev):
            msg = f'{where} rev must be a full 40-hex commit (its release is immutable per pin), got {rev!r}'
            raise ValueError(msg)
        out[dist] = (git, rev)
    return out


def vendor_workflow(text: str, origin: str) -> dict[str, Any] | None:
    """The vendored-wheels workflow pyproject *text* declares, or ``None`` with no vendor row. PURE.

    Raises:
        ValueError: a row lacks its GitHub ``git`` URL or a full 40-hex ``rev``; *origin* names the text.

    """
    vendored = sorted(_vendored(text, origin).items())
    if not vendored:
        return None
    builds = [
        {'dist': dist, 'repository': git.removeprefix('https://github.com/'), 'rev': rev, 'os': runner}
        for dist, (git, rev) in vendored
        for runner in RUNNERS.values()
    ]
    pins = [{'dist': dist, 'rev': rev, 'release': vendor_release(dist, rev)} for dist, (_, rev) in vendored]
    checkout = {'repository': '${{ matrix.repository }}', 'ref': '${{ matrix.rev }}', 'submodules': 'recursive'}
    build = {
        'strategy': {'fail-fast': False, 'matrix': {'include': builds}},
        'runs-on': '${{ matrix.os }}',
        'steps': [
            {'uses': 'actions/checkout@v4', 'with': {**checkout, 'path': 'src'}},
            {'uses': 'actions/setup-python@v5', 'with': {'python-version': VERSION}},
            {
                'uses': _CIBUILDWHEEL,
                'with': {'package-dir': 'src', 'output-dir': 'dist'},
                'env': {'CIBW_BUILD': f'cp{VERSION.replace(".", "")}-*', 'CIBW_ARCHS': 'native'},
            },
            {
                'uses': 'actions/upload-artifact@v4',
                'with': {'name': 'vendor-${{ matrix.dist }}-${{ matrix.os }}', 'path': 'dist/*.whl'},
            },
        ],
    }
    publish = {
        'needs': 'build',
        'runs-on': 'ubuntu-latest',
        'strategy': {'matrix': {'include': pins}},
        'permissions': {'contents': 'write'},
        'env': {
            'GH_TOKEN': '${{ github.token }}',
            'GH_REPO': '${{ github.repository }}',
            'DIST': '${{ matrix.dist }}',
            'REV': '${{ matrix.rev }}',
            'RELEASE': '${{ matrix.release }}',
        },
        'steps': [
            {
                'uses': 'actions/download-artifact@v4',
                'with': {'path': 'dist', 'pattern': 'vendor-${{ matrix.dist }}-*', 'merge-multiple': True},
            },
            {'name': 'Publish each missing wheel to the pin release', 'shell': 'bash', 'run': _UPLOAD},
        ],
    }
    return {
        'name': 'Vendored wheels',
        'on': {'push': {'branches': ['main'], 'paths': ['pyproject.toml']}, 'workflow_dispatch': {}},
        'permissions': {'contents': 'read'},
        'jobs': {'build': build, 'publish': publish},
    }
