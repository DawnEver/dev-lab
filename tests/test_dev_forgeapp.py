"""A GitHub App judge: its JWT, its installation token, and the gate that reads ONLY its check run.

The RSA key is generated per test run, never committed. PLANTED CONTROLS: the declared App's ``success`` check run
at the head passes the gate, and against it the same-named run from another App, from Actions, at another head,
still in progress, or concluding ``failure`` each blocks.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from dev_lab.dev import forgeapp
from dev_lab.dev import forgereview_bundle as fb
from dev_lab.dev._forge_journal import WRITES, outbox_dir
from dev_lab.dev._forge_records import PullRequest
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgecontexts import JUDGE_CHECK
from dev_lab.dev.forgereview_declared import review_from
from dev_lab.dev.forgework import Client
from dev_lab.dev.reviewgate import DeclarationUnread, app_verdicts

APP = 5619495
HEAD = 'a' * 40
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
FORGE = Forge('github.com', 'o', 'r')


@pytest.fixture(scope='module')
def key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _pem(key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


def _unb64(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + '=' * (-len(part) % 4))


def test_the_jwt_is_rs256_signed_by_the_key_and_lives_under_ten_minutes(key: rsa.RSAPrivateKey) -> None:
    head, body, signature = forgeapp.app_jwt(APP, _pem(key), NOW).split('.')
    assert json.loads(_unb64(head)) == {'alg': 'RS256', 'typ': 'JWT'}
    claims = json.loads(_unb64(body))
    assert claims['iss'] == str(APP)
    assert claims['iat'] == int((NOW - timedelta(seconds=60)).timestamp())
    assert 0 < claims['exp'] - int(NOW.timestamp()) <= 600
    key.public_key().verify(_unb64(signature), f'{head}.{body}'.encode(), padding.PKCS1v15(), hashes.SHA256())


def test_a_key_that_is_not_rsa_is_refused() -> None:
    with pytest.raises(TypeError, match='RSA'):
        forgeapp.app_jwt(APP, _pem(ec.generate_private_key(ec.SECP256R1())), NOW)


class _Response:
    def __init__(self, status: int, payload: object) -> None:
        self.status, self._payload = status, json.dumps(payload).encode()

    def getheader(self, _name: str) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


class _GitHub:
    """GitHub's App endpoints: who the JWT is, the repository's installation, and its token exchange."""

    def __init__(self, app_id: int = APP) -> None:
        self.app_id, self.asked = app_id, []
        self._last: tuple[str, str, dict[str, str]] = ('', '', {})

    def __call__(self, _host: str, _timeout: float) -> _GitHub:
        return self

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None) -> None:
        del body
        self._last = (method, path, dict(headers or {}))
        self.asked.append((method, path, (headers or {}).get('Authorization', '').split(' ')[0]))

    def getresponse(self) -> _Response:
        method, path, _ = self._last
        answers = {
            ('GET', '/app'): {'id': self.app_id, 'slug': 'acme-review'},
            ('GET', '/repos/o/r/installation'): {'id': 77},
            ('POST', '/app/installations/77/access_tokens'): {'token': 'inst', 'expires_at': '2026-11-04T13:00:00Z'},
        }
        return _Response(200, answers[(method, path)])

    def close(self) -> None:
        pass


def test_the_installation_token_is_minted_once_per_run_and_names_the_app(
    tmp_path: Path, key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(forgeapp, '_MINTED', {})
    pem = tmp_path / 'app.pem'
    pem.write_bytes(_pem(key))
    github = _GitHub()
    for _ in range(2):
        app, token = forgeapp.installation(FORGE, APP, pem, transport=github, clock=lambda: NOW)
        assert (app, token) == (forgeapp.App(APP, 'acme-review'), 'inst')
    assert github.asked == [
        ('GET', '/app', 'Bearer'), ('GET', '/repos/o/r/installation', 'Bearer'),
        ('POST', '/app/installations/77/access_tokens', 'Bearer'),
    ]  # fmt: skip
    assert app.login == 'acme-review[bot]'
    client = forgeapp.AppClient(FORGE, 'inst', app=app)
    assert client.whoami() == 'acme-review[bot]'  # never asks /user
    assert (forgeapp.app_of(client), forgeapp.app_of(Client(FORGE, 'inst'))) == (app, None)


def test_a_key_github_names_another_app_for_is_refused(
    tmp_path: Path, key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(forgeapp, '_MINTED', {})
    pem = tmp_path / 'app.pem'
    pem.write_bytes(_pem(key))
    with pytest.raises(ValueError, match='names App 1'):
        forgeapp.installation(FORGE, APP, pem, transport=_GitHub(app_id=1), clock=lambda: NOW)


def _run(*, app: int | None = APP, head: str = HEAD, status: str = 'completed', conclusion: str = 'success',
         ident: int = 1, slug: str = 'acme-review') -> dict[str, Any]:  # fmt: skip
    owner = {'id': app, 'slug': slug} if app is not None else None
    return {'id': ident, 'name': JUDGE_CHECK, 'head_sha': head, 'status': status, 'conclusion': conclusion,
            'app': owner}  # fmt: skip


def test_an_app_judge_on_gitea_is_refused() -> None:
    with pytest.raises(DeclarationUnread, match='no GitHub'):
        app_verdicts(Client(Forge('gitea.example', 'o', 'r'), 't'), HEAD)


_JUDGE = '[tool.dev_lab.review]\nwhere = "judge"\n'


def test_a_judge_repo_declares_exactly_one_identity() -> None:
    assert review_from(_JUDGE + f'judge_app = {APP}\n', 'x').judge_app == APP
    assert review_from(_JUDGE + 'judge_login = "bot"\n', 'x').judge_login == 'bot'
    for both_or_none in ('', f'judge_login = "bot"\njudge_app = {APP}\n'):
        with pytest.raises(ValueError, match='exactly ONE identity'):
            review_from(_JUDGE + both_or_none, 'x')


@pytest.mark.parametrize('bad', ['true', '-1', '"5619495"'])
def test_a_judge_app_that_is_no_app_id_is_refused(bad: str) -> None:
    with pytest.raises(ValueError, match='no GitHub App id'):
        review_from(_JUDGE + f'judge_app = {bad}\n', 'x')


class _GitHubTakingChecks(_GitHub):
    """:class:`_GitHub` that also takes a check run, noting which journal entries existed as it arrived."""

    def __init__(self, journal: Path) -> None:
        super().__init__()
        self.journal, self.journaled = journal, []

    def getresponse(self) -> _Response:
        method, path, _ = self._last
        if (method, path) == ('POST', '/repos/o/r/check-runs'):
            self.journaled.append(sorted(p.name for p in self.journal.glob('*.json')))
            return _Response(201, {'id': 1})
        return super().getresponse()


def test_the_judge_runs_from_a_directory_that_is_no_checkout_journaling_into_its_home(
    tmp_path: Path, key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deployed unit: cwd ``/`` (no git repo), only HOME. The check run posts; its journal is under HOME's state.

    PLANTED CONTROL: the checkout-derived outbox the judge used before raises in that same directory.
    """
    nowhere, home = tmp_path / 'nowhere', tmp_path / 'home'
    nowhere.mkdir()
    home.mkdir()
    monkeypatch.chdir(nowhere)
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('USERPROFILE', str(home))
    monkeypatch.delenv('XDG_STATE_HOME', raising=False)
    monkeypatch.setattr(forgeapp, '_MINTED', {})
    pem = tmp_path / 'app.pem'
    pem.write_bytes(_pem(key))
    state = home / '.local' / 'state' / fb.JUDGE_STATE_REL
    github = _GitHubTakingChecks(state / WRITES)
    monkeypatch.setattr(fb, 'app_client', lambda *a, **k: forgeapp.app_client(*a, **k, transport=github))
    monkeypatch.setattr(fb, 'review_runtimes', lambda _given: {})
    pull = PullRequest(7, 't', 'open', '', '', 'a', 'h', 'integrate/main', head_sha=HEAD)
    monkeypatch.setattr(
        fb, 'judge_pending',
        lambda client, **_: [fb.post_verdict(client, pull, fb.Verdict('APPROVED', 'ok')), 'posted'][1:],
    )  # fmt: skip
    argv = ['judge', '--url', 'https://github.com/o/r', '--app-id', str(APP), '--app-key-file', str(pem)]
    assert fb.main(argv) == 0
    assert len(github.journaled) == 1
    assert len(github.journaled[0]) == 1, 'journaled under the declared state before it was sent'
    assert list((state / WRITES).glob('*.json')) == [], 'and acknowledged once GitHub answered'
    assert list(nowhere.iterdir()) == []
    with pytest.raises(RuntimeError, match='not a git repository'):
        outbox_dir(nowhere)
