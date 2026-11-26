"""``[tool.dev_lab.wheels]`` renders the native-wheels workflow; a repo without it renders nothing of it (dev-lab #981).

Every planted declaration is invented: a repo whose maturin extension is ``pkg._native``. The release scripts run
in bash against a ``gh`` function standing in for GitHub (``_FAKE_GH``), so what they publish, keep and refuse is
measured, not read off the text.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from _roles_fixtures import CI_REPO, HPC_REPO

from dev_lab.dev import ciworkflows
from dev_lab.dev.ciworkflows import declared_paths, drift, placed, write
from dev_lab.dev.nativewheels import EXISTING, MANYLINUX, SHAPE, TARGETS, WORKFLOW
from dev_lab.dev.rusttoolchain import CHANNEL

if TYPE_CHECKING:
    from dev_lab.dev.roles import Roles

_MATURIN = '[tool.maturin]\nmodule-name = "pkg._native"\n'
_INTEGRATOR = '[tool.dev_lab.integrator]\nintegration = "integrate/main"\ntrunk = "stable"\n'
_RELEASE = 'release = { rolling = "wheels", versioned = true }\n'
_WHEELS = (
    '[tool.dev_lab.wheels]\ntargets = ["linux-x86_64", "windows-x86_64", "macos-universal2"]\n'
    'python = ["3.15", "3.12"]\nabi3 = "3.12"\n' + _RELEASE
)
_PER_VERSION = _WHEELS.replace('abi3 = "3.12"', 'abi3 = false')
_TARGETS = ('linux-x86_64', 'windows-x86_64', 'macos-universal2')
_PROMOTES = 'dev_lab.dev.integrate promote'


def _rendered(text: str, forge: str = 'github', roles: Roles = CI_REPO) -> dict[str, dict[str, Any]]:
    return {name: flow for name, (_, flow) in placed(text, 'pyproject.toml', forge, roles).items()}


def _flow(release: str = _RELEASE) -> dict[str, Any]:
    return _rendered(_MATURIN + _INTEGRATOR + _WHEELS.replace(_RELEASE, release))[WORKFLOW]


def _steps(job: dict[str, Any]) -> list[str]:
    return [step.get('name') or step['uses'] for step in job['steps']]


def _cells(flow: dict[str, Any], job: str) -> list[dict[str, str]]:
    return flow['jobs'][job]['strategy']['matrix']['include']


def test_abi3_builds_one_wheel_per_target_on_its_floor_and_tests_it_on_every_version() -> None:
    flow = _flow()
    assert flow['on'] == {'push': {'branches': ['stable']}, 'workflow_dispatch': {}}, 'the DECLARED trunk'
    assert flow['permissions'] == {'contents': 'read'}
    builds = _cells(flow, 'build')
    assert {(cell['target'], cell['python'], cell['artifact']) for cell in builds} == {
        (name, '3.12', f'wheel-{name}-cp312-abi3') for name in _TARGETS
    }
    linux = next(cell for cell in builds if cell['target'] == 'linux-x86_64')
    assert (linux['runner'], linux['rust'], linux['manylinux'], linux['interpreter']) == (
        'ubuntu-latest', 'x86_64-unknown-linux-gnu', MANYLINUX, 'python3.12'
    )  # fmt: skip
    mac = next(cell for cell in builds if cell['target'] == 'macos-universal2')
    assert (mac['rust'], mac['manylinux'], mac['interpreter']) == ('universal2-apple-darwin', '', 'python')
    assert {(cell['target'], cell['python'], cell['artifact']) for cell in _cells(flow, 'test')} == {
        (name, version, f'wheel-{name}-cp312-abi3') for name in _TARGETS for version in ('3.12', '3.15')
    }
    check = next(step for step in flow['jobs']['build']['steps'] if step.get('name') == 'The wheel is cp312-abi3')
    assert 'ls dist/*-cp312-abi3-*.whl' in check['run']
    assert 'abi3-py312' in check['run'], 'a crate without the matching feature fails naming it'


def test_per_version_is_the_option_one_wheel_per_target_and_version() -> None:
    flow = _rendered(_MATURIN + _PER_VERSION)[WORKFLOW]
    builds = _cells(flow, 'build')
    assert {(cell['target'], cell['python'], cell['artifact']) for cell in builds} == {
        (name, version, f'wheel-{name}-cp{version.replace(".", "")}')
        for name in _TARGETS
        for version in ('3.12', '3.15')
    }
    assert {(cell['target'], cell['python'], cell['artifact']) for cell in _cells(flow, 'test')} == {
        (cell['target'], cell['python'], cell['artifact']) for cell in builds
    }, 'each test installs the wheel its own version built'
    assert not any('abi3' in name for name in _steps(flow['jobs']['build'])), 'no abi3 check without abi3'


def test_every_wheel_is_tested_installed_never_from_its_source_tree() -> None:
    test = _flow()['jobs']['test']
    assert test['needs'] == 'build'
    assert not any(step.get('uses', '').startswith('actions/checkout') for step in test['steps'])
    assert test['steps'][-2]['run'] == 'python -m pip install dist/*.whl'
    assert test['steps'][-1]['run'] == 'python -c "import pkg._native"', 'the import is [tool.maturin] module-name'


def test_every_wheel_and_the_sdist_carry_their_build_provenance_attestation() -> None:
    jobs = _flow()['jobs']
    for job, files in (('build', 'dist/*.whl'), ('sdist', 'dist/*.tar.gz')):
        names = _steps(jobs[job])
        (attest,) = [step for step in jobs[job]['steps'] if step.get('uses', '').startswith('actions/attest')]
        assert attest['uses'] == 'actions/attest-build-provenance@v4'
        assert attest['with'] == {'subject-path': files}
        assert names.index(attest['name']) < names.index('actions/upload-artifact@v4')
        assert jobs[job]['permissions'] == {
            'contents': 'read', 'id-token': 'write', 'attestations': 'write', 'artifact-metadata': 'write'
        }  # fmt: skip


def test_one_sdist_is_built_by_maturin_and_its_version_is_the_job_s_output() -> None:
    sdist = _flow()['jobs']['sdist']
    build = next(step for step in sdist['steps'] if step.get('uses') == 'PyO3/maturin-action@v1')
    assert build['with'] == {'command': 'sdist', 'args': '--out dist'}
    assert sdist['outputs'] == {'version': '${{ steps.version.outputs.version }}'}
    assert sdist['steps'][-1]['with'] == {'name': 'sdist', 'path': 'dist/*.tar.gz', 'if-no-files-found': 'error'}


def test_the_sdist_is_built_installed_and_imported_on_a_fresh_runner_with_the_family_toolchain() -> None:
    test = _flow()['jobs']['test-sdist']
    assert (test['needs'], test['runs-on']) == ('sdist', 'ubuntu-latest')
    assert not any(step.get('uses', '').startswith('actions/checkout') for step in test['steps'])
    assert test['steps'][0]['with'] == {'python-version': '3.12'}, 'the oldest declared python'
    toolchain = test['steps'][1]
    assert toolchain['run'] == f'rustup toolchain install {CHANNEL} --profile minimal\nrustup default {CHANNEL}'
    assert [step.get('run') for step in test['steps'][-2:]] == [
        'python -m pip install dist/*.tar.gz', 'python -c "import pkg._native"'
    ]  # fmt: skip


def _version_read(tmp_path: Path, pkg_info: str) -> subprocess.CompletedProcess[str]:
    """The sdist job's version step, run on an sdist whose top ``PKG-INFO`` is *pkg_info*."""
    run = next(step['run'] for step in _flow()['jobs']['sdist']['steps'] if step.get('id') == 'version')
    (tmp_path / 'dist').mkdir()
    with tarfile.open(tmp_path / 'dist' / 'pkg-1.2.0.tar.gz', 'w:gz') as sdist:
        data = pkg_info.encode()
        member = tarfile.TarInfo('pkg-1.2.0/PKG-INFO')
        member.size = len(data)
        sdist.addfile(member, io.BytesIO(data))
    bash = shutil.which('bash')
    assert bash, 'the step is bash'
    env = {**os.environ, 'GITHUB_OUTPUT': (tmp_path / 'output').as_posix()}
    return subprocess.run(
        [bash, '-eo', 'pipefail', '-c', run],
        env=env,
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        encoding='utf-8',
    )


