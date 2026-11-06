"""Tests for dev_lab.dev.forgecred: refreshing a refused credential as git does after a 401."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lab_commons.credentials import credential_for, store_credential

from dev_lab.dev import forgecred
from dev_lab.dev.forgecred import refresh_credential

if TYPE_CHECKING:
    from pathlib import Path

HOST = 'forge.example.org'


def test_a_verified_provider_can_refresh_without_erasing_the_refused_secret(monkeypatch) -> None:
    """Verified provider-native refresh, not username-based destructive invalidation."""
    monkeypatch.setattr(forgecred, '_refresh_support', lambda *_a, **_kw: '')
    monkeypatch.setattr(forgecred, 'credential_for', lambda *_a, **_kw: ('oauth2', 'fresh'))
    outcome = refresh_credential(HOST, ('oauth2', 'stale'))
    assert outcome.credential == ('oauth2', 'fresh')
    assert outcome.state == 'refreshed'
    assert outcome.attempted


def test_a_store_with_no_refresh_token_is_never_erased_by_one_401(tmp_path: Path) -> None:
    """PLANTED CONTROL: a plain store keeps no refresh token, so it is never rejected.

    A reject would ERASE a credential that a transient 401 refused; the refresh leaves it stored and hands it back.
    """
    config = tmp_path / 'gitconfig'
    config.write_text(f'[credential]\n\thelper = "store --file={(tmp_path / "creds").as_posix()}"\n', encoding='utf-8')
    env = {'GIT_CONFIG_GLOBAL': str(config), 'GIT_CONFIG_SYSTEM': str(tmp_path / 'absent')}
    store_credential(HOST, 'alice', 'good', cwd=tmp_path, env=env)
    outcome = refresh_credential(HOST, ('alice', 'good'), cwd=tmp_path, env=env)
    assert outcome.credential == ('alice', 'good')
    assert outcome.state == 'kept'
    assert not outcome.attempted
    assert credential_for(HOST, cwd=tmp_path, env=env) == ('alice', 'good')


def test_a_refused_credential_that_exists_is_never_answered_with_a_re_login() -> None:
    """Ruling 2026-10-18: the forge never needs a re-login -- a 401/403 on a stored credential is retried and measured.

    Gitea's first attempt answers a transient 401 that the next one does not; a remedy naming ``auth login`` sent
    agents to hand the user a login. Only a box holding NO credential is told to log in (``forgeauth``).
    """
    remedies = (forgecred.AUTH_GONE, forgecred.AUTH_KEPT, forgecred.AUTH_REMEDY, forgecred.AUTH_TRANSIENT)
    assert all('auth login' not in said for said in remedies), remedies
    assert all('forge auth status' in said for said in (forgecred.AUTH_GONE, forgecred.AUTH_KEPT))
