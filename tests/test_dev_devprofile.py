"""An undeclared machine renders the family default and is refused write and HPC doors by name; bridge.hpc renders."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from lab_commons.hpc.grants import AccessRefused

from dev_lab.dev import devcredential, devdeclared, devhost, devprofile, devschema
from dev_lab.dev.hpcaccount import division
from dev_lab.ops.configcheck import check_family, check_host

FAMILY = """\
[dev]
ref = "integrate/main"
forges = { "forge.example" = ["dev-user"] }
bridge = { hpc = { cadence_hours = 6 } }

[dev.default]
forges = {}
hpc = []
hooks = "warn"

[hpc]
session_reach = { lead = ["verification"] }
"""

HOST = '[dev]\nhpc = ["research"]\nos = "windows"\n'
#: The machine's stable tool interpreter, a local-only fact (#782).
LIVE = {'tools': {'python': '/opt/tools/bin/python'}}


def _clone(tmp_path: Path, family: str = FAMILY) -> Path:
    clone = tmp_path / 'config-source'
    (clone / 'hosts').mkdir(parents=True)
    (clone / 'family.toml').write_text(family, encoding='utf-8')
    (clone / 'hosts' / 'ws.toml').write_text(HOST, encoding='utf-8')
    return clone


def test_an_unknown_hostname_renders_the_default_stamped_unmanaged(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    rendered = tomllib.loads(devhost.render(clone, 'stranger', LIVE))
    assert rendered['devhost']['unmanaged'] == 'stranger'
    assert rendered['devhost']['hooks'] == 'warn'
    assert rendered['hpc']['reach'] == [], 'the default reaches no HPC role'
    assert 'capabilities' not in rendered, 'the default holds no vendor seat'
    dev = devdeclared.declared(clone / 'hosts' / 'stranger.toml', clone / 'family.toml')
    assert dev['forges'] == {}, "the default REPLACES the family's forges: no write account"


def test_a_declared_host_is_unaffected(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    rendered = tomllib.loads(devhost.render(clone, 'ws', LIVE))
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
        hpc = tomllib.loads(devhost.render(clone, host, LIVE))['bridge']['hpc']
        assert hpc['command'] == [LIVE['tools']['python'], *devprofile.HPC_READ_DOOR]
        assert hpc['cadence_hours'] == 6


def test_the_bridge_interpreter_is_the_machines_declared_one_never_the_renderers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#782: two renders from different interpreters agree byte for byte; an undeclared one is refused by name.

    PLANTED CONTROL: the same family and host with no ``[tools] python`` is refused, naming the local door.
    """
    clone = _clone(tmp_path)
    renders = []
    for caller in ('/wt/a/.venvs/x/python', '/wt/b/.venv/python'):
        monkeypatch.setattr(devprofile, 'running_interpreter', lambda caller=caller: caller)
        renders.append(devhost.render(clone, 'ws', LIVE))
    assert renders[0] == renders[1]
    with pytest.raises(ValueError, match=r'local set tools\.python'):
        devhost.render(clone, 'ws', {})


def test_without_a_declared_default_an_unknown_host_is_refused_by_name(tmp_path: Path) -> None:
    clone = _clone(tmp_path, FAMILY.replace('[dev.default]\nforges = {}\nhpc = []\nhooks = "warn"\n', ''))
    with pytest.raises(LookupError, match=r'\[dev.default\]'):
        devhost.render(clone, 'stranger', LIVE)


def test_the_unmanaged_machine_is_refused_write_and_hpc_naming_the_enrolment_door(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    live = tomllib.loads(devhost.render(_clone(tmp_path), 'stranger', LIVE))
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
    bad = FAMILY.replace('hooks = "warn"', 'hooks = "off"').replace('cadence_hours = 6', 'cadence_hours = 0')
    found = devschema.check_family(tomllib.loads(bad))
    assert any('default.hooks' in line for line in found), found
    assert any('cadence_hours must be 1..168' in line for line in found), found
    assert devschema.check({'dev': {'default': {}}}, tomllib.loads(FAMILY)), 'a host may not declare the default'


def test_the_enrolment_door_names_the_config_sources_own_checkout_loop() -> None:
    """#745: a proposal runs IN the config source's checkout, so its own hooks and forge judge it."""
    text = devprofile.enrolment('WSX')
    assert 'own checkout' in text
    assert 'worktree add' in text
    assert 'forge pr create` FROM that worktree' in text
    # the control: the render door is still named last
    assert text.rstrip().endswith('render --host WSX --write')


def test_local_set_heals_the_missing_bridge_interpreter_it_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Measured 2026-11-20: the refusal named `local set tools.python`, and that door refused itself.

    PLANTED CONTROL: render with the key still unset is refused by name and writes nothing.
    """
    clone = _clone(tmp_path)
    rendered = tomllib.loads(devhost.render(clone, 'ws', LIVE))
    rendered.pop('tools')
    rendered.pop('bridge')
    machine = tmp_path / 'machine.toml'
    machine.write_text(devhost.dumps(rendered), encoding='utf-8')
    before = machine.read_text(encoding='utf-8')
    backups = str(tmp_path / 'b')
    code = devhost.main(['--machine', str(machine), 'render', '--write', '--backups', backups])
    assert code == 2, 'a render missing the local interpreter is refused, never a traceback'
    assert r'local set tools.python' in capsys.readouterr().err
    assert machine.read_text(encoding='utf-8') == before, 'a refused render writes nothing'
    python = '/opt/tools/bin/python'
    code = devhost.main(['--machine', str(machine), 'local', 'set', 'tools.python', python, '--backups', backups])
    assert code == 0, 'the door the refusal names sets the key it names'
    healed = tomllib.loads(machine.read_text(encoding='utf-8'))
    assert healed['tools']['python'] == python
    assert healed['bridge']['hpc']['command'][0] == python
