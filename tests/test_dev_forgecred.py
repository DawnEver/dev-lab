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


def test_a_store_with_no_refresh_token_is_never_erased_by_one_401(tmp_path: Path) -> None:
    """PLANTED CONTROL: a plain store keeps no refresh token, so it is never rejected.

    A reject would ERASE a credential that a transient 401 refused; the refresh leaves it stored and hands it back.
    """
    config = tmp_path / 'gitconfig'
    config.write_text(f'[credential]\n\thelper = "store --file={(tmp_path / "creds").as_posix()}"\n', encoding='utf-8')
    env = {'GIT_CONFIG_GLOBAL': str(config), 'GIT_CONFIG_SYSTEM': str(tmp_path / 'absent')}
    store_credential(HOST, 'alice', 'good', cwd=tmp_path, env=env)
    assert refresh_credential(HOST, ('alice', 'good'), cwd=tmp_path, env=env) == ('alice', 'good')
    assert credential_for(HOST, cwd=tmp_path, env=env) == ('alice', 'good')


def test_a_refresh_fills_again_as_the_refused_username_never_another_identity(tmp_path: Path) -> None:
    """A refreshed serve credential stays the bot's: the second fill names the refused username."""
    config = tmp_path / 'gitconfig'
    config.write_text(f'[credential]\n\thelper = "store --file={(tmp_path / "creds").as_posix()}"\n', encoding='utf-8')
    env = {'GIT_CONFIG_GLOBAL': str(config), 'GIT_CONFIG_SYSTEM': str(tmp_path / 'absent')}
    store_credential(HOST, 'dev', 'D', cwd=tmp_path, env=env)
    store_credential(HOST, 'OAUTH_USER', 'stale', cwd=tmp_path, env=env)
    with pytest.raises(NoCredential, match='OAUTH_USER'):  # never the developer's 'dev'
        refresh_credential(HOST, ('OAUTH_USER', 'stale'), cwd=tmp_path, env=env)
