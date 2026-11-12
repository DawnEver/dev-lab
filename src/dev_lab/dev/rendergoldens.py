"""Every family file the generators render for a set of declaration fixtures, pinned byte for byte as goldens.

THE CONTRACT IT CLOSES: a generator change is shown not to change unrelated repos. A fixture is a directory holding a
``pyproject.toml`` (its ``[tool.dev_lab.ci]`` declarations) and a ``deltas.py`` (its ``DELTAS``); its render is
every RENDERED famconfig base it declares a delta for, every whole family file (:func:`famfiles.render_agent_files`'s
set) and every workflow :mod:`dev_lab.dev.ciworkflows` places. :func:`compare` names each render that moved against
the goldens, so a generator change shows exactly which renders it moves; ``update`` rewrites them, and that rewrite is
the explicit edit a reviewer reads.

``python -m dev_lab.dev.rendergoldens check|update --fixtures <dir> --goldens <dir>``
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev import ciworkflows, famfiles
from dev_lab.dev.famconfig import RENDERED, artefact_base, render

if TYPE_CHECKING:
    from collections.abc import Mapping

    from dev_lab.dev.famconfig import Delta

__all__ = [
    'DELTAS_FILE',
    'MANIFEST',
    'SEP',
    'SUFFIX',
    'compare',
    'main',
    'read_goldens',
    'render_fixture',
    'render_fixtures',
    'write',
]

#: The declaration file of a fixture: its ``[tool.dev_lab.ci]`` tables.
MANIFEST: Final = 'pyproject.toml'
#: The module file of a fixture holding its ``DELTAS``.
DELTAS_FILE: Final = 'deltas.py'
#: The suffix of a golden file: a rendered ``.gitignore`` stored bare would be read by git as an ignore rule.
SUFFIX: Final = '.golden'
#: What a golden's file name spells a repo-relative ``/`` as. Goldens are FLAT under their fixture: a nested
#: ``.claude/rem.json`` golden sat under the family's ``**/.claude/**`` ignore, was never committed, and every
#: other checkout read it as missing.
SEP: Final = '--'


def _file(key: str) -> str:
    fixture, rel = key.split('/', 1)
    return f'{fixture}/{rel.replace("/", SEP)}{SUFFIX}'


def _key(path: Path, goldens: Path) -> str:
    fixture, name = path.relative_to(goldens).as_posix().split('/', 1)
    return f'{fixture}/{name.removesuffix(SUFFIX).replace(SEP, "/")}'


def render_fixture(text: str, deltas: Mapping[str, Delta], origin: str) -> dict[str, str]:
    """Every family file one repo declaring pyproject *text* and *deltas* renders, by repo-relative path."""
    out = {
        artefact: render(artefact_base(artefact), delta)
        for artefact, delta in deltas.items()
        if artefact_base(artefact).mode == RENDERED
    }
    out.update(famfiles.whole_files())
    forge = ciworkflows.declared_forge(text, origin)
    for name, (directory, workflow) in ciworkflows.placed(text, origin, forge).items():
        out[(directory / name).as_posix()] = ciworkflows.render(workflow)
    return dict(sorted(out.items()))


def render_fixtures(fixtures: Path) -> dict[str, str]:
    """Every fixture directory under *fixtures* rendered, keyed ``<fixture>/<repo-relative path>``."""
    out: dict[str, str] = {}
    for fixture in sorted(path for path in fixtures.iterdir() if (path / MANIFEST).is_file()):
        manifest = fixture / MANIFEST
        deltas = famfiles.load_deltas(fixture / DELTAS_FILE)
        rendered = render_fixture(manifest.read_text(encoding='utf-8'), deltas, str(manifest))
        out.update({f'{fixture.name}/{rel}': text for rel, text in rendered.items()})
    return out


def read_goldens(goldens: Path) -> dict[str, str]:
    """Every golden under *goldens*, keyed by its path relative to it less :data:`SUFFIX`."""
    return {_key(path, goldens): path.read_bytes().decode('utf-8') for path in sorted(goldens.rglob(f'*{SUFFIX}'))}


def compare(rendered: Mapping[str, str], goldens: Mapping[str, str]) -> list[str]:
    """One line per render that moved: changed, new (no golden) or gone (a golden nothing renders)."""
    out = [f'{key}: changed' for key in sorted(rendered.keys() & goldens.keys()) if rendered[key] != goldens[key]]
    out += [f'{key}: new, no golden' for key in sorted(rendered.keys() - goldens.keys())]
    out += [f'{key}: gone, its golden is stale' for key in sorted(goldens.keys() - rendered.keys())]
    return out


def write(rendered: Mapping[str, str], goldens: Path) -> list[str]:
    """Rewrite *goldens* to exactly *rendered*; returns the moved lines :func:`compare` read before the write."""
    moved = compare(rendered, read_goldens(goldens) if goldens.is_dir() else {})
    for key in read_goldens(goldens) if goldens.is_dir() else {}:
        if key not in rendered:
            (goldens / _file(key)).unlink()
    for key, text in rendered.items():
        path = goldens / _file(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode('utf-8'))
    return moved


def main(argv: list[str] | None = None) -> int:
    """``check`` exits 1 naming each moved render; ``update`` rewrites the goldens and names what moved."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.rendergoldens', description=__doc__.splitlines()[0])
    parser.add_argument('verb', choices=('check', 'update'))
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--goldens', type=Path, required=True)
    args = parser.parse_args(argv)
    rendered = render_fixtures(args.fixtures)
    if args.verb == 'update':
        for line in write(rendered, args.goldens):
            emit(f'[rendergoldens] {line}')
        return 0
    moved = compare(rendered, read_goldens(args.goldens))
    for line in moved:
        emit(f'[rendergoldens] {line}')
    return 1 if moved else 0


if __name__ == '__main__':
    raise SystemExit(main())
