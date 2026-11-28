"""NATIVE WHEELS ARE OPT-IN (#981): ``[tool.dev_lab.native] wheels`` renders ``wheels.yml``; no declaration, no job."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _roles_fixtures import EVERY_CI, carry

from dev_lab.dev import ciworkflows, nativewheeljobs, nativewheels, rusttoolchain
from dev_lab.dev.ciworkflows import drift, workflows, write

_MATURIN = """\
[project]
name = "doc-lab"
requires-python = ">=3.12"

[build-system]
requires = ["maturin>=1.7"]
build-backend = "maturin"

[tool.maturin]
module-name = "doc_lab._pdf"
"""
_DECLARED = _MATURIN + '\n[tool.dev_lab.native]\nwheels = ["linux", "windows", "macos"]\n'


def _repo(tmp_path: Path, text: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / 'pyproject.toml').write_text(text, encoding='utf-8')
    return tmp_path


@pytest.fixture(autouse=True)
def _github(monkeypatch: pytest.MonkeyPatch) -> None:
    carry(monkeypatch, EVERY_CI)
    monkeypatch.setattr(ciworkflows, 'repo_forge', lambda _root: 'github')


def test_an_undeclared_repo_renders_no_wheels_workflow(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same maturin repo without the declaration gets nothing."""
    assert nativewheels.wheels_workflow(_MATURIN, 'x') is None
    assert nativewheels.WORKFLOW not in workflows(_repo(tmp_path, _MATURIN))


def test_a_declared_maturin_repo_builds_one_abi3_wheel_per_declared_os_on_push_to_main(tmp_path: Path) -> None:
    flow = workflows(_repo(tmp_path, _DECLARED))[nativewheels.WORKFLOW]
    assert flow['on']['push']['branches'] == ['main']
    assert 'workflow_dispatch' in flow['on']
    build = flow['jobs']['build']
    assert [row['os'] for row in build['strategy']['matrix']['include']] == [
        'ubuntu-latest',
        'windows-latest',
        'macos-latest',
    ]
    steps = json.dumps(build['steps'])
    assert 'PyO3/maturin-action' in steps
    assert 'cibuildwheel' not in steps
    assert 'abi3' in steps
    assert 'import doc_lab._pdf' in steps
    assert 'actions/upload-artifact' in steps
    assert 'main-latest' in json.dumps(flow['jobs']['publish'])


def test_a_subset_of_systems_builds_only_those() -> None:
    text = _MATURIN + '\n[tool.dev_lab.native]\nwheels = ["linux"]\n'
    build = nativewheels.wheels_workflow(text, 'x')
    assert build is not None
    assert [row['os'] for row in build['jobs']['build']['strategy']['matrix']['include']] == ['ubuntu-latest']


def test_another_backend_builds_with_cibuildwheel() -> None:
    text = _DECLARED.replace('build-backend = "maturin"', 'build-backend = "setuptools.build_meta"')
    flow = nativewheels.wheels_workflow(text, 'x')
    assert flow is not None
    steps = json.dumps(flow['jobs']['build']['steps'])
    assert 'pypa/cibuildwheel' in steps
    assert 'maturin-action' not in steps
    assert 'import doc_lab._pdf' in steps


def test_every_wheel_and_the_sdist_carry_their_build_provenance_attestation() -> None:
    flow = nativewheels.wheels_workflow(_DECLARED, 'x')
    assert flow is not None
    build = flow['jobs']['build']
    attest = [step for step in build['steps'] if 'attest-build-provenance' in step.get('uses', '')]
    assert [step['with']['subject-path'] for step in attest] == ['dist/*']
    upload = next(i for i, step in enumerate(build['steps']) if 'upload-artifact' in step.get('uses', ''))
    assert build['steps'].index(attest[0]) < upload
    assert build['permissions'] == {'contents': 'read', 'id-token': 'write', 'attestations': 'write'}


def test_the_sdist_is_built_installed_and_imported_on_a_fresh_runner_with_the_family_toolchain() -> None:
    flow = nativewheels.wheels_workflow(_DECLARED, 'x')
    assert flow is not None
    job = flow['jobs']['test-sdist']
    assert job['needs'] == 'build'
    assert job['runs-on'] == 'ubuntu-latest'
    steps = json.dumps(job['steps'])
    assert 'actions/checkout' not in steps
    assert f'rustup default {rusttoolchain.CHANNEL}' in steps
    assert 'pip install dist/*.tar.gz' in steps
    assert 'import doc_lab._pdf' in steps
    assert flow['jobs']['publish']['needs'] == ['build', 'test-sdist']


