"""Break-glass on a GitHub forge acts as an App (one-hour installation token), never a standing personal token.

A GitHub PAT is a person's (or a bot account's) standing credential: it outlives every wave, names a user the
ruleset cannot name, and is the token the forge host must not hold. So ``[ops.breakglass.tokens]`` keys a GitHub host
only as a refusal naming the remedy, ``[ops.breakglass.apps]``; Gitea, which has no Apps, keeps its token.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dev_lab.ops import breakglass
from dev_lab.ops.config import Breakglass, Judge
from dev_lab.ops.secretplace import declared
from dev_lab.ops.served import app_of_forge, credential_files
from tests._ops_fixtures import GLASS, config

APP = {'app_id': 4242, 'key_file': '/etc/forge-breakglass/ops-app.pem'}
BASE: dict[str, Any] = {'account': 'b', 'state': 's', 'log': 'l', 'repos': GLASS}


def test_a_github_token_in_breakglass_is_refused_naming_the_app() -> None:
    with pytest.raises(ValueError, match=r'github\.com.*\[ops\.breakglass\.apps\]'):
        Breakglass(**BASE, tokens={'gitea.example': 't', 'github.com': 'pat'})


def test_a_github_app_serves_breakglass_and_gitea_keeps_its_token() -> None:
    role = Breakglass(**BASE, tokens={'gitea.example': 't'}, apps={'github.com': APP})
    assert app_of_forge(role.apps, GLASS[1]) == (4242, Path(APP['key_file']))
    assert app_of_forge(role.apps, GLASS[0]) is None  # control: Gitea has no App, its token stays
    assert role.token_file(GLASS[0]) == 't'
    assert set(credential_files(role.tokens, role.apps)) == {'t', APP['key_file']}


def test_a_github_token_in_the_judge_is_refused_naming_the_app() -> None:
    with pytest.raises(ValueError, match=r'github\.com.*\[ops\.judge\.apps\]'):
        Judge(user='judge', schedule='hourly', repos=('https://github.com/owner/beta',), tokens={'github.com': 'pat'})


def test_the_forge_of_an_app_repo_presents_a_minted_installation_token() -> None:
    role = Breakglass(**BASE, tokens={'gitea.example': 't'}, apps={'github.com': APP})
    minted: list[tuple[int, Path]] = []

    def mint(url: str, app_id: int, key: Path) -> str:
        minted.append((app_id, key))
        return f'installation-for-{url.split("/")[2]}'

    secrets = {'t': 'gitea-token'}
    assert breakglass.credential(role, GLASS[1], secret=secrets.__getitem__, mint=mint) == 'installation-for-github.com'
    assert minted == [(4242, Path(APP['key_file']))]
    assert breakglass.credential(role, GLASS[0], secret=secrets.__getitem__, mint=mint) == 'gitea-token'
    assert len(minted) == 1  # control: a Gitea repo mints nothing


def test_the_breakglass_app_key_is_a_declared_secret_of_its_account(tmp_path: Path) -> None:
    built = config(tmp_path, [])
    assert built.breakglass is not None
    owners = declared(built)
    glass = built.breakglass
    assert all(owners[path] == glass.account for path in credential_files(glass.tokens, glass.apps))
