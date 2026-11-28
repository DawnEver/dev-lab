"""NATIVE WHEELS ARE OPT-IN (#981): native wheels built from the trunk on GitHub, for EXTERNAL users.

A repo with a native extension declares the systems in its ``pyproject.toml`` -- the single source::

    [tool.dev_lab.native]
    wheels = ["linux", "windows", "macos"]   # also "linux-arm64", "windows-arm64": every RUNNERS key
    # every option below is optional; each default is the behavior without it
    python = ["3.13", "3.14"]   # test each wheel installed on these; default: the family Python's smoke import
    abi3 = true                 # one wheel per system; false: one per system and python
    manylinux = "auto"          # the Linux platform policy: "auto" or a "2_X" glibc floor
    rolling = "main-latest"     # the prerelease recreated at every trunk build (ROLLING)
    versioned = false           # true: publish v<version>, read from the sdist's PKG-INFO, once per version
    existing = "refuse"         # with versioned: a version released from another commit fails, or "keep" it

and :mod:`dev_lab.dev.ciworkflows` renders :data:`WORKFLOW` (its jobs: :mod:`dev_lab.dev.nativewheeljobs`) beside
the base workflows. A repo without the declaration renders nothing. Family repos keep depending on each other by
``git+https://`` (built from source with the pinned toolchain); these wheels are for consumers outside the family.

* Trigger: each push to the trunk (``[tool.dev_lab.integrator] trunk``), a version tag (``v*``), and
  ``workflow_dispatch``. The promote job pushes the trunk with the job token, which starts no workflow, so
  :func:`dispatched` has it dispatch :data:`WORKFLOW` once it promoted.
* Build: per the repo's ``[build-system] build-backend`` -- ``maturin`` builds with ``PyO3/maturin-action`` (the
  toolchain from the repo's ``rust-toolchain.toml``), any other backend with ``pypa/cibuildwheel``. With ``abi3``
  (the default) one wheel per system serves every Python, so a built wheel that is not ``abi3`` fails the job by
  name; ``abi3 = false`` builds one per system and declared ``python``.
* Smoke and test: each wheel installs into a clean venv on its build interpreter and imports the extension
  (``[tool.maturin] module-name``, else the project name as a module); a declared ``python`` list also installs
  each wheel on each listed interpreter.
* Attest: every wheel and the sdist carry GitHub's build provenance attestation, made where they were built and
  checked by ``gh attestation verify <file> --repo <owner>/<repo>``.
* Sdist: a maturin repo's one sdist (built on its first Linux system) is installed on a fresh Linux runner -- no
  checkout, the family Rust toolchain (:data:`dev_lab.dev.rusttoolchain.CHANNEL`) -- and its extension imported.
* Publish: the wheels and the sdist go to the rolling prerelease (replaced on each trunk build), with ``versioned``
  to ``v<version>`` (never overwritten: a re-run on its commit leaves it, another commit fails unless ``existing =
  "keep"``), and, on a pushed tag, to that tag's release. PyPI stays out of scope until a repo asks.

GitHub only: Gitea runners carry no macOS or Windows host, so a Gitea repo declaring wheels is refused by name.

VENDORED WHEELS (FAM-16): a third-party package the family pins at a commit that only builds from source (a C
extension: every consumer would need a compiler) is declared once, in the repo that builds family wheels::

    [tool.dev_lab.native.vendor.triangle]
    git = "https://github.com/drufat/triangle"
    rev = "<40-hex commit>"

and renders :data:`VENDOR_WORKFLOW`: ``pypa/cibuildwheel`` builds that commit (submodules included) for the family
Python on every :data:`VENDOR_SYSTEMS` system, runs the package's own cibuildwheel test, and publishes to the release
:func:`vendor_release` names. That release is IMMUTABLE: an existing asset is never replaced, since a consumer's lock
pins its hash. A consumer reads it as a uv flat index (``[[tool.uv.index]] format = "flat"``, url
``https://github.com/<owner>/<repo>/releases/expanded_assets/<release>``) and pins the distribution's version.
"""

from __future__ import annotations

import re
import tomllib
from typing import Any, Final, cast

from dev_lab.dev.family import declared_table
from dev_lab.dev.lanepolicy import Policy
from dev_lab.dev.nativewheeljobs import RUNNERS, Wheels, jobs
from dev_lab.dev.pythontoolchain import VERSION

__all__ = [
    'EXISTING',
    'ROLLING',
    'VENDOR_SYSTEMS',
    'VENDOR_WORKFLOW',
    'WORKFLOW',
    'dispatched',
    'vendor_release',
    'vendor_workflow',
    'wheels_workflow',
]

#: The workflow file a declaring repo renders.
WORKFLOW: Final = 'wheels.yml'
#: The rolling prerelease every trunk build replaces, when ``rolling`` is not declared.
ROLLING: Final = 'main-latest'
#: What a trunk build does when its ``v<version>`` is released from another commit (the first is the default).
EXISTING: Final = ('refuse', 'keep')
_PYTHON: Final = re.compile(r'3\.\d+')
_MANYLINUX: Final = re.compile(r'auto|2_\d+')
#: The systems a vendored commit is built on: x86_64 Linux and Windows, arm64 macOS.
VENDOR_SYSTEMS: Final = ('linux', 'windows', 'macos')
#: What the promote step runs (``ci_base.toml``): the dispatch follows the step that runs it.
_PROMOTES: Final = 'dev_lab.dev.integrate promote'
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