def test_a_non_maturin_build_carries_no_sdist_test() -> None:
    """PLANTED CONTROL: cibuildwheel builds no sdist, so nothing tests one."""
    text = _DECLARED.replace('build-backend = "maturin"', 'build-backend = "setuptools.build_meta"')
    flow = nativewheels.wheels_workflow(text, 'x')
    assert flow is not None
    assert 'test-sdist' not in flow['jobs']
    assert flow['jobs']['publish']['needs'] == ['build']


def test_a_maturin_repo_declaring_no_linux_builds_no_sdist_to_test() -> None:
    """PLANTED CONTROL: the sdist is built on the Linux runner only, so without it nothing tests one."""
    flow = nativewheels.wheels_workflow(_MATURIN + '\n[tool.dev_lab.native]\nwheels = ["windows"]\n', 'x')
    assert flow is not None
    assert 'test-sdist' not in flow['jobs']


def test_the_import_defaults_to_the_project_name() -> None:
    text = _DECLARED.replace('module-name = "doc_lab._pdf"', '')
    flow = nativewheels.wheels_workflow(text, 'x')
    assert flow is not None
    assert 'import doc_lab' in json.dumps(flow['jobs']['build']['steps'])


@pytest.mark.parametrize(
    ('declaration', 'named'),
    [('wheels = ["solaris"]', 'solaris'), ('wheels = []', 'no system'), ('wheels = "linux"', 'list')],
)
def test_a_malformed_declaration_is_refused_by_name(declaration: str, named: str) -> None:
    with pytest.raises((ValueError, TypeError), match=named):
        nativewheels.wheels_workflow(_MATURIN + f'\n[tool.dev_lab.native]\n{declaration}\n', 'x')


def test_a_gitea_repo_declaring_wheels_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ciworkflows, 'repo_forge', lambda _root: 'gitea')
    with pytest.raises(ValueError, match='GitHub'):
        workflows(_repo(tmp_path, _DECLARED))


def test_the_render_writes_the_file_and_drift_accepts_it(tmp_path: Path) -> None:
    root = _repo(tmp_path, _DECLARED)
    written = write(root)
    assert root / '.github/workflows' / nativewheels.WORKFLOW in written
    assert drift(root) == []
    assert '.github/workflows/wheels.yml' in ciworkflows.declared_paths(root)
    assert '.github/workflows/wheels.yml' not in ciworkflows.declared_paths(_repo(tmp_path / 'u', _MATURIN))


# VENDORED WHEELS (FAM-16): a family-pinned third-party commit, built per OS on Actions so no consumer compiles it.
_REV = '595b43eb6682992a0b1012b9671bf860c0e6ae56'
_VENDORED = (
    '[project]\nname = "dev-lab"\n\n[tool.dev_lab.native.vendor.triangle]\n'
    f'git = "https://github.com/drufat/triangle"\nrev = "{_REV}"\n'
)


def test_an_undeclared_repo_renders_no_vendor_workflow(tmp_path: Path) -> None:
    """PLANTED CONTROL: the native wheels declaration alone vendors nothing."""
    assert nativewheels.vendor_workflow(_DECLARED, 'x') is None
    assert nativewheels.VENDOR_WORKFLOW not in workflows(_repo(tmp_path, _DECLARED))


def test_a_vendored_commit_builds_family_python_wheels_on_every_os_from_that_commit(tmp_path: Path) -> None:
    flow = workflows(_repo(tmp_path, _VENDORED))[nativewheels.VENDOR_WORKFLOW]
    assert flow['on']['push'] == {'branches': ['main'], 'paths': ['pyproject.toml']}
    build = flow['jobs']['build']
    rows = build['strategy']['matrix']['include']
    assert sorted(row['os'] for row in rows) == sorted(
        nativewheeljobs.RUNNERS[name] for name in nativewheels.VENDOR_SYSTEMS
    )
    assert {row['dist'] for row in rows} == {'triangle'}
    assert {(row['repository'], row['rev']) for row in rows} == {('drufat/triangle', _REV)}
    steps = json.dumps(build['steps'])
    assert 'recursive' in steps  # triangle's C sources are a submodule
    assert 'pypa/cibuildwheel@v3' in steps
    assert f'cp{nativewheels.VERSION.replace(".", "")}-*' in steps


def test_a_vendored_wheel_is_tested_by_importing_it_not_by_the_upstream_test_tree(tmp_path: Path) -> None:
    # The upstream pyproject's own cibuildwheel test-command (`pytest {project}/tests`) named a directory the pinned
    # commit lacks (Actions run 46093742941): the build must not depend on the upstream test tree.
    build = workflows(_repo(tmp_path, _VENDORED))[nativewheels.VENDOR_WORKFLOW]['jobs']['build']
    env = next(step['env'] for step in build['steps'] if 'env' in step)
    assert env['CIBW_TEST_COMMAND'] == 'python -c "import ${{ matrix.dist }}"'
    assert env['CIBW_TEST_REQUIRES'] == ''


