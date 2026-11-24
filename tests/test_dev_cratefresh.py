"""Crate freshness: caret semantics, the lower of two declared specs, and three distinct exit answers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dev_lab.dev.cratefresh import allows, declared_crates, latest_stable, main

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ('spec', 'version', 'ok'),
    [
        ('0.29', '0.29.5', True),
        ('0.29', '0.30.0', False),
        ('1.1', '1.9.0', True),
        ('1.1', '2.0.0', False),
        ('^0', '0.99.0', True),
        ('1.2', '1.1.0', False),
    ],
)
def test_caret_semantics_make_the_0x_minor_the_breaking_slot(spec: str, version: str, *, ok: bool) -> None:
    assert allows(spec, version) is ok


def _workspace(root: Path) -> None:
    (root / 'a').mkdir()
    (root / 'target' / 'x').mkdir(parents=True)
    (root / 'Cargo.toml').write_text(
        '[workspace.dependencies]\npyo3 = "0.30"\nlocal = { path = "a" }\n', encoding='utf-8'
    )
    (root / 'a' / 'Cargo.toml').write_text('[dependencies]\npyo3 = { version = "0.29" }\n', encoding='utf-8')
    (root / 'target' / 'x' / 'Cargo.toml').write_text('[dependencies]\nignored = "1"\n', encoding='utf-8')


def test_the_lower_declared_spec_is_reported_and_build_output_is_not_read(tmp_path: Path) -> None:
    _workspace(tmp_path)
    assert declared_crates(tmp_path) == {'pyo3': '0.29'}


def test_the_three_exit_answers_are_distinct(tmp_path: Path) -> None:
    _workspace(tmp_path)
    assert main(['--root', str(tmp_path)], fetch=lambda _crate: '0.29.9') == 0
    assert main(['--root', str(tmp_path)], fetch=lambda _crate: '0.30.0') == 1

    def unreachable(crate: str) -> str:
        raise OSError(crate)

    assert main(['--root', str(tmp_path)], fetch=unreachable) == 2


def test_a_search_line_naming_another_crate_is_refused() -> None:
    assert latest_stable('pyo3', search=lambda _c: 'pyo3 = "0.30.1"    # bindings') == '0.30.1'
    with pytest.raises(ValueError, match='did not name'):
        latest_stable('pyo3', search=lambda _c: 'pyo3-ffi = "0.30.1"')
