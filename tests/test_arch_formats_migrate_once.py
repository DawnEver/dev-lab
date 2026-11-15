"""FORMATS-MIGRATE-ONCE: a stored format change migrates its stored records ONCE and deletes the old reader.

THE RULING, 2026-11-11 (consumer-a task D51/D52, no-backward-compatibility): a reader that
upgrades every older schema on read is a dual path kept forever -- each schema change adds a step nobody
deletes, and the old shape stays a supported input. A format change instead ships a one-time migration of
the records that exist, the old reader is deleted in the same change, and a record still at an older
schema is REFUSED by name with the instruction that migrates it (or discards it, for a store that drains).

WHAT IS CHECKED, STATICALLY, AS DATA. A module declaring a format version -- a module-level ``SCHEMA`` or
``SCHEMA_VERSION`` (or ``<X>_SCHEMA_VERSION``) bound to an int literal -- may not bind ``_UPGRADES``, the
per-schema step table that was the old reader's shape. That the refusal names its remedy is each format's
own test. An old-shape reader no table reveals (a retired key, a retired text) carries the marker
:data:`MARKER` in a comment, and every marked module is OWED a migration in :data:`_OWED` -- on record by
name, never silent; the ratchet's other side reds a row whose module no longer carries the marker.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
SRC: Final = ROOT / 'src' / 'dev_lab'

#: A schema constant's name.
_VERSION_NAMES: Final = ('SCHEMA', 'SCHEMA_VERSION')

#: The upgrade-step table's name: the dual path this rule forbids.
_TABLE: Final = '_UPGRADES'

#: The comment token that marks an old-shape reader awaiting its one-time migration.
MARKER: Final = 'OLD-SHAPE-READER'

#: Each marked module -> why its migration is still owed. Delete a row in the change that migrates and
#: deletes the reader; never add one to dodge the table check (a table is red whatever this says).
_OWED: Final[dict[str, str]] = {
    'dev_lab/ops/configupgrade.py': 'live [ops] files on the ops hosts: needs a `config migrate` run on each host',
    'dev_lab/ops/wave.py': 'wave files under each ops host state dir written before `summarized`',
    'dev_lab/dev/forgestatus.py': 'forge statuses posted under the retired carry wording, readable on old shas',
}

#: The versioned formats this tree holds today: forgerunstate and supervise.state. A floor, not a count
#: pin: finding fewer means the scan stopped reading them, which is not a clean tree.
_FLOOR: Final = 2


def _is_version_name(name: str) -> bool:
    return name in _VERSION_NAMES or name.endswith('_SCHEMA_VERSION')


def _bound(node: ast.stmt) -> tuple[str, ast.expr] | None:
    """``(name, value)`` of a module-level single-name binding, annotated or not."""
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id, node.value
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
        return node.target.id, node.value
    return None


def violations(source: str) -> tuple[int | None, list[str]]:
    """``(declared schema or None, why it keeps an old-schema reader)`` for one module's *source*."""
    bindings = dict(filter(None, (_bound(node) for node in ast.parse(source).body)))
    versions = [
        value.value
        for name, value in bindings.items()
        if _is_version_name(name) and isinstance(value, ast.Constant) and type(value.value) is int
    ]
    if not versions:
        return None, []
    if _TABLE in bindings:
        return versions[0], [f'binds {_TABLE}: an old schema is migrated once and refused after, never read']
    return versions[0], []


def _scan() -> dict[str, tuple[int, list[str]]]:
    found = {}
    for path in sorted(SRC.rglob('*.py')):
        schema, problems = violations(path.read_text(encoding='utf-8'))
        if schema is not None:
            found[path.relative_to(SRC.parent).as_posix()] = (schema, problems)
    return found


def test_no_versioned_format_this_kit_writes_keeps_an_old_schema_reader() -> None:
    found = _scan()
    assert len(found) >= _FLOOR, f'the scan found {sorted(found)}: fewer than {_FLOOR} versioned formats is unread'
    red = {path: problems for path, (_, problems) in found.items() if problems}
    assert not red, f'FORMATS-MIGRATE-ONCE: {red}'


def _marked() -> set[str]:
    return {
        path.relative_to(SRC.parent).as_posix()
        for path in SRC.rglob('*.py')
        if MARKER in path.read_text(encoding='utf-8')
    }


def test_every_old_shape_reader_is_owed_a_migration_by_name() -> None:
    marked = _marked()
    assert not marked - set(_OWED), f'{sorted(marked - set(_OWED))} read an old shape and owe nothing on record'
    assert not set(_OWED) - marked, f'{sorted(set(_OWED) - marked)} no longer read an old shape: delete their rows'


def test_planted_formats_are_judged() -> None:
    """PLANTED CONTROL: an upgrade table is red; the same module without it is green."""
    good = """
        SCHEMA = 3
        def read(raw):
            if raw['schema'] != SCHEMA:
                raise ValueError('run the migration')
            return raw
    """
    assert violations(textwrap.dedent(good)) == (3, [])
    assert violations('VERSION_OF_NOTHING = 2\n_UPGRADES = {}\n') == (None, []), 'an unversioned module is no format'
    bad = textwrap.dedent(good) + "def _from_2(raw): return {**raw, 'schema': 3}\n_UPGRADES = {2: _from_2}\n"
    schema, problems = violations(bad)
    assert schema == 3
    assert any('binds _UPGRADES' in problem for problem in problems), problems
