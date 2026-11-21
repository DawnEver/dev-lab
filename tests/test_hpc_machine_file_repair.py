"""``hpcaccount repair-machine-file``: the one-time migration of a machine file holding several ``[hpc]`` tables.

Measured 2026-11-21 on two research accounts of the Ada fleet: the append-grant code before #878 wrote a second
``[hpc]`` table below the rendered one, so every read raised "Cannot declare ('hpc',) twice" -- before the fixed
``grant()`` could run, so a redeploy could never self-repair. FORMATS-MIGRATE-ONCE: the reader keeps the current
shape (one ``[hpc]``) and refuses the old one BY NAME with this door; the door migrates the file once.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Final

import pytest

from dev_lab.dev.hpcaccount import main as hpcaccount
from dev_lab.dev.hpcaccount.repairfile import repaired
from dev_lab.dev.hpcaccount.spec import REPAIR_DOOR, grant_refusal, has_grant, load

#: The rendered file: [deploy], the rendered reach, then the slice the old grant() APPENDED as a second [hpc].
BROKEN: Final = """[dev]
name = "ada-alice"

[deploy]
host = "login1.example"
root = "/r/src"
repos = [
  { name = "dev-lab", url = "https://forge.example/o/dev-lab.git", ref = "integrate/main" },
]

[hpc]
reach = ["research"]

[hpc.clusters.ada]
hosts = ["old.example"]

[env]
FEMM_DIR = "~/opt/femm"

[hpc]
reach = ["research"]

[hpc.clusters.ada]
hosts = ["login1.example"]
root = "/r/src"

[[hpc.grant]]
user = "alice"
cluster = "ada"
slurm_account = "acct"
"""


def _write(tmp_path: Path, text: str = BROKEN) -> Path:
    path = tmp_path / 'machine.toml'
    path.write_bytes(text.encode())
    return path


def test_the_broken_file_is_refused_by_name_with_the_repair_door(tmp_path: Path) -> None:
    """Every reader of the machine file names the door, never a bare "Cannot declare ('hpc',) twice"."""
    path = _write(tmp_path)
    for read in (lambda: load(path), lambda: has_grant(path, 'alice')):
        with pytest.raises(ValueError, match='repair-machine-file') as refused:
            read()
        assert str(path) in str(refused.value)
    assert 'repair-machine-file' in grant_refusal(path)  # the grant check answers the refusal as its reason


def test_a_file_with_one_hpc_table_is_not_refused(tmp_path: Path) -> None:
    """PLANTED CONTROL: the current shape loads, so the refusal above can say no."""
    path = _write(tmp_path, repaired(BROKEN) or '')
    assert load(path) is not None
    assert has_grant(path, 'alice')


def test_the_repair_keeps_one_hpc_table_merged_later_wins_and_every_other_table() -> None:
    text = repaired(BROKEN)
    assert text is not None
    assert text.count('[hpc]') == 1
    table = tomllib.loads(text)
    assert table['hpc']['clusters'] == {'ada': {'hosts': ['login1.example'], 'root': '/r/src'}}  # the appended slice
    assert table['hpc']['grant'] == [{'user': 'alice', 'cluster': 'ada', 'slurm_account': 'acct'}]
    assert table['hpc']['reach'] == ['research']
    assert table['env'] == {'FEMM_DIR': '~/opt/femm'}
    assert table['deploy']['host'] == 'login1.example'
    assert table['dev'] == {'name': 'ada-alice'}


def test_a_loadable_file_needs_no_repair() -> None:
    """Idempotent: a file that already loads (the repair's own output) has nothing to repair."""
    once = repaired(BROKEN)
    assert once is not None
    assert repaired(once) is None


def test_the_door_is_a_dry_run_by_default(tmp_path: Path, capsys) -> None:
    path = _write(tmp_path)
    assert hpcaccount(['repair-machine-file', '--config', str(path)]) == 0
    assert path.read_bytes() == BROKEN.encode()  # unchanged
    assert '[dry-run]' in capsys.readouterr().out


def test_apply_backs_up_then_rewrites_once(tmp_path: Path, capsys) -> None:
    path, backups = _write(tmp_path), tmp_path / 'backups'
    argv = ['repair-machine-file', '--config', str(path), '--apply', '--backups', str(backups)]
    assert hpcaccount(argv) == 0
    assert load(path) is not None
    (backup,) = backups.iterdir()
    assert backup.read_bytes() == BROKEN.encode()
    capsys.readouterr()
    assert hpcaccount(argv) == 0  # the second run: nothing to repair, nothing written
    assert len(list(backups.iterdir())) == 1
    assert 'nothing to repair' in capsys.readouterr().out


def test_a_file_broken_some_other_way_is_refused_not_rewritten(tmp_path: Path) -> None:
    """PLANTED CONTROL: the door migrates ONE known old shape; any other broken TOML is refused untouched."""
    path = _write(tmp_path, '[deploy]\nhost = \n')
    assert hpcaccount(['repair-machine-file', '--config', str(path), '--apply']) == 2
    assert path.read_text(encoding='utf-8') == '[deploy]\nhost = \n'


def test_the_refusal_names_the_door_verb() -> None:
    assert REPAIR_DOOR.startswith('python -m dev_lab.dev.hpcaccount repair-machine-file')
