"""FORMATS-UPGRADE-ON-READ: a persisted format this kit writes READS every older schema by upgrading it.

THE INCIDENT, 2026-10-17 (Ada): a redeploy moved the forge run journal from schema 1 to 2 under 17 live
schema-1 runs. The reader refused any schema but its own, so every serve tick of four accounts stopped on
the first file -- the refusal was "safe" and stalled the cluster. A tool is redeployed under its own
data as a matter of course (dependencies float, user ruling 2026-10-17), so refusing an older file is
refusing the ordinary case. Refusal is for a schema the reader does not KNOW: newer, or unheard of.

WHAT IS CHECKED, STATICALLY, AS DATA. A module declaring a format version -- a module-level ``SCHEMA`` or
``SCHEMA_VERSION`` (or ``<X>_SCHEMA_VERSION``) bound to an int literal ``N`` -- must also declare
``_UPGRADES``: a dict literal whose keys are EXACTLY ``1 .. N-1``, each value a function defined in that
module (the step that takes that schema one on), and the module must READ ``_UPGRADES`` somewhere other
than its binding, so the table is consulted rather than decorative. What cannot be checked statically --
that the reader upgrades BEFORE it refuses -- is each format's own test.
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

#: The upgrade table's name -- the convention every versioned format here follows.
_TABLE: Final = '_UPGRADES'

#: The versioned formats this tree holds today. A floor, not a count pin: finding fewer means the scan
#: stopped reading them, which is not a clean tree.
_FLOOR: Final = 1  # dev-lab at the 2026-10-22 split: forgerunstate; the box/compute formats stayed in lab-commons

#: A format whose upgrade path is OWED by a named lane -- on record, never skipped. A row whose module
#: complies is a red too (the ratchet's other side): delete it in the merge that brings the upgrade.
_OWED: Final[dict[str, str]] = {}


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
    """``(declared schema or None, why it does not upgrade on read)`` for one module's *source*."""
    tree = ast.parse(source)
    bindings = dict(filter(None, (_bound(node) for node in tree.body)))
    versions = [
        value.value
        for name, value in bindings.items()
        if _is_version_name(name) and isinstance(value, ast.Constant) and type(value.value) is int
    ]
    if not versions:
        return None, []
    schema = versions[0]
    table = bindings.get(_TABLE)
    if not isinstance(table, ast.Dict):
        return schema, [f'schema {schema} declares no {_TABLE} dict literal (older schema -> its upgrade step)']
    problems = []
    keys = {key.value for key in table.keys if isinstance(key, ast.Constant) and type(key.value) is int}
    if len(keys) != len(table.keys):
        problems.append(f'{_TABLE} keys must be int literals')
    if missing := sorted(set(range(1, schema)) - keys):
        problems.append(f'no upgrade from schema {missing} to {schema}')
    if extra := sorted(keys - set(range(1, schema))):
        problems.append(f'{_TABLE} names schema {extra}, not older than {schema}')
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    if strays := [ast.unparse(v) for v in table.values if not (isinstance(v, ast.Name) and v.id in functions)]:
        problems.append(f'{_TABLE} steps {strays} are not functions of this module')
    reads = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == _TABLE and isinstance(n.ctx, ast.Load)]
    if not reads:
        problems.append(f'{_TABLE} is declared and never read: the reader cannot be upgrading through it')
    return schema, problems


def _scan() -> dict[str, tuple[int, list[str]]]:
    found = {}
    for path in sorted(SRC.rglob('*.py')):
        schema, problems = violations(path.read_text(encoding='utf-8'))
        if schema is not None:
            found[path.relative_to(SRC.parent).as_posix()] = (schema, problems)
    return found


def test_every_versioned_format_this_kit_writes_upgrades_every_older_schema_on_read() -> None:
    found = _scan()
    assert len(found) >= _FLOOR, f'the scan found {sorted(found)}: fewer than {_FLOOR} versioned formats is unread'
    red = {path: problems for path, (_, problems) in found.items() if problems and path not in _OWED}
    assert not red, f'FORMATS-UPGRADE-ON-READ: {red}'
    paid = sorted(path for path in _OWED if path in found and not found[path][1])
    assert not paid, f'{paid} now upgrade on read: delete their _OWED rows'
    assert set(_OWED) <= set(found), f'an _OWED row names no versioned format: {sorted(set(_OWED) - set(found))}'


def test_planted_formats_are_judged_on_each_clause() -> None:
    """PLANTED CONTROL: one compliant module, and one per clause it can break."""
    good = """
        SCHEMA = 3
        def _from_1(raw): return {**raw, 'schema': 2}
        def _from_2(raw): return {**raw, 'schema': 3}
        _UPGRADES = {1: _from_1, 2: _from_2}
        def read(raw):
            while raw['schema'] in _UPGRADES:
                raw = _UPGRADES[raw['schema']](raw)
            return raw
    """
    assert violations(textwrap.dedent(good)) == (3, [])
    assert violations('VERSION_OF_NOTHING = 2\n') == (None, []), 'an unversioned module is not a format'
    assert violations('SCHEMA_VERSION = 1\n_UPGRADES = {}\nx = _UPGRADES\n') == (1, []), 'a first schema owes none'
    cases = {
        'no upgrade from schema [2]': good.replace('2: _from_2', ''),
        'declares no _UPGRADES': good.replace('_UPGRADES = {1: _from_1, 2: _from_2}', ''),
        'not older than 3': good.replace('2: _from_2}', '2: _from_2, 3: _from_2}'),
        'not functions of this module': good.replace('2: _from_2', '2: other.step'),
        'never read': good.replace("while raw['schema'] in _UPGRADES:", 'while False:').replace(
            "raw = _UPGRADES[raw['schema']](raw)", 'pass'
        ),
    }
    for why, source in cases.items():
        schema, problems = violations(textwrap.dedent(source))
        assert schema == 3
        assert any(why in problem for problem in problems), (why, problems)
