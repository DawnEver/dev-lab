"""Every process the kit starts goes through ONE door, :mod:`lab_commons.launch` (``run``/``popen``).

INCIDENT 2026-10-16: the serve Task's ``pythonw`` has no console, and every console child it started
directly -- git and uv in the host refresh -- opened a window on the user's desktop every five minutes.
The door adds ``CREATE_NO_WINDOW`` on Windows; a spawn that bypasses it is the incident again, so a raw
``subprocess`` spawner (called, or handed on as a default) and ``os.system``/``os.startfile``/``os.popen``/
``os.spawn*`` are refused anywhere in ``src`` but the door itself.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from _arch_corpus import assert_floor, parse, rel, source_modules

#: The ``subprocess`` names that start a process.
SUBPROCESS_SPAWNERS = frozenset({'run', 'Popen', 'call', 'check_call', 'check_output', 'getoutput', 'getstatusoutput'})
#: The ``os`` names that start a process.
OS_SPAWNERS = frozenset({'system', 'startfile', 'popen'})
#: The door: the one module allowed to touch the spawners.
DOOR = 'src/lab_commons/launch.py'
#: Modules that spawn WITHOUT the door, each with the reason: none reaches a console-less Windows parent.
STANDALONE: dict[str, str] = {
    'src/lab_commons/hpc/pytest_item.py': 'shipped as TEXT to a cluster node and run there; imports no lab_commons',
}
#: The kit's source-module floor; MEASURED 2026-10-16 well above it.
SOURCE_FLOOR = 100


def _spawner(node: ast.expr) -> str:
    if not (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)):
        return ''
    module, name = node.value.id, node.attr
    if (module == 'subprocess' and name in SUBPROCESS_SPAWNERS) or (
        module == 'os' and (name in OS_SPAWNERS or name.startswith('spawn'))
    ):
        return f'{module}.{name}'
    return ''


def _defaults(node: ast.AST) -> list[ast.expr]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        return [d for d in (*node.args.defaults, *node.args.kw_defaults) if d is not None]
    return []


def raw_spawns(tree: ast.Module) -> list[str]:
    """Each raw spawn in *tree*: a spawner called, handed on as a default, or imported by name."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (name := _spawner(node.func)):
            found.append(f'{node.lineno}:{name}')
        found.extend(f'{d.lineno}:{name}' for d in _defaults(node) if (name := _spawner(d)))
        if isinstance(node, ast.ImportFrom) and node.module == 'subprocess':
            found.extend(f'{node.lineno}:{a.name}' for a in node.names if a.name in SUBPROCESS_SPAWNERS)
    return found


def test_every_process_in_the_kit_starts_through_the_door() -> None:
    modules = source_modules()
    assert_floor(len(modules), SOURCE_FLOOR, 'kit source')
    exempt = {DOOR, *STANDALONE}
    found = [f'{rel(path)}:{hit}' for path in modules if rel(path) not in exempt for hit in raw_spawns(parse(path))]
    assert found == [], f'start these through lab_commons.launch.run/popen (CREATE_NO_WINDOW): {found}'


@pytest.mark.parametrize(
    ('body', 'flagged'),
    [
        ("subprocess.run(['git'])\n", True),
        ("subprocess.Popen(['git'])\n", True),
        ("subprocess.check_output(['git'])\n", True),
        ('def f(run=subprocess.run): ...\n', True),
        ('from subprocess import Popen\n', True),
        ("os.system('git')\n", True),
        ("os.startfile('x')\n", True),
        ("os.spawnl(os.P_WAIT, 'x')\n", True),
        ("proc.run(['git'])\n", False),
        ('isinstance(p, subprocess.Popen)\n', False),
        ('def f(p: subprocess.Popen[bytes]) -> None: ...\n', False),
    ],
)
def test_a_planted_raw_spawn_is_refused(tmp_path: Path, body: str, *, flagged: bool) -> None:
    """THE PLANTED CONTROL: the real scan flags each raw spawner shape and passes the door."""
    planted = tmp_path / 'planted.py'
    planted.write_text(f'import os, subprocess\n{body}', encoding='utf-8')
    assert bool(raw_spawns(parse(planted))) is flagged
