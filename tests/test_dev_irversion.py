"""The IR version class (docs-src/dev/ir-schema.md, "Versioning"), computed against the last commit."""

from __future__ import annotations

import shutil
from pathlib import Path

import lab_commons.launch as _door
import pytest

from dev_lab.dev.ircheck import load
from dev_lab.dev.irversion import Level, at_revision, bump_refusal, classify, declared_level

SPARE = '[quantity.spare]\nunit = "m"\ndimension = "0 1 0 0 0 0 0"\n'
GIT = shutil.which('git') or 'git'
FIXTURE = Path(__file__).parent / 'data' / 'ir_schema' / 'repo'


def _git(root: Path, *args: str) -> None:
    _door.run([GIT, '-C', str(root), *args], check=True, capture_output=True, text=True, encoding='utf-8', timeout=60)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = Path(shutil.copytree(FIXTURE, tmp_path / 'repo'))
    _git(root, 'init', '-q')
    _git(root, 'add', '.')
    _git(root, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'base')
    return root


def _edit(root: Path, relative: str, old: str, new: str) -> None:
    path = root / relative
    text = path.read_text(encoding='utf-8')
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


def _bump(root: Path, version: str) -> None:
    _edit(root, 'pyproject.toml', 'version = "1.0.0"', f'version = "{version}"')


def _change(root: Path) -> tuple[Level, frozenset[str], str | None]:
    old, new = at_revision(root, 'HEAD'), load(root)
    change = classify(old, new)
    return change.level, change.records, bump_refusal(old, new)


def test_an_untouched_ir_is_no_change(repo: Path) -> None:
    assert _change(repo) == (Level.NONE, frozenset(), None)


def test_a_doc_edit_is_a_patch_and_needs_a_patch_bump(repo: Path) -> None:
    _edit(repo, 'ir/widgets.toml', 'doc = "One manufactured widget."', 'doc = "One widget, as made."')
    level, _, refused = _change(repo)
    assert level == Level.PATCH
    assert refused is not None
    assert refused.startswith('IR-VERSION-NOT-BUMPED')
    assert ' -- ' in refused
    _bump(repo, '1.0.1')
    assert _change(repo)[2] is None


def test_an_optional_field_is_minor_and_reaches_every_container(repo: Path) -> None:
    _edit(
        repo,
        'ir/widgets.toml',
        '[record.Widget.field.finish]',
        '[record.Widget.field.note]\ntype = "str"\noptional = true\n[record.Widget.field.finish]',
    )
    level, records, _ = _change(repo)
    assert level == Level.MINOR
    assert records == {'widgets.Widget', 'samples.Sample', 'samples.Batch'}
    _bump(repo, '1.0.1')
    assert 'the change is MINOR' in _change(repo)[2]
    _edit(repo, 'pyproject.toml', 'version = "1.0.1"', 'version = "1.1.0"')
    assert _change(repo)[2] is None


@pytest.mark.parametrize(
    ('relative', 'old', 'new'),
    [
        ('ir/samples.toml', '[record.Sample.field.label]\ntype = "str"\n', ''),
        ('ir/samples.toml', 'shape = ["n", 3]', 'shape = ["n", 2]'),
        ('ir/widgets.toml', 'quantity = "mass"', 'quantity = "length"'),
        (
            'ir/widgets.toml',
            'type = "float"\nquantity = "temperature"\noptional = true',
            'type = "float"\nquantity = "temperature"',
        ),
        ('ir/widgets.toml', '"painted", ', ''),
        ('ir/quantities.toml', '[port_domain.electrical]', SPARE + '[port_domain.electrical]'),
    ],
    ids=[
        'field-removed',
        'shape-changed',
        'quantity-changed',
        'optional-made-required',
        'enum-value-removed',
        'quantity-added',
    ],
)
def test_each_change_gets_its_class(repo: Path, relative: str, old: str, new: str) -> None:
    _edit(repo, relative, old, new)
    level, _, refused = _change(repo)
    assert level == (Level.MINOR if 'spare' in new else Level.MAJOR)
    _bump(repo, '1.1.0')
    assert (_change(repo)[2] is None) == (level == Level.MINOR)
    _edit(repo, 'pyproject.toml', 'version = "1.1.0"', 'version = "2.0.0"')
    assert _change(repo)[2] is None
    assert refused is not None


def test_a_new_enum_value_is_minor_and_touches_its_users(repo: Path) -> None:
    _edit(repo, 'ir/widgets.toml', '"anodized"]', '"anodized", "polished"]')
    level, records, _ = _change(repo)
    assert level == Level.MINOR
    assert 'widgets.Widget' in records


def test_a_version_that_goes_backwards_is_refused(repo: Path) -> None:
    _edit(repo, 'ir/widgets.toml', 'doc = "One manufactured widget."', 'doc = "x"')
    _bump(repo, '0.9.0')
    assert 'a decrease' in _change(repo)[2]


def test_declared_level_reads_the_highest_moved_part() -> None:
    assert declared_level((1, 2, 3), (1, 2, 3)) == Level.NONE
    assert declared_level((1, 2, 3), (1, 2, 4)) == Level.PATCH
    assert declared_level((1, 2, 3), (1, 3, 0)) == Level.MINOR
    assert declared_level((1, 2, 3), (2, 0, 0)) == Level.MAJOR
    assert declared_level((1, 2, 3), (1, 2, 2)) is None