def test_the_version_is_the_one_maturin_wrote_into_the_sdist(tmp_path: Path) -> None:
    done = _version_read(tmp_path, 'Metadata-Version: 2.4\nName: pkg\nVersion: 1.2.0\n')
    assert done.returncode == 0, done.stdout + done.stderr
    assert (tmp_path / 'output').read_text(encoding='utf-8') == 'version=1.2.0\n'


def test_an_sdist_carrying_no_version_fails_the_job_naming_it(tmp_path: Path) -> None:
    done = _version_read(tmp_path, 'Metadata-Version: 2.4\nName: pkg\n')
    assert done.returncode != 0
    assert 'carries no Version in its PKG-INFO' in done.stdout


def test_each_release_publishes_every_wheel_and_the_sdist_from_the_trunk_after_every_test() -> None:
    jobs = _flow()['jobs']
    for name in ('release', 'prerelease'):
        job = jobs[name]
        assert job['needs'] == ['sdist', 'test', 'test-sdist']
        assert job['if'] == "${{ github.ref == 'refs/heads/stable' }}", 'a dispatch elsewhere publishes nothing'
        assert job['permissions'] == {'contents': 'write'}
        assert job['env']['VERSION'] == '${{ needs.sdist.outputs.version }}'
        assert [step.get('with') for step in job['steps'][:2]] == [
            {'pattern': 'wheel-*', 'path': 'dist', 'merge-multiple': True}, {'name': 'sdist', 'path': 'dist'}
        ]  # fmt: skip
    assert jobs['release']['env']['TAG'] == 'v${{ needs.sdist.outputs.version }}'
    assert jobs['prerelease']['env']['ROLLING'] == 'wheels'


