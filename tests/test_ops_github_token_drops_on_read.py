"""A retired standing GitHub token (#403) is DROPPED ON READ (owed a migration: FORMATS-MIGRATE-ONCE), not refused.

forge-a1, 2026-11-11: its old code ran the upgrade, whose self-check loads the LIVE file under the tip; the tip refused
``[ops.breakglass.tokens] "github.com"``, so no upgrade could land while the old code refused the new ``apps`` key.
Dropping the PAT is stricter, never wider: the role loses its GitHub repositories and refuses to act there until an
App is declared, and no dropped PAT is ever presented.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.ops.config import load

_GITEA = 'https://gitea.example/owner/alpha.git'
_GITHUB = 'https://github.com/owner/beta.git'


def _host(tmp: Path, *, apps: str = '') -> Path:
    home = (tmp / 'home').as_posix()
    text = f"""
[ops]
home = "{home}"
python = "/opt/ops/bin/python"
repos = ["{_GITEA}", "{_GITHUB}"]
[ops.breakglass]
account = "breakglass"
keys = ["ssh-ed25519 AAAA agent"]
repos = ["{_GITEA}", "{_GITHUB}"]
state = "{(tmp / 'state').as_posix()}"
log = "{(tmp / 'audit.log').as_posix()}"
[ops.breakglass.tokens]
"gitea.example" = "{(tmp / 'gitea-token').as_posix()}"
"github.com" = "{(tmp / 'github-token').as_posix()}"
{apps}
"""
    path = tmp / 'supervise.toml'
    path.write_text(text, encoding='utf-8')
    return path


def test_the_live_shape_loads_and_its_break_glass_holds_no_github_credential(tmp_path: Path, capsys) -> None:
    glass = load(_host(tmp_path), environ={}).breakglass
    assert glass is not None
    assert 'github.com' not in glass.tokens, 'a dropped PAT is never presented'
    assert not glass.apps
    assert _GITHUB not in glass.repos, 'with no App, break-glass refuses to act on GitHub'
    assert _GITEA in glass.repos
    said = capsys.readouterr().err
    assert '[ops.breakglass.tokens] github.com' in said
    assert '[ops.breakglass.apps]' in said, 'the remedy is named'


def test_a_github_token_beside_a_github_app_is_still_refused(tmp_path: Path) -> None:  # PLANTED CONTROL
    apps = f'[ops.breakglass.apps]\n"github.com" = {{app_id = 7, key_file = "{(tmp_path / "k.pem").as_posix()}"}}\n'
    with pytest.raises(ValueError, match=r'github\.com names both a token and an app'):
        load(_host(tmp_path, apps=apps), environ={})
