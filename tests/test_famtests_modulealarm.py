"""The shared layout body measures real tracked inputs, not a count-shaped substitute for coverage.

Import the proposed owner only inside executed calls: its absence is a real test failure, not a
collection collapse. These fixtures use no private repository identities or fabricated old-policy reader.
"""

from __future__ import annotations

import dataclasses
import shutil
import subprocess
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import BinaryIO, TextIO

import pytest

_GIT = shutil.which('git') or 'git'


def _engine() -> ModuleType:
    return import_module('dev_lab.dev.famtests.modulealarm')


def _policy(unit: str = 'raw', limit: int = 300, *, extra: str = '') -> str:
    return f'[tool.dev_lab.layout]\nmodule_unit = "{unit}"\nmodule_limit = {limit}\n{extra}'


def _repo(root: Path, files: dict[str, str], *, policy: str | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    manifest = '[project]\nname = "planted-layout"\nversion = "0"\n'
    files = {'pyproject.toml': manifest + (_policy() if policy is None else policy), **files}
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding='utf-8')
    subprocess.run([_GIT, 'init', '-q'], cwd=root, check=True, timeout=60)
    subprocess.run([_GIT, 'add', '--', '.'], cwd=root, check=True, timeout=60)
    return root


def test_the_policy_has_explicit_inclusive_units_and_no_guessed_limit(tmp_path: Path) -> None:
    engine = _engine()
    root = _repo(tmp_path, {'src/a.py': 'x = 1\n'}, policy=_policy('code', 300))
    policy = engine.read_policy(root)
    assert policy.module_unit == 'code'
    assert policy.module_limit == 300
    assert not policy.languages


@pytest.mark.parametrize(
    'policy',
    [
        '',
        '[tool.dev_lab.layout]\n',
        '[tool.dev_lab.layout]\nmodule_unit = "raw"\n',
        '[tool.dev_lab.layout]\nmodule_limit = 300\n',
        '[tool.dev_lab.layout\n',
        '[tool.dev_lab]\nlayout = "not-a-policy"\n',
        _policy(extra='roots = ["src"]\n'),
        _policy(extra='suffixes = [".py"]\n'),
        _policy(extra='exempt = ["tests"]\n'),
        _policy(extra='debt = {"src/a.py" = 999999}\n'),
        _policy(extra='directory_limit = 999999\n'),
        _policy(extra='depth_limit = 999999\n'),
    ],
)
def test_missing_malformed_or_escape_shaped_policy_is_refused(tmp_path: Path, policy: str) -> None:
    engine = _engine()
    root = _repo(tmp_path, {'src/a.py': 'x = 1\n'}, policy=policy)
    with pytest.raises(engine.LayoutViolation, match=r'policy|module_|layout'):
        engine.read_policy(root)


@pytest.mark.parametrize('value', ['true', '0', '-1', '1.5', '"300"'])
def test_the_line_limit_is_a_positive_integer_not_a_bool_or_coercion(tmp_path: Path, value: str) -> None:
    engine = _engine()
    policy = f'[tool.dev_lab.layout]\nmodule_unit = "raw"\nmodule_limit = {value}\n'
    root = _repo(tmp_path, {'src/a.py': 'x = 1\n'}, policy=policy)
    with pytest.raises(engine.LayoutViolation, match='module_limit'):
        engine.read_policy(root)


@pytest.mark.parametrize('unit', ['CODE', 'python', 'lines', ''])
def test_unknown_units_are_not_aliases_for_a_supported_measurement(tmp_path: Path, unit: str) -> None:
    engine = _engine()
    root = _repo(tmp_path, {'src/a.py': 'x = 1\n'}, policy=_policy(unit))
    with pytest.raises(engine.LayoutViolation, match='module_unit'):
        engine.read_policy(root)


