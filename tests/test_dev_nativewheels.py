"""``[tool.dev_lab.wheels]`` renders the native-wheels workflow; a repo without it renders nothing of it (dev-lab #981).

Every planted declaration is invented: a repo whose maturin extension is ``pkg._native``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _roles_fixtures import CI_REPO, HPC_REPO

from dev_lab.dev import ciworkflows
from dev_lab.dev.ciworkflows import declared_paths, drift, placed, write
from dev_lab.dev.nativewheels import MANYLINUX, SHAPE, TARGETS, WORKFLOW

_MATURIN = '[tool.maturin]\nmodule-name = "pkg._native"\n'
_INTEGRATOR = '[tool.dev_lab.integrator]\nintegration = "integrate/main"\ntrunk = "stable"\n'
_WHEELS = (
    '[tool.dev_lab.wheels]\ntargets = ["linux-x86_64", "windows-x86_64", "macos-universal2"]\n'
    'python = ["3.15", "3.12"]\nabi3 = "3.12"\nrelease = "wheels"\n'
)
_PER_VERSION = _WHEELS.replace('abi3 = "3.12"', 'abi3 = false')
_TARGETS = ('linux-x86_64', 'windows-x86_64', 'macos-universal2')
_PROMOTES = 'dev_lab.dev.integrate promote'


def _rendered(text: str, forge: str = 'github', roles: Any = CI_REPO) -> dict[str, dict[str, Any]]:  # noqa: ANN401
    return {name: flow for name, (_, flow) in placed(text, 'pyproject.toml', forge, roles).items()}


def _steps(job: dict[str, Any]) -> list[str]:
    return [step.get('name') or step['uses'] for step in job['steps']]


def _cells(flow: dict[str, Any], job: str) -> list[dict[str, str]]:
    return flow['jobs'][job]['strategy']['matrix']['include']


def test_abi3_builds_one_wheel_per_target_on_its_floor_and_tests_it_on_every_version() -> None:
    flow = _rendered(_MATURIN + _INTEGRATOR + _WHEELS)[WORKFLOW]
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
    test = _rendered(_MATURIN + _WHEELS)[WORKFLOW]['jobs']['test']
    assert test['needs'] == 'build'
    assert not any(step.get('uses', '').startswith('actions/checkout') for step in test['steps'])
    assert test['steps'][-2]['run'] == 'python -m pip install dist/*.whl'
    assert test['steps'][-1]['run'] == 'python -c "import pkg._native"', 'the import is [tool.maturin] module-name'


def test_every_wheel_carries_its_build_provenance_attestation() -> None:
    build = _rendered(_MATURIN + _WHEELS)[WORKFLOW]['jobs']['build']
    names = _steps(build)
    attest = build['steps'][names.index('Attest the build provenance of the wheel')]
    assert attest['uses'] == 'actions/attest-build-provenance@v4'
    assert attest['with'] == {'subject-path': 'dist/*.whl'}
    assert names.index('Attest the build provenance of the wheel') < names.index('actions/upload-artifact@v4')
    assert build['permissions'] == {
        'contents': 'read', 'id-token': 'write', 'attestations': 'write', 'artifact-metadata': 'write'
    }  # fmt: skip


def test_the_trunk_s_wheels_replace_the_declared_release() -> None:
    release = _rendered(_MATURIN + _INTEGRATOR + _WHEELS)[WORKFLOW]['jobs']['release']
    assert release['needs'] == 'test'
    assert release['if'] == "${{ github.ref == 'refs/heads/stable' }}", 'a dispatch elsewhere publishes nothing'
    assert release['permissions'] == {'contents': 'write'}
    assert release['env']['RELEASE'] == 'wheels'
    assert release['steps'][0]['with'] == {'pattern': 'wheel-*', 'path': 'dist', 'merge-multiple': True}
    assert 'gh release create "$RELEASE" dist/*.whl' in release['steps'][-1]['run']
    assert '--target "$GITHUB_SHA"' in release['steps'][-1]['run']


def test_without_a_release_the_wheels_are_the_run_s_artifacts_only() -> None:
    flow = _rendered(_MATURIN + _WHEELS.replace('release = "wheels"\n', ''))[WORKFLOW]
    assert set(flow['jobs']) == {'build', 'test'}
    upload = flow['jobs']['build']['steps'][-1]
    assert upload['uses'] == 'actions/upload-artifact@v4'
    assert upload['with']['if-no-files-found'] == 'error'


def test_every_action_is_pinned_to_a_major_version() -> None:
    flow = _rendered(_MATURIN + _WHEELS)[WORKFLOW]
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
        (_ONE + 'abi3 = false\nrelease = "a b"\n', 'release is not'),
        (_ONE + 'abi3 = false\nmanylinux = "2 28"\n', 'manylinux is not'),
        (_ONE + 'abi3 = false\npypi = true\n', "unknown key(s) ['pypi']"),
    ],
)
def test_a_malformed_declaration_is_refused_naming_the_shape(table: str, why: str) -> None:
    with pytest.raises(ValueError, match='write ') as refused:
        _rendered(_MATURIN + '[tool.dev_lab.wheels]\n' + table)
    assert why in str(refused.value)
    assert SHAPE in str(refused.value), 'the refusal names the shape to write'


def test_every_target_is_named_in_the_shape() -> None:
    assert all(name in SHAPE for name in TARGETS)


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