@pytest.mark.parametrize(
    ('release', 'jobs'),
    [
        (_RELEASE, {'release', 'prerelease'}),
        ('release = { versioned = true }\n', {'release'}),
        ('release = { rolling = "nightly" }\n', {'prerelease'}),
        ('', set()),
    ],
)
def test_only_the_declared_releases_are_rendered(release: str, jobs: set[str]) -> None:
    assert set(_flow(release)['jobs']) == {'build', 'sdist', 'test', 'test-sdist', *jobs}


_SHA, _OTHER = 'a' * 40, 'b' * 40
#: ``gh`` standing in for GitHub: each call logged to stderr; ``$AT`` is the commit the tag resolves to (none when
#: empty), ``$RELEASED`` whether a release of the tag exists.
_FAKE_GH = """\
gh() {
  echo "gh $*" >&2
  case "$1 $2" in
    "api "*) [ -n "$AT" ] && echo "$AT" ;;
    "release view") [ "$RELEASED" = 1 ] ;;
    *) return 0 ;;
  esac
}
"""


def _published(
    tmp_path: Path, job: str, *, at: str, released: bool, existing: str = EXISTING[0]
) -> tuple[int, str, list[str]]:
    """Run *job*'s publishing step with the tag at commit *at* (``''``: no tag): exit code, stdout, ``gh`` calls."""
    release = f'release = {{ rolling = "wheels", versioned = true, existing = "{existing}" }}\n'
    run = _flow(release)['jobs'][job]['steps'][-1]['run']
    bash = shutil.which('bash')
    assert bash, 'the step is bash'
    env = {
        **os.environ, 'AT': at, 'RELEASED': '1' if released else '0', 'GITHUB_SHA': _SHA, 'VERSION': '1.2.0',
        'TAG': 'v1.2.0', 'ROLLING': 'wheels', 'GITHUB_REPOSITORY': 'owner/pkg', 'GITHUB_SERVER_URL': 'https://x',
        'GITHUB_RUN_ID': '7',
    }  # fmt: skip
    done = subprocess.run(
        [bash, '-e', '-c', _FAKE_GH + run],
        env=env,
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        encoding='utf-8',
    )
    return done.returncode, done.stdout, [line for line in done.stderr.splitlines() if line.startswith('gh ')]


def _writes(calls: list[str]) -> list[str]:
    return [call for call in calls if call.startswith(('gh release create', 'gh release delete'))]


