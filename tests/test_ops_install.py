"""The one install door renders every file the config asks for, idempotently, from the config alone."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import pytest
from _ops_fixtures import config
from lab_commons.config import CONFIG_ENV

from dev_lab.dev.privatemarkers import load_markers, scan_text
from dev_lab.ops import hostverbs
from dev_lab.ops.__main__ import main
from dev_lab.ops.config import OpsConfig, load
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.install import BREAKGLASS_MACHINE, family_env, files, install


def test_install_renders_units_sshd_and_sudoers_and_is_idempotent(tmp_path: Path) -> None:
    host = config(tmp_path, ['https://forge.example/owner/alpha.git'])
    root = tmp_path / 'root'
    first = install(host, root)
    assert set(first.paths.values()) == {'written', 'created'}  # the clone home is created
    assert set(install(host, root).paths.values()) == {'unchanged'}
    rendered = files(host)
    timer = rendered['etc/systemd/system/dev-lab-ops-promote.timer']
    assert 'OnCalendar=*-*-* 04:30:00 Europe/London' in timer
    sshd = rendered['etc/ssh/sshd_config.d/60-dev-lab-ops-breakglass.conf']
    assert 'Match User breakglass' in sshd
    assert 'breakglass serve' in sshd
    assert 'ExposeAuthInfo yes' in sshd
    assert rendered['etc/dev-lab/ops/breakglass.keys'] == 'ssh-ed25519 AAAA agent\n'
    sudo = rendered['etc/sudoers.d/dev-lab-ops-breakglass']
    assert sudo.startswith('Defaults:breakglass env_keep += "SSH_USER_AUTH"\nbreakglass ALL=(root) NOPASSWD: ')
    issuer = rendered['etc/ssh/sshd_config.d/60-dev-lab-ops-consent.conf']  # the consent issuer's own account
    assert 'Match User consent' in issuer
    assert 'consent serve' in issuer


def test_a_disabled_role_renders_nothing(tmp_path: Path) -> None:
    host = config(tmp_path, [], extra='')
    text = host.path.read_text(encoding='utf-8').replace('[ops.breakglass]', '[ops.breakglass]\nenabled = false')
    host.path.write_text(text, encoding='utf-8')
    assert not any('breakglass' in path for path in files(load(host.path, environ={})))


def test_no_host_fact_is_in_the_code() -> None:
    package = Path(__file__).resolve().parents[1] / 'src' / 'dev_lab' / 'ops'
    markers = load_markers()
    for source in package.glob('*.py'):
        text = source.read_text(encoding='utf-8')
        for fact in ('79.72', '152.67', 'Europe/London'):
            assert fact not in text, (source.name, fact)
        assert not scan_text(text, markers), source.name  # the machine-local denylist names the rest


@pytest.mark.parametrize(
    ('table', 'why'),
    [
        ('[ops.promote]\nuser = "p"\nschedule = "daily"\ncredentials = "c"\ntypo = 1\n', 'unknown keys'),
        ('[ops.promote]\nuser = "p"\n', 'promote'),
    ],
)
def test_a_bad_role_table_is_refused_at_load(tmp_path: Path, table: str, why: str) -> None:
    path = tmp_path / 'supervise.toml'
    path.write_text(f'[ops]\nhome = "h"\npython = "p"\nrepos = []\n{table}', encoding='utf-8')
    with pytest.raises(ValueError, match=why):
        load(path, environ={})


def test_a_duplicate_repo_name_is_refused(tmp_path: Path) -> None:
    path = tmp_path / 'supervise.toml'
    path.write_text(
        '[ops]\nhome = "h"\npython = "p"\nrepos = ["https://a/x/r.git", "https://b/y/r"]\n', encoding='utf-8'
    )
    with pytest.raises(ValueError, match='twice'):
        load(path, environ={})


def test_the_door_refuses_a_file_with_no_ops_table(tmp_path: Path) -> None:
    path = tmp_path / 'supervise.toml'
    path.write_text('[target]\nname = "x"\n', encoding='utf-8')
    assert main(['--config', str(path), 'install', '--root', str(tmp_path / 'r')]) == 2


_GLASS_FAMILY = '\n[ops.breakglass.family]\nsource = "/etc/dev-lab/family.toml"\nmax_age = "7 d"\n'


def _with_glass_family(tmp_path: Path) -> OpsConfig:
    host = config(tmp_path, [])
    host.path.write_text(host.path.read_text(encoding='utf-8') + _GLASS_FAMILY, encoding='utf-8')
    return load(host.path, environ={})


def test_break_glass_reads_the_roles_through_a_rendered_family_machine_file(tmp_path: Path) -> None:
    """D73: break-glass reads who produces tests from the family's roles -- install renders its machine file."""
    host = _with_glass_family(tmp_path)
    rendered = tomllib.loads(files(host)[BREAKGLASS_MACHINE])
    assert rendered == {'family': {'source': '/etc/dev-lab/family.toml', 'max_age': '7 d'}}
    assert family_env(host.breakglass) == {CONFIG_ENV: f'/{BREAKGLASS_MACHINE}'}


def test_no_break_glass_family_renders_no_machine_file_and_sets_no_env(tmp_path: Path) -> None:
    """PLANTED CONTROL: without [ops.breakglass.family] nothing is rendered and the process keeps its own config."""
    host = config(tmp_path, [])
    assert BREAKGLASS_MACHINE not in files(host)
    assert family_env(host.breakglass) == {}


def test_a_break_glass_family_with_no_source_is_refused_at_load(tmp_path: Path) -> None:
    host = config(tmp_path, [])
    host.path.write_text(
        host.path.read_text(encoding='utf-8') + '\n[ops.breakglass.family]\nmax_age = "7 d"\n', encoding='utf-8'
    )
    with pytest.raises(ValueError, match=r'\[ops\.breakglass\.family\] names no source'):
        load(host.path, environ={})


def test_the_break_glass_verb_points_lab_commons_at_its_machine_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The serve/tick process reads the roles through the rendered machine file, not a HOME it does not have."""
    host = _with_glass_family(tmp_path)
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    seen: list[str | None] = []

    def ends(*_args: object, **_kwargs: object) -> tuple[object, object]:
        seen.append(os.environ.get(CONFIG_ENV))
        msg = 'stop here'
        raise ConsentRefused(msg)

    monkeypatch.setattr(hostverbs.consentverbs, 'ends', ends)
    assert hostverbs.breakglass_verb(host, 'tick') == 2
    assert seen == [f'/{BREAKGLASS_MACHINE}']
