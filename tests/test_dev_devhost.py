"""A development machine is declared in its host file; its machine file is the render; drift is reported."""

from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
from _arch_corpus import module_names
from _ops_fixtures import git

from dev_lab.dev import devdeclared, devhost, devschema, devsource, opsserver, vendordetect, venvfollow
from dev_lab.dev.agent_wiring import WIRING
from dev_lab.ops.configcheck import check_family, check_host

FAMILY = """\
[dev]
ref = "integrate/main"
forges = { "forge.example" = ["dev-user"] }
helpers = { "forge.example" = "store" }

[consent]
endpoint = "consent@forge.example"

[hpc]
session_reach = { lead = ["verification"] }

[hpc.clusters.c]
hosts = ["login.example"]
slurm_accounts = { a = { billed = false } }

[[hpc.grant]]
user = "u1"
cluster = "c"
slurm_account = "a"
role = "research"
"""

HOST = """\
[dev]
hpc = ["research"]
os = "windows"

[dev.resources]
cpu = "cpu-x"
cores = 16
logical_cores = 24
memory_gb = 64
gpu = "gpu-x"

[dev.vendors.solverx]
seats = 4
version = "1.0"
home = "C:/Program Files/SolverX"

[capabilities.solverx]
in_use = { process = ["solverx.exe"] }
"""

LOCAL = """\
[user]
text_editor_command = "edit"

[repos]
dev-lab = "C:/src/dev-lab"
"""


