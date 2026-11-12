"""A development machine is declared in its host file; its machine file is the render; drift is reported."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest

from dev_lab.dev import devhost
from dev_lab.ops.configcheck import check_family, check_host

FAMILY = """\
[dev]
ref = "integrate/main"
forges = { "forge.example" = ["dev-user"] }

[consent]
endpoint = "consent@forge.example"

[[hpc.grant]]
user = "u1"
costed = true
hosts = ["login.example"]
"""

HOST = """\
[dev]
role = "workstation"
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

[serve]
parts = "any"
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
        (HOST.replace('"workstation"', '"server"'), 'role'),
        (HOST.replace('cores = 16', 'cores = "16"'), 'resources.cores'),
        (HOST.replace('version = "1.0"', 'licence = "x"'), 'licence'),
        (HOST.replace('[dev]\n', '[dev]\nref = "main"\n', 1), 'restates'),
        (HOST + '\n[consent]\nendpoint = "consent@elsewhere"\n', 'consent.endpoint restates'),
        (HOST + '\n[bogus_table]\nx = 1\n', 'bogus_table'),
    ],
)
def test_a_dev_host_defect_is_refused_by_name(tmp_path: Path, host: str, named: str) -> None:
    clone = _clone(tmp_path, host)
    found = check_host(clone / 'hosts/ws.toml', clone / 'family.toml')
    assert [line for line in found if named in line], found


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
    rendered = tomllib.loads(text)
    assert rendered['consent'] == {'endpoint': 'consent@forge.example'}
    assert rendered['hpc'] == {'grant': [{'user': 'u1', 'costed': True, 'hosts': ['login.example']}]}
    assert rendered['capabilities'] == {'solverx': {'in_use': {'process': ['solverx.exe']}, 'seats': 4}}
    assert rendered['user'] == {'text_editor_command': 'edit'}
    assert rendered['devhost'] == {'host': 'ws', 'source': clone.as_posix()}
    assert 'dev' not in rendered


def test_a_declared_table_replaces_the_live_copy(tmp_path: Path) -> None:
    live = tomllib.loads(LOCAL + '\n[consent]\nendpoint = "consent@stale"\n')
    rendered = tomllib.loads(devhost.render(_clone(tmp_path), 'ws', live))
    assert rendered['consent'] == {'endpoint': 'consent@forge.example'}


def _rendered_machine(tmp_path: Path) -> dict:
    return tomllib.loads(devhost.render(_clone(tmp_path), 'ws', tomllib.loads(LOCAL)))


def test_a_fresh_render_has_no_drift_and_an_unrendered_file_is_silent(tmp_path: Path) -> None:
    assert devhost.drift(_rendered_machine(tmp_path)) == []
    assert devhost.drift(tomllib.loads(LOCAL)) == []
    assert devhost.notice(tomllib.loads(LOCAL)) is None


def test_a_hand_edit_is_drift_named_by_table(tmp_path: Path) -> None:
    live = _rendered_machine(tmp_path)
    live['consent'] = {'endpoint': 'consent@elsewhere'}
    del live['serve']
    assert devhost.drift(live) == ['[consent] is not the render', '[serve] is absent']
    line = devhost.notice(live)
    assert line is not None
    assert devhost.RENDER_DOOR in line


def test_a_dev_lab_checkout_off_the_declared_ref_is_drift(tmp_path: Path) -> None:
    kit = tmp_path / 'kit'
    subprocess.run(['git', 'init', '-q', '-b', 'feature', str(kit)], check=True)  # noqa: S607
    live = _rendered_machine(tmp_path)
    live['repos'] = {'dev-lab': str(kit)}
    assert devhost.drift(live) == ["the dev-lab checkout is on 'feature', declared ref 'integrate/main'"]


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
    assert devhost.usable(whole) == (20, 160)
    shared = {'resources': {**whole['resources'], 'shared': True}}
    assert devhost.usable(shared) == (None, None)
    allotted = {'resources': {**shared['resources'], 'allotted_cores': 8, 'allotted_memory_gb': 48}}
    assert devhost.usable(allotted) == (8, 48)


def test_a_resources_type_defect_is_refused(tmp_path: Path) -> None:
    clone = _clone(tmp_path, HOST.replace('gpu = "gpu-x"', 'gpu = "gpu-x"\nshared = "yes"'))
    assert any('resources.shared' in line for line in check_host(clone / 'hosts/ws.toml', clone / 'family.toml'))


def test_a_vendor_with_seats_and_no_home_is_named_with_the_detect_door(tmp_path: Path) -> None:
    clone = _clone(tmp_path, HOST.replace('home = "C:/Program Files/SolverX"\n', ''))
    live = tomllib.loads(devhost.render(clone, 'ws', tomllib.loads(LOCAL)))
    assert devhost.drift(live) == [f'home not declared for solverx; run {devhost.DETECT_DOOR}']


def test_detect_finds_the_newest_matching_home_and_nothing_else(tmp_path: Path) -> None:
    for name in ('SolverX-24.1', 'SolverX-25.2', 'Other'):
        (tmp_path / name).mkdir()
    (tmp_path / 'SolverX-99.notadir').write_text('', encoding='utf-8')
    patterns = {'solverx': [f'{tmp_path.as_posix()}/SolverX-*'], 'absent': [f'{tmp_path.as_posix()}/Nope*']}
    assert devhost.detect(patterns) == {'solverx': (tmp_path / 'SolverX-25.2').as_posix()}


def test_a_detect_entry_that_is_not_a_pattern_list_is_refused(tmp_path: Path) -> None:
    family = FAMILY.replace('[dev]\n', '[dev]\ndetect = { solverx = "C:/x" }\n')
    assert any('detect.solverx' in line for line in check_family(_write(tmp_path, 'family.toml', family)))