def test_a_vendored_commit_publishes_to_its_own_immutable_release() -> None:
    flow = nativewheels.vendor_workflow(_VENDORED, 'x')
    assert flow is not None
    publish = json.dumps(flow['jobs']['publish'])
    assert nativewheels.vendor_release('triangle', _REV) == 'vendor-triangle-595b43eb6682'
    assert 'vendor-triangle-595b43eb6682' in json.dumps(flow['jobs'])
    assert '--clobber' not in publish  # a published wheel is never replaced: a consumer's lock pins its hash


@pytest.mark.parametrize(
    ('row', 'named'),
    [
        ('git = "https://github.com/drufat/triangle"\nrev = "595b43eb"', '40-hex'),
        (f'rev = "{_REV}"', 'git'),
        ('git = "https://github.com/drufat/triangle"', 'rev'),
    ],
)
def test_a_malformed_vendor_row_is_refused_by_name(row: str, named: str) -> None:
    with pytest.raises(ValueError, match=named):
        nativewheels.vendor_workflow(f'[project]\nname = "x"\n[tool.dev_lab.native.vendor.triangle]\n{row}\n', 'x')


def test_a_gitea_repo_vendoring_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ciworkflows, 'repo_forge', lambda _root: 'gitea')
    with pytest.raises(ValueError, match='GitHub'):
        workflows(_repo(tmp_path, _VENDORED))


def test_the_vendor_render_writes_the_file_and_drift_accepts_it(tmp_path: Path) -> None:
    root = _repo(tmp_path, _VENDORED)
    assert root / '.github/workflows' / nativewheels.VENDOR_WORKFLOW in write(root)
    assert drift(root) == []
    assert f'.github/workflows/{nativewheels.VENDOR_WORKFLOW}' in ciworkflows.declared_paths(root)


def _flow(extra: str, base: str = _DECLARED) -> dict[str, Any]:
    flow = nativewheels.wheels_workflow(base + extra, 'x')
    assert flow is not None
    return flow