@pytest.mark.parametrize(
    ('unit', 'limit', 'lines', 'accepted'),
    [
        ('code', 300, 299, True),
        ('code', 300, 300, True),
        ('code', 300, 301, False),
        ('raw', 600, 599, True),
        ('raw', 600, 600, True),
        ('raw', 600, 601, False),
        ('raw', 799, 798, True),
        ('raw', 799, 799, True),
        ('raw', 799, 800, False),
    ],
)
def test_actual_bands_keep_their_exact_inclusive_boundaries(
    tmp_path: Path, unit: str, limit: int, lines: int, *, accepted: bool
) -> None:
    engine = _engine()
    root = _repo(tmp_path, {'src/a.py': 'x = 1\n' * lines}, policy=_policy(unit, limit))
    policy = engine.read_policy(root)
    scan = engine.scan(root, policy)
    assert scan.module_lengths['src/a.py'] == lines
    if accepted:
        engine.assert_layout(scan, policy)
    else:
        with pytest.raises(engine.LayoutViolation, match=r'src/a\.py'):
            engine.assert_layout(scan, policy)


def test_code_and_raw_are_real_different_readings_not_rescaled_names(tmp_path: Path) -> None:
    engine = _engine()
    source = '"""\n' + 'prose\n' * 400 + '"""\n' + '# comment\n' * 100 + 'x = 1\n' * 300
    root = _repo(tmp_path, {'src/a.py': source}, policy=_policy('code', 300))
    policy = engine.read_policy(root)
    scan = engine.scan(root, policy)
    assert scan.module_lengths['src/a.py'] == 300
    engine.assert_layout(scan, policy)
    (root / 'pyproject.toml').write_text(_policy('raw', 300), encoding='utf-8')
    with pytest.raises(engine.LayoutViolation, match=r'src/a\.py'):
        engine.check(root)


@pytest.mark.parametrize('ending', ['lf', 'crlf', 'no-final-newline'])
def test_raw_lines_count_logical_lines_with_or_without_a_final_newline(tmp_path: Path, ending: str) -> None:
    engine = _engine()
    source = {'lf': 'x = 1\nx = 2\n', 'crlf': 'x = 1\r\nx = 2\r\n', 'no-final-newline': 'x = 1\nx = 2'}[ending]
    root = _repo(tmp_path, {'scripts/a.py': source}, policy=_policy('raw', 2))
    policy = engine.read_policy(root)
    scan = engine.scan(root, policy)
    assert scan.module_lengths['scripts/a.py'] == 2
    engine.assert_layout(scan, policy)


@pytest.mark.parametrize('tree', ['src', 'tests', 'scripts', 'a-new-authored-tree'])
@pytest.mark.parametrize(('count', 'accepted'), [(25, True), (26, False)])
def test_the_existing_directory_must_band_is_blocking_in_every_authored_tree(
    tmp_path: Path, tree: str, count: int, *, accepted: bool
) -> None:
    engine = _engine()
    root = _repo(tmp_path, {f'{tree}/a{i}.py': 'x = 1\n' for i in range(count)})
    if accepted:
        engine.check(root)
    else:
        with pytest.raises(engine.LayoutViolation, match=tree):
            engine.check(root)


def test_directory_counts_are_direct_not_recursive(tmp_path: Path) -> None:
    engine = _engine()
    files = {f'src/group{i}/a.py': 'x = 1\n' for i in range(26)}
    root = _repo(tmp_path, files)
    policy = engine.read_policy(root)
    scan = engine.scan(root, policy)
    assert scan.folder_counts['src/group0'] == 1
    assert scan.folder_counts.get('src', 0) == 0
    engine.assert_layout(scan, policy)


def test_a_successful_scan_accounts_for_the_exact_tracked_identity_set(tmp_path: Path) -> None:
    engine = _engine()
    files = {'src/a.py': 'x = 1\n', 'tests/test_a.py': 'x = 1\n', 'scripts/a.py': 'x = 1\n', 'notes.md': 'facts\n'}
    root = _repo(tmp_path, files)
    (root / 'untracked.py').write_text('x = 1\n' * 1000, encoding='utf-8')
    policy = engine.read_policy(root)
    scan = engine.scan(root, policy)
    expected = frozenset({'pyproject.toml', *files})
    assert scan.expected == expected
    assert scan.read == expected
    assert not scan.unread
    substituted = dataclasses.replace(scan, read=(scan.read - {'src/a.py'}) | {'untracked.py'})
    assert len(substituted.read) == len(scan.read), 'the same count must not conceal a different population'
    with pytest.raises(engine.LayoutViolation, match=r'src/a\.py|untracked\.py'):
        engine.assert_layout(substituted, policy)


