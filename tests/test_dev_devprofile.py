"""An undeclared machine renders the family default and is refused write and HPC doors by name; bridge.hpc renders."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from lab_commons import config as machineconfig
from lab_commons import storage
from lab_commons.hpc.grants import AccessRefused
from lab_commons.storage import StorageError

from dev_lab.dev import devcredential, devdeclared, devhost, devprofile, devrender, devschema, tomlleaves
from dev_lab.dev._machinefile import dumps
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
#: The machine's dev-lab checkout, the local fact the bridge interpreter derives from (#782, D96).
LIVE = {'repos': {'dev-lab': '/opt/dev-lab'}}
#: The derived bridge interpreter per declared os: the checkout's ``.venv`` pointer, never resolved.
BRIDGE = {'ws': '/opt/dev-lab/.venv/Scripts/python.exe', 'stranger': '/opt/dev-lab/.venv/bin/python'}


def _clone(tmp_path: Path, family: str = FAMILY) -> Path:
    clone = tmp_path / 'config-source'
    (clone / 'hosts').mkdir(parents=True)
    (clone / 'family.toml').write_text(family, encoding='utf-8')
    (clone / 'hosts' / 'ws.toml').write_text(HOST, encoding='utf-8')
    return clone


def test_an_unknown_hostname_renders_the_default_stamped_unmanaged(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    rendered = tomllib.loads(devrender.render(clone, 'stranger', LIVE))
    assert rendered['devhost']['unmanaged'] == 'stranger'
    assert rendered['devhost']['hooks'] == 'warn'
    assert rendered['hpc']['reach'] == [], 'the default reaches no HPC role'
    assert 'capabilities' not in rendered, 'the default holds no vendor seat'
    dev = devdeclared.declared(clone / 'hosts' / 'stranger.toml', clone / 'family.toml')
    assert dev['forges'] == {}, "the default REPLACES the family's forges: no write account"


def test_a_declared_host_is_unaffected(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    rendered = tomllib.loads(devrender.render(clone, 'ws', LIVE))
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
        hpc = tomllib.loads(devrender.render(clone, host, LIVE))['bridge']['hpc']
        assert hpc['command'] == [BRIDGE[host], *devprofile.HPC_READ_DOOR]
        assert hpc['cadence_hours'] == 6


def test_the_bridge_interpreter_is_derived_from_the_dev_lab_checkout_never_the_renderers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#782, D96: two renders from different interpreters agree byte for byte; no checkout is refused by name.

    PLANTED CONTROL: the same family and host with no ``[repos] dev-lab`` is refused, naming the local door.
    """
    clone = _clone(tmp_path)
    renders = []
    for caller in ('/wt/a/.venvs/x/python', '/wt/b/.venv/python'):
        monkeypatch.setattr(devprofile, 'running_interpreter', lambda caller=caller: caller)
        renders.append(devrender.render(clone, 'ws', LIVE))
    assert renders[0] == renders[1]
    with pytest.raises(ValueError, match=r'local set repos\.dev-lab'):
        devrender.render(clone, 'ws', {})


def test_drift_names_an_unrenderable_machine_file_never_crashes(tmp_path: Path) -> None:
    """2026-11-20: ``devhost drift`` crashed on the bridge interpreter's refusal; it is one line naming the door.

    PLANTED CONTROL: the same machine with its dev-lab checkout set drifts on no render line.
    """
    clone = _clone(tmp_path)
    own = {'devhost': {'host': 'ws', 'source': str(clone)}}
    found = devhost.drift(own)
    assert found[0].startswith('the machine file cannot be rendered:'), found
    assert 'local set repos.dev-lab' in found[0]
    healed = devhost.drift({**own, **LIVE})
    assert not any('cannot be rendered' in line for line in healed), healed


def test_without_a_declared_default_an_unknown_host_is_refused_by_name(tmp_path: Path) -> None:
    clone = _clone(tmp_path, FAMILY.replace('[dev.default]\nforges = {}\nhpc = []\nhooks = "warn"\n', ''))
    with pytest.raises(LookupError, match=r'\[dev.default\]'):
        devrender.render(clone, 'stranger', LIVE)


