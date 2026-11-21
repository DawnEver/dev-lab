"""A config-source repository is checked by STRUCTURE: hosts load; the family file holds no local fact or secret."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev import accounthost
from dev_lab.ops import config as opsconfig
from dev_lab.ops.configcheck import check_family, check_host, needs_consent

HOST = """\
[ops]
home = "/var/lib/ops"
python = "/opt/dev-lab/.venv/bin/python"
environment_file = "/etc/dev-lab/alerts.env"
repos = ["https://forge.example/o/a.git"]

[ops.judge]
repos = ["https://forge.example/o/a.git"]
keys_file = "/etc/dev-lab/judge.keys"
user = "judge"
schedule = "*:0/5"

[ops.judge.tokens]
"forge.example" = "/etc/dev-lab/judge.token"
"""


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding='utf-8')
    return path


def test_the_live_loader_refuses_a_host_file_off_its_host(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='environment_file'):
        opsconfig.load(_write(tmp_path, 'h.toml', HOST), environ={}, as_root=False)


def test_structure_only_skips_the_host_environment_and_secret_files(tmp_path: Path) -> None:
    loaded = opsconfig.load(_write(tmp_path, 'h.toml', HOST), environ={}, as_root=True, structure_only=True)
    assert loaded.judge is not None


def test_check_host_reports_a_structural_defect(tmp_path: Path) -> None:
    assert check_host(_write(tmp_path, 'ok.toml', HOST)) == []
    bad = HOST.replace(
        'repos = ["https://forge.example/o/a.git"]\n\n',
        'repos = ["https://forge.example/o/a.git", "https://forge.example/p/a.git"]\n\n',
        1,
    )
    assert any('twice' in found for found in check_host(_write(tmp_path, 'bad.toml', bad)))


@pytest.mark.parametrize(
    ('extra', 'named'),
    [
        ('[bogus_section]\nx = 1\n', 'bogus_section'),
        ('[alerts]\ncooldwon = 600\n', 'alerts.cooldwon'),
        ('[ops.bogus]\nx = 1\n', 'bogus'),
        ('[ops.judge.bogus]\nx = 1\n', 'bogus'),
    ],
)
def test_check_host_refuses_an_undeclared_table_or_key_by_name(tmp_path: Path, extra: str, named: str) -> None:
    assert check_host(_write(tmp_path, 'ok.toml', HOST + '\n[components.anything]\nenabled = true\n')) == []
    found = check_host(_write(tmp_path, 'bad.toml', HOST + '\n' + extra))
    assert len(found) == 1
    assert named in found[0]


def test_a_misspelt_ops_scalar_is_refused_at_load(tmp_path: Path) -> None:
    host = _write(tmp_path, 'h.toml', HOST.replace('[ops]\n', '[ops]\npyhton = "x"\n', 1))
    with pytest.raises(ValueError, match='pyhton'):
        opsconfig.load(host, environ={}, as_root=False, structure_only=True)


@pytest.mark.parametrize('table', ['repos', 'writeroots', 'sync'])
def test_the_family_file_refuses_a_local_only_table(tmp_path: Path, table: str) -> None:
    found = check_family(_write(tmp_path, 'family.toml', f'[{table}]\nx = "y"\n'))
    assert any(table in line and 'local' in line for line in found)


def test_the_family_file_refuses_a_secret_value_and_admits_a_path(tmp_path: Path) -> None:
    ok = '[ai_lab.review]\ntoken_file = "/etc/dev-lab/review.token"\n'
    assert check_family(_write(tmp_path, 'ok.toml', ok)) == []
    bad = '[ai_lab.review]\napi_key = "sk-ant-abcdefabcdefabcdef"\n'
    found = check_family(_write(tmp_path, 'bad.toml', bad))
    assert any('ai_lab.review.api_key' in line for line in found)
    assert not any('sk-ant' in line for line in found)  # a refusal never repeats the value


def test_a_token_shaped_value_is_refused_under_any_name(tmp_path: Path) -> None:
    found = check_family(_write(tmp_path, 'f.toml', '[x]\nnote = "ghp_' + 'a' * 36 + '"\n'))
    assert any('x.note' in line for line in found)


def test_needs_consent_names_the_boundary_keys_a_change_touches() -> None:
    old = HOST
    assert needs_consent(old, old.replace('/opt/dev-lab', '/srv/dev-lab')) == ('ops.python',)
    assert needs_consent(old, old.replace('repos = ["https://forge.example/o/a.git"]\nkeys', 'repos = []\nkeys')) == ()
    assert needs_consent('', old)[0].startswith('ops.')


DEV_HOST = '[dev]\nhpc = []\nref = "integrate/main"\n'
SSH_ROUTES = '[ssh.jump]\n"node.example" = "bastion.example"\n\n[ssh.hold]\nmax_hours = 8\nidle_minutes = 30\n'


def test_a_dev_host_file_declares_its_ssh_routes(tmp_path: Path) -> None:
    assert check_host(_write(tmp_path, 'G.toml', DEV_HOST + '\n' + SSH_ROUTES)) == []


@pytest.mark.parametrize(
    ('extra', 'named'),
    [
        ('[ssh]\nbogus = 1\n', 'ssh.bogus'),
        ('[ssh.hold]\nmax_hour = 8\n', 'ssh.hold.max_hour'),
        ('[ssh.jump]\n"node.example" = 22\n', 'ssh.jump'),
        ('[ssh.jump]\n"node.example" = ""\n', 'ssh.jump'),
        ('[ssh]\njump = "bastion.example"\n', 'ssh.jump'),
        ('[ssh.hold]\nmax_hours = "8"\n', 'ssh.hold.max_hours'),
    ],
)
def test_an_ssh_key_or_value_off_the_schema_is_refused(tmp_path: Path, extra: str, named: str) -> None:
    found = check_host(_write(tmp_path, 'G.toml', DEV_HOST + '\n' + extra))
    assert len(found) == 1, found
    assert named in found[0]


def test_a_host_key_or_its_unfilled_placeholder_is_declarable(tmp_path: Path) -> None:
    """SSH-HOST-KEY-DECLARED: the placeholder passes the check and is refused where the door uses it."""
    key = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample'
    for value in (key, 'FILL-FROM-A-TRUSTED-SOURCE'):
        text = f'{DEV_HOST}\n[ssh.host_keys]\n"node.example" = "{value}"\n'
        assert check_host(_write(tmp_path, 'G.toml', text)) == []


def test_a_dev_host_file_carrying_serve_is_refused(tmp_path: Path) -> None:
    """A workstation never serves a merge's parts (user ruling 2026-11-16); PLANTED CONTROL: the same card without."""
    assert check_host(_write(tmp_path, 'G.toml', DEV_HOST + '\n' + SSH_ROUTES)) == []
    found = check_host(_write(tmp_path, 'W.toml', DEV_HOST + '\n' + SSH_ROUTES + '\n[serve]\nparts = "every"\n'))
    assert [line for line in found if line.startswith('W.toml: [serve] on a host that is no HPC account')]


