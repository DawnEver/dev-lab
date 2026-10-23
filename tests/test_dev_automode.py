"""REPO-AUTOMODE: ``.claude/automode.json`` is RENDERED from single sources, prose only, and drift is refused."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev.automode import (
    AUTOMODE_REL,
    INTENTS,
    OPTIONAL_INTENTS,
    automode,
    check,
    spelled_commands,
    write,
)
from dev_lab.dev.famtests.visibility import plant_checkout

_GIT = shutil.which('git') or 'git'

_MANIFEST = """[project]
name = "planted"
version = "0"

[tool.lab_commons.branchset]
trunk = "main"
sessions = ["integrate/main"]
{extra}"""


def _repo(tmp_path: Path, extra: str = '') -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    work = plant_checkout(tmp_path, trunk='main').work
    (work / 'pyproject.toml').write_text(_MANIFEST.format(extra=extra), encoding='utf-8')
    subprocess.run(
        [_GIT, '-C', str(work), 'remote', 'set-url', 'origin', 'https://forge.example/Team/planted.git'], check=True
    )
    return work


def test_every_array_opens_with_defaults_and_is_prose(tmp_path: Path) -> None:
    rendered = automode(_repo(tmp_path))
    for key in ('environment', 'allow'):
        entries = rendered['autoMode'][key]
        assert entries[0] == '$defaults', key
        assert len(entries) > 1
        assert spelled_commands(entries[1:]) == (), key
    assert any('forge.example' in line and 'Team/planted' in line for line in rendered['autoMode']['environment'])
    assert len(rendered['autoMode']['allow']) == 1 + len(INTENTS)


def test_the_spelling_scan_sees_a_planted_command() -> None:
    """PLANTED CONTROL: the scan the prose test relies on does fire."""
    assert spelled_commands(['run python -m dev_lab.dev.forge watch']) != ()
    assert spelled_commands(['deploy with `ssh host`']) != ()
    assert spelled_commands(['installs the kit hooks']) == ()


def test_an_optional_intent_is_rendered_only_where_the_repo_declares_it(tmp_path: Path) -> None:
    plain = automode(_repo(tmp_path / 'a'))['autoMode']['allow']
    declared = automode(_repo(tmp_path / 'b', '\n[tool.lab_commons.automode]\ndeclares = ["jmag-material-card"]\n'))
    assert OPTIONAL_INTENTS['jmag-material-card'] not in plain
    assert OPTIONAL_INTENTS['jmag-material-card'] in declared['autoMode']['allow']


def test_an_unknown_declared_intent_is_refused(tmp_path: Path) -> None:
    work = _repo(tmp_path, '\n[tool.lab_commons.automode]\ndeclares = ["anything-goes"]\n')
    with pytest.raises(ValueError, match='anything-goes'):
        automode(work)


def test_the_tracked_file_must_equal_a_fresh_render(tmp_path: Path) -> None:
    work = _repo(tmp_path)
    assert check(work) is False, 'absent is stale'
    write(work)
    assert check(work) is True
    target = work / AUTOMODE_REL
    edited = json.loads(target.read_text(encoding='utf-8'))
    edited['autoMode']['allow'].append('anything at all')
    target.write_text(json.dumps(edited), encoding='utf-8')
    assert check(work) is False, 'PLANTED: a hand edit is drift'
