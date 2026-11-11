"""TRACKED-CITES-NO-EPHEMERAL at the DOOR (issue #419): a journal line citing an ignored path is never written.

THE DEADLOCK. rem's ``task.js log`` appends a line to a TRACKED journal. A line citing a git-ignored path is
then refused by the pre-commit ephemeral-refs scan, the journal is append-only (no edit repairs it), and the
agent may not run the commit-bypass itself -- so the line can never be committed or repaired. The fix refuses
the COMMAND that would write it: a deny row on ``task.js log|decide|open-item|close-item|handoff`` whose
decision is the same :func:`dev_lab.dev.ephemeralrefs.judge` the scan runs, asked only after the row matched.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from dev_lab.dev import agenthooks, ephemeralrefs, hooks
from dev_lab.dev._deny_ephemeral_row import JOURNAL_CITES_EPHEMERAL
from dev_lab.dev.hook_adoption import HookAdoption, render

_TASK_JS = 'X:/kit/rem/scripts/task.js'


def _repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    ephemeralrefs._door.run(['git', 'init', '-q'], cwd=root, check=True, timeout=60)
    (root / '.gitignore').write_text('/output/\n/.venv/\n', encoding='utf-8')
    (root / 'src').mkdir()
    (root / 'src' / 'a.py').write_text('', encoding='utf-8')
    ephemeralrefs._door.run(['git', 'add', '-A'], cwd=root, check=True, timeout=60)
    return root


def test_a_journal_line_citing_an_ignored_path_is_refused_by_name(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    said = ephemeralrefs.door(root, f'node "{_TASK_JS}" log "measured, see output/logs/26/11/11/run/a.md"')
    assert said is not None
    assert 'output/logs/26/11/11/run/a.md' in said
    assert said.startswith(f'{ephemeralrefs.RULE}:')


def test_planted_control_a_tracked_cite_a_shape_and_the_task_js_path_itself_pass(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same verb, citing nothing ephemeral, is admitted.

    The script's own machine path is the command, not the line, so it is never judged.
    """
    root = _repo(tmp_path)
    for text in ('see src/a.py', 'logs go to output/logs/<yy>/<mm>/<dd>/<kind>/', 'no path at all'):
        assert ephemeralrefs.door(root, f'node "{_TASK_JS}" decide "{text}"') is None, text
    assert ephemeralrefs.door(root, f'node "{_TASK_JS}" show "output/x.md"') is None, 'not a journal verb'


def test_the_row_fires_on_every_journal_verb_and_binds_only_when_the_door_says_so() -> None:
    rule = next(r for r in hooks.DENY_RULES if r.id == JOURNAL_CITES_EPHEMERAL['id'])
    assert rule.when == 'cites-ephemeral'
    for command in rule.refuses:
        assert hooks.denies((rule,), command, conditions=frozenset({'cites-ephemeral'})) == rule.id, command
        assert hooks.denies((rule,), command) is None, f'bound without the door asked: {command}'
    for command in rule.permits:
        assert hooks.denies((rule,), command, conditions=frozenset({'cites-ephemeral'})) is None, command


def _link_venv(root: Path) -> None:
    """*root*'s ``.venv`` is this suite's own environment, linked: the engine asks the session checkout's venv."""
    here = Path(sys.prefix)
    if os.name == 'nt':
        import _winapi  # noqa: PLC0415 -- Windows-only: a junction needs no privilege, a symlink does

        _winapi.CreateJunction(str(here), str(root / '.venv'))
    else:
        (root / '.venv').symlink_to(here, target_is_directory=True)


@pytest.mark.skipif(shutil.which('node') is None, reason='no node: the engine cannot run here')
def test_the_engine_refuses_the_journal_line_and_admits_its_planted_control(tmp_path: Path) -> None:
    """Through the real ``deny-commands.js``: the row matches, the engine asks the door, the door refuses."""
    root = _repo(tmp_path / 'repo')
    _link_venv(root)
    rules = root / '.claude' / 'hooks' / 'deny-rules.json'
    rules.parent.mkdir(parents=True)
    rules.write_text(render(HookAdoption(app_name='door suite', remedies={})), encoding='utf-8')
    engine = agenthooks.engine_path('deny-commands')
    bad = f'node "{_TASK_JS}" log "see output/x.md"'
    said = agenthooks.run_engine(engine, bad, rules, cwd=root, live_run=False)
    assert said is not None
    assert 'output/x.md' in said
    good = f'node "{_TASK_JS}" log "see src/a.py"'
    assert agenthooks.run_engine(engine, good, rules, cwd=root, live_run=False) is None