def test_a_missing_tracked_member_is_not_dropped_behind_a_large_clean_count(tmp_path: Path) -> None:
    engine = _engine()
    files = {f'src/group{i // 20}/a{i}.py': 'x = 1\n' for i in range(60)}
    root = _repo(tmp_path, {**files, 'tests/missing.py': 'x = 1\n'})
    (root / 'tests/missing.py').unlink()
    with pytest.raises(engine.LayoutViolation, match=r'tests/missing\.py'):
        engine.check(root)


def test_an_unreadable_source_member_is_not_counted_as_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine()
    root = _repo(tmp_path, {'src/unreadable.py': 'x = 1\n'})
    target = root / 'src/unreadable.py'
    original = Path.open

    def unreadable(path: Path, *args: object, **kwargs: object) -> TextIO | BinaryIO:
        if path == target:
            message = 'planted unreadable source'
            raise PermissionError(message)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', unreadable)
    with pytest.raises(engine.LayoutViolation, match=r'src/unreadable\.py'):
        engine.check(root)


def test_python_code_measurement_refuses_syntax_errors_without_raw_fallback(tmp_path: Path) -> None:
    engine = _engine()
    root = _repo(tmp_path, {'src/broken.py': 'def broken(:\n'}, policy=_policy('code', 300))
    with pytest.raises(engine.LayoutViolation, match=r'src/broken\.py'):
        engine.check(root)


def test_raw_size_is_not_falsely_advertised_as_a_python_syntax_certificate(tmp_path: Path) -> None:
    engine = _engine()
    root = _repo(tmp_path, {'src/broken.py': 'def broken(:\n'}, policy=_policy('raw', 1))
    policy = engine.read_policy(root)
    scan = engine.scan(root, policy)
    assert scan.module_lengths['src/broken.py'] == 1
    engine.assert_layout(scan, policy)


_NON_PYTHON = [
    ('javascript', 'js', 'function f() {}\n// actual JavaScript\n'),
    ('rust', 'rs', 'fn main() {}\n// actual Rust\n'),
    ('shell', 'sh', '#!/bin/sh\necho ready\n'),
    ('powershell', 'ps1', 'param()\nWrite-Output ready\n'),
]


@pytest.mark.parametrize(('language', 'suffix', 'source'), _NON_PYTHON)
def test_code_profiles_refuse_a_named_non_python_language_without_an_explicit_metric(
    tmp_path: Path, language: str, suffix: str, source: str
) -> None:
    engine = _engine()
    root = _repo(tmp_path, {f'src/a.{suffix}': source}, policy=_policy('code', 300))
    with pytest.raises(engine.LayoutViolation, match=language) as refused:
        engine.check(root)
    assert f'src/a.{suffix}' in str(refused.value)


@pytest.mark.parametrize(('language', 'suffix', 'source'), _NON_PYTHON)
def test_explicit_raw_language_policy_does_not_feed_real_source_to_the_python_reader(
    tmp_path: Path, language: str, suffix: str, source: str
) -> None:
    engine = _engine()
    extra = f'[tool.dev_lab.layout.languages.{language}]\nmodule_unit = "raw"\nmodule_limit = 2\n'
    root = _repo(tmp_path, {'src/a.py': 'x = 1\n', f'src/a.{suffix}': source}, policy=_policy('code', 300, extra=extra))
    policy = engine.read_policy(root)
    assert policy.languages[language].module_unit == 'raw'
    assert policy.languages[language].module_limit == 2
    scan = engine.scan(root, policy)
    assert scan.module_lengths[f'src/a.{suffix}'] == 2
    engine.assert_layout(scan, policy)


def test_unknown_language_policy_and_unknown_source_language_are_named_refusals(tmp_path: Path) -> None:
    engine = _engine()
    extra = '[tool.dev_lab.layout.languages.unregistered]\nmodule_unit = "raw"\nmodule_limit = 2\n'
    root = _repo(tmp_path, {'src/a.py': 'x = 1\n'}, policy=_policy(extra=extra))
    with pytest.raises(engine.LayoutViolation, match='unregistered'):
        engine.read_policy(root)
    (root / 'pyproject.toml').write_text(_policy(), encoding='utf-8')
    unknown = root / 'src/a.unregistered'
    unknown.write_text('an unknown source language\n', encoding='utf-8')
    subprocess.run([_GIT, 'add', '--', str(unknown)], cwd=root, check=True, timeout=60)
    with pytest.raises(engine.LayoutViolation, match=r'src/a\.unregistered'):
        engine.check(root)