def _strings(value: object, where: str, what: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        msg = f'{where} must be a list of {what}'
        raise TypeError(msg)
    return tuple(str(item) for item in cast('list[object]', value))


def _declared(text: str, origin: str) -> Wheels | None:
    """The wheels declaration of pyproject *text*, every option resolved; ``None`` without ``wheels``."""
    data = tomllib.loads(text)
    native = declared_table(data, 'native', {})
    if native.get('wheels') is None:
        return None
    where = f'{origin}: [tool.dev_lab.native]'
    systems = _strings(native['wheels'], f'{where} wheels', f'systems from {sorted(RUNNERS)}')
    if not systems:
        msg = f'{where} wheels names no system -- name some of {sorted(RUNNERS)} or drop it'
        raise ValueError(msg)
    if unknown := [name for name in systems if name not in RUNNERS]:
        msg = f'{where} wheels names {unknown}; the systems are {sorted(RUNNERS)}'
        raise ValueError(msg)
    python = _strings(native.get('python', []), f'{where} python', '"3.X" versions')
    abi3, manylinux = native.get('abi3', True), native.get('manylinux', 'auto')
    rolling, versioned, existing = (
        native.get('rolling', ROLLING),
        native.get('versioned', False),
        native.get('existing'),
    )
    refusals = [
        *(f'python names {bad}, not "3.X"' for bad in python if not _PYTHON.fullmatch(bad)),
        *([] if isinstance(abi3, bool) else [f'abi3 = {abi3!r} is not true or false']),
        *([] if not (abi3 is False and not python) else ['abi3 = false builds one wheel per python: declare python']),
        *(
            []
            if isinstance(manylinux, str) and _MANYLINUX.fullmatch(manylinux)
            else [f'manylinux = {manylinux!r} is not "auto" or "2_X"']
        ),
        *(
            []
            if isinstance(rolling, str) and rolling and not re.match(r'v\d', rolling)
            else [f"rolling = {rolling!r} names no tag, or a v<digit> one (the versioned release's)"]
        ),
        *([] if isinstance(versioned, bool) else [f'versioned = {versioned!r} is not true or false']),
        *(
            []
            if existing is None or (versioned is True and existing in EXISTING)
            else [f'existing = {existing!r} needs versioned = true and one of {list(EXISTING)}']
        ),
    ]
    maturin = data.get('build-system', {}).get('build-backend') == 'maturin'
    if versioned is True and not (maturin and any(name.startswith('linux') for name in systems)):
        refusals.append('versioned reads the version from the sdist: it needs maturin and a Linux system')
    if refusals:
        msg = f'{where}: ' + '; '.join(refusals)
        raise ValueError(msg)
    return Wheels(
        systems=systems,
        module=data.get('tool', {}).get('maturin', {}).get('module-name') or data['project']['name'].replace('-', '_'),
        maturin=maturin,
        python=python,
        abi3=bool(abi3),
        manylinux=str(manylinux),
        rolling=str(rolling),
        versioned=bool(versioned),
        existing=str(existing or EXISTING[0]),
        trunk=str(declared_table(data, 'integrator', {}).get('trunk') or Policy.trunk),
    )


def wheels_workflow(text: str, origin: str) -> dict[str, Any] | None:
    """The wheels workflow pyproject *text* declares, or ``None`` with no ``[tool.dev_lab.native] wheels``. PURE.

    Raises:
        TypeError: ``wheels`` or ``python`` is not a list.
        ValueError: an option is malformed or contradicts another; *origin* names the text.

    """
    wheels = _declared(text, origin)
    if wheels is None:
        return None
    return {
        'name': 'Wheels',
        'on': {'push': {'branches': [wheels.trunk], 'tags': ['v*']}, 'workflow_dispatch': {}},
        'permissions': {'contents': 'read'},
        'jobs': jobs(wheels),
    }


def dispatched(ci: dict[str, Any], text: str, origin: str) -> dict[str, Any]:
    """*ci* with its promote job dispatching :data:`WORKFLOW` on the trunk once it promoted. PURE.

    The job token's push of the trunk starts no workflow, so the job starts it. Without a wheels declaration, or
    with no promote job (the role is on a host, whose push starts the workflow itself), *ci* is returned as is.
    """
    wheels = _declared(text, origin)
    promote = ci.get('jobs', {}).get('promote')
    if wheels is None or promote is None:
        return ci
    at = next(i for i, step in enumerate(promote['steps']) if _PROMOTES in step.get('run', '')) + 1
    step = {
        'name': f'Build the native wheels of the promoted {wheels.trunk}',
        'run': f'gh workflow run {WORKFLOW} --repo "$GITHUB_REPOSITORY" --ref {wheels.trunk}',
        'env': {'GH_TOKEN': '${{ github.token }}'},
    }
    job = {
        **promote,
        'permissions': {**promote.get('permissions', {}), 'actions': 'write'},
        'steps': [*promote['steps'][:at], step, *promote['steps'][at:]],
    }
    return {**ci, 'jobs': {**ci['jobs'], 'promote': job}}


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
        for runner in (RUNNERS[name] for name in VENDOR_SYSTEMS)
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
                # The test is an import of the built wheel: an upstream pyproject's own test-command may name a
                # test tree its pinned commit lacks (Actions run 46093742941), so it is overridden, never inherited.
                'env': {
                    'CIBW_BUILD': f'cp{VERSION.replace(".", "")}-*',
                    'CIBW_ARCHS': 'native',
                    'CIBW_TEST_COMMAND': 'python -c "import ${{ matrix.dist }}"',
                    'CIBW_TEST_REQUIRES': '',
                },
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
