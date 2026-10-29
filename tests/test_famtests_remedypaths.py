"""A remedy names an ABSOLUTE interpreter: the resolver, the famtest convicting a relative one, its adoption.

THE INCIDENT, 2026-10-26: a remedy spelled ``.venv/Scripts/python.exe`` relative, the agent's shell sat in another
directory, the command failed, and the agent handed the user an absolute rewrite instead of running it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lab_commons.census import Process

from dev_lab.dev import agenthooks, forgecred, forgeoutbox, liverun
from dev_lab.dev._deny_interpreter_row import INTERPRETER_REMEDY
from dev_lab.dev.famtests.remedypaths import (
    assert_a_planted_relative_remedy_is_convicted,
    assert_remedies_name_absolute_interpreters,
    relative_interpreters,
)
from dev_lab.dev.floors import FloorUnmet
from dev_lab.dev.hooks import DENY_RULES
from dev_lab.dev.venvpath import (
    PYTHON_SLOT,
    current_os_name,
    expand_interpreter,
    remedy_interpreter,
    venv_interpreter,
)

_OS = current_os_name()


def _venv(root: Path) -> Path:
    python = root / venv_interpreter(os_name=_OS)
    python.parent.mkdir(parents=True)
    python.write_text('', encoding='utf-8')
    return python


def test_the_checkouts_own_interpreter_is_named_absolute(tmp_path: Path) -> None:
    python = _venv(tmp_path)
    assert remedy_interpreter(tmp_path, os_name=_OS) == python.as_posix()


def test_a_linked_worktree_without_a_venv_names_the_main_checkouts(tmp_path: Path) -> None:
    main = tmp_path / 'main'
    python = _venv(main)
    lane = main / '.claude' / 'worktrees' / 'lane'
    lane.mkdir(parents=True)
    (lane / '.git').write_text(f'gitdir: {(main / ".git" / "worktrees" / "lane").as_posix()}\n', encoding='utf-8')
    assert remedy_interpreter(lane, os_name=_OS) == python.as_posix()


def test_no_venv_anywhere_still_spells_an_absolute_path(tmp_path: Path) -> None:
    said = remedy_interpreter(tmp_path, os_name=_OS)
    assert Path(said).is_absolute()
    assert said == (tmp_path / venv_interpreter(os_name=_OS)).as_posix()


def test_both_tokens_expand_to_the_absolute_interpreter(tmp_path: Path) -> None:
    python = _venv(tmp_path).as_posix()
    said = expand_interpreter(f'stop it: {PYTHON_SLOT} -m x; or <venv python> -m y', tmp_path, os_name=_OS)
    assert said == f'stop it: {python} -m x; or {python} -m y'


def test_the_planted_control_convicts_and_spares() -> None:
    assert_a_planted_relative_remedy_is_convicted()


@pytest.mark.parametrize(
    'line',
    ['.venv/Scripts/python.exe -m x', './.venv/bin/python -m x', 'stop it: python -m dev_lab.dev.stoprun', '(py -m x)'],
)
def test_a_relative_or_bare_interpreter_is_found(line: str) -> None:
    assert relative_interpreters(line) == (line,)


@pytest.mark.parametrize(
    'line',
    ['C:/r/.venv/Scripts/python.exe -m x', '/srv/r/.venv/bin/python -m x', f'{PYTHON_SLOT} -m x', 'git grep -n'],
)
def test_an_absolute_or_tokenised_interpreter_is_spared(line: str) -> None:
    assert relative_interpreters(line) == ()


def test_a_scan_that_read_too_little_is_not_a_pass() -> None:
    with pytest.raises(FloorUnmet):
        assert_remedies_name_absolute_interpreters({}, floor=1)


def test_every_remedy_this_kit_prints_names_an_absolute_interpreter(tmp_path: Path) -> None:
    """ADOPTION: every deny row's exit, and the runtime remedies of the doors, as the agent reads them."""
    root = tmp_path / 'tree'
    run = Process(7, 1, str(root / venv_interpreter(os_name=_OS)), 'x -m app deck run', 600.0, str(root))
    texts = {f'deny row {rule.id}': rule.remedy for rule in DENY_RULES}
    texts |= {
        'interpreter remedy': INTERPRETER_REMEDY,
        'liverun refusal': liverun.refusal(root, [run]),
        'liverun env_in_use': liverun.env_in_use('DEP', str(root / '.venv'), [run]),
        'forge credential gone': forgecred.AUTH_GONE,
        'forge credential kept': forgecred.AUTH_KEPT,
        'forge outbox': forgeoutbox._REMEDY,
    }
    assert_remedies_name_absolute_interpreters(texts, floor=len(DENY_RULES))


def test_the_engine_prints_the_target_checkouts_interpreter_absolute(tmp_path: Path) -> None:
    """The JS printer agrees with the Python resolver: a linked worktree with no venv names main's, absolute."""
    main = tmp_path / 'main'
    python = _venv(main)
    (main / '.git').mkdir()
    lane = main / '.claude' / 'worktrees' / 'lane'
    lane.mkdir(parents=True)
    (lane / '.git').write_text(f'gitdir: {(main / ".git" / "worktrees" / "lane").as_posix()}\n', encoding='utf-8')
    rules = lane / '.claude' / 'hooks' / 'deny-rules.json'
    rules.parent.mkdir(parents=True)
    row = {'name': 'X', 'pattern': 'boom', 'reason': f'X: h\nstop it: {PYTHON_SLOT} -m s; door <venv python> -m d'}
    rules.write_text(json.dumps([row]), encoding='utf-8')
    said = agenthooks.decide('boom', rules, cwd=lane)
    assert said == f'X: h\nstop it: {python.as_posix()} -m s; door {python.as_posix()} -m d'
    assert remedy_interpreter(lane, os_name=_OS) == python.as_posix()
