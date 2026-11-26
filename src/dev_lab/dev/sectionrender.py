"""Render a family SECTION base into a TOML file: the owned keys written, every other key and table left alone.

The section bases (:mod:`dev_lab.dev._famconfig_sections`) COMPARE; this is the one writer beside them, so adopting
a base is a command rather than hand-copied keys: ``python -m dev_lab.dev.sectionrender <file> '<section>'``
writes the base's scalars and sets (plus a ``SectionDelta``'s additions less its drops, when a caller passes one)
into the table at its full dotted path, creating it when absent. Comments and the rest of the file survive
(tomlkit). After a render the section inspects OWNED -- the property the tests pin.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import tomlkit

from dev_lab.dev.famconfig import SectionBase, SectionDelta, expected_entries, section_base

if TYPE_CHECKING:
    from tomlkit.items import Table

__all__ = ['main', 'render_section']


def _table(document: Any, path: tuple[str, ...]) -> Table:  # noqa: ANN401 -- tomlkit containers are untyped here
    node = document
    for depth, step in enumerate(path):
        if step not in node:
            node[step] = tomlkit.table(is_super_table=depth < len(path) - 1)
        node = node[step]
    return node


def render_section(path: Path, base: SectionBase, delta: SectionDelta | None = None) -> None:
    """Write *base* (and *delta*) into the TOML file at *path*; a missing file is created."""
    delta = delta or SectionDelta(repo=path.parent.name, added={}, dropped={}, ceiling=0)
    document = tomlkit.parse(path.read_text(encoding='utf-8')) if path.is_file() else tomlkit.document()
    table = _table(document, base.table)
    for key, value in base.scalars.items():
        if (key, None) not in delta.dropped:
            table[key] = value
    for key in base.sets:
        table[key] = sorted(expected_entries(base, delta, key))
    path.write_text(tomlkit.dumps(document), encoding='utf-8', newline='')


def main(argv: list[str] | None = None) -> int:
    """Render one named section base into one file."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.sectionrender', description=__doc__.splitlines()[0])
    parser.add_argument('file', type=Path, help='the TOML file (pyproject.toml, a workspace Cargo.toml)')
    parser.add_argument('section', help="the section, as the registry spells it (e.g. '[tool.pyright]')")
    parsed = parser.parse_args(argv)
    render_section(parsed.file, section_base(parsed.section))
    sys.stdout.write(f'rendered {parsed.section} into {parsed.file}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
