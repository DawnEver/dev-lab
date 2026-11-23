"""``devhost admit``: ONE door, runnable from ANY machine the issuer already admits, that puts a declared key in.

Measured 2026-11-22: a workstation's key was declared (merged) yet the issuer refused it, and its agent concluded a
person must log in on the forge host. The door authors the ``ops.config`` plan applying the config source's main on
the issuer host, its subject derived through the SAME function the host's ``planrun`` uses, preflights it, and asks
for one code only when green. Planted controls: an unadmitted key yields a plan whose preflight is green; an
already-admitted one ("nothing to apply" from the issuer's own read) yields "nothing to admit" and no plan.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import lab_commons.launch as _door
import pytest

from dev_lab.dev import devhostadmit
from dev_lab.dev.planrunpreflight import Readers
from dev_lab.ops import configdoor

_SOURCE = 'https://forge.example/team/config.git'
_KEY = 'ssh-ed25519 AAAAC3NzaPLANTED'
_HOSTS = {
    'hosts/ws9.toml': f'[dev]\nclient_keys = ["{_KEY} ws9"]\n',
    'hosts/forgehost.toml': f'[ops.config]\nsource = "{_SOURCE}"\npath = "hosts/forgehost.toml"\n',
}
_ISSUER = """
[ops.consent]
account = "consent"

[ops.access]
account = "ops"
commands = ["/opt/v/bin/python -m dev_lab.ops --config /etc/x/supervise.toml config apply *"]
"""


def _readers(refusal: str | None, subject: str | None = None) -> Readers:
    def text(_source: str, path: str, _ref: str) -> str:
        return _HOSTS[path]

    derived = configdoor.local_subject(_SOURCE, 'hosts/forgehost.toml', text)
    return Readers(
        text=text, listed=lambda *_: [], config_source=lambda: _SOURCE,
        issued=lambda _dest, _action, _argv: (subject or derived, refusal),
    )  # fmt: skip


def _admit(tmp_path: Path, readers: Readers, said: list[str]) -> int:
    issuer = tmp_path / 'clone' / 'hosts' / 'forgehost.toml'
    issuer.parent.mkdir(parents=True)
    issuer.write_text(_ISSUER, encoding='utf-8')
    return devhostadmit.offer(
        machine='ws9', clone=tmp_path / 'clone', endpoint='consent@forgehost.example', readers=readers,
        out=tmp_path / 'out', check=lambda _plan, _steps: (True, ['preflight: GREEN']), say=said.append,
    )  # fmt: skip


def test_an_unadmitted_key_yields_a_green_plan_and_one_code_asked(tmp_path: Path) -> None:
    said: list[str] = []
    assert _admit(tmp_path, _readers(None), said) == 0
    plan = json.loads(next((tmp_path / 'out').glob('*.plan.json')).read_text(encoding='utf-8'))
    assert plan['hosts'] == ['ops@forgehost.example']
    assert [grant['action'] for grant in plan['grants']] == ['ops.config']
    steps = json.loads(next((tmp_path / 'out').glob('*.steps.json')).read_text(encoding='utf-8'))
    assert steps['steps'] == [{'argv': ['config', 'apply'], 'config_host': 'forgehost'}]
    assert steps['config'] == '/etc/x/supervise.toml'
    assert 'ask the user for one code' in '\n'.join(said)


def test_an_admitted_key_has_nothing_to_admit_and_no_plan(tmp_path: Path) -> None:
    said: list[str] = []
    assert _admit(tmp_path, _readers(configdoor.UNCHANGED), said) == 0
    assert 'nothing to admit' in '\n'.join(said)
    assert not (tmp_path / 'out').exists()


def test_a_subject_the_host_derives_otherwise_is_refused_before_a_plan(tmp_path: Path) -> None:
    said: list[str] = []
    assert _admit(tmp_path, _readers(None, subject='0' * 64), said) == 2
    assert not (tmp_path / 'out').exists()
    assert 'ask the user' not in '\n'.join(said)


@pytest.mark.parametrize('declared', [_SOURCE, _SOURCE.removesuffix('.git'), _SOURCE + '/'])
def test_a_clone_url_without_the_git_suffix_is_the_same_source(declared: str) -> None:
    text = f'[ops.config]\nsource = "{declared}"\npath = "hosts/h.toml"\n'
    local = _SOURCE.removesuffix('.git')
    assert configdoor.local_subject(local, 'hosts/h.toml', lambda *_: text) == configdoor.digest(text)


def test_another_source_is_still_refused() -> None:
    text = f'[ops.config]\nsource = "{_SOURCE}"\npath = "hosts/h.toml"\n'
    with pytest.raises(configdoor.ConfigRefused, match='derive it there'):
        configdoor.local_subject('https://forge.example/other/config', 'hosts/h.toml', lambda *_: text)


@pytest.mark.parametrize('first', ['dev_lab.dev.sshhold', 'dev_lab.dev.planrunpreflight', 'dev_lab.dev.devhost'])
def test_each_module_of_the_cycle_imports_first(first: str) -> None:
    """The admit door sits inside devhost -> planrunpreflight -> devhost; any of them imported first must load."""
    done = _door.run(
        [sys.executable, '-c', f'import {first}'], capture_output=True, text=True, encoding='utf-8', errors='replace',
        check=False, timeout=120,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr[-600:]
