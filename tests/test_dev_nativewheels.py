"""NATIVE WHEELS ARE OPT-IN (#981): ``[tool.dev_lab.native] wheels`` renders ``wheels.yml``; no declaration, no job."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _roles_fixtures import EVERY_CI, carry

from dev_lab.dev import ciworkflows, nativewheels
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
    assert sorted(row['os'] for row in rows) == sorted(nativewheels.RUNNERS.values())
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
