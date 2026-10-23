"""Tests for dev_lab.dev.forgecred: refreshing a refused credential as git does after a 401."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from _forge_fake import oauth_env
from lab_commons.credentials import NoCredential, credential_for, store_credential

from dev_lab.dev.forgecred import refresh_credential

if TYPE_CHECKING:
    from pathlib import Path

HOST = 'forge.example.org'


def test_a_refresh_rejects_the_refused_secret_and_fills_again_as_git_does_after_a_401(tmp_path: Path) -> None:
    """The GCM OAuth shape: ``reject`` drops the expired access token, the next ``fill`` answers a fresh one."""
    env = oauth_env(tmp_path)
    stale = credential_for(HOST, cwd=tmp_path, env=env)
    assert stale == ('OAUTH_USER', 'stale')
    assert refresh_credential(HOST, stale, cwd=tmp_path, env=env) == ('OAUTH_USER', 'fresh')


def test_a_refresh_of_a_store_that_held_only_the_refused_secret_leaves_no_credential(tmp_path: Path) -> None:
    """PLANTED CONTROL: a plain store keeps no refresh token, so after ``reject`` nothing is left -- refused."""
    config = tmp_path / 'gitconfig'
    config.write_text(f'[credential]\n\thelper = "store --file={(tmp_path / "creds").as_posix()}"\n', encoding='utf-8')
    env = {'GIT_CONFIG_GLOBAL': str(config), 'GIT_CONFIG_SYSTEM': str(tmp_path / 'absent')}
    store_credential(HOST, 'alice', 'revoked', cwd=tmp_path, env=env)
    with pytest.raises(NoCredential):
        refresh_credential(HOST, ('alice', 'revoked'), cwd=tmp_path, env=env)
