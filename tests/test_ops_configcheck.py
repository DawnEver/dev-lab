"""A config-source repository is checked by STRUCTURE: hosts load; the family file holds no local fact or secret."""

from __future__ import annotations

from pathlib import Path

import pytest

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
