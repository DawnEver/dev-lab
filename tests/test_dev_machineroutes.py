"""MACHINES-MEET-ONLY-THROUGH-THE-FORGE: a development machine's host file declaring a route to another is refused."""

from __future__ import annotations

from pathlib import Path

from dev_lab.dev.machineroutes import identities, route_defects
from dev_lab.ops.configcheck import main

_KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIA1dtjiBuQjg+mT4+rUmSfSrdgiwtUSw9TlircWVvVC0'
_A = {'dev': {'client_keys': [f'{_KEY} me@alpha-box']}}
_B = {'dev': {'hostname': 'beta-box.lab.example.org'}}
_SERVER = {'ops': {}}


def test_a_machine_is_known_by_its_stem_hostname_and_client_key_hosts() -> None:
    assert identities('A', _A) == {'a', 'alpha-box'}
    assert identities('B', _B) == {'b', 'beta-box'}


def test_a_route_to_a_server_or_to_itself_is_no_defect() -> None:
    """PLANTED CONTROL for the refusals below: the same tables pointing at a forge server pass."""
    a = {**_A, 'ssh': {'jump': {'ops@10.0.0.2': 'ops@server'}, 'host_keys': {'server': 'k'}}}
    a['consent'] = {'endpoint': 'consent@server'}
    assert route_defects({'A': a, 'B': _B, 'server': _SERVER}) == []
    assert route_defects({'A': {**_A, 'ssh': {'host_keys': {'alpha-box': 'k'}}}, 'B': _B}) == []


def test_every_route_kind_to_another_development_machine_is_refused_naming_both() -> None:
    cases = {
        'jump destination': {'jump': {'me@beta-box.lab.example.org': 'ops@server'}},
        'jump bastion': {'jump': {'ops@10.0.0.2': 'me@B'}},
        'host key': {'host_keys': {'BETA-BOX': 'k'}},
    }
    for kind, ssh in cases.items():
        found = route_defects({'A': {**_A, 'ssh': ssh}, 'B': _B, 'server': _SERVER})
        assert len(found) == 1, (kind, found)
        assert found[0].startswith('A: '), (kind, found)
        assert 'development machine B' in found[0], (kind, found)
        assert 'MACHINES-MEET-ONLY-THROUGH-THE-FORGE' in found[0]
    found = route_defects({'A': _A, 'B': {**_B, 'relay': {'endpoint': 'me@alpha-box:22'}}})
    assert found
    assert found[0].startswith('B: [relay] endpoint')


def test_configcheck_refuses_the_host_files_that_declare_such_a_route(tmp_path: Path, capsys) -> None:
    alpha = tmp_path / 'A.toml'
    beta = tmp_path / 'B.toml'
    alpha.write_text(f'[dev]\nclient_keys = ["{_KEY} me@alpha-box"]\nos = "windows"\n', encoding='utf-8')
    beta.write_text('[dev]\nos = "linux"\n', encoding='utf-8')
    main([str(alpha), str(beta)])  # bare host files carry other, unrelated defects without their family file
    assert 'MACHINES-MEET-ONLY-THROUGH-THE-FORGE' not in capsys.readouterr().err, 'PLANTED CONTROL: no route'
    beta.write_text('[dev]\nos = "linux"\n\n[ssh]\njump = { "me@alpha-box" = "ops@server" }\n', encoding='utf-8')
    assert main([str(alpha), str(beta)]) == 1
    assert 'B: [ssh] jump' in capsys.readouterr().err