APP_FAMILY = '[dev]\nref = "integrate/main"\napps = ["demo"]\n'
APP_TABLE = '[demo.core]\ncache_cap_gb = 10\n'


def test_a_family_declared_app_table_is_open_in_a_dev_host_file(tmp_path: Path) -> None:
    """[dev] apps (family-only) opens [<app>] for every host; PLANTED CONTROL: without it the table is refused."""
    host = DEV_HOST.replace('ref = "integrate/main"\n', '') + '\n' + APP_TABLE
    family = _write(tmp_path, 'family.toml', APP_FAMILY)
    assert check_host(_write(tmp_path, 'G.toml', host), family) == []
    bare = _write(tmp_path, 'bare.toml', '[dev]\nref = "integrate/main"\n')
    assert [line for line in check_host(_write(tmp_path, 'H.toml', host), bare) if 'demo is not a declared key' in line]


def test_apps_is_a_family_fact_never_a_host_one(tmp_path: Path) -> None:
    family = _write(tmp_path, 'family.toml', APP_FAMILY)
    found = check_host(_write(tmp_path, 'G.toml', '[dev]\nhpc = []\napps = ["demo"]\n'), family)
    assert [line for line in found if 'apps' in line and 'family' in line], found


def test_a_family_declared_app_table_is_open_in_an_account_file() -> None:
    """The same opening reaches an HPC account file; PLANTED CONTROL: an undeclared app stays refused."""
    host = {'deploy': {'host': 'login01'}, 'demo': {'core': {'cache_cap_gb': 10}}}
    opened = {'dev': {'apps': ['demo']}}
    assert not [
        line for line in accounthost.check(Path('c-u.toml'), host, opened) if 'demo is not an account table' in line
    ]
    assert [line for line in accounthost.check(Path('c-u.toml'), host, {}) if 'demo is not an account table' in line]


