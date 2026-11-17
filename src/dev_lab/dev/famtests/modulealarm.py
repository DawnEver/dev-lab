"""Tracked layout readings and the shared hard directory band.

Depth is a watch reading, not a refusal. A successful reading accounts for every tracked
identity; unreadable or unknown inputs cannot become a smaller, greener population.
"""

from __future__ import annotations

import tokenize
import tomllib
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from dev_lab.dev.family import declared_table
from dev_lab.dev.famtests.density import code_only
from dev_lab.dev.rules import tracked_files

__all__ = [
    'DEPTH_WATCH',
    'DIRECTORY_LIMIT',
    'LayoutPolicy',
    'LayoutScan',
    'LayoutViolation',
    'ModuleMetric',
    'assert_layout',
    'assert_not_relaxed',
    'check',
    'read_policy',
    'scan',
]

DIRECTORY_LIMIT = 25
DEPTH_WATCH = 5
_LANGUAGES = {
    '.py': 'python',
    '.pyi': 'python',
    '.js': 'javascript',
    '.mjs': 'javascript',
    '.cjs': 'javascript',
    '.rs': 'rust',
    '.sh': 'shell',
    '.ps1': 'powershell',
}
_DATA = frozenset(
    {
        '.toml',
        '.md',
        '.rst',
        '.txt',
        '.json',
        '.jsonl',
        '.yaml',
        '.yml',
        '.csv',
        '.tsv',
        '.svg',
        '.png',
        '.jpg',
        '.jpeg',
        '.ico',
        '.lock',
    }
)


class LayoutViolation(AssertionError):
    """The declared policy or its complete reading cannot establish layout conformance."""


@dataclass(frozen=True)
class ModuleMetric:
    """An inclusive maximum, in one explicitly declared line unit."""

    module_unit: str
    module_limit: int


@dataclass(frozen=True)
class LayoutPolicy(ModuleMetric):
    """Default metric plus explicit closed-language metrics, never path exemptions."""

    languages: Mapping[str, ModuleMetric]


@dataclass(frozen=True)
class LayoutScan:
    """Complete identity evidence and measured quantities, without a policy verdict."""

    expected: frozenset[str]
    read: frozenset[str]
    unread: frozenset[str]
    module_lengths: Mapping[str, int]
    folder_counts: Mapping[str, int]
    depths: Mapping[str, int]


def _refuse(message: str) -> None:
    raise LayoutViolation(message)


def _metric(row: object, subject: str, *, languages: bool = False) -> ModuleMetric:
    keys = {'module_unit', 'module_limit'}
    if not isinstance(row, dict) or set(row) - (keys | ({'languages'} if languages else set())):
        _refuse(f'layout policy {subject}: unknown fields or non-table')
    if not keys <= row.keys():
        _refuse(f'layout policy {subject}: module_unit and module_limit are required')
    unit, limit = row['module_unit'], row['module_limit']
    if unit not in ('raw', 'code'):
        _refuse(f'layout policy {subject}: module_unit must be raw or code')
    if type(limit) is not int or limit <= 0:
        _refuse(f'layout policy {subject}: module_limit must be a positive integer')
    if subject not in {'default', 'python'} and unit == 'code':
        _refuse(f'layout policy {subject}: code measurement is supported only for python')
    return ModuleMetric(unit, limit)


def read_policy(root: Path) -> LayoutPolicy:
    """Read the sole typed layout declaration; missing, malformed and unknown fields refuse."""
    try:
        data = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
        row = declared_table(data, 'layout')
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        message = f'layout policy cannot be read: {type(exc).__name__}'
        raise LayoutViolation(message) from exc
    metric = _metric(row, 'default', languages=True)
    rows = row.get('languages', {})
    if not isinstance(rows, dict):
        _refuse('layout policy languages must be a table')
    metrics = {}
    for language, value in rows.items():
        if language not in _LANGUAGES.values():
            _refuse(f'layout policy unknown language {language}')
        metrics[language] = _metric(value, language)
    return LayoutPolicy(metric.module_unit, metric.module_limit, MappingProxyType(metrics))


def _for_language(policy: LayoutPolicy, language: str) -> ModuleMetric:
    metric = policy.languages.get(language, policy)
    if language != 'python' and metric.module_unit == 'code':
        _refuse(f'{language}: an explicit supported raw language metric is required')
    return metric


def scan(root: Path, policy: LayoutPolicy) -> LayoutScan:
    """Read the tracked corpus once; no missing or unsupported member is silently dropped."""
    try:
        expected = tracked_files(root)
    except (OSError, RuntimeError, AssertionError) as exc:
        message = 'layout tracked population cannot be established'
        raise LayoutViolation(message) from exc
    lengths, folders, depths = {}, Counter(), {}
    read = set()
    for name in sorted(expected):
        relative = Path(name)
        path = root / relative
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                _refuse(f'{name}: layout requires an owned ordinary tracked file')
            raw = path.read_bytes()
            language = _LANGUAGES.get(relative.suffix.lower())
            if language is not None:
                metric = _for_language(policy, language)
                text = raw.decode('utf-8')
                lengths[name] = len(code_only(text) if metric.module_unit == 'code' else text.splitlines())
            elif relative.suffix and relative.suffix.lower() not in _DATA:
                _refuse(f'{name}: unsupported source language {relative.suffix}')
        except (OSError, UnicodeError, SyntaxError, tokenize.TokenError, LayoutViolation) as exc:
            message = f'{name}: layout reading refused: {exc}'
            raise LayoutViolation(message) from exc
        read.add(name)
        folders[relative.parent.as_posix()] += 1
        depths[name] = max(0, len(relative.parts) - 2)
    return LayoutScan(
        expected,
        frozenset(read),
        expected - read,
        MappingProxyType(lengths),
        MappingProxyType(dict(folders)),
        MappingProxyType(depths),
    )


def assert_layout(reading: LayoutScan, policy: LayoutPolicy) -> None:
    """Require complete identities, inclusive module limits and the global direct width band."""
    if reading.read != reading.expected or reading.unread:
        _refuse(f'layout corpus mismatch: {sorted((reading.expected ^ reading.read) | reading.unread)}')
    errors = []
    for name, length in reading.module_lengths.items():
        metric = _for_language(policy, _LANGUAGES[Path(name).suffix.lower()])
        if length > metric.module_limit:
            errors.append(f'{name}: {length} {metric.module_unit} lines > {metric.module_limit}')
    errors.extend(
        f'{folder}: {count} direct files > {DIRECTORY_LIMIT}'
        for folder, count in reading.folder_counts.items()
        if count > DIRECTORY_LIMIT
    )
    if errors:
        _refuse('\n'.join(errors))


def assert_not_relaxed(current: LayoutPolicy, baseline: LayoutPolicy) -> None:
    """Compare same-dimensional bars; a changed unit is not evidence of a tighter policy."""
    for language in {'default', *current.languages, *baseline.languages}:
        old = baseline.languages.get(language, baseline)
        new = current.languages.get(language, current)
        if new.module_unit != old.module_unit:
            _refuse(f'{language}: module unit changed; an equivalent migration must be proved')
        if new.module_limit > old.module_limit:
            _refuse(f'{language}: module limit relaxed from {old.module_limit} to {new.module_limit}')


def check(root: Path) -> None:
    """Read the declaration and require its complete tracked layout to conform."""
    policy = read_policy(root)
    assert_layout(scan(root, policy), policy)
