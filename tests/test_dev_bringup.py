"""``devhost bringup --check``: every wall a new or migrated workstation hits, each with its door, before any code.

Measured on a workstation 2026-11-20, in order: no bridge interpreter (drift crashed), no issuer host key, the
machine's key not authorized on the issuer, an issuer too old to handshake. Each wall here is planted red and green.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from dev_lab.dev import bringup, devhost
from dev_lab.dev.locklag import LAG_WINDOW, Lag
from dev_lab.ops.consent.door import hello

KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIA1dtjiBuQjg+mT4+rUmSfSrdgiwtUSw9TlircWVvVC0'
FAMILY = '[dev]\nref = "integrate/main"\nbridge = { hpc = { cadence_hours = 6 } }\n[consent]\nendpoint = "c@i"\n'


def _machine(tmp_path: Path, *, declared: bool = True, keyed: bool = True) -> dict[str, Any]:
    clone = tmp_path / 'source'
    (clone / 'hosts').mkdir(parents=True)
    (clone / 'family.toml').write_text(FAMILY, encoding='utf-8')
    keys = f'client_keys = ["{KEY} dev@ws"]\n' if keyed else ''
    if declared:
        (clone / 'hosts' / 'ws.toml').write_text(f'[dev]\nos = "windows"\n{keys}', encoding='utf-8')
    ssh = tmp_path / 'ssh'
    ssh.mkdir()
    (ssh / 'id_ed25519.pub').write_text(f'{KEY} me@here\n', encoding='utf-8')
    live = {'repos': {'dev-lab': (tmp_path / 'dev-lab').as_posix()}, 'devhost': {'host': 'ws', 'source': str(clone)}}
    if declared:
        live = {**tomllib.loads(devhost.render(clone, 'ws', live)), 'repos': live['repos']}
    return live


def _speaks(_table: Mapping[str, Any], _request: dict[str, Any]) -> tuple[int, str]:
    return 0, json.dumps(hello())


def _walls(tmp_path: Path, live: Mapping[str, Any], **kw: object) -> dict[str, bringup.Wall]:
    kw.setdefault('send', _speaks)
    kw.setdefault('exists', lambda _path: True)
    kw.setdefault('credential', lambda _dev: [])
    kw.setdefault('measure', lambda _checkout, _ref: Lag(0, timedelta(0)))
    return {wall.name: wall for wall in bringup.walls(live, ssh_dir=tmp_path / 'ssh', **kw)}


def test_a_ready_workstation_is_green_on_every_wall(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    found = _walls(tmp_path, _machine(tmp_path))
    assert [name for name, wall in found.items() if not wall.green] == []
    assert list(found) == [
        'config-source', 'enrollment', 'bridge-interpreter', 'dev-lab-kit', 'machine-file', 'client-key', 'issuer',
        'forge-credential',
    ]  # fmt: skip
    assert bringup.report(found.values()) == 0
    assert 'bringup: GREEN' in capsys.readouterr().out


def test_an_undeclared_machine_stops_at_enrollment_naming_its_door(tmp_path: Path) -> None:
    found = _walls(tmp_path, _machine(tmp_path, declared=False))
    assert not found['enrollment'].green
    assert 'declare hosts/ws.toml' in found['enrollment'].said


def test_the_bridge_interpreter_is_derived_and_must_exist(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same machine with the interpreter on disk is green."""
    live = _machine(tmp_path)
    missing = _walls(tmp_path, live, exists=lambda _path: False)['bridge-interpreter']
    assert not missing.green
    assert '/dev-lab/.venv/Scripts/python.exe does not exist' in missing.said
    assert 'dep --bootstrap' in missing.said
    unset = _walls(tmp_path, {k: v for k, v in live.items() if k != 'repos'})['bridge-interpreter']
    assert 'local set repos.dev-lab' in unset.said


def test_an_undeclared_client_key_names_the_host_file_line(tmp_path: Path) -> None:
    found = _walls(tmp_path, _machine(tmp_path, keyed=False))['client-key']
    assert not found.green
    assert f'[dev] client_keys = ["{KEY} <comment>"]' in found.said


