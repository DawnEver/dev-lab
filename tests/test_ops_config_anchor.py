"""FIRST CONTACT: a host that verifies nothing takes exactly ``[ops.consent_client]`` from the reviewed source.

Planted controls: each refusal test holds a reviewed file whose anchor WOULD land if the guard under test were absent.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from dev_lab.ops import configdoor, configverbs, upgrade
from dev_lab.ops.config import ConfigSource, OpsConfig
from dev_lab.ops.configdoor import anchor

LIVE = """\
[cycle]
interval_s = 60

[ops]
home = "/var/lib/ops"
python = "/opt/dev-lab/.venv/bin/python"
repos = ["https://forge.example/o/a.git"]
"""

CLIENT = """
[ops.consent_client]
endpoint = "consent@issuer.example"
public_key = "-----BEGIN PUBLIC KEY-----\\nMCow\\n-----END PUBLIC KEY-----\\n"
known_hosts = "/var/lib/ops/known_hosts"
"""

MAIN = LIVE + CLIENT


def _ok(_path: Path) -> object:
    return None


def _green(_argv: list[str]) -> tuple[int, str]:
    return 0, 'ok'


def _live(tmp_path: Path, text: str = LIVE) -> Path:
    path = tmp_path / 'supervise.toml'
    path.write_text(text, encoding='utf-8')
    return path


def _client(path: Path) -> object:
    return tomllib.loads(path.read_text(encoding='utf-8'))['ops'].get('consent_client')


def test_a_fresh_host_takes_the_client_table_from_main(tmp_path: Path) -> None:
    live = _live(tmp_path)
    taken = anchor(live, MAIN, loads=_ok, checks={'loads': ['true']}, run=_green)
    assert taken is not None
    table, backup = taken
    assert table['endpoint'] == 'consent@issuer.example'
    assert _client(live) == tomllib.loads(MAIN)['ops']['consent_client']
    assert backup.read_text(encoding='utf-8') == LIVE
    assert configdoor.changes(tomllib.loads(live.read_text(encoding='utf-8')), tomllib.loads(MAIN)) == ()


def test_a_host_holding_the_table_keeps_it_even_when_main_differs(tmp_path: Path) -> None:
    live = _live(tmp_path, LIVE + CLIENT.replace('issuer.example', 'old.example'))
    before = live.read_text(encoding='utf-8')
    assert anchor(live, MAIN, loads=_ok, checks={}, run=_green) is None
    assert live.read_text(encoding='utf-8') == before


def test_an_issuer_never_bootstraps_a_client(tmp_path: Path) -> None:
    live = _live(tmp_path, LIVE + '\n[ops.consent]\nstate = "/var/lib/ops/consent"\n')
    before = live.read_text(encoding='utf-8')
    assert anchor(live, MAIN, loads=_ok, checks={}, run=_green) is None
    assert live.read_text(encoding='utf-8') == before


def test_only_the_table_is_taken_and_another_boundary_change_still_parks(tmp_path: Path) -> None:
    live = _live(tmp_path)
    main = MAIN.replace('/opt/dev-lab/.venv/bin/python', '/opt/other/python')
    assert anchor(live, main, loads=_ok, checks={}, run=_green) is not None
    assert tomllib.loads(live.read_text(encoding='utf-8'))['ops']['python'] == '/opt/dev-lab/.venv/bin/python'
    with pytest.raises(configdoor.ConfigRefused, match=r'ops\.python'):
        configdoor.apply(live, main, loads=_ok, checks={}, run=_green)


def _config(live: Path) -> OpsConfig:
    token = str(live.parent / 'token')
    source = ConfigSource(source='https://forge.example/t/hosts.git', path='h.toml', token_file=token, ref='main')
    return OpsConfig(
        path=live, home=live.parent, python='p', repos=(), promote=None, breakglass=None, merged={},
        config_source=source,
    )  # fmt: skip


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(configdoor, 'fetch', lambda _source, run: MAIN)  # noqa: ARG005 -- the reviewed main
    monkeypatch.setattr(configverbs, 'load', _ok)
    monkeypatch.setattr(upgrade, 'checks', lambda _config: {})


@pytest.mark.usefixtures('offline')
def test_a_bare_apply_bootstraps_from_the_fetched_main(tmp_path: Path) -> None:
    live = _live(tmp_path)
    said = configverbs.apply(_config(live), None, '', alert=lambda *_: None, redeemer=lambda: lambda _a: None)
    assert said == 0
    assert _client(live) == tomllib.loads(MAIN)['ops']['consent_client']


@pytest.mark.usefixtures('offline')
def test_a_local_candidate_is_never_a_bootstrap_source(tmp_path: Path) -> None:
    live = _live(tmp_path)
    local = tmp_path / 'candidate.toml'
    local.write_text(MAIN, encoding='utf-8')  # the same table main holds: refused only because it is local
    said = configverbs.apply(_config(live), local, '', alert=lambda *_: None, redeemer=lambda: lambda _a: None)
    assert said == 2
    assert _client(live) is None