def _publish_steps(flow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {step.get('name', ''): step for step in flow['jobs']['publish']['steps']}


_VERSIONED = 'Publish v<version> unless it is released'


def test_versioned_publishes_v_version_read_from_the_sdist_and_refuses_another_commit_by_default() -> None:
    step = _publish_steps(_flow('versioned = true\n'))[_VERSIONED]
    assert "'*/PKG-INFO'" in step['run']
    assert step['if'] == "github.ref == 'refs/heads/main'"
    assert '::error::$tag is released from $at' in step['run']
    assert 'gh release create "$tag" dist/*' in step['run']


def test_existing_keep_leaves_a_version_released_from_another_commit() -> None:
    run = _publish_steps(_flow('versioned = true\nexisting = "keep"\n'))[_VERSIONED]['run']
    assert 'existing = \\"keep\\" leaves it as it is' in run
    assert '::error::$tag is released' not in run


def test_without_versioned_no_version_release_is_rendered_PLANTED() -> None:
    assert _VERSIONED not in _publish_steps(_flow(''))


@pytest.mark.parametrize(
    ('extra', 'named'),
    [
        ('existing = "keep"\n', 'existing'),
        ('versioned = true\nexisting = "overwrite"\n', 'existing'),
        ('versioned = "yes"\n', 'versioned'),
        ('rolling = "v1-latest"\n', 'rolling'),
        ('rolling = ""\n', 'rolling'),
        ('python = ["3.x"]\n', 'python'),
        ('abi3 = false\n', 'abi3 = false'),
        ('abi3 = "no"\n', 'abi3'),
        ('manylinux = "musllinux"\n', 'manylinux'),
    ],
)
def test_a_malformed_option_is_refused_naming_it(extra: str, named: str) -> None:
    with pytest.raises(ValueError, match=named):
        nativewheels.wheels_workflow(_DECLARED + extra, 'x')


def test_versioned_without_an_sdist_is_refused() -> None:
    text = _MATURIN + '\n[tool.dev_lab.native]\nwheels = ["windows"]\nversioned = true\n'
    with pytest.raises(ValueError, match='versioned reads the version from the sdist'):
        nativewheels.wheels_workflow(text, 'x')


def test_a_declared_rolling_tag_replaces_main_latest() -> None:
    steps = _publish_steps(_flow('rolling = "nightly"\n'))
    assert 'gh release create nightly dist/* --prerelease' in steps['Replace the rolling nightly prerelease']['run']
    assert f'Replace the rolling {nativewheels.ROLLING} prerelease' in _publish_steps(_flow(''))


def test_arm64_systems_build_on_their_native_runners_and_one_sdist_is_built() -> None:
    text = _MATURIN + '\n[tool.dev_lab.native]\nwheels = ["linux", "linux-arm64", "windows-arm64"]\n'
    cells = _flow('', text)['jobs']['build']['strategy']['matrix']['include']
    assert [cell['os'] for cell in cells] == ['ubuntu-latest', 'ubuntu-24.04-arm', 'windows-11-arm']
    assert [cell['sdist'] for cell in cells] == [True, False, False]


def test_an_unknown_system_is_refused_naming_the_systems_PLANTED() -> None:
    with pytest.raises(ValueError, match='linux-arm64'):
        nativewheels.wheels_workflow(_MATURIN + '\n[tool.dev_lab.native]\nwheels = ["linux-riscv"]\n', 'x')


def test_a_python_list_tests_each_wheel_installed_on_every_version() -> None:
    flow = _flow('python = ["3.13", "3.14"]\n')
    cells = flow['jobs']['test']['strategy']['matrix']['include']
    runners = ('ubuntu-latest', 'windows-latest', 'macos-latest')
    assert {(cell['os'], cell['python']) for cell in cells} == {(r, v) for r in runners for v in ('3.13', '3.14')}
    assert {cell['artifact'] for cell in cells} == {f'wheels-{runner}' for runner in runners}
    assert 'actions/checkout' not in json.dumps(flow['jobs']['test']['steps'])
    assert flow['jobs']['publish']['needs'] == ['build', 'test', 'test-sdist']


def test_without_a_python_list_no_test_job_is_rendered_PLANTED() -> None:
    assert 'test' not in _flow('')['jobs']


def test_abi3_false_builds_one_wheel_per_system_and_version_without_the_abi3_refusal() -> None:
    build = _flow('python = ["3.13", "3.14"]\nabi3 = false\n')['jobs']['build']
    cells = build['strategy']['matrix']['include']
    assert len(cells) == 6
    assert {cell['artifact'] for cell in cells} >= {'wheels-ubuntu-latest-cp313', 'wheels-ubuntu-latest-cp314'}
    assert sum(cell['sdist'] for cell in cells) == 1
    steps = json.dumps(build['steps'])
    assert 'not abi3' not in steps
    assert '--interpreter ${{ matrix.python }}' in steps
    assert 'not abi3' in json.dumps(_flow('')['jobs']['build']['steps'])


def test_abi3_false_with_cibuildwheel_builds_each_version() -> None:
    text = _DECLARED.replace('build-backend = "maturin"', 'build-backend = "setuptools.build_meta"')
    build = _flow('python = ["3.13"]\nabi3 = false\n', text)['jobs']['build']
    assert build['strategy']['matrix']['include'][0]['cibw'] == 'cp313-*'
    assert build['steps'][2]['env']['CIBW_BUILD'] == '${{ matrix.cibw }}'


def test_a_manylinux_policy_reaches_maturin_and_cibuildwheel() -> None:
    assert '"manylinux": "2_28"' in json.dumps(_flow('manylinux = "2_28"\n')['jobs']['build']['steps'])
    assert '"manylinux": "auto"' in json.dumps(_flow('')['jobs']['build']['steps'])
    text = _DECLARED.replace('build-backend = "maturin"', 'build-backend = "setuptools.build_meta"')
    env = _flow('manylinux = "2_28"\n', text)['jobs']['build']['steps'][2]['env']
    assert env['CIBW_MANYLINUX_X86_64_IMAGE'] == 'manylinux_2_28'


def test_the_trunk_is_read_from_the_integrator_table() -> None:
    flow = _flow('\n[tool.dev_lab.integrator]\ntrunk = "release"\n')
    assert flow['on']['push']['branches'] == ['release']
    steps = _publish_steps(flow)
    assert steps['Replace the rolling main-latest prerelease']['if'] == "github.ref == 'refs/heads/release'"
    assert _flow('')['on']['push']['branches'] == ['main']


def test_the_promote_job_dispatches_the_wheels_on_the_trunk_after_promoting(tmp_path: Path) -> None:
    promote = workflows(_repo(tmp_path, _DECLARED))['ci.yml']['jobs']['promote']
    runs = [step.get('run', '') for step in promote['steps']]
    at = next(i for i, run in enumerate(runs) if 'dev_lab.dev.integrate promote' in run)
    assert runs[at + 1] == 'gh workflow run wheels.yml --repo "$GITHUB_REPOSITORY" --ref main'
    assert promote['permissions']['actions'] == 'write'


def test_an_undeclared_repo_s_promote_dispatches_nothing_PLANTED(tmp_path: Path) -> None:
    promote = workflows(_repo(tmp_path, _MATURIN))['ci.yml']['jobs']['promote']
    assert not any('gh workflow run' in step.get('run', '') for step in promote['steps'])


def test_a_ci_without_a_promote_job_is_returned_as_is() -> None:
    ci: dict[str, Any] = {'jobs': {'parts': {'steps': []}}}
    assert nativewheels.dispatched(ci, _DECLARED, 'x') is ci
