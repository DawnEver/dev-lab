"""THE RENDERED .claude/settings.json (user ruling 2026-11-24): family base plus the repo's [tool.dev_lab.claude] delta.

Each arm plants the refusal beside the acceptance: a hand edit reds, an unknown delta key is refused by name,
and the delta lands where it is declared and nowhere else.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev_lab.dev import autodoors
from dev_lab.dev.agent_wiring import SETTINGS_REL, rows
from dev_lab.dev.claudesettings import BASE_ENV, document, drift, main, render, write


def _repo(tmp_path: Path, delta: str = '') -> Path:
    (tmp_path / 'pyproject.toml').write_text(f'[project]\nname = "x"\n{delta}', encoding='utf-8')
    return tmp_path


def test_the_base_is_the_hooks_the_door_rows_and_the_agg_backend(tmp_path: Path) -> None:
    """Every family hook row, every door row of the shared source, MPLBACKEND=Agg -- and no enabledPlugins."""
    doc = document(_repo(tmp_path))
    assert doc['env'] == BASE_ENV == {'MPLBACKEND': 'Agg'}
    wired = [
        (event, hook['command']) for event, entries in doc['hooks'].items() for e in entries for hook in e['hooks']
    ]
    assert wired == [(row.event, row.command) for row in rows(tmp_path)]
    assert set(autodoors.claude_rows()) <= set(doc['permissions']['allow'])
    assert 'enabledPlugins' not in doc, 'the sharp-review switch retired with the plugin'


def test_the_delta_lands_where_declared(tmp_path: Path) -> None:
    """Env merges over the base; allow and deny append."""
    root = _repo(
        tmp_path, '[tool.dev_lab.claude]\nenv = { FOO = "1" }\nallow = ["Bash(make x)"]\ndeny = ["Bash(rm *)"]\n'
    )
    doc = document(root)
    assert doc['env'] == {'MPLBACKEND': 'Agg', 'FOO': '1'}
    assert doc['permissions']['allow'][-1] == 'Bash(make x)'
    assert doc['permissions']['deny'] == ['Bash(rm *)']


def test_an_unknown_delta_key_is_refused_by_name(tmp_path: Path) -> None:
    """PLANTED CONTROL: a delta reaching for a key the renderer does not own is a fork, refused."""
    with pytest.raises(ValueError, match="'enabledPlugins'"):
        document(_repo(tmp_path, '[tool.dev_lab.claude]\nenabledPlugins = {}\n'))


def test_a_hand_edit_reds_and_one_render_settles_it(tmp_path: Path) -> None:
    """PLANTED CONTROL: absent reds, rendered is current, one changed byte reds, the CLI check exits 1."""
    root = _repo(tmp_path)
    assert 'absent' in (drift(root) or '')
    assert write(root) == f'{SETTINGS_REL}: rendered'
    assert drift(root) is None
    assert json.loads((root / SETTINGS_REL).read_text(encoding='utf-8')) == document(root)
    (root / SETTINGS_REL).write_text(render(root).replace('Agg', 'TkAgg'), encoding='utf-8')
    assert 'differs' in (drift(root) or '')
    assert main(['check', '--repo', str(root)]) == 1
    assert main(['render', '--repo', str(root)]) == 0
    assert main(['check', '--repo', str(root)]) == 0