FORGE_HOST = """\
[ops]
home = "/var/lib/ops"
python = "/opt/dev-lab/.venv/bin/python"

[ops.caddy]
sites = ["forge.example"]
allow = ["127.0.0.1/32"]

[ops.forge]
api = "http://127.0.0.1:3000"
admin = "site-admin"
repos = ["o/a", "o/b"]

[ops.forge.accounts.reader]
role = "read"
"""
FORGE_FAMILY = """\
[family_repos]
a = { remote = "https://forge.example/o/a.git", branch = "main" }
b = { remote = "https://forge.example/o/b.git", branch = "main" }
c = { remote = "https://github.com/x/c.git", branch = "main" }
"""


def test_the_forge_repos_are_the_family_repos_on_that_forge(tmp_path: Path) -> None:
    host, family = _write(tmp_path, 'f.toml', FORGE_HOST), _write(tmp_path, 'family.toml', FORGE_FAMILY)
    assert check_host(host, family) == []


@pytest.mark.parametrize(
    ('family', 'named'),
    [
        (FORGE_FAMILY + 'd = { remote = "https://forge.example/o/d.git", branch = "main" }\n', "missing ['o/d']"),
        (FORGE_FAMILY.replace('o/b.git', 'o/z.git'), "extra ['o/b']"),
    ],
)
def test_forge_repos_off_the_family_are_refused(tmp_path: Path, family: str, named: str) -> None:
    """Planted control: the forge's set is derived from [family_repos]; a repo either side lacks is named."""
    found = check_host(_write(tmp_path, 'f.toml', FORGE_HOST), _write(tmp_path, 'family.toml', family))
    assert [line for line in found if '[ops.forge] repos' in line and named in line], found


def test_an_account_file_may_declare_its_priority() -> None:
    """``[priority]`` (whose jobs the account serves first) is an account fact (hosts-config #73, user 2026-11-20).

    PLANTED CONTROL: an undeclared table is still refused.
    """
    host = {'deploy': {'host': 'login01'}, 'priority': {'logins': ['someone']}, 'nonsense': {}}
    found = accounthost.check(Path('c-u.toml'), host, {})
    assert not [line for line in found if 'priority is not an account table' in line], found
    assert [line for line in found if 'nonsense is not an account table' in line], found


REACH = '[storage.reach.results]\ncredentials_file = "~/.secrets/results"\n'


def test_a_host_file_declares_which_storage_remote_it_reaches(tmp_path: Path) -> None:
    """[storage.reach] is the host's own fact (lab_commons.storage); PLANTED CONTROL: an unknown table stays refused."""
    family = _write(tmp_path, 'family.toml', '[dev]\nref = "integrate/main"\n')
    host = DEV_HOST.replace('ref = "integrate/main"\n', '')
    assert check_host(_write(tmp_path, 'G.toml', host + '\n' + REACH), family) == []
    found = check_host(_write(tmp_path, 'H.toml', host + '\n[nope]\nx = 1\n'), family)
    assert [line for line in found if 'nope is not a declared key' in line]


def test_an_account_file_declares_which_storage_remote_it_reaches() -> None:
    host = {'deploy': {'host': 'login01'}, 'storage': {'reach': {'results': {'credentials_file': '~/.secrets/r'}}}}
    assert not [line for line in accounthost.check(Path('c-u.toml'), host, {}) if 'storage' in line]


def test_a_non_serving_account_declaring_a_schedule_is_refused() -> None:
    """SCHEDULER-ONLY-FOR-SERVING, at the declaration: ``[schedule]`` (the tick period) is serving baggage elsewhere.

    Measured 2026-11-20: every Ada research account file carried ``[schedule] tick_minutes = 15``.
    PLANTED CONTROL: the same table on a verification account is admitted.
    """

    def family(role: str) -> dict[str, object]:
        return {'hpc': {'grant': [{'cluster': 'c', 'user': 'u', 'role': role, 'slurm_account': 'a'}]}}

    host = {'deploy': {'host': 'login01'}, 'schedule': {'tick_minutes': 15}}
    refused = accounthost.check(Path('c-u.toml'), host, family('research'))
    assert [line for line in refused if '[schedule]' in line and 'SCHEDULER-ONLY-FOR-SERVING' in line], refused
    admitted = accounthost.check(Path('c-u.toml'), host, family('verification'))
    assert not [line for line in admitted if '[schedule]' in line], admitted
