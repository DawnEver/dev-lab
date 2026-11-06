"""Only fake metadata/stores: no test may consult, refresh or erase an actual credential."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Never

import pytest
from lab_commons.credentials import NoCredential

from dev_lab.dev import forgecred
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgework import Client

HOST = 'forge.example.invalid'
REFUSED = ('OAUTH_USER', 'planted-refused-secret')


@pytest.fixture(autouse=True)
def isolated_process_environment(monkeypatch) -> None:
    """Assertions may expose only planted context, never a caller's real environment secrets."""
    monkeypatch.setattr(os, 'environ', {'PATH': 'planted-safe-path'})


def _metadata(
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider: str | None = 'generic',
    helpers: tuple[str, ...] = ('manager',),
    scoped: bool = False,
    broken: bool = False,
    status: int = 0,
) -> list[tuple[Path | None, dict[str, str]]]:
    contexts = []

    def config(args: list[str], *, cwd: Path | None, env: Mapping[str, str]) -> tuple[int, str]:
        contexts.append((cwd, dict(env)))
        if status:
            return status, ''
        if broken:
            msg = 'planted configuration read failure'
            raise OSError(msg)
        if '--get-urlmatch' in args:
            assert args[-1] == f'https://{HOST}'
            return (1, '') if provider is None else (0, provider)
        if '--name-only' in args:
            return (0, 'credential.https://other.example.helper') if scoped else (1, '')
        return 0, '\0'.join(helpers) + '\0'

    monkeypatch.setattr(forgecred, '_git_config', config, raising=False)
    return contexts


def _store(
    monkeypatch: pytest.MonkeyPatch,
    *,
    answer: tuple[str, str] = ('oauth2', 'planted-new-secret'),
    empty: bool = False,
) -> list[str]:
    verbs = []

    def fill(*_args: object, **_kwargs: object) -> tuple[str, str]:
        verbs.append('fill')
        if empty:
            msg = 'planted store cannot provide a credential'
            raise NoCredential(msg)
        return answer

    def destructive(verb: str, *_args: object, **_kwargs: object) -> None:
        verbs.append(verb)

    monkeypatch.setattr(forgecred, 'credential_for', fill)
    monkeypatch.setattr(forgecred, '_credential', destructive, raising=False)
    return verbs


@pytest.mark.parametrize('provider', ['generic', 'github', 'azure-repos', 'unknown', None])
@pytest.mark.parametrize('username', ['OAUTH_USER', 'oauth2'])
def test_an_oauth_looking_username_never_authorizes_unknown_provider_erasure(monkeypatch, provider, username) -> None:
    _metadata(monkeypatch, provider=provider)
    verbs = _store(monkeypatch)
    refused = (username, REFUSED[1])
    outcome = forgecred.refresh_credential(HOST, refused, env={'GCM_PROVIDER': ''})
    assert verbs == []
    assert outcome.credential == refused
    assert not outcome.attempted
    assert outcome.reason
    assert refused[1] not in repr(outcome)


@pytest.mark.parametrize('helpers', [('store',), ('!opaque-helper',), ('manager --unsafe',), ('manager', 'store'), ()])
def test_unverified_or_multiple_helpers_keep_even_a_gitlab_oauth_credential(monkeypatch, helpers) -> None:
    _metadata(monkeypatch, provider='gitlab', helpers=helpers)
    verbs = _store(monkeypatch)
    outcome = forgecred.refresh_credential(HOST, ('oauth2', REFUSED[1]), env={'GCM_PROVIDER': ''})
    assert verbs == []
    assert not outcome.attempted


@pytest.mark.parametrize('options', [{'scoped': True}, {'broken': True}, {'status': 2}])
def test_uncertain_configuration_preserves_the_original_pair(monkeypatch, options) -> None:
    _metadata(monkeypatch, provider='gitlab', **options)
    verbs = _store(monkeypatch)
    outcome = forgecred.refresh_credential(HOST, ('oauth2', REFUSED[1]), env={'GCM_PROVIDER': ''})
    assert verbs == []
    assert outcome.credential == ('oauth2', REFUSED[1])
    assert not outcome.attempted


