"""dev-lab reads a need-set through ONE door, :func:`dev_lab.dev.partrows.needs_of_row`.

INCIDENT 2026-11-05 (PR #215): ``lab_commons.hpc.needsets.needs_of`` takes a bare PART and raises "not a part
name" on an OS row (``base@windows``). Each caller had wrapped its own argument in ``row_part(...)``, and the
callers that forgot (forgetake, forgeslurm) raised on the first OS row. Every dev-lab caller holds a row or a
part, so a direct ``needs_of`` reference anywhere in ``src/dev_lab`` but the door is refused.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from _arch_corpus import assert_floor, parse, rel, source_modules

#: The door: the one dev-lab module that may name lab-commons' ``needs_of``.
DOOR = 'src/dev_lab/dev/partrows.py'
#: dev-lab's source-module floor; MEASURED 2026-11-05 well above it.
SOURCE_FLOOR = 100


def raw_reads(tree: ast.Module) -> list[str]:
    """Each direct reach for ``needs_of`` in *tree*: imported by name, or called/handed on as an attribute."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == 'lab_commons.hpc.needsets':
            found.extend(f'{node.lineno}:import' for a in node.names if a.name == 'needs_of')
        if isinstance(node, ast.Attribute) and node.attr == 'needs_of':
            found.append(f'{node.lineno}:attribute')
    return found


def test_every_dev_lab_need_set_is_read_through_the_row_door() -> None:
    modules = [path for path in source_modules() if rel(path).startswith('src/dev_lab/')]
    assert_floor(len(modules), SOURCE_FLOOR, 'dev-lab source')
    found = [f'{rel(path)}:{hit}' for path in modules if rel(path) != DOOR for hit in raw_reads(parse(path))]
    assert found == [], f'read a row or part need-set through partrows.needs_of_row: {found}'


@pytest.mark.parametrize(
    ('body', 'flagged'),
    [
        ('from lab_commons.hpc.needsets import needs_of\n', True),
        ('from lab_commons.hpc.needsets import BASE, needs_of\n', True),
        ("needsets.needs_of('base@windows')\n", True),
        ('from lab_commons.hpc.needsets import BASE\n', False),
        ("from dev_lab.dev.partrows import needs_of_row\nneeds_of_row('base@windows')\n", False),
    ],
)
def test_a_planted_direct_need_set_read_is_refused(tmp_path: Path, body: str, *, flagged: bool) -> None:
    """THE PLANTED CONTROL: the real scan flags each direct shape and passes the door."""
    planted = tmp_path / 'planted.py'
    planted.write_text(body, encoding='utf-8')
    assert bool(raw_reads(parse(planted))) is flagged
