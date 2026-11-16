"""An undeclared machine renders the family default and is refused write and HPC doors by name; bridge.hpc renders."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from lab_commons.hpc.grants import AccessRefused

from dev_lab.dev import devcredential, devhost, devprofile, devschema
from dev_lab.dev.hpcaccount import division
from dev_lab.ops.configcheck import check_family, check_host

FAMILY = """\
[dev]
ref = "integrate/main"
forges = { "forge.example" = ["dev-user"] }
bridge = { hpc = { every_hours = 6 } }

[dev.default]
forges = {}
hpc = []
hooks = "warn"

[hpc]
session_reach = { lead = ["verification"] }
"""

HOST = '[dev]\nhpc = ["research"]\nos = "windows"\n'


def _clone(tmp_path: Path, family: str = FAMILY) -> Path:
    clone = tmp_path / 'config-source'
    (clone / 'hosts').mkdir(parents=True)
    (clone / 'family.toml').write_text(family, encoding='utf-8')
    (clone / 'hosts' / 'ws.toml').write_text(HOST, encoding='utf-8')
    return clone


def test_an_unknown_hostname_renders_the_default_stamped_unmanaged(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    rendered = tomllib.loads(devhost.render(clone, 'stranger', {}))
    assert rendered['devhost']['unmanaged'] == 'stranger'
    assert rendered['devhost']['hooks'] == 'warn'
    assert rendered['hpc']['reach'] == [], 'the default reaches no HPC role'
    assert 'capabilities' not in rendered, 'the default holds no vendor seat'
    dev = devhost.declared(clone / 'hosts' / 'stranger.toml', clone / 'family.toml')
    assert dev['forges'] == {}, "the default REPLACES the family's forges: no write account"


def test_a_declared_host_is_unaffected(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    rendered = tomllib.loads(devhost.render(clone, 'ws', {}))
    assert 'unmanaged' not in rendered['devhost']
    assert 'hooks' not in rendered['devhost']
    assert rendered['hpc']['reach'] == ['research']
    assert devprofile.refusal(rendered, 'an HPC action') is None
    assert devhost.notice({**rendered, 'devhost': {**rendered['devhost'], 'unmanaged': 'ws'}}).startswith(
        'HOST-CONFIG FIRST: this machine is UNMANAGED'
    ), 'the session start names the enrolment door first on an unmanaged machine'


def test_bridge_hpc_renders_on_every_dev_machine_from_the_family(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    for host in ('ws', 'stranger'):
        hpc = tomllib.loads(devhost.render(clone, host, {}))['bridge']['hpc']
        assert hpc['command'][1:] == list(devprofile.HPC_READ_DOOR)
        assert hpc['every_hours'] == 6


def test_without_a_declared_default_an_unknown_host_is_refused_by_name(tmp_path: Path) -> None:
    clone = _clone(tmp_path, FAMILY.replace('[dev.default]\nforges = {}\nhpc = []\nhooks = "warn"\n', ''))
    with pytest.raises(LookupError, match=r'\[dev.default\]'):
        devhost.render(clone, 'stranger', {})


def test_the_unmanaged_machine_is_refused_write_and_hpc_naming_the_enrolment_door(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    live = tomllib.loads(devhost.render(_clone(tmp_path), 'stranger', {}))
    monkeypatch.setattr(division.config, 'machine', lambda: live)
    with pytest.raises(AccessRefused, match=r'declare hosts/stranger\.toml .* render --host stranger'):
        division.reached_machine()
    monkeypatch.setattr(devcredential.machineconfig, 'machine', lambda: live)
    code = devcredential.main(['--login', 'dev-user', '--forge-config', str(tmp_path / 'absent.toml')])
    assert code == 2
    assert 'hosts/stranger.toml' in capsys.readouterr().out


def test_the_family_default_and_bridge_are_checked(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    assert check_family(clone / 'family.toml') == []
    assert check_host(clone / 'hosts' / 'ws.toml', clone / 'family.toml') == []
    bad = FAMILY.replace('hooks = "warn"', 'hooks = "off"').replace('every_hours = 6', 'every_hours = 0')
    found = devschema.check_family(tomllib.loads(bad))
    assert any('default.hooks' in line for line in found), found
    assert any('every_hours must be 1..168' in line for line in found), found
    assert devschema.check({'dev': {'default': {}}}, tomllib.loads(FAMILY)), 'a host may not declare the default'
