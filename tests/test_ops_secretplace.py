"""``ops secret place``: one DECLARED secret file written 0600 for its declared reader, under one consent.

The consent is bound to the path and the content's digest; the value never reaches an argv, the output or a refusal.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from _ops_fixtures import config

from dev_lab.ops import __main__ as ops_main
from dev_lab.ops import secretplace
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.secretplace import SecretRefused

SECRET = b'planted-judge-token-0123456789\n'
JUDGE_TOKEN = '/etc/review-bot/gitea-token'  # noqa: S105 -- a path, not a value


def _host(tmp_path: Path):  # noqa: ANN202 -- the fixture's OpsConfig
    extra = (
        f'[ops.judge]\nuser = "judge"\nschedule = "*:0/5"\nrepos = ["https://gitea.example/owner/alpha"]\n'
        f'[ops.judge.tokens]\n"gitea.example" = "{JUDGE_TOKEN}"\n'
    )
    return config(tmp_path, [], extra=extra)


class _Consent:
    """A redeemer granting exactly one subject, once: what an issued single-use credential does."""

    def __init__(self, granted: str) -> None:
        self.granted, self.spent = granted, False

    def __call__(self, _credential: Mapping[str, Any], subject: str) -> None:
        if subject != self.granted or self.spent:
            msg = 'the credential does not consent to this subject'
            raise ConsentRefused(msg)
        self.spent = True


def _chown(seen: list[tuple[str, str | None]]):  # noqa: ANN202
    return lambda path, user, _group: seen.append((path.name, user))


def test_a_declared_path_is_written_0600_for_its_declared_reader(tmp_path: Path) -> None:
    host, root, owned = _host(tmp_path), tmp_path / 'root', []
    consent = _Consent(secretplace.subject(JUDGE_TOKEN, SECRET))
    said = secretplace.place(host, JUDGE_TOKEN, SECRET, redeem=consent, credential={}, chown=_chown(owned), root=root)
    target = root / 'etc/review-bot/gitea-token'
    assert target.read_bytes() == SECRET
    assert owned == [('.gitea-token.placing', 'judge')]  # owned BEFORE the rename: never a wider file
    assert not list(target.parent.glob('.*.placing'))
    assert SECRET.decode().strip() not in said  # only the digest is said
    assert 'owner judge' in said
    if hasattr(target.stat(), 'st_mode') and secretplace.os.name == 'posix':
        assert target.stat().st_mode & 0o777 == 0o600


def test_an_undeclared_path_is_refused_before_the_consent_is_spent(tmp_path: Path) -> None:
    host = _host(tmp_path)
    consent = _Consent(secretplace.subject('/etc/shadow', SECRET))
    with pytest.raises(SecretRefused, match=r'not a secret file .* declares; declared: \[.*gitea-token'):
        secretplace.place(host, '/etc/shadow', SECRET, redeem=consent, credential={}, chown=_chown([]),
                          root=tmp_path / 'root')  # fmt: skip
    assert not consent.spent


def test_a_credential_for_other_bytes_does_not_write_these(tmp_path: Path) -> None:
    """Planted control: the user consented to one value; a different value at the same path is refused."""
    host, root = _host(tmp_path), tmp_path / 'root'
    consent = _Consent(secretplace.subject(JUDGE_TOKEN, b'the-value-the-user-was-shown\n'))
    with pytest.raises(SecretRefused) as refused:
        secretplace.place(host, JUDGE_TOKEN, SECRET, redeem=consent, credential={}, chown=_chown([]), root=root)
    assert SECRET.decode().strip() not in str(refused.value)  # the refusal names the request, never the value
    assert json.loads(str(refused.value).split('grant ', 1)[1].split(' and pass', 1)[0]) == secretplace.request(
        JUDGE_TOKEN, SECRET
    )
    assert not (root / 'etc/review-bot/gitea-token').exists()


def test_a_spent_credential_places_once(tmp_path: Path) -> None:
    host, root = _host(tmp_path), tmp_path / 'root'
    consent = _Consent(secretplace.subject(JUDGE_TOKEN, SECRET))
    secretplace.place(host, JUDGE_TOKEN, SECRET, redeem=consent, credential={}, chown=_chown([]), root=root)
    with pytest.raises(SecretRefused, match='does not consent'):
        secretplace.place(host, JUDGE_TOKEN, SECRET, redeem=consent, credential={}, chown=_chown([]), root=root)


def test_empty_content_is_refused(tmp_path: Path) -> None:
    host = _host(tmp_path)
    with pytest.raises(SecretRefused, match='no content on stdin'):
        secretplace.place(host, JUDGE_TOKEN, b'\n', redeem=_Consent(''), credential={}, chown=_chown([]),
                          root=tmp_path / 'root')  # fmt: skip


def test_the_subject_binds_both_the_path_and_the_content() -> None:
    one = secretplace.subject(JUDGE_TOKEN, SECRET)
    assert one != secretplace.subject('/etc/other', SECRET)
    assert one != secretplace.subject(JUDGE_TOKEN, SECRET + b'x')
    assert SECRET.decode().strip() not in json.dumps(secretplace.request(JUDGE_TOKEN, SECRET))


def test_the_declared_set_names_each_role_reader(tmp_path: Path) -> None:
    owners = secretplace.declared(_host(tmp_path))
    assert owners[JUDGE_TOKEN] == 'judge'
    assert owners[(tmp_path / 'creds').as_posix()] == 'promote'


def test_the_ops_cli_routes_secret_place_and_reads_stdin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    host = _host(tmp_path)
    seen: dict[str, object] = {}

    def fake_place(_config: object, path: str, content: bytes, **kwargs: object) -> str:
        seen.update(path=path, content=content, credential=kwargs['credential'])
        return 'placed'

    credential = tmp_path / 'cred.json'
    credential.write_text('{"id": "x"}', encoding='utf-8')
    monkeypatch.setattr(secretplace, 'place', fake_place)
    monkeypatch.setattr(ops_main, '_redeemer', lambda _config: lambda _action: _Consent(''))
    monkeypatch.setattr('sys.stdin', type('S', (), {'buffer': type('B', (), {'read': staticmethod(lambda: SECRET)})})())
    argv = ['--config', str(host.path), 'secret', 'place', '--path', JUDGE_TOKEN, '--credential', str(credential)]
    assert ops_main.main(argv) == 0
    assert seen == {'path': JUDGE_TOKEN, 'content': SECRET, 'credential': {'id': 'x'}}
