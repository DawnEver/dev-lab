"""REPO-AUTOMODE: ``.claude/automode.json`` is RENDERED from single sources, prose only, and drift is refused."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from lab_commons.hpc.grants import Grant

from dev_lab.dev.autodoors import INCONCLUSIVE
from dev_lab.dev.autodoors import main as autodoors_main
from dev_lab.dev.automode import (
    AUTOMODE_REL,
    INTENTS,
    OPTIONAL_INTENTS,
    Fleet,
    SourcesUnavailable,
    automode,
    check,
    read_fleet,
    spelled_commands,
    write,
)
from dev_lab.dev.famtests.visibility import plant_checkout

_GIT = shutil.which('git') or 'git'

_FLEET = Fleet(
    workstations=(
        {'name': 'G', 'computer': 'G', 'address': '10.0.0.1', 'roles': ['client', 'node', 'forge']},
        {'name': 'WS1', 'computer': 'BOXONE', 'address': 'boxone.example', 'roles': ['client', 'node']},
    ),
    grants=(
        Grant(user='alice', hosts=('login1.example', 'login2.example'), slurm_account='acct'),
        Grant(user='alice', hosts=('login1.example',), slurm_account='other'),
        Grant(user='bob', hosts=('login2.example',), slurm_account='acct'),
    ),
)

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
    rendered = automode(_repo(tmp_path), _FLEET)
    for key in ('environment', 'allow'):
        entries = rendered['autoMode'][key]
        assert entries[0] == '$defaults', key
        assert len(entries) > 1
        assert spelled_commands(entries[1:]) == (), key
    assert any('forge.example' in line and 'Team/planted' in line for line in rendered['autoMode']['environment'])
    assert len(rendered['autoMode']['allow']) == 1 + len(INTENTS)


def test_the_trusted_hosts_are_named_from_the_sources(tmp_path: Path) -> None:
    environment = ' '.join(automode(_repo(tmp_path), _FLEET)['autoMode']['environment'])
    for name in ('G (computer G; address 10.0.0.1', 'serves the forge', 'WS1 (computer BOXONE; address boxone.example'):
        assert name in environment
    assert 'account alice at login hosts login1.example, login2.example (Slurm account acct)' in environment
    assert 'account bob at login hosts login2.example' in environment
    assert environment.count('account alice') == 1, 'one line per account, its first grant'


def test_the_spelling_scan_sees_a_planted_command() -> None:
    """PLANTED CONTROL: the scan the prose test relies on does fire."""
    assert spelled_commands(['run python -m dev_lab.dev.forge watch']) != ()
    assert spelled_commands(['deploy with `ssh host`']) != ()
    assert spelled_commands(['installs the kit hooks']) == ()


def test_an_optional_intent_is_rendered_only_where_the_repo_declares_it(tmp_path: Path) -> None:
    plain = automode(_repo(tmp_path / 'a'), _FLEET)['autoMode']['allow']
    declared = automode(
        _repo(tmp_path / 'b', '\n[tool.lab_commons.automode]\ndeclares = ["jmag-material-card"]\n'), _FLEET
    )
    assert OPTIONAL_INTENTS['jmag-material-card'] not in plain
    assert OPTIONAL_INTENTS['jmag-material-card'] in declared['autoMode']['allow']


def test_an_unknown_declared_intent_is_refused(tmp_path: Path) -> None:
    work = _repo(tmp_path, '\n[tool.lab_commons.automode]\ndeclares = ["anything-goes"]\n')
    with pytest.raises(ValueError, match='anything-goes'):
        automode(work, _FLEET)


def test_the_tracked_file_must_equal_a_fresh_render(tmp_path: Path) -> None:
    work = _repo(tmp_path)
    assert check(work, _FLEET) is False, 'absent is stale'
    write(work, _FLEET)
    assert check(work, _FLEET) is True
    moved = Fleet(_FLEET.workstations[:1], _FLEET.grants)
    assert check(work, moved) is False, 'a fleet source that changed makes the file stale'
    target = work / AUTOMODE_REL
    edited = json.loads(target.read_text(encoding='utf-8'))
    edited['autoMode']['allow'].append('anything at all')
    target.write_text(json.dumps(edited), encoding='utf-8')
    assert check(work, _FLEET) is False, 'PLANTED: a hand edit is drift'


def test_an_unreadable_source_is_inconclusive_never_a_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL: a machine file with no registry -- a cluster login node -- cannot judge the file."""
    work = _repo(tmp_path)
    write(work, _FLEET)
    machine = tmp_path / 'config.toml'
    machine.write_text('[hpc]\n', encoding='utf-8')
    monkeypatch.setenv('LAB_COMMONS_CONFIG', str(machine))
    with pytest.raises(SourcesUnavailable, match='registry'):
        read_fleet()
    with pytest.raises(SourcesUnavailable):
        check(work)
    before = (work / AUTOMODE_REL).read_text(encoding='utf-8')
    assert autodoors_main(['--repo', str(work)]) == INCONCLUSIVE
    assert autodoors_main(['--repo', str(work), '--write']) == INCONCLUSIVE
    assert (work / AUTOMODE_REL).read_text(encoding='utf-8') == before, 'nothing is written on an unread source'