@pytest.mark.parametrize(
    'extra',
    [
        '[tool.dev_lab.layout.languages.javascript]\nmodule_unit = "raw"\n',
        '[tool.dev_lab.layout.languages.javascript]\nmodule_limit = 2\n',
        '[tool.dev_lab.layout.languages.javascript]\nmodule_unit = "code"\nmodule_limit = 2\n',
        '[tool.dev_lab.layout.languages.javascript]\nmodule_unit = "raw"\nmodule_limit = 2\nexempt = true\n',
    ],
)
def test_language_metrics_cannot_inherit_a_guessed_limit_or_add_an_escape(tmp_path: Path, extra: str) -> None:
    engine = _engine()
    root = _repo(tmp_path, {'src/a.py': 'x = 1\n'}, policy=_policy('code', 300, extra=extra))
    with pytest.raises(engine.LayoutViolation, match=r'javascript|module_|exempt'):
        engine.read_policy(root)


@pytest.mark.parametrize(('limit', 'accepted'), [(299, True), (300, True), (301, False), (999999, False)])
def test_a_positive_new_limit_does_not_bypass_the_previously_accepted_policy(
    tmp_path: Path, limit: int, *, accepted: bool
) -> None:
    engine = _engine()
    root = _repo(tmp_path, {'src/a.py': 'x = 1\n'}, policy=_policy('code', 300))
    baseline = engine.read_policy(root)
    (root / 'pyproject.toml').write_text(_policy('code', limit), encoding='utf-8')
    current = engine.read_policy(root)
    if accepted:
        engine.assert_not_relaxed(current, baseline)
    else:
        with pytest.raises(engine.LayoutViolation, match=r'limit|relax|300'):
            engine.assert_not_relaxed(current, baseline)


def test_a_unit_change_is_not_a_smaller_number_in_the_same_dimension(tmp_path: Path) -> None:
    engine = _engine()
    root = _repo(tmp_path, {'src/a.py': 'x = 1\n'}, policy=_policy('raw', 799))
    baseline = engine.read_policy(root)
    (root / 'pyproject.toml').write_text(_policy('code', 300), encoding='utf-8')
    with pytest.raises(engine.LayoutViolation, match='unit'):
        engine.assert_not_relaxed(engine.read_policy(root), baseline)


@pytest.mark.parametrize('limit', [11, 999999])
def test_a_language_override_is_not_an_unchecked_escape_from_the_default_bar(tmp_path: Path, limit: int) -> None:
    engine = _engine()
    extra = '[tool.dev_lab.layout.languages.javascript]\nmodule_unit = "raw"\nmodule_limit = 10\n'
    root = _repo(tmp_path, {'src/a.js': 'function f() {}\n'}, policy=_policy('code', 300, extra=extra))
    baseline = engine.read_policy(root)
    changed = extra.replace('module_limit = 10', f'module_limit = {limit}')
    (root / 'pyproject.toml').write_text(_policy('code', 300, extra=changed), encoding='utf-8')
    with pytest.raises(engine.LayoutViolation, match='javascript'):
        engine.assert_not_relaxed(engine.read_policy(root), baseline)


def test_removing_a_stricter_override_does_not_silently_restore_a_larger_default(tmp_path: Path) -> None:
    engine = _engine()
    extra = '[tool.dev_lab.layout.languages.javascript]\nmodule_unit = "raw"\nmodule_limit = 10\n'
    root = _repo(tmp_path, {'src/a.js': 'function f() {}\n'}, policy=_policy('raw', 300, extra=extra))
    baseline = engine.read_policy(root)
    (root / 'pyproject.toml').write_text(_policy('raw', 300), encoding='utf-8')
    with pytest.raises(engine.LayoutViolation, match='javascript'):
        engine.assert_not_relaxed(engine.read_policy(root), baseline)


def test_depth_five_is_recorded_as_watch_not_a_new_hard_limit(tmp_path: Path) -> None:
    engine = _engine()
    name = 'src/a/b/c/d/e/module.py'
    root = _repo(tmp_path, {name: 'x = 1\n'})
    policy = engine.read_policy(root)
    scan = engine.scan(root, policy)
    assert scan.depths[name] == 5
    engine.assert_layout(scan, policy)
