"""``hpcaccount keys``: a cluster account's login keys DERIVED from hosts-config, placed as a managed block.

User ruling 2026-11-22: every workstation can do what another can, controlled by config; hosts-config is the one
source. Each test plants the case that must say no beside the one that says yes.
"""

from __future__ import annotations

from functools import partial

from lab_commons.hpc.cluster import Runner
from lab_commons.hpc.grants import Grant

from dev_lab.dev.credstore import digest
from dev_lab.dev.hpcaccount import keys
from dev_lab.dev.hpcaccount.division import Division

A = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIA1dtjiBuQjg+mT4+rUmSfSrdgiwtUSw9TlircWVvVC0 dev@a'
B = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFZKJeP/Iu77SvrXZgzPfe5sojh4r7eOvoyM/aOmdprC dev@b'
C = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExampleExampleExampleExample dev@c'
FOREIGN = 'ssh-rsa AAAAB3NzaC1yc2EAAAADAQAB someone@else'
FILES = {
    'a.toml': f'[dev]\nos = "windows"\nhpc = ["research"]\nclient_keys = ["{A}"]\n',
    'b.toml': f'[dev]\nos = "linux"\nhpc = ["research", "verification"]\nclient_keys = ["{B}"]\n',
    'c.toml': f'[dev]\nos = "linux"\nhpc = ["verification"]\nclient_keys = ["{C}"]\n',
    'nokeys.toml': '[dev]\nos = "linux"\nhpc = ["research"]\n',
    'alice.toml': '[deploy]\nhost = "h"\n',
}
GRANTS = (Grant(user='alice', hosts=('login1.example',), slurm_account='acct'),)
DIVISION = Division(grant_roles={'alice': 'research'})


def _account(home: dict[str, str], seen: list[str]) -> Runner:
    """A fake key-only connection backed by one ``authorized_keys`` text in *home*."""

    def shell(cmd: str, stdin: str | None = None) -> str:
        seen.append(cmd)
        if cmd.startswith('cat ~/.ssh/authorized_keys'):
            return home.get('keys', '')
        if 'mv -f' in cmd:
            home['keys'] = stdin or ''
            return 'backup ~/.ssh/authorized_keys.bak-T\n'
        raise AssertionError(cmd)

    return shell


def _place(home: dict[str, str], seen: list[str], said: list[str]) -> int:
    return keys.place_keys(
        'alice@login1.example', files=FILES, grants=GRANTS, division=DIVISION, say=said.append,
        connect=lambda _g: _account(home, seen), stamp='T',
    )  # fmt: skip


def test_only_workstations_reaching_the_role_contribute_their_keys() -> None:
    """PLANTED CONTROL: ``c`` reaches only ``verification`` and is left out of ``research``."""
    assert keys.reaching(FILES, 'research') == (A, B)
    assert keys.reaching(FILES, 'verification') == (B, C)
    assert keys.reaching(FILES, 'nobody') == ()


def test_the_placement_keeps_foreign_lines_verifies_and_is_idempotent() -> None:
    home = {'keys': f'{FOREIGN}\n{keys.BEGIN}\n{C}\n{keys.END}\n'}
    seen: list[str] = []
    said: list[str] = []
    assert _place(home, seen, said) == 0
    assert home['keys'] == f'{FOREIGN}\n{keys.BEGIN}\n{A}\n{B}\n{keys.END}\n'
    assert said[-1].startswith('verified: alice (research)')
    writes = sum('mv -f' in cmd for cmd in seen)
    assert _place(home, seen, said) == 0
    assert sum('mv -f' in cmd for cmd in seen) == writes, 'an unchanged file is not rewritten'
    assert 'unchanged' in said[-1]
    assert A not in ''.join(said), 'a key is printed only by its hash'


def test_a_write_that_did_not_land_is_not_verified() -> None:
    """PLANTED CONTROL: the read-back finds the old block, so the door exits 2 naming what it found."""
    seen: list[str] = []
    said: list[str] = []

    def lost(cmd: str, _stdin: str | None = None) -> str:
        seen.append(cmd)
        return '' if 'mv -f' in cmd else f'{keys.BEGIN}\n{C}\n{keys.END}\n'

    code = keys.place_keys(
        'alice@login1.example', files=FILES, grants=GRANTS, division=DIVISION, say=said.append,
        connect=lambda _g: lost, stamp='T',
    )  # fmt: skip
    assert code == 2
    assert said[-1].startswith('keys: not verified')
    assert digest(C) in said[-1]


def test_the_dry_run_connects_to_nothing_and_prints_hashes_only() -> None:
    said: list[str] = []
    code = keys.place_keys(
        'alice@login1.example', files=FILES, grants=GRANTS, division=DIVISION, say=said.append, dry_run=True,
        connect=lambda _g: (_ for _ in ()).throw(AssertionError('connected')),
    )  # fmt: skip
    assert code == 0
    assert digest(A) in said[0]
    assert digest(B) in said[0]
    assert A not in said[0]
    assert B not in said[0]


def test_every_refusal_names_its_door() -> None:
    said: list[str] = []
    none = Division(grant_roles={'alice': 'nobody'})
    refused = partial(keys.place_keys, files=FILES, grants=GRANTS, say=said.append, dry_run=True)
    assert refused('alice@login1.example', division=none) == 2
    assert '[dev] hpc' in said[-1]
    assert 'client_keys' in said[-1]
    assert refused('bob@login1.example', division=DIVISION) == 2
    assert '[[hpc.grant]]' in said[-1]


def test_a_broken_managed_block_is_refused_and_left_untouched() -> None:
    home = {'keys': f'{FOREIGN}\n{keys.BEGIN}\n{A}\n'}
    seen: list[str] = []
    said: list[str] = []
    assert _place(home, seen, said) == 2
    assert 'broken managed block' in said[-1]
    assert home['keys'] == f'{FOREIGN}\n{keys.BEGIN}\n{A}\n'


SESSION_REACH = {'integrator': ['verification']}
VERIFIER = Division(grant_roles={'alice': 'verification'})
SESSION_FILES = {
    'a.toml': FILES['a.toml'],
    'none.toml': f'[dev]\nos = "linux"\nhpc = []\nclient_keys = ["{C}"]\n',
}


def test_a_session_role_takes_the_keys_of_every_workstation_whose_reach_admits_it() -> None:
    """PLANTED CONTROL: ``none`` (hpc = []) may hold no session role, so its key is left out."""
    assert keys.reaching(SESSION_FILES, 'verification', SESSION_REACH) == (A,)
    assert keys.reaching(SESSION_FILES, 'verification') == (), 'no session_reach declared: no session admission'
    assert keys.reaching(FILES, 'research', SESSION_REACH) == (A, B), 'a standing role is unchanged'


def test_a_verification_account_is_placed_through_the_session_rule() -> None:
    said: list[str] = []
    code = keys.place_keys(
        'alice@login1.example', files=SESSION_FILES, grants=GRANTS, division=VERIFIER,
        say=said.append, dry_run=True, session_reach=SESSION_REACH,
    )  # fmt: skip
    assert code == 0, said
    assert digest(A) in said[-1]
    assert digest(C) not in said[-1]