def test_an_unreleased_version_is_published_as_v_version_and_the_latest(tmp_path: Path) -> None:
    code, _, calls = _published(tmp_path, 'release', at='', released=False)
    assert code == 0
    (create,) = _writes(calls)
    assert create.startswith('gh release create v1.2.0 dist/* --repo owner/pkg --target ' + _SHA + ' --latest')


def test_a_released_version_is_never_overwritten_by_a_re_run_of_its_commit(tmp_path: Path) -> None:
    code, out, calls = _published(tmp_path, 'release', at=_SHA, released=True)
    assert (code, _writes(calls)) == (0, [])
    assert 'its assets are never overwritten' in out


def test_a_trunk_build_of_a_version_released_from_another_commit_is_refused_naming_both(tmp_path: Path) -> None:
    code, out, calls = _published(tmp_path, 'release', at=_OTHER, released=True)
    assert (code, _writes(calls)) == (1, [])
    assert f'v1.2.0 is released from {_OTHER}, and this trunk build {_SHA}' in out
    assert 'existing = "keep"' in out, 'the refusal names the declaration that changes it'


def test_existing_keep_leaves_a_version_released_from_another_commit_as_it_is(tmp_path: Path) -> None:
    code, out, calls = _published(tmp_path, 'release', at=_OTHER, released=True, existing='keep')
    assert (code, _writes(calls)) == (0, [])
    assert f'v1.2.0 is released from {_OTHER}' in out


@pytest.mark.parametrize('before', ['released', 'absent'])
def test_the_rolling_prerelease_is_recreated_at_the_built_commit(tmp_path: Path, before: str) -> None:
    released = before == 'released'
    code, _, calls = _published(tmp_path, 'prerelease', at=_OTHER, released=released)
    assert code == 0
    *deleted, create = _writes(calls)
    assert deleted == (['gh release delete wheels --repo owner/pkg --yes --cleanup-tag'] if released else [])
    assert create.startswith(f'gh release create wheels dist/* --repo owner/pkg --target {_SHA} --prerelease ')
    assert '--latest' not in create, 'a prerelease is never the latest'


def test_every_action_is_pinned_to_a_major_version() -> None:
    flow = _flow()
    used = {step['uses'] for job in flow['jobs'].values() for step in job['steps'] if 'uses' in step}
    assert all(_pinned_major(name) for name in used), used
    assert 'PyO3/maturin-action@v1' in used


def _pinned_major(action: str) -> bool:
    """Whether *action* names its major version tag (``owner/name@vN``), the family's pin."""
    _, _, version = action.partition('@')
    return version.startswith('v') and version[1:].isdigit()


def test_the_promote_job_dispatches_the_wheels_on_the_trunk_after_promoting() -> None:
    # The job token's push of the trunk starts no workflow: the job that pushed it starts the wheels.
    promote = _rendered(_MATURIN + _INTEGRATOR + _WHEELS)['ci.yml']['jobs']['promote']
    at = next(i for i, step in enumerate(promote['steps']) if _PROMOTES in step.get('run', ''))
    step = promote['steps'][at + 1]
    assert step['name'] == 'Build the native wheels of the promoted stable'
    assert step['run'] == f'gh workflow run {WORKFLOW} --repo "$GITHUB_REPOSITORY" --ref stable'
    assert 'if' not in step, 'only once the promote step passed'
    assert promote['permissions']['actions'] == 'write'


def test_a_repo_without_the_table_renders_nothing_of_it() -> None:
    rendered = _rendered(_MATURIN + _INTEGRATOR)
    assert WORKFLOW not in rendered
    promote = rendered['ci.yml']['jobs']['promote']
    assert WORKFLOW not in json.dumps(promote)
    assert 'actions' not in promote['permissions']


def test_a_repo_whose_promote_is_on_a_host_still_renders_the_wheels() -> None:
    # The host pushes the trunk with its own credential, and that push starts the workflow.
    rendered = _rendered(_MATURIN + _WHEELS, roles=HPC_REPO)
    assert WORKFLOW in rendered
    assert 'promote' not in rendered.get('ci.yml', {}).get('jobs', {})


