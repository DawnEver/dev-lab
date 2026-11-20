"""A refusal names a FAMILY door with the interpreter that carries it: the session's kit, not the target's.

Wall 2026-11-19: a recursive delete in a sibling repo was refused naming ``worktrees --remove`` under THAT repo's
venv, an older kit without ``--remove``; the agent ran it and hit a second wall. ``{door}`` is the session checkout's
interpreter (whose rendered rules named the door); ``{python}`` stays the target's (its own environment).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dev_lab.dev import agenthooks
from dev_lab.dev._deny_delete_row import RECURSIVE_DELETE
from dev_lab.dev.hook_adoption import HookAdoption, render
from dev_lab.dev.venvpath import DOOR_SLOT, PYTHON_SLOT, expand_interpreter, running_interpreter

if os.name == 'nt':
    import _winapi

_TAIL = ('Scripts', 'python.exe') if os.name == 'nt' else ('bin', 'python')


def _session(tmp_path: Path) -> Path:
    """A checkout whose ``.venv`` is this test's real environment, with its own rendered rules."""
    root = tmp_path / 'session'
    hooks = root / '.claude' / 'hooks'
    hooks.mkdir(parents=True)
    (root / '.git').mkdir()
    (hooks / 'deny-rules.json').write_text(render(HookAdoption(app_name='door (suite)')), encoding='utf-8')
    target, link = Path(sys.executable).parents[1], root / '.venv'
    if os.name == 'nt':
        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)
    return root


def _target(tmp_path: Path) -> Path:
    """A sibling checkout with its OWN interpreter -- an older kit, as far as any door is concerned."""
    root = tmp_path / 'sibling'
    (root / '.git').mkdir(parents=True)
    own = root.joinpath('.venv', *_TAIL)
    own.parent.mkdir(parents=True)
    own.write_text('', encoding='utf-8')
    return root


def test_a_family_door_is_printed_with_the_sessions_interpreter_never_the_targets(tmp_path: Path) -> None:
    session, sibling = _session(tmp_path), _target(tmp_path)
    reason = agenthooks.decide('rm -rf build', session / '.claude' / 'hooks' / 'deny-rules.json', cwd=sibling)
    assert reason is not None, 'a recursive delete was let through'
    sibling_python = sibling.joinpath('.venv', *_TAIL).as_posix()
    assert f'{sibling_python} -m dev_lab.dev.worktrees --remove' not in reason, "the target's older kit named"
    assert '-m dev_lab.dev.worktrees --remove <name>' in reason
    assert DOOR_SLOT not in reason, 'the slot was printed unfilled'
    assert sibling_python not in reason, 'every door of this row is a family door'


def test_planted_control_the_python_slot_still_names_the_targets_own_interpreter(tmp_path: Path) -> None:
    """``{python}`` is the target's own environment (bootstrap, verify): unchanged by the door slot."""
    sibling = _target(tmp_path)
    text = expand_interpreter(f'{DOOR_SLOT} -m dev_lab.dev.x; {PYTHON_SLOT} -m y', sibling, os_name=os.name)
    door, own = text.split('; ')
    assert door == f'{running_interpreter()} -m dev_lab.dev.x', 'a family door names the running kit'
    assert Path(own.removesuffix(' -m y')).samefile(sibling.joinpath('.venv', *_TAIL)), 'python names the target'


def test_every_door_of_the_delete_row_carries_the_door_slot() -> None:
    remedy = str(RECURSIVE_DELETE['remedy'])
    for door in ('scratch clear', 'branchset --apply', 'branchset --discard', 'worktrees --remove', 'venvprune'):
        assert f'{DOOR_SLOT} -m dev_lab.dev.{door}' in remedy, f'{door} is named without its interpreter'
    assert PYTHON_SLOT not in remedy, 'a family door names the target kit'
