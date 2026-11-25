"""Declared seeds are copied into a worktree where absent, reported where the main lacks them, never overwritten."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dev_lab.dev.worktreeseeds import declared_seeds, seed

if TYPE_CHECKING:
    from pathlib import Path

_DECL = '[tool.dev_lab.worktree]\nseeds = ["rust/Cargo.lock", "gone.lock", "kept.lock"]\n'


def test_seeds_copy_where_absent_report_where_missing_and_never_overwrite(tmp_path: Path) -> None:
    main, tree = tmp_path / 'main', tmp_path / 'tree'
    for root in (main, tree):
        root.mkdir()
        (root / 'pyproject.toml').write_text(_DECL, encoding='utf-8')
    (main / 'rust').mkdir()
    (main / 'rust/Cargo.lock').write_text('locked', encoding='utf-8')
    (main / 'kept.lock').write_text('main', encoding='utf-8')
    (tree / 'kept.lock').write_text('own', encoding='utf-8')
    lines = seed(tree, main=main)
    assert (tree / 'rust/Cargo.lock').read_text(encoding='utf-8') == 'locked'
    assert (tree / 'kept.lock').read_text(encoding='utf-8') == 'own'
    assert not (tree / 'gone.lock').exists()
    assert [line.split(':')[0] for line in lines] == ['seed rust/Cargo.lock', 'seed gone.lock']
    # planted control: the main checkout itself is never seeded from itself
    assert seed(main, main=main) == []


@pytest.mark.parametrize('bad', ['../x', '/etc/x', 'C:/x'])
def test_a_seed_outside_the_checkout_is_refused_by_name(tmp_path: Path, bad: str) -> None:
    (tmp_path / 'pyproject.toml').write_text(f'[tool.dev_lab.worktree]\nseeds = ["{bad}"]\n', encoding='utf-8')
    with pytest.raises(ValueError, match='not a repo-relative path'):
        declared_seeds(tmp_path)