_ONE = 'targets = ["linux-x86_64"]\npython = ["3.12"]\n'
_OK = _ONE + 'abi3 = false\n'


@pytest.mark.parametrize(
    ('table', 'why'),
    [
        ('targets = ["linux-x86_64"]\nabi3 = false\n', 'python is not'),
        ('targets = ["linux-riscv"]\npython = ["3.12"]\nabi3 = false\n', 'targets is not'),
        ('targets = []\npython = ["3.12"]\nabi3 = false\n', 'targets is not'),
        ('targets = ["linux-x86_64"]\npython = ["3.12", "3.12"]\nabi3 = false\n', 'python is not'),
        ('targets = ["linux-x86_64"]\npython = ["3.1x"]\nabi3 = false\n', 'python is not'),
        (_ONE, 'abi3 is neither'),
        (_ONE + 'abi3 = true\n', 'abi3 is neither'),
        (_ONE + 'abi3 = "3.13"\n', 'abi3 = "3.13" is above the oldest python'),
        (_OK + 'manylinux = "2 28"\n', 'manylinux is not'),
        (_OK + 'pypi = true\n', "unknown key(s) ['pypi']"),
        (_OK + 'release = "wheels"\n', 'release is not a table'),
        (_OK + 'release = {}\n', 'release declares neither rolling nor versioned = true'),
        (_OK + 'release = { versioned = false }\n', 'release declares neither rolling nor versioned = true'),
        (_OK + 'release = { rolling = "a b" }\n', 'release.rolling is not a tag name'),
        (_OK + 'release = { rolling = "v1.2" }\n', "release.rolling = 'v1.2' is a v<digit> tag"),
        (_OK + 'release = { versioned = "yes" }\n', 'release.versioned is not true or false'),
        (_OK + 'release = { versioned = true, existing = "replace" }\n', 'release.existing is not one of'),
        (_OK + 'release = { rolling = "wheels", existing = "keep" }\n', 'existing is declared without versioned'),
        (_OK + 'release = { versioned = true, latest = true }\n', "release has unknown key(s) ['latest']"),
    ],
)
def test_a_malformed_declaration_is_refused_naming_the_shape(table: str, why: str) -> None:
    with pytest.raises(ValueError, match='write ') as refused:
        _rendered(_MATURIN + '[tool.dev_lab.wheels]\n' + table)
    assert why in str(refused.value)
    assert SHAPE in str(refused.value), 'the refusal names the shape to write'


def test_every_target_and_every_existing_choice_is_named_in_the_shape() -> None:
    assert all(name in SHAPE for name in (*TARGETS, *EXISTING))


def test_a_declaration_with_no_module_to_import_is_refused_naming_it() -> None:
    with pytest.raises(ValueError, match=r'\[tool.maturin\] module-name = None names none'):
        _rendered(_WHEELS)


def test_a_gitea_repo_declaring_wheels_is_refused() -> None:
    with pytest.raises(ValueError, match='this repo is on gitea, which has none: delete the table'):
        _rendered(_MATURIN + _WHEELS, forge='gitea')


def test_a_ci_table_declaring_the_wheels_workflow_is_refused() -> None:
    with pytest.raises(ValueError, match=r'delete that table and declare what differs in \[tool.dev_lab.wheels\]'):
        _rendered(_MATURIN + _WHEELS + '[tool.dev_lab.ci."wheels.yml"]\nname = "mine"\n')


def test_the_rendered_file_is_declared_written_and_without_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ciworkflows, 'repo_forge', lambda _root: 'github')
    (tmp_path / 'pyproject.toml').write_text(_MATURIN + _WHEELS, encoding='utf-8')
    assert f'.github/workflows/{WORKFLOW}' in declared_paths(tmp_path)
    write(tmp_path)
    assert (tmp_path / '.github' / 'workflows' / WORKFLOW).is_file()
    assert drift(tmp_path) == []
    (tmp_path / 'pyproject.toml').write_text(_MATURIN, encoding='utf-8')
    assert f'.github/workflows/{WORKFLOW}' not in declared_paths(tmp_path), 'PLANTED CONTROL'
    write(tmp_path)
    assert not (tmp_path / '.github' / 'workflows' / WORKFLOW).exists(), 'an undeclared render is removed'