@pytest.mark.parametrize('empty', [False, True])
def test_verified_gitlab_uses_its_native_noninteractive_refresh_without_reject(monkeypatch, empty) -> None:
    _metadata(monkeypatch, provider='gitlab')
    verbs = _store(monkeypatch, empty=empty)
    outcome = forgecred.refresh_credential(HOST, ('oauth2', REFUSED[1]), env={'GCM_PROVIDER': ''})
    assert verbs == ['fill']
    assert outcome.attempted
    assert outcome.credential == (('oauth2', REFUSED[1]) if empty else ('oauth2', 'planted-new-secret'))
    assert outcome.reason


@pytest.mark.parametrize(
    ('configured', 'override', 'attempted'), [('gitlab', 'generic', False), ('generic', 'gitlab', True)]
)
def test_explicit_provider_environment_overrides_url_matched_configuration(
    monkeypatch, configured, override, attempted
) -> None:
    contexts = _metadata(monkeypatch, provider=configured)
    verbs = _store(monkeypatch)
    outcome = forgecred.refresh_credential(HOST, ('oauth2', REFUSED[1]), cwd=Path(), env={'GCM_PROVIDER': override})
    assert outcome.attempted is attempted
    assert verbs == (['fill'] if attempted else [])
    assert contexts
    assert all(cwd == Path() and env['GCM_PROVIDER'] == override for cwd, env in contexts)


def test_client_diagnosis_uses_the_typed_outcome_not_the_username() -> None:
    kept = forgecred.CredentialRefresh(REFUSED, 'kept', attempted=False, reason='unverified provider')
    client = Client(Forge(HOST, 'o', 'r'), REFUSED[1], username=REFUSED[0], refresh=lambda *_a: kept)
    assert not client._refresh()
    assert client._kept
    assert client.token == REFUSED[1]
    assert 'explicit user authorization' in forgecred.AUTH_KEPT
    assert 'store reads empty' not in forgecred.AUTH_KEPT


@pytest.mark.parametrize('error', [OSError('planted launch failure'), subprocess.TimeoutExpired(['git', 'config'], 1)])
def test_metadata_launch_failures_and_timeouts_keep_credentials(monkeypatch, error) -> None:
    def failed(*_args: object, **_kwargs: object) -> Never:
        raise error

    monkeypatch.setattr(forgecred, '_git_config', failed)
    verbs = _store(monkeypatch)
    outcome = forgecred.refresh_credential(HOST, ('oauth2', REFUSED[1]))
    assert verbs == []
    assert outcome.state == 'kept'
    assert outcome.credential == ('oauth2', REFUSED[1])


def test_metadata_verification_and_native_fill_share_one_effective_environment(monkeypatch) -> None:
    contexts = _metadata(monkeypatch, provider='generic')
    monkeypatch.setenv('PRESERVATION_TEST_CONTEXT', 'inherited')
    received = []

    def fill(_host: str, *, username: str, cwd: Path | None, env: Mapping[str, str]) -> tuple[str, str]:
        assert username == 'oauth2'
        received.append((cwd, dict(env)))
        return 'oauth2', 'planted-new-secret'

    monkeypatch.setattr(forgecred, 'credential_for', fill)
    result = forgecred.refresh_credential(HOST, ('oauth2', REFUSED[1]), cwd=Path(), env={'GCM_PROVIDER': 'gitlab'})
    assert result.state == 'refreshed'
    assert contexts
    assert received[0][1]['PRESERVATION_TEST_CONTEXT'] == 'inherited'
    assert all(context == received[0] for context in contexts)


@pytest.mark.parametrize('helpers', [('store', '', 'manager'), ('/tools/git-credential-manager',)])
def test_explicit_helper_reset_or_absolute_gcm_declaration_retains_native_refresh(monkeypatch, helpers) -> None:
    _metadata(monkeypatch, provider='gitlab', helpers=helpers)
    verbs = _store(monkeypatch)
    result = forgecred.refresh_credential(HOST, ('oauth2', REFUSED[1]))
    assert verbs == ['fill']
    assert result.state == 'refreshed'


def test_a_verified_provider_returning_the_same_pair_is_kept_not_falsely_refreshed(monkeypatch) -> None:
    refused = ('oauth2', REFUSED[1])
    _metadata(monkeypatch, provider='gitlab')
    verbs = _store(monkeypatch, answer=refused)
    result = forgecred.refresh_credential(HOST, refused)
    assert verbs == ['fill']
    assert result.attempted
    assert result.state == 'kept'
    assert result.credential == refused
