"""Client keys are DERIVED: a server's approval accounts accept every development machine's declared key, no hand list.

Measured 2026-11-20: a workstation's key was not authorized for breakglass@/consent@ because the server file listed
the keys by hand and nobody added it. Now each machine declares ``[dev] client_keys`` once in its own host file, and
the server's fetch derives ``[ops.clients]`` from the same reviewed clone.
"""

from __future__ import annotations

import dataclasses
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from _ops_fixtures import config

from dev_lab.dev import devschema
from dev_lab.ops import clientkeys
from dev_lab.ops.config import ConfigSource, load
from dev_lab.ops.configcheck import check_host
from dev_lab.ops.configdoor import ConfigRefused, boundary, digest, fetch, local_subject

G_KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFZKJeP/Iu77SvrXZgzPfe5sojh4r7eOvoyM/aOmdprC dev@g'
WS_KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIA1dtjiBuQjg+mT4+rUmSfSrdgiwtUSw9TlircWVvVC0 dev@ws'
SERVER = (
    '[ops]\nhome = "/h"\npython = "/p"\n[ops.config]\nsource = "S"\npath = "hosts/forge.toml"\n'
    'token_file = "/t"\nclients = "hosts"\n'
)
FILES = {
    'g.toml': f'[dev]\nos = "windows"\nclient_keys = ["{G_KEY}"]\n',
    'ws.toml': f'[dev]\nos = "windows"\nclient_keys = ["{WS_KEY}", "{G_KEY}"]\n',
    'nokey.toml': '[dev]\nos = "linux"\n',
    'ada-user.toml': '[deploy]\nhost = "h"\n',
    'forge.toml': SERVER,
}


def test_every_development_machines_declared_key_is_derived_once_in_name_order() -> None:
    """PLANTED CONTROL: a machine declaring no key, an HPC account and a server add nothing."""
    assert clientkeys.derive(FILES) == (G_KEY, WS_KEY)
    assert clientkeys.derive({name: FILES[name] for name in ('nokey.toml', 'ada-user.toml', 'forge.toml')}) == ()


#: A private-key ARMOR line, joined at runtime so the source holds no secret-shaped literal for a scanner to flag.
PRIVATE_ARMOR = '-----BEGIN OPENSSH ' + 'PRIVATE KEY-----'


@pytest.mark.parametrize('bad', [PRIVATE_ARMOR, '', 'ssh-ed25519', 'AAAA dev@x'])
def test_a_malformed_key_is_refused_naming_its_file(bad: str) -> None:
    with pytest.raises(ValueError, match=r'ws\.toml \[dev\] client_keys\[0\]'):
        clientkeys.derive({'ws.toml': f'[dev]\nclient_keys = ["{bad}"]\n'})


def _clone(files: Mapping[str, str]) -> Callable[[list[str], Mapping[str, str]], tuple[int, str]]:
    """The fetch's runner: a clone that writes *files* under ``hosts/``."""

    def run(argv: list[str], _env: Mapping[str, str]) -> tuple[int, str]:
        hosts = Path(argv[-1]) / 'hosts'
        hosts.mkdir(parents=True)
        for name, text in files.items():
            (hosts / name).write_text(text, encoding='utf-8')
        return 0, ''

    return run


def _source(tmp_path: Path, clients: str = 'hosts') -> ConfigSource:
    (tmp_path / 'token').write_text('t\n', encoding='utf-8')
    return ConfigSource('S', 'hosts/forge.toml', str(tmp_path / 'token'), clients=clients)


def test_the_fetch_folds_the_derived_table_and_the_off_host_subject_agrees(tmp_path: Path) -> None:
    """The candidate carries ``[ops.clients]``; ``local_subject`` derives the same digest from a listing.

    The CANDIDATE's declaration decides, never the live table's: the first apply declaring ``clients`` is fetched
    by a host whose live table does not yet, and keyed on that it would drop every key the file stops listing.

    PLANTED CONTROL: a host file declaring no ``clients`` is fetched unchanged; a subject asked with no listing is
    refused by name rather than derived without the keys.
    """
    fetched = fetch(_source(tmp_path, clients=''), run=_clone(FILES)).host
    assert tomllib.loads(fetched)['ops']['clients'] == {'keys': [G_KEY, WS_KEY]}
    plain = SERVER.replace('clients = "hosts"\n', '')
    assert fetch(_source(tmp_path), run=_clone({**FILES, 'forge.toml': plain})).host == plain

    def read(_source: str, path: str, _ref: str) -> str:
        return FILES[path.removeprefix('hosts/')]

    def listed(_source: str, where: str, _ref: str) -> list[str]:
        return sorted(FILES) if where == 'hosts' else []

    assert local_subject('S', 'hosts/forge.toml', read, listed=listed) == digest(fetched)
    with pytest.raises(ConfigRefused, match=r'clients = .hosts.: the subject needs the listing'):
        local_subject('S', 'hosts/forge.toml', read)


