"""``ops forge account ensure`` / ``ops forge token mint``: machine accounts made through a consented door.

Every use redeems a single-use consent credential whose subject is the request's digest, is audited without the
token, and talks to Gitea through a runner the tests fake.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from dev_lab.ops import forgeaccounts
from dev_lab.ops.config import Forge
from dev_lab.ops.consent.actions import ACTIONS, SINGLE
from dev_lab.ops.forgeaccounts import AccountRequest, ForgeRefused, TokenRequest


@dataclass
class FakeGitea:
    """A Gitea holding users, collaborators ``{(repo, login): permission}`` and tokens ``{login: {name: scopes}}``."""

    users: set[str] = field(default_factory=set)
    repos: set[str] = field(default_factory=lambda: {'owner/a', 'owner/b'})
    collaborators: dict[tuple[str, str], str] = field(default_factory=dict)
    tokens: dict[str, dict[str, str]] = field(default_factory=dict)
    created: list[tuple[str, str]] = field(default_factory=list)

    def user_exists(self, login: str) -> bool:
        return login in self.users

    def create_user(self, login: str, email: str) -> None:
        self.users.add(login)
        self.created.append((login, email))

    def permission(self, repo: str, login: str) -> str | None:
        if repo not in self.repos:
            msg = f'no repository {repo}'
            raise ForgeRefused(msg)
        return self.collaborators.get((repo, login))

    def grant_read(self, repo: str, login: str) -> None:
        self.collaborators[repo, login] = 'read'

    def token_names(self, login: str) -> set[str]:
        return set(self.tokens.get(login, {}))

    def delete_token(self, login: str, name: str) -> None:
        del self.tokens[login][name]

    def generate_token(self, login: str, name: str, scopes: str) -> str:
        self.tokens.setdefault(login, {})[name] = scopes
        return f'secret-{name}'


def _role(tmp_path: Path) -> Forge:
    return Forge(api='http://127.0.0.1:3000', admin='site-admin', read_only=('server-reader',),
                 log=str(tmp_path / 'forge.jsonl'))  # fmt: skip


def _consent(subject: str) -> Callable[[object], str]:
    def redeem(_credential: object) -> str:
        return subject

    return redeem


def _audit(tmp_path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (tmp_path / 'forge.jsonl').read_text(encoding='utf-8').splitlines()]


def test_the_two_actions_are_single_use_registry_rows() -> None:
    assert {forgeaccounts.ACCOUNT_ACTION, forgeaccounts.MINT_ACTION} <= set(ACTIONS)
    assert {ACTIONS[forgeaccounts.ACCOUNT_ACTION].scope, ACTIONS[forgeaccounts.MINT_ACTION].scope} == {SINGLE}


def test_ensure_creates_a_restricted_reader_grants_exactly_read_and_reports_drift(tmp_path: Path) -> None:
    gitea = FakeGitea(collaborators={('owner/b', 'server-reader'): 'write'})
    request = AccountRequest('server-reader', ('owner/b', 'owner/a'))
    said = forgeaccounts.ensure(_role(tmp_path), gitea, request, redeem=_consent(request.subject()), credential={},
                                by='ops')  # fmt: skip
    assert gitea.created == [('server-reader', 'server-reader@noreply.invalid')]
    assert gitea.collaborators == {('owner/a', 'server-reader'): 'read', ('owner/b', 'server-reader'): 'read'}
    assert said == ('created server-reader', 'owner/a: granted read', 'owner/b: drift write -> read')
    assert _audit(tmp_path)[-1]['what'] == list(said)
    # PLANTED CONTROL: a second run changes nothing and says so
    again = forgeaccounts.ensure(_role(tmp_path), gitea, request, redeem=_consent(request.subject()), credential={},
                                 by='ops')  # fmt: skip
    assert again == ('server-reader exists', 'owner/a: read', 'owner/b: read')
    assert len(gitea.created) == 1


def test_a_credential_for_another_request_is_refused_and_nothing_changes(tmp_path: Path) -> None:
    gitea = FakeGitea()
    request = AccountRequest('server-reader', ('owner/a',))
    other = AccountRequest('server-reader', ('owner/a', 'owner/b')).subject()
    with pytest.raises(ForgeRefused, match='another request'):
        forgeaccounts.ensure(_role(tmp_path), gitea, request, redeem=_consent(other), credential={}, by='ops')
    assert gitea.users == set()
    assert gitea.collaborators == {}


def test_mint_prints_the_token_once_and_audits_everything_but_it(tmp_path: Path) -> None:
    gitea = FakeGitea(users={'server-reader'})
    request = TokenRequest('server-reader', 'host-x', 'read:repository', rotate=False)
    minted = forgeaccounts.mint(_role(tmp_path), gitea, request, redeem=_consent(request.subject()), credential={},
                               by='ops')  # fmt: skip
    assert minted == 'secret-host-x'
    log = (tmp_path / 'forge.jsonl').read_text(encoding='utf-8')
    assert 'secret-host-x' not in log
    assert _audit(tmp_path)[-1] | {'at': ''} == {
        'at': '', 'by': 'ops', 'action': forgeaccounts.MINT_ACTION, 'login': 'server-reader', 'name': 'host-x',
        'scope': 'read:repository', 'rotated': False,
    }  # fmt: skip


def test_a_read_only_login_is_refused_a_write_scope(tmp_path: Path) -> None:
    gitea = FakeGitea(users={'server-reader', 'builder'})
    wide = TokenRequest('server-reader', 'host-x', 'read:repository,write:repository', rotate=False)
    with pytest.raises(ForgeRefused, match='read-only'):
        forgeaccounts.mint(_role(tmp_path), gitea, wide, redeem=_consent(wide.subject()), credential={}, by='ops')
    assert gitea.tokens == {}
    # PLANTED CONTROL: a login not declared read-only may hold a write scope
    other = TokenRequest('builder', 'host-x', 'write:repository', rotate=False)
    forgeaccounts.mint(_role(tmp_path), gitea, other, redeem=_consent(other.subject()), credential={}, by='ops')
    assert gitea.tokens == {'builder': {'host-x': 'write:repository'}}


def test_a_duplicate_name_is_refused_unless_rotated(tmp_path: Path) -> None:
    gitea = FakeGitea(users={'server-reader'}, tokens={'server-reader': {'host-x': 'read:repository'}})
    plain = TokenRequest('server-reader', 'host-x', 'read:repository', rotate=False)
    with pytest.raises(ForgeRefused, match='--rotate'):
        forgeaccounts.mint(_role(tmp_path), gitea, plain, redeem=_consent(plain.subject()), credential={}, by='ops')
    rotated = TokenRequest('server-reader', 'host-x', 'read:repository', rotate=True)
    minted = forgeaccounts.mint(_role(tmp_path), gitea, rotated, redeem=_consent(rotated.subject()), credential={},
                               by='ops')  # fmt: skip
    assert minted == 'secret-host-x'
    assert _audit(tmp_path)[-1]['rotated'] is True


def test_a_mint_for_an_absent_login_is_refused(tmp_path: Path) -> None:
    gitea = FakeGitea()
    request = TokenRequest('server-reader', 'host-x', 'read:repository', rotate=False)
    with pytest.raises(ForgeRefused, match='account ensure'):
        forgeaccounts.mint(_role(tmp_path), gitea, request, redeem=_consent(request.subject()), credential={},
                           by='ops')  # fmt: skip


def test_the_gitea_cli_adapter_runs_as_the_gitea_user_and_reads_a_raw_token() -> None:
    calls: list[list[str]] = []

    def run(argv: list[str]) -> tuple[int, str]:
        calls.append(argv)
        return 0, 'tok123\n'

    role = Forge(api='http://127.0.0.1:3000', admin='site-admin', config='/etc/gitea/app.ini')
    cli = forgeaccounts.GiteaCli(role, run=run, http=lambda *_a: (200, None))
    assert cli.generate_token('server-reader', 'host-x', 'read:repository') == 'tok123'
    assert calls[-1] == [
        'runuser', '-u', 'gitea', '--', 'gitea', '--config', '/etc/gitea/app.ini', 'admin', 'user',
        'generate-access-token', '--username', 'server-reader', '--token-name', 'host-x', '--scopes',
        'read:repository', '--raw',
    ]  # fmt: skip