def _write(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


def _clone(tmp_path: Path, host: str = HOST) -> Path:
    clone = tmp_path / 'config-source'
    _write(clone, 'family.toml', FAMILY)
    _write(clone, 'hosts/ws.toml', host)
    return clone


def test_a_dev_host_file_passes_with_its_family(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    assert check_host(clone / 'hosts/ws.toml', clone / 'family.toml') == []
    assert check_family(clone / 'family.toml') == []


@pytest.mark.parametrize(
    ('host', 'named'),
    [
        (HOST.replace('cores = 16', 'cores = 16\nbogus = 1'), 'bogus'),
        (HOST.replace('hpc = ["research"]', 'role = "integrator"'), 'role is retired'),
        (HOST.replace('hpc = ["research"]', 'hpc = "research"'), 'hpc must list'),
        (HOST.replace('cores = 16', 'cores = "16"'), 'resources.cores'),
        (HOST.replace('version = "1.0"', 'license = "x"'), 'license'),
        (HOST.replace('[dev]\n', '[dev]\nref = "main"\n', 1), 'restates'),
        (HOST + '\n[consent]\nendpoint = "consent@elsewhere"\n', 'consent.endpoint restates'),
        (HOST + '\n[bogus_table]\nx = 1\n', 'bogus_table'),
    ],
)
def test_a_dev_host_defect_is_refused_by_name(tmp_path: Path, host: str, named: str) -> None:
    clone = _clone(tmp_path, host)
    found = check_host(clone / 'hosts/ws.toml', clone / 'family.toml')
    assert [line for line in found if named in line], found


def test_a_host_forge_login_equal_to_the_family_one_is_refused(tmp_path: Path) -> None:
    """The family declares the workstation login once; a host copying it is a second source (planted control)."""
    host = HOST.replace('os = "windows"', 'os = "windows"\nforges = { "forge.example" = ["dev-user"] }')
    clone = _clone(tmp_path, host)
    found = check_host(clone / 'hosts/ws.toml', clone / 'family.toml')
    assert [line for line in found if 'forges' in line and 'restates' in line], found


def test_a_host_forge_login_that_differs_overrides_the_family_one(tmp_path: Path) -> None:
    """Another person's machine names its own login: an override, not a restatement."""
    host = HOST.replace('os = "windows"', 'os = "windows"\nforges = { "forge.example" = ["other-user"] }')
    clone = _clone(tmp_path, host)
    assert check_host(clone / 'hosts/ws.toml', clone / 'family.toml') == []
    assert devhost.declared(clone / 'hosts/ws.toml', clone / 'family.toml')['forges'] == {
        'forge.example': ['other-user'],
    }


def test_a_host_without_forges_inherits_the_family_login(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    assert devhost.declared(clone / 'hosts/ws.toml', clone / 'family.toml')['forges'] == {
        'forge.example': ['dev-user'],
    }


def test_a_differing_host_value_of_a_non_overridable_key_still_restates(tmp_path: Path) -> None:
    clone = _clone(tmp_path, HOST.replace('os = "windows"', 'os = "windows"\nref = "main"'))
    found = check_host(clone / 'hosts/ws.toml', clone / 'family.toml')
    assert [line for line in found if 'ref restates' in line], found


def test_a_server_file_may_not_carry_a_machine_table(tmp_path: Path) -> None:
    server = _write(tmp_path, 's.toml', '[ops]\nhome = "/h"\npython = "/p"\n\n[capabilities.x]\nseats = 1\n')
    assert any('capabilities' in line for line in check_host(server))


def test_without_the_family_the_shared_ref_is_missing(tmp_path: Path) -> None:
    found = check_host(_write(tmp_path, 'ws.toml', HOST))
    assert any('ref is required' in line for line in found)


def test_a_family_dev_key_outside_the_schema_is_refused(tmp_path: Path) -> None:
    found = check_family(_write(tmp_path, 'family.toml', FAMILY.replace('[dev]\n', '[dev]\nrefs = "x"\n')))
    assert any('refs' in line for line in found)


def test_the_render_layers_family_host_and_local_and_drops_dev(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    text = devhost.render(clone, 'ws', tomllib.loads(LOCAL))
    assert text.startswith('# RENDERED')
    assert 'consent' not in tomllib.loads(text), 'a family table stays in the family file'
    rendered = devdeclared.layered(tomllib.loads(text))  # the whole machine a reader sees
    assert rendered['consent'] == {'endpoint': 'consent@forge.example'}
    assert rendered['hpc']['grant'] == [{'user': 'u1', 'cluster': 'c', 'slurm_account': 'a', 'role': 'research'}]
    assert rendered['hpc']['reach'] == ['research'], "the host's [dev] hpc renders as the machine's reach"
    assert rendered['hpc']['session_reach'] == {'lead': ['verification']}, 'the family keeps the session rule'
    assert rendered['capabilities'] == {'solverx': {'in_use': {'process': ['solverx.exe']}, 'seats': 4}}
    assert rendered['user'] == {'text_editor_command': 'edit'}
    assert rendered['devhost'] == {'host': 'ws', 'source': clone.as_posix()}
    assert 'dev' not in rendered


def test_a_declared_table_replaces_the_live_copy(tmp_path: Path) -> None:
    live = tomllib.loads(LOCAL + '\n[consent]\nendpoint = "consent@stale"\n')
    rendered = tomllib.loads(devhost.render(_clone(tmp_path), 'ws', live))
    assert 'consent' not in rendered, 'the stale local copy of a family table is dropped, not kept'
    assert devdeclared.layered(rendered)['consent'] == {'endpoint': 'consent@forge.example'}


@pytest.fixture(autouse=True)
def _credentials_agree(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real git store and helpers are not the fixture's: credential drift is tested on its own."""
    monkeypatch.setattr(devhost.forgecredential, 'drift', lambda _dev: [])


def _rendered_machine(tmp_path: Path) -> dict:
    return tomllib.loads(devhost.render(_clone(tmp_path), 'ws', tomllib.loads(LOCAL)))


def test_a_fresh_render_has_no_drift_and_an_unrendered_file_is_silent(tmp_path: Path) -> None:
    assert devhost.drift(_rendered_machine(tmp_path)) == []
    assert devhost.drift(tomllib.loads(LOCAL)) == []
    assert devhost.notice(tomllib.loads(LOCAL)) is None


def test_a_hand_edit_is_drift_named_by_key_and_its_owning_layer(tmp_path: Path) -> None:
    live = _rendered_machine(tmp_path)
    live['consent'] = {'endpoint': 'consent@elsewhere'}
    del live['capabilities']
    live['hpc']['reach'] = ['verification']
    edit = f'change it there through its pull request, then {devhost.RENDER_DOOR}'
    assert devhost.drift(live) == [
        f'[capabilities].solverx.in_use.process is absent -- host layer (hosts/ws.toml): {edit}',
        f'[capabilities].solverx.seats is absent -- host layer (hosts/ws.toml [dev], rendered): {edit}',
        f'[consent].endpoint is not the render -- family layer (family.toml): {edit}',
        f'[hpc].reach is not the render -- host layer (hosts/ws.toml [dev], rendered): {edit}',
    ]
    line = devhost.notice(live)
    assert line is not None
    assert devhost.RENDER_DOOR in line


def test_a_family_repo_without_a_path_is_drift_with_its_door(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    family = (clone / 'family.toml').read_text(encoding='utf-8')
    (clone / 'family.toml').write_text(
        family + '\n[family_repos]\ndev-lab = { remote = "https://forge.example/o/dev-lab.git", branch = "main" }\n'
        'other = { remote = "https://forge.example/o/other.git", branch = "main" }\n',
        encoding='utf-8',
    )
    live = tomllib.loads(devhost.render(clone, 'ws', tomllib.loads(LOCAL)))
    found = devhost.drift(live)
    assert len(found) == 1, found
    assert found[0].startswith('family repo other has no [repos] path')


def test_the_local_door_refuses_a_rendered_table(tmp_path: Path) -> None:
    live = _rendered_machine(tmp_path)
    with pytest.raises(ValueError, match=r'\[consent\] is rendered from the config source'):
        devhost.local_set(live, 'consent.endpoint', 'x')
    assert devhost.local_set(live, 'user.text_editor_command', 'vi')['user'] == {'text_editor_command': 'vi'}


def test_the_local_door_re_renders_a_rendered_machine_file(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    machine = _write(tmp_path, 'machine/m.toml', devhost.render(clone, 'ws', tomllib.loads(LOCAL)))
    other = (tmp_path / 'other').as_posix()
    argv = ['--machine', str(machine), 'local', 'set', 'repos.other', other, '--backups', str(tmp_path / 'b')]
    assert devhost.main(argv) == 0
    live = tomllib.loads(machine.read_text(encoding='utf-8'))
    assert live['repos'] == {'dev-lab': 'C:/src/dev-lab', 'other': other}
    assert devhost.drift(live) == []


def test_a_dev_lab_checkout_off_the_declared_ref_is_drift(tmp_path: Path) -> None:
    kit = tmp_path / 'kit'
    subprocess.run([shutil.which('git') or 'git', 'init', '-q', '-b', 'feature', str(kit)], check=True)
    live = _rendered_machine(tmp_path)
    live['repos'] = {'dev-lab': str(kit)}
    assert devhost.drift(live) == ["the dev-lab checkout is on 'feature', declared ref 'integrate/main'"]


def test_a_stale_source_path_is_one_drift_line_and_from_names_the_clone(tmp_path: Path) -> None:
    live = _rendered_machine(tmp_path)
    clone = Path(live[devdeclared.OWN_TABLE]['source'])
    live[devdeclared.OWN_TABLE]['source'] = (tmp_path / 'another-machine').as_posix()
    (stale,) = devhost.drift(live)
    assert 'is not a clone here' in stale
    assert '--from' in stale
    compared = devhost.drift(live, clone)  # the control: --from renders, so it compares key by key
    assert any(line.startswith('[devhost].source is not the render') for line in compared), compared
    machine = _write(tmp_path, 'machine/m.toml', devhost.dumps(live))
    assert devhost.main(['--machine', str(machine), 'drift', '--from', str(clone)]) == 1


def test_drift_writes_nothing_and_render_write_backs_up_first(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    machine = _write(tmp_path, 'machine/m.toml', LOCAL)
    before = machine.read_bytes()
    assert devhost.main(['--machine', str(machine), 'drift']) == 0
    assert machine.read_bytes() == before
    backups = tmp_path / 'backups'
    argv = ['--machine', str(machine), 'render', '--host', 'ws', '--from', str(clone), '--write', '--backups']
    assert devhost.main([*argv, str(backups)]) == 0
    assert [p.read_bytes() for p in backups.iterdir()] == [before]
    assert devhost.main(['--machine', str(machine), 'drift']) == 0
    assert sorted(p.name for p in machine.parent.iterdir()) == ['m.toml']


def test_a_shared_box_offers_its_allotment_never_its_total() -> None:
    whole = {'resources': {'cores': 20, 'memory_gb': 160}}
    assert devschema.usable(whole) == (20, 160)
    shared = {'resources': {**whole['resources'], 'shared': True}}
    assert devschema.usable(shared) == (None, None)
    allotted = {'resources': {**shared['resources'], 'allotted_cores': 8, 'allotted_memory_gb': 48}}
    assert devschema.usable(allotted) == (8, 48)


def test_a_resources_type_defect_is_refused(tmp_path: Path) -> None:
    clone = _clone(tmp_path, HOST.replace('gpu = "gpu-x"', 'gpu = "gpu-x"\nshared = "yes"'))
    assert any('resources.shared' in line for line in check_host(clone / 'hosts/ws.toml', clone / 'family.toml'))


def test_a_vendor_with_seats_and_no_home_is_named_with_the_detect_door(tmp_path: Path) -> None:
    clone = _clone(tmp_path, HOST.replace('home = "C:/Program Files/SolverX"\n', ''))
    live = tomllib.loads(devhost.render(clone, 'ws', tomllib.loads(LOCAL)))
    assert devhost.drift(live) == [devschema.fill_remedy(['solverx'])]
    line = devhost.notice(live)
    assert line is not None
    assert line.startswith('HOST-CONFIG FIRST:')
    assert devschema.DETECT_DOOR in line


def _unfilled_machine(tmp_path: Path) -> dict:
    clone = _clone(tmp_path, HOST.replace('"C:/Program Files/SolverX"', f'"{devschema.UNFILLED}"'))
    return tomllib.loads(devhost.render(clone, 'ws', tomllib.loads(LOCAL)))


def test_the_placeholder_passes_configcheck_and_is_named_by_render_and_drift(tmp_path: Path) -> None:
    clone = _clone(tmp_path, HOST.replace('"C:/Program Files/SolverX"', f'"{devschema.UNFILLED}"'))
    assert check_host(clone / 'hosts/ws.toml', clone / 'family.toml') == []
    assert devhost.drift(_unfilled_machine(tmp_path))[0] == devschema.fill_remedy(['solverx'])


def test_the_session_start_verb_says_the_unfilled_home_and_a_render_says_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The notice the Stop hook once blocked on is said at session start, as context, never a block."""
    unfilled, rendered = tmp_path / 'unfilled.toml', tmp_path / 'rendered.toml'
    clone = _clone(tmp_path, HOST.replace('"C:/Program Files/SolverX"', f'"{devschema.UNFILLED}"'))
    unfilled.write_text(devhost.render(clone, 'ws', tomllib.loads(LOCAL)), encoding='utf-8')
    assert devhost.main(['--machine', str(unfilled), 'session-start']) == 0
    said = capsys.readouterr().out
    assert devschema.DETECT_DOOR in said
    assert 'decision' not in said, 'a notice, never a block'
    rendered.write_text(devhost.render(_clone(tmp_path / 'b'), 'ws', tomllib.loads(LOCAL)), encoding='utf-8')
    assert devhost.main(['--machine', str(rendered), 'session-start']) == 0
    assert capsys.readouterr().out == '', 'PLANTED CONTROL: a machine file that is its render says nothing'


def test_the_machine_notice_has_one_trigger_once_per_session() -> None:
    """Drift cannot change within a turn: one SessionStart row, once; no Stop row, and venvfollow no longer says it."""
    rows = [w for w in WIRING if w.module == 'dev_lab.dev.devhost']
    assert [(w.events, w.argv, w.once, w.may_block) for w in rows] == [
        (('SessionStart',), ('session-start',), True, False)
    ]
    assert not any('Stop' in w.events for w in rows), 'PLANTED CONTROL: the Stop row is gone'
    assert 'devhost' not in module_names(venvfollow), 'the notice is said by its own row alone'


def test_a_path_needing_an_unfilled_home_refuses_with_the_remedy() -> None:
    with pytest.raises(devschema.HomeUnfilled, match='detect'):
        devschema.home_of({'vendors': {'solverx': {'seats': 1, 'home': devschema.UNFILLED}}}, 'solverx')
    with pytest.raises(devschema.HomeUnfilled):
        devschema.home_of({'vendors': {'solverx': {'seats': 1}}}, 'solverx')
    assert devschema.home_of({'vendors': {'solverx': {'home': 'C:/x'}}}, 'solverx') == Path('C:/x')


def test_a_session_fair_box_is_sized_live_and_its_share_is_a_declared_enum(tmp_path: Path) -> None:
    fair = {'resources': {'logical_cores': 20, 'memory_gb': 160, 'shared': True, 'cpu_share': 'session-fair'}}
    assert devschema.usable(fair) == (None, None)
    clone = _clone(tmp_path, HOST.replace('gpu = "gpu-x"', 'gpu = "gpu-x"\nshared = true\ncpu_share = "even"'))
    assert any('cpu_share' in line for line in check_host(clone / 'hosts/ws.toml', clone / 'family.toml'))


def test_detect_finds_the_newest_matching_home_and_nothing_else(tmp_path: Path) -> None:
    for name in ('SolverX-24.1', 'SolverX-25.2', 'Other'):
        (tmp_path / name).mkdir()
    (tmp_path / 'SolverX-99.notadir').write_text('', encoding='utf-8')
    patterns = {'solverx': [f'{tmp_path.as_posix()}/SolverX-*'], 'absent': [f'{tmp_path.as_posix()}/Nope*']}
    assert vendordetect.detect(patterns) == {'solverx': (tmp_path / 'SolverX-25.2').as_posix()}


def test_a_detect_entry_that_is_not_a_pattern_list_is_refused(tmp_path: Path) -> None:
    family = FAMILY.replace('[dev]\n', '[dev]\ndetect = { solverx = "C:/x" }\n')
    assert any('detect.solverx' in line for line in check_family(_write(tmp_path, 'family.toml', family)))


def test_a_host_declaring_no_hpc_renders_a_reach_of_none(tmp_path: Path) -> None:
    """PLANTED CONTROL for the reach render: a host with no [dev] hpc reaches nothing, never the family's accounts."""
    rendered = tomllib.loads(
        devhost.render(_clone(tmp_path, HOST.replace('hpc = ["research"]\n', '')), 'ws', tomllib.loads(LOCAL))
    )
    assert rendered['hpc']['reach'] == []


DATED = """\
[hpc.clusters.d.slurm_accounts.b.budget]
since = 2026-09-01
checked = 2026-11-12T08:30:00Z
local = 2026-11-12T08:30:00
at = 08:30:00
"""


def test_toml_dates_round_trip_through_the_render(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    _write(clone, 'family.toml', FAMILY + '\n' + DATED)
    rendered = devdeclared.layered(tomllib.loads(devhost.render(clone, 'ws', tomllib.loads(LOCAL))))
    budget = rendered['hpc']['clusters']['d']['slurm_accounts']['b']['budget']
    assert budget == tomllib.loads(DATED)['hpc']['clusters']['d']['slurm_accounts']['b']['budget']


def test_render_write_refuses_a_render_that_does_not_parse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clone = _clone(tmp_path)
    machine = _write(tmp_path, 'machine/m.toml', LOCAL)
    before = machine.read_bytes()
    monkeypatch.setattr(devhost, 'render', lambda *_: 'since = datetime.date(2026, 9, 1)\n')
    argv = ['--machine', str(machine), 'render', '--host', 'ws', '--from', str(clone), '--write', '--backups']
    assert devhost.main([*argv, str(tmp_path / 'backups')]) == 2
    assert machine.read_bytes() == before
    assert not (tmp_path / 'backups').exists()


CHANNELS = HOST.replace('os = "windows"\n', 'os = "windows"\nchannels = { "bridge-x" = "user-x" }\n')


def test_declared_channels_render_as_the_agent_table_and_read_back(tmp_path: Path) -> None:
    clone = _clone(tmp_path, CHANNELS)
    assert check_host(clone / 'hosts/ws.toml', clone / 'family.toml') == []
    rendered = tomllib.loads(devhost.render(clone, 'ws', tomllib.loads(LOCAL)))
    assert rendered['agent'] == {'channels': {'bridge-x': 'user-x'}}
    assert devschema.declared_channels(rendered) == {'bridge-x': 'user-x'}
    assert devhost.drift(rendered) == []


def test_a_machine_declaring_no_channel_grants_none(tmp_path: Path) -> None:
    rendered = _rendered_machine(tmp_path)
    assert 'agent' not in rendered, 'no declaration renders no table, never an empty grant'
    assert devschema.declared_channels(rendered) == {}
    assert devschema.declared_channels(tomllib.loads(LOCAL)) == {}


@pytest.mark.parametrize(
    'channels',
    [
        '"bridge-x"',
        '{ "bridge-x" = 1 }',
        '{ "bridge-x" = ["user-x"] }',
        '{ "bridge-x" = "" }',
        '{ "" = "user-x" }',
        '{ "bridge-x" = { user = "user-x" } }',
    ],
)
def test_a_channel_declaration_that_is_not_source_to_user_strings_is_refused(tmp_path: Path, channels: str) -> None:
    clone = _clone(tmp_path, HOST.replace('os = "windows"\n', f'os = "windows"\nchannels = {channels}\n'))
    found = check_host(clone / 'hosts/ws.toml', clone / 'family.toml')
    assert [line for line in found if 'channels' in line], found
    live = {'agent': {'channels': tomllib.loads(f'c = {channels}')['c']}}
    with pytest.raises(ValueError, match='channels'):
        devschema.declared_channels(live)


def test_channels_are_one_machine_fact_never_the_family(tmp_path: Path) -> None:
    family = FAMILY.replace('[dev]\n', '[dev]\nchannels = { "b" = "u" }\n')
    found = check_family(_write(tmp_path, 'family.toml', family))
    assert any('channels' in line for line in found), found


def test_the_channels_verb_prints_the_declaration_as_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    machine = tmp_path / 'machine.toml'
    machine.write_text(LOCAL + '\n[agent]\nchannels = { "bridge-x" = "123456" }\n', encoding='utf-8')
    assert devhost.main(['--machine', str(machine), 'channels', '--json']) == 0
    assert json.loads(capsys.readouterr().out) == {'bridge-x': '123456'}


def test_the_channels_verb_prints_an_empty_object_when_nothing_is_declared(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    machine = tmp_path / 'machine.toml'
    machine.write_text(LOCAL, encoding='utf-8')
    assert devhost.main(['--machine', str(machine), 'channels', '--json']) == 0
    assert json.loads(capsys.readouterr().out) == {}
    assert devhost.main(['--machine', str(tmp_path / 'absent.toml'), 'channels', '--json']) == 0
    assert json.loads(capsys.readouterr().out) == {}


def test_the_channels_verb_refuses_a_malformed_declaration(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    machine = tmp_path / 'machine.toml'
    machine.write_text(LOCAL + '\n[agent]\nchannels = { "bridge-x" = 1 }\n', encoding='utf-8')
    assert devhost.main(['--machine', str(machine), 'channels', '--json']) == 2
    captured = capsys.readouterr()
    assert captured.out == ''
    assert 'channels' in captured.err


def test_a_relative_from_renders_an_absolute_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """#556: ``--from .`` once rendered ``source = "."``, so the config source followed whatever the CWD was."""
    clone = _clone(tmp_path)
    monkeypatch.chdir(clone.parent)
    rendered = tomllib.loads(devhost.render(Path(clone.name), 'ws', tomllib.loads(LOCAL)))
    assert rendered['devhost']['source'] == clone.resolve().as_posix()


def test_the_config_source_refuses_a_relative_clone_and_names_the_door(tmp_path: Path) -> None:
    """#556: a relative ``[devhost] source`` resolves against the CWD; it is refused, never read from another clone."""
    with pytest.raises(ValueError, match=r'relative.*devhost render --host G --from <absolute clone> --write'):
        devsource.config_source({'devhost': {'host': 'G', 'source': '.'}})
    # the control: an absolute clone with an origin is its origin
    clone = _clone(tmp_path)
    git(tmp_path, 'init', '-q', str(clone))
    git(clone, 'remote', 'add', 'origin', 'https://forge.example/t/hc.git')
    assert (
        devsource.config_source({'devhost': {'host': 'G', 'source': clone.as_posix()}})
        == 'https://forge.example/t/hc.git'
    )


# An HPC ACCOUNT is the third host kind (user ruling 2026-11-15): `hosts/<cluster>-<user>.toml` holds only what is
# true of that account alone; its grant (role, slurm account) and its cluster stay in the family file.
ACCOUNT = """\
[deploy]
host = "login01"
root = "/scratch/u1"
python = "3.13"
repos = [{ name = "dev-lab", url = "https://forge.example/o/dev-lab.git", ref = "integrate/main" }]

[hpc.paging]
page_cpus = 8
page_mem_gb = 20

[capabilities.solverx]
"""


def _account(tmp_path: Path, text: str = ACCOUNT, name: str = 'c-u1') -> Path:
    clone = _clone(tmp_path)
    _write(clone, f'hosts/{name}.toml', text)
    return clone


def test_an_account_file_passes_and_renders_its_grant_role(tmp_path: Path) -> None:
    clone = _account(tmp_path)
    assert check_host(clone / 'hosts/c-u1.toml', clone / 'family.toml') == []
    rendered = devdeclared.layered(tomllib.loads(devhost.render(clone, 'c-u1', {})))
    assert rendered['deploy']['role'] == 'research', 'the role is the family grant, derived, never restated'
    assert rendered['hpc']['reach'] == ['research'], 'an account reaches its own grant: its role, derived'
    assert rendered['hpc']['paging'] == {'page_cpus': 8, 'page_mem_gb': 20}
    assert rendered['hpc']['grant'][0]['user'] == 'u1', 'the family grants ride along unchanged'


@pytest.mark.parametrize(
    ('name', 'text', 'named'),
    [
        ('c-u9', ACCOUNT, 'no family grant'),
        ('c-u1', ACCOUNT.replace('root = "/scratch/u1"', 'root = "/scratch/u1"\nrole = "research"'), 'deploy.role'),
        ('c-u1', ACCOUNT + '\n[[hpc.grant]]\nuser = "u1"\n', 'hpc.grant'),
        ('c-u1', ACCOUNT + '\n[consent]\nendpoint = "consent@forge.example"\n', 'restates'),
        ('c-u1', ACCOUNT + '\n[bogus]\nx = 1\n', 'bogus'),
        ('c-u1', ACCOUNT + '\n[schedule]\ntick_minutes = 15\n', '[schedule] on a research account'),
        ('c-u1', ACCOUNT.replace('repos = [', 'repo = ['), 'deploy'),
    ],
)
def test_an_account_file_defect_is_refused_by_name(tmp_path: Path, name: str, text: str, named: str) -> None:
    clone = _account(tmp_path, text, name)
    found = check_host(clone / f'hosts/{name}.toml', clone / 'family.toml')
    assert any(named in line for line in found), found


def test_forge_credential_drift_is_part_of_drift_with_the_declared_dev(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict] = []
    monkeypatch.setattr(devhost.forgecredential, 'drift', lambda dev: seen.append(dev) or ['forge x: missing'])
    assert devhost.drift(_rendered_machine(tmp_path)) == ['forge x: missing']
    assert seen[0]['forges'] == {'forge.example': ['dev-user']}


def test_use_store_applies_only_for_a_host_declaring_the_store_helper(tmp_path: Path) -> None:
    dev = devdeclared.declared_by(_rendered_machine(tmp_path)['devhost'])
    applied: list[str] = []
    store = tmp_path / '.git-credentials'
    store.write_text('https://dev-user:x@forge.example\n', encoding='utf-8')
    assert devhost.forgecredential.use_declared(dev, 'not.declared', applied.append, store) == 2
    assert applied == []
    assert devhost.forgecredential.use_declared(dev, 'forge.example', applied.append, store) == 0
    assert applied == ['forge.example']


def test_use_store_refuses_by_name_while_the_store_lacks_a_declared_login(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """PLANTED CONTROL: an empty store read alone cuts the host off the forge (2026-11-21), so the door refuses."""
    dev = devdeclared.declared_by(_rendered_machine(tmp_path)['devhost'])
    applied: list[str] = []
    assert devhost.forgecredential.use_declared(dev, 'forge.example', applied.append, tmp_path / 'absent') == 2
    assert applied == []
    said = capsys.readouterr()
    assert 'dev_lab.dev.devcredential --login dev-user' in said.out + said.err


# THE SERVERS ARE A RENDER (user ruling 2026-11-25): every registered workstation operates the family servers. The
# family names each server and its address once; the login and status card come from the server's own host card.
SERVER_CARD = """\
[target]
name = "box"

[ops]
home = "/var/lib/clones"
python = "/opt/dev-lab/.venv/bin/python"
repos = []

[ops.access]
account = "ops"

[ops.status]
file = "/var/lib/dev-lab/status.json"
site = "forge.example"
"""


def _served(tmp_path: Path) -> Path:
    clone = _clone(tmp_path)
    family = FAMILY.replace(
        'ref = "integrate/main"\n', 'ref = "integrate/main"\nservers = { box = { address = "198.51.100.7" } }\n'
    )
    _write(clone, 'family.toml', family)
    _write(clone, 'hosts/box.toml', SERVER_CARD)
    _write(clone, 'hosts/c-u1.toml', ACCOUNT)
    return clone


def test_a_workstation_renders_every_family_server_derived_from_its_card(tmp_path: Path) -> None:
    rendered = tomllib.loads(devhost.render(_served(tmp_path), 'ws', tomllib.loads(LOCAL)))
    assert rendered['server'] == [
        {'name': 'box', 'target': 'ops@198.51.100.7', 'status': 'https://forge.example/dev-lab/status.json'},
    ]
    assert set(opsserver.declared_servers(rendered)) == {'box'}, 'the ops door reads the rendered rows'


def test_an_hpc_account_renders_no_server(tmp_path: Path) -> None:
    rendered = tomllib.loads(devhost.render(_served(tmp_path), 'c-u1', {}))
    assert 'server' not in rendered, 'an account is no workstation: it operates no server'


@pytest.mark.usefixtures('_credentials_agree')
def test_a_hand_written_server_that_differs_is_drift_naming_the_family(tmp_path: Path) -> None:
    clone = _served(tmp_path)
    live = tomllib.loads(devhost.render(clone, 'ws', tomllib.loads(LOCAL)))
    assert devhost.drift(live, clone) == [], 'the planted control: the render itself is no drift'
    live['server'] = [{'name': 'box', 'target': 'ops@203.0.113.9'}]
    edit = f'change it there through its pull request, then {devhost.RENDER_DOOR}'
    owner = 'family layer (family.toml [dev] servers, rendered)'
    assert devhost.drift(live, clone) == [f'[server] is not the render -- {owner}: {edit}']


def test_a_server_without_its_host_card_is_refused_by_name(tmp_path: Path) -> None:
    clone = _served(tmp_path)
    (clone / 'hosts/box.toml').unlink()
    with pytest.raises(ValueError, match=r"names 'box', but hosts/box\.toml declares no \[ops\.access\]"):
        devhost.render(clone, 'ws', {})
    assert any("names 'box'" in line for line in check_family(clone / 'family.toml'))


@pytest.mark.parametrize(
    ('servers', 'named'),
    [
        ('{ box = { address = "ops@198.51.100.7" } }', 'bare host'),
        ('{ box = { address = "198.51.100.7", target = "x" } }', 'only'),
    ],
)
def test_a_malformed_server_declaration_is_refused(tmp_path: Path, servers: str, named: str) -> None:
    clone = _served(tmp_path)
    family = FAMILY.replace('ref = "integrate/main"\n', f'ref = "integrate/main"\nservers = {servers}\n')
    _write(clone, 'family.toml', family)
    assert any(named in line for line in check_family(clone / 'family.toml'))


def test_servers_are_a_family_fact_never_a_host_one(tmp_path: Path) -> None:
    clone = _clone(tmp_path, HOST.replace('os = "windows"\n', 'os = "windows"\nservers = {}\n'))
    assert any('servers' in line for line in check_host(clone / 'hosts/ws.toml', clone / 'family.toml'))