@pytest.mark.parametrize(
    ('answer', 'said', 'code'),
    [
        ((255, 'Host key verification failed.'), 'host key is not known here', ''),
        ((255, 'c@i: Permission denied (publickey).'), 'does not admit this machine', 'ops.config'),
        ((255, 'ssh: connect to host i port 22: Connection timed out'), 'is not reached', ''),
        ((1, 'refused: unknown verb hello'), 'no version handshake', ''),
    ],
)
def test_each_issuer_wall_is_told_apart_and_names_its_door(
    tmp_path: Path, answer: tuple[int, str], said: str, code: str
) -> None:
    """One ``hello`` tells host key, authorization, reach and version apart; only authorization spends a code."""
    found = _walls(tmp_path, _machine(tmp_path), send=lambda _t, _r: answer)['issuer']
    assert not found.green
    assert said in found.said
    assert found.code == code


def test_a_declared_unadmitted_key_names_the_admit_door_runnable_from_any_admitted_machine(tmp_path: Path) -> None:
    """Measured 2026-11-22: the wall sent the agent to "someone on the forge host"; it names the one door instead."""
    denied = (255, 'c@i: Permission denied (publickey).')
    found = _walls(tmp_path, _machine(tmp_path), send=lambda _t, _r: denied)['issuer']
    assert 'declared but not yet admitted' in found.said
    assert 'devhost admit --host ws' in found.said
    assert 'ANY machine the issuer already admits' in found.said
    assert found.said.index('devhost admit') < found.said.index('devhost enroll')
    assert 'forge host' not in found.said
    assert 'install' not in found.said
    undeclared = _walls(tmp_path / 'b', _machine(tmp_path / 'b', keyed=False), send=lambda _t, _r: denied)['issuer']
    assert 'declared but not yet admitted' not in undeclared.said
    assert 'client-key' in undeclared.said


def test_codes_are_listed_last_and_only_after_the_no_code_walls(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """PLANTED CONTROL: with only code walls left, the report says the codes may be asked now."""
    live = _machine(tmp_path, keyed=False)
    found = _walls(tmp_path, live, credential=lambda _dev: ['no stored credential'])
    assert bringup.report(found.values()) == 1
    out = capsys.readouterr().out
    assert 'codes, after the walls above are green, in order: forge.token for forge-credential' in out
    found = _walls(tmp_path, _machine(tmp_path / 'b'), credential=lambda _dev: ['no stored credential'])
    bringup.report(found.values())
    assert 'codes, now: every no-code wall is green' in capsys.readouterr().out


def test_the_verb_is_wired_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Mapping[str, Any]] = []
    monkeypatch.setattr(bringup, 'main', lambda live: seen.append(live) or 0)
    machine = tmp_path / 'm.toml'
    machine.write_text('[devhost]\nhost = "ws"\n', encoding='utf-8')
    assert devhost.main(['--machine', str(machine), 'bringup', '--check']) == 0
    assert seen == [{'devhost': {'host': 'ws'}}]
    assert machine.read_text(encoding='utf-8') == '[devhost]\nhost = "ws"\n'


@pytest.mark.parametrize(
    ('lag', 'verdict'),
    [(Lag(0, timedelta(0)), 'green'), (Lag(3, LAG_WINDOW), 'green'), (Lag(46, LAG_WINDOW * 7), 'wall')],
)
def test_a_stale_kit_is_a_wall_naming_pull_and_sync(lag: Lag, verdict: str) -> None:
    """Measured 2026-11-23: a workstation ran a dev-lab older than D94 and saw a hidden prompt; nothing said so.

    PLANTED CONTROL: a checkout at its ref, and one inside the one window, have no wall.
    """
    found = bringup.kit('D:/x/dev-lab', 'integrate/main', measure=lambda _checkout, _ref: lag)
    assert found.green is (verdict == 'green')
    assert f'{lag} behind origin/integrate/main' in found.said
    if verdict == 'wall':
        assert '-m dev_lab.dev.netverb -- git pull --ff-only' in found.said
        assert 'uv sync --frozen' in found.said


def test_an_unreadable_checkout_is_not_read_as_current() -> None:
    found = bringup.kit('D:/x/dev-lab', 'integrate/main', measure=lambda _c, _r: None)
    assert not found.green
    assert 'cannot be read' in found.said


def test_the_session_start_notice_names_a_stale_kit(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same machine inside the window says nothing."""
    live = _machine(tmp_path)
    stale = bringup.stale_kit(live, measure=lambda _c, _r: Lag(46, LAG_WINDOW * 7))
    assert len(stale) == 1
    assert stale[0].startswith('DEV-LAB-KIT STALE: 46 landings')
    assert 'git pull --ff-only' in stale[0]
    assert bringup.stale_kit(live, measure=lambda _c, _r: Lag(1, timedelta(hours=1))) == []
