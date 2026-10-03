"""The bodies a consumer calls to judge ITSELF -- planted here, run on the kit, never reaching a sibling."""

from __future__ import annotations

from pathlib import Path

import pytest
from _famconfig_pyproject_section_delta import PYPROJECT_SECTION_DELTAS
from _famconfig_section_delta import SECTION_DELTAS

from lab_commons.dev.devdocs import CANONICAL_TREE, pointer_table
from lab_commons.dev.famtests.configrender import assert_every_section_is_owned
from lab_commons.dev.famtests.devdocs import assert_the_index_holds_the_live_table

ROOT = Path(__file__).resolve().parents[1]


def _index(root: Path, text: str) -> None:
    path = root.joinpath(*CANONICAL_TREE.split('/'), 'index.md')
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding='utf-8')


def test_a_live_table_passes_and_a_stale_or_missing_one_reds(tmp_path: Path) -> None:
    """PLANTED: one live copy greens; a table missing its last row, or no index, reds."""
    live = pointer_table('../lab-commons/docs-src/dev')
    _index(tmp_path / 'ok', f'# Dev\n\n{live}\n')
    assert_the_index_holds_the_live_table(root=tmp_path / 'ok', base='../lab-commons/docs-src/dev')
    stale = '\n'.join(live.splitlines()[:-1])
    _index(tmp_path / 'stale', f'# Dev\n\n{stale}\n')
    with pytest.raises(AssertionError, match='Re-render'):
        assert_the_index_holds_the_live_table(root=tmp_path / 'stale', base='../lab-commons/docs-src/dev')
    with pytest.raises(AssertionError, match='no dev index'):
        assert_the_index_holds_the_live_table(root=tmp_path / 'none', base='.')


def test_the_kit_owns_every_family_table_and_an_undeclared_one_reds() -> None:
    """The kit's own tables through the consumer body, then a declaration with a base missing."""
    deltas = {**SECTION_DELTAS['lab-commons'], **PYPROJECT_SECTION_DELTAS['lab-commons']}
    assert_every_section_is_owned(root=ROOT, deltas=deltas, repo='lab-commons')
    short = dict(list(deltas.items())[1:])
    with pytest.raises(AssertionError, match='no SectionDelta declared'):
        assert_every_section_is_owned(root=ROOT, deltas=short, repo='lab-commons')