def test_a_host_file_writing_the_derived_table_by_hand_is_refused(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same server file without the hand table passes the config-source check."""
    forged = {**FILES, 'forge.toml': SERVER + f'[ops.clients]\nkeys = ["{G_KEY}"]\n'}
    with pytest.raises(ConfigRefused, match=r'declares \[ops.clients\] by hand'):
        fetch(_source(tmp_path), run=_clone(forged))
    path = tmp_path / 'forge.toml'
    path.write_text(forged['forge.toml'], encoding='utf-8')
    assert any('[ops.clients] is derived' in line for line in check_host(path))
    path.write_text(SERVER, encoding='utf-8')
    assert not any('[ops.clients]' in line for line in check_host(path))


def test_the_derived_keys_join_break_glass_and_consent_keeping_their_own(tmp_path: Path) -> None:
    """A server's own declared key stays; each derived key is added once. The change is security boundary.

    PLANTED CONTROL: a config with no ``[ops.clients]`` keeps exactly its declared keys.
    """
    plain = config(tmp_path, [])
    text = plain.path.read_text(encoding='utf-8') + f'[ops.clients]\nkeys = ["ssh-ed25519 AAAA agent", "{WS_KEY}"]\n'
    plain.path.write_text(text, encoding='utf-8')
    found = load(plain.path, environ={})
    assert found.breakglass is not None
    assert found.consent is not None
    assert found.breakglass.keys == ('ssh-ed25519 AAAA agent', WS_KEY)
    assert found.consent.keys == ('ssh-ed25519 AAAA agent', WS_KEY)
    assert plain.consent is not None
    assert plain.consent.keys == ()
    assert boundary(('ops.clients.keys',)) == ('ops.clients.keys',), 'who may log in is never routine'


def test_a_machine_declares_its_keys_in_its_own_host_file_only() -> None:
    """PLANTED CONTROL: the family declaring client_keys is refused as one machine's fact; a good host passes."""
    family = {'dev': {'ref': 'integrate/main', 'key_account': 'dev'}}
    assert devschema.check({'dev': {'client_keys': [WS_KEY], 'hostname': 'ws'}}, family) == []
    assert any('client_keys' in line for line in devschema.check({'dev': {'client_keys': ['nope']}}, family))
    assert any('client_keys' in line for line in devschema.check_family({'dev': {'client_keys': [WS_KEY]}}))


def test_the_source_table_declares_clients_as_a_boundary_key(tmp_path: Path) -> None:
    assert boundary(('ops.config.clients',)) == ('ops.config.clients',)
    assert dataclasses.replace(_source(tmp_path), clients='hosts').clients == 'hosts'


_ACCESS = '[ops.access]\naccount = "ops"\nkeys = ["ssh-ed25519 AAAA own"]\n'
_OPT_IN = '[ops.config]\nsource = "S"\npath = "hosts/forge.toml"\ntoken_file = "/t"\nclients = "hosts"\n'


def _with_access(tmp_path: Path, extra: str) -> Path:
    path = config(tmp_path, []).path
    text = path.read_text(encoding='utf-8') + _ACCESS + extra + f'[ops.clients]\nkeys = ["{WS_KEY}"]\n'
    path.write_text(text, encoding='utf-8')
    return path


def test_an_opted_in_host_adds_the_derived_keys_to_the_operator_login_keeping_its_own(tmp_path: Path) -> None:
    """``[ops.config] clients`` set: ``[ops.access]`` keys are its own plus every derived workstation key."""
    found = load(_with_access(tmp_path, _OPT_IN), environ={})
    assert found.access is not None
    assert found.access.keys == ('ssh-ed25519 AAAA own', WS_KEY)


def test_a_host_that_does_not_opt_in_keeps_exactly_its_declared_access_keys(tmp_path: Path) -> None:
    """PLANTED CONTROL: no ``clients`` opt-in, the operator login is not widened even with ``[ops.clients]`` present."""
    found = load(_with_access(tmp_path, ''), environ={})
    assert found.access is not None
    assert found.access.keys == ('ssh-ed25519 AAAA own',)
