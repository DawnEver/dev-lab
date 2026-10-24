"""Dependency groups are a separate install axis, and frozen installs do not re-resolve."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from dev_lab.dev.collectcensus import CollectRow, assert_reaches, measure
from dev_lab.dev.installdoor import Delivery, classify, floating_in_manifest, scan_doors
from dev_lab.dev.syncscope import Scope, scope, selection, survivors

MANIFEST = """
[project]
name = "fixture"
dependencies = ["numpy"]
[dependency-groups]
dev = [{include-group = "lint"}, "pytest", "dev-lab @ git+https://example.invalid/dev.git"]
lint = ["ruff"]
docs = ["sphinx"]
"""


def test_plain_sync_includes_the_actual_default_dev_group_not_a_fake_extra() -> None:
    chosen = selection(['uv', 'sync'])
    assert scope(chosen, MANIFEST) is Scope.COMPLETE
    assert survivors(chosen, MANIFEST) == {'fixture', 'numpy', 'pytest', 'ruff', 'dev-lab'}
    with pytest.raises(ValueError, match='dev'):
        survivors(selection(['uv', 'sync', '--extra', 'dev']), MANIFEST)


@pytest.mark.parametrize(
    'flags',
    [
        ['--no-dev'],
        ['--no-default-groups'],
        ['--no-group', 'dev'],
    ],
)
def test_disabling_group_tooling_really_strands_the_verdict(flags) -> None:
    assert scope(selection(['uv', 'sync', *flags]), MANIFEST) is Scope.STRANDS


@pytest.mark.parametrize(
    'flags',
    [
        ['--group', 'dev'],
        ['--group=dev'],
        ['--all-groups'],
    ],
)
def test_groups_are_selected_after_defaults_are_disabled(flags) -> None:
    assert scope(selection(['uv', 'sync', '--no-default-groups', *flags]), MANIFEST) is Scope.COMPLETE


def test_only_group_excludes_the_project_and_default_groups() -> None:
    chosen = selection(['uv', 'sync', '--only-group', 'lint'])
    assert survivors(chosen, MANIFEST) == {'ruff'}
    assert scope(chosen, MANIFEST) is Scope.STRANDS


def test_exclusion_wins_over_explicit_and_all_group_inclusion() -> None:
    chosen = selection(['uv', 'sync', '--all-groups', '--group', 'dev', '--no-group', 'dev'])
    assert 'pytest' not in survivors(chosen, MANIFEST)
    assert scope(chosen, MANIFEST) is Scope.STRANDS


def test_manifest_default_groups_are_not_assumed_to_be_dev() -> None:
    text = MANIFEST + '\n[tool.uv]\ndefault-groups = ["docs"]\n'
    assert scope(selection(['uv', 'sync']), text) is Scope.STRANDS
    assert scope(selection(['uv', 'sync', '--group', 'dev']), text) is Scope.COMPLETE


@pytest.mark.parametrize('defaults', ['"docs"', '42', '["docs", 42]'])
def test_malformed_manifest_defaults_are_refused_not_guessed(defaults) -> None:
    text = MANIFEST + f'\n[tool.uv]\ndefault-groups = {defaults}\n'
    with pytest.raises(ValueError, match='default-groups'):
        survivors(selection(['uv', 'sync']), text)


def test_only_groups_with_project_extras_is_refused_rather_than_claimed_complete() -> None:
    text = MANIFEST + '\n[project.optional-dependencies]\ndev = ["pytest", "ruff"]\n'
    with pytest.raises(ValueError, match='only-group'):
        survivors(selection(['uv', 'sync', '--only-group', 'lint', '--extra', 'dev']), text)


def test_an_unknown_excluded_group_is_not_silently_ignored() -> None:
    with pytest.raises(ValueError, match='group'):
        survivors(selection(['uv', 'sync', '--no-group', 'missing']), MANIFEST)


def test_group_flags_owned_by_the_child_do_not_change_uv_selection() -> None:
    chosen = selection(['uv', 'run', 'pytest', '--no-dev'])
    assert scope(chosen, MANIFEST) is Scope.COMPLETE


def test_dynamic_group_selection_is_unmeasured_not_an_empty_selection() -> None:
    assert scope(selection(['uv', 'sync', '--group', '$GROUP']), MANIFEST) is Scope.UNMEASURED


def test_unknown_and_cyclic_group_includes_are_refused() -> None:
    for text in [
        MANIFEST.replace('include-group = "lint"', 'include-group = "missing"'),
        MANIFEST.replace('lint = ["ruff"]', 'lint = [{include-group = "dev"}]'),
    ]:
        with pytest.raises(ValueError, match=r'group|cycle'):
            survivors(selection(['uv', 'sync']), text)


def test_collection_census_records_actual_groups_without_turning_them_into_extras(tmp_path) -> None:
    git = shutil.which('git')
    assert git is not None
    subprocess.run([git, 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / 'pyproject.toml').write_text(MANIFEST, encoding='utf-8')
    tests = tmp_path / 'tests'
    tests.mkdir()
    (tests / 'test_fixture.py').write_text('import pytest\n', encoding='utf-8')
    result = measure(tmp_path, (), groups=('dev',), at_head=False)
    assert not result.errors
    assert not result.degrades
    assert not result.unresolved
    row = CollectRow(
        'fixture',
        (),
        frozenset(),
        frozenset(),
        frozenset(),
        'The real manifest declares dependency groups, not an interchangeable development extra. '
        'This row must join its selected groups to collection imports, preserve equality in both '
        'directions and keep a nonvacuous test-tree floor rather than weakening the census.',
        groups=('dev',),
    )
    assert assert_reaches((row,), {'fixture': tmp_path}, {'fixture': 1}, here='fixture', repo_floor=1, row_floor=1) == {
        'fixture'
    }


def test_floating_requirements_include_all_actual_group_entries() -> None:
    assert floating_in_manifest(MANIFEST) == ('dev-lab',)


@pytest.mark.parametrize('flag', ['--frozen', '--locked'])
def test_locked_install_is_not_misrepresented_as_reresolution(flag) -> None:
    assert classify(['uv', 'sync', flag], ('dev-lab',), locked=True) is Delivery.LOCKED
    assert classify(['uv', 'sync', flag], ('dev-lab',)) is Delivery.UNMEASURED


def test_a_child_frozen_flag_does_not_prove_a_uv_install_lock() -> None:
    assert classify(['uv', 'run', 'pytest', '--frozen'], ('dev-lab',), locked=True) is Delivery.UNLOCKED


def test_freezing_does_not_become_an_upgrade_when_both_flags_appear() -> None:
    assert classify(['uv', 'sync', '--frozen', '-U'], ('dev-lab',), locked=True) is Delivery.LOCKED


@pytest.mark.parametrize('flag', ['--directory', '--project', '--script', '--config-file'])
def test_another_project_cannot_borrow_the_scanned_roots_lock_proof(flag) -> None:
    assert classify(['uv', 'sync', '--frozen', flag, 'elsewhere'], ('dev-lab',), locked=True) is Delivery.UNMEASURED


def test_global_directory_redirect_cannot_look_like_an_inert_command() -> None:
    assert (
        classify(['uv', '--directory=elsewhere', 'sync', '--frozen'], ('dev-lab',), locked=True) is Delivery.UNMEASURED
    )
    assert (
        classify(['uv', '--directory', 'elsewhere', 'sync', '--frozen'], ('dev-lab',), locked=True)
        is Delivery.UNMEASURED
    )


def test_actual_tracked_readable_lock_is_required_at_the_scan_boundary(tmp_path) -> None:
    (tmp_path / 'Makefile').write_text('install:\n\tuv sync --frozen\n', encoding='utf-8')
    lock = tmp_path / 'uv.lock'
    lock.write_text(
        'version = 1\n[[package]]\nname = "fixture"\nversion = "1"\nsource = {virtual = "."}\n', encoding='utf-8'
    )
    git = shutil.which('git')
    assert git is not None
    subprocess.run([git, 'init', '-q', str(tmp_path)], check=True)
    assert scan_doors(tmp_path, ['Makefile'], ('dev-lab',))[0].delivery is Delivery.UNMEASURED
    subprocess.run([git, '-C', str(tmp_path), 'add', 'uv.lock'], check=True)
    assert scan_doors(tmp_path, ['Makefile'], ('dev-lab',))[0].delivery is Delivery.LOCKED
    lock.write_text('invalid [', encoding='utf-8')
    assert scan_doors(tmp_path, ['Makefile'], ('dev-lab',))[0].delivery is Delivery.UNMEASURED