def test_the_unmanaged_machine_is_refused_write_and_hpc_naming_the_enrolment_door(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    live = tomllib.loads(devrender.render(_clone(tmp_path), 'stranger', LIVE))
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


def test_local_set_heals_the_missing_checkout_the_bridge_refusal_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Measured 2026-11-20: a refusal's door refused itself; the door it names now sets the key it names.

    PLANTED CONTROL: render with the checkout still unset is refused by name and writes nothing.
    """
    clone = _clone(tmp_path)
    rendered = tomllib.loads(devrender.render(clone, 'ws', LIVE))
    rendered.pop('repos')
    rendered.pop('bridge')
    machine = tmp_path / 'machine.toml'
    machine.write_text(dumps(rendered), encoding='utf-8')
    before = machine.read_text(encoding='utf-8')
    backups = str(tmp_path / 'b')
    code = devhost.main(['--machine', str(machine), 'render', '--write', '--backups', backups])
    assert code == 2, 'a render missing the local checkout is refused, never a traceback'
    assert 'local set repos.dev-lab' in capsys.readouterr().err
    assert machine.read_text(encoding='utf-8') == before, 'a refused render writes nothing'
    checkout = (tmp_path / 'dev-lab').as_posix()
    code = devhost.main(['--machine', str(machine), 'local', 'set', 'repos.dev-lab', checkout, '--backups', backups])
    assert code == 0, 'the door the refusal names sets the key it names'
    healed = tomllib.loads(machine.read_text(encoding='utf-8'))
    assert healed['bridge']['hpc']['command'][0] == f'{checkout}/.venv/Scripts/python.exe'


def test_the_render_never_copies_a_family_only_storage_fact(tmp_path: Path) -> None:
    """The render never copies the family's [storage] remotes; it names the [family] source the reader uses.

    Measured 2026-11-20: the copy was refused by the storage reader ("a family fact"), so every pre-push failed.

    PLANTED CONTROL: the same remotes in a machine file are refused by the reader.
    """
    family_text = FAMILY + (
        '\n[storage.remotes.store-x]\ntype = "s3"\nendpoint = "https://store.example"\n'
        'secret_keys = ["secret_access_key"]\n'
    )
    host_text = HOST + '\n[storage.reach.store-x]\ncredentials_file = "/secrets/store-x"\n'
    clone = _clone(tmp_path, family_text)
    (clone / 'hosts' / 'ws.toml').write_text(host_text, encoding='utf-8')
    rendered = tomllib.loads(devrender.render(clone, 'ws', LIVE))
    assert 'remotes' not in rendered.get('storage', {}), 'a family-only fact stays in the family file'
    assert rendered['storage']['reach'] == {'store-x': {'credentials_file': '/secrets/store-x'}}
    family = tomllib.loads(family_text)
    assert rendered['family'] == {'source': clone.resolve().as_posix()}
    assert [remote.name for remote in storage.declared(rendered, family).reach] == ['store-x']
    with pytest.raises(StorageError, match='family fact'):
        storage.declared(
            {**rendered, 'storage': {**rendered['storage'], 'remotes': family['storage']['remotes']}}, family
        )


def test_the_render_restates_no_family_leaf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With [family] source declared, the machine file holds no leaf the family file holds (one rule, every table).

    Measured 2026-11-20: after [storage] remotes, the render still copied [breakglass] endpoint and the reader
    refused it ("restates a key the family layer holds"). An older render's copy in the live file is dropped too.

    PLANTED CONTROL: the reader's own restatement check refuses the old copy the render no longer writes.
    """
    family_text = FAMILY + '\n[breakglass]\nendpoint = "bg@forge.example"\n'
    clone = _clone(tmp_path, family_text)
    stale = {**LIVE, 'breakglass': {'endpoint': 'bg@forge.example'}}
    rendered = tomllib.loads(devrender.render(clone, 'ws', stale))
    family = {k: v for k, v in tomllib.loads(family_text).items() if k != 'dev'}
    restated = sorted(set(tomlleaves.leaves(rendered)) & set(tomlleaves.leaves(family)))
    assert restated == [], f'the render restates family leaves {restated}'
    assert rendered['family'] == {'source': clone.resolve().as_posix()}
    monkeypatch.setattr(machineconfig, 'family', lambda: family)
    monkeypatch.setattr(machineconfig, 'machine', lambda: rendered)
    assert machineconfig.section('breakglass') == family['breakglass'], 'the reader takes it from the family file'
    monkeypatch.setattr(machineconfig, 'machine', lambda: stale)
    with pytest.raises(ValueError, match='restates a key the family layer holds'):
        machineconfig.section('breakglass')


def test_a_host_value_for_a_family_leaf_is_refused_by_name(tmp_path: Path) -> None:
    """A host giving a family leaf another value is refused at render, naming the family file -- never silently lost."""
    clone = _clone(tmp_path, FAMILY + '\n[breakglass]\nendpoint = "bg@forge.example"\n')
    (clone / 'hosts' / 'ws.toml').write_text(
        HOST + '\n[breakglass]\nendpoint = "other@forge.example"\n', encoding='utf-8'
    )
    with pytest.raises(ValueError, match=r'\[breakglass\]\.endpoint.*family file'):
        devrender.render(clone, 'ws', LIVE)
