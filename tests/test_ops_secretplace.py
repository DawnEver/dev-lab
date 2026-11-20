"""``ops secret place``: one DECLARED secret file written 0600 for its declared reader, under one consent.

The consent is bound to the path and the content's digest; the value never reaches an argv, the output or a refusal.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
from _ops_fixtures import config
from lab_commons.storage import declared as storage_declared

from dev_lab.ops import __main__ as ops_main
from dev_lab.ops import redeemverbs, secretplace
from dev_lab.ops.config import OpsConfig
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.secretplace import SecretRefused

SECRET = b'planted-judge-token-0123456789\n'
JUDGE_FILE = '/etc/review-bot/gitea-token'


def _host(tmp_path: Path) -> OpsConfig:
    extra = (
        f'[ops.judge]\nuser = "judge"\nschedule = "*:0/5"\nrepos = ["https://gitea.example/owner/alpha"]\n'
        f'[ops.judge.tokens]\n"gitea.example" = "{JUDGE_FILE}"\n'
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


def _chown(seen: list[tuple[str, str | None]]) -> Callable[[Path, str | None, str | None], None]:
    return lambda path, user, _group: seen.append((path.name, user))


def test_a_declared_path_is_written_0600_for_its_declared_reader(tmp_path: Path) -> None:
    host, root, owned = _host(tmp_path), tmp_path / 'root', []
    consent = _Consent(secretplace.subject(JUDGE_FILE, SECRET))
    said = secretplace.place(
        secretplace.declared(host),
        str(host.path),
        JUDGE_FILE,
        SECRET,
        redeem=consent,
        credential={},
        chown=_chown(owned),
        root=root,
    )
    target = root / 'etc/review-bot/gitea-token'
    assert target.read_bytes() == SECRET
    assert owned == [('.gitea-token.placing', 'judge')]  # owned BEFORE the rename: never a wider file
    assert not list(target.parent.glob('.*.placing'))
    assert SECRET.decode().strip() not in said  # only the digest is said
    if secretplace.os.name == 'posix':  # st_mode always exists; only POSIX carries the 0600 bits
        assert target.stat().st_mode & 0o777 == 0o600


def test_an_undeclared_path_is_refused_before_the_consent_is_spent(tmp_path: Path) -> None:
    host = _host(tmp_path)
    consent = _Consent(secretplace.subject('/etc/shadow', SECRET))
    with pytest.raises(SecretRefused, match=r'not a secret file .* declares; declared: \[.*gitea-token'):
        secretplace.place(secretplace.declared(host), str(host.path), '/etc/shadow', SECRET, redeem=consent,
                          credential={}, chown=_chown([]), root=tmp_path / 'root')  # fmt: skip
    assert not consent.spent


def test_a_credential_for_other_bytes_does_not_write_these(tmp_path: Path) -> None:
    """Planted control: the user consented to one value; a different value at the same path is refused."""
    host, root = _host(tmp_path), tmp_path / 'root'
    consent = _Consent(secretplace.subject(JUDGE_FILE, b'the-value-the-user-was-shown\n'))
    with pytest.raises(SecretRefused) as refused:
        secretplace.place(
            secretplace.declared(host),
            str(host.path),
            JUDGE_FILE,
            SECRET,
            redeem=consent,
            credential={},
            chown=_chown([]),
            root=root,
        )
    assert SECRET.decode().strip() not in str(refused.value)  # the refusal names the request, never the value
    assert json.loads(str(refused.value).split('grant ', 1)[1].split(' and pass', 1)[0]) == secretplace.request(
        JUDGE_FILE, SECRET
    )
    assert not (root / 'etc/review-bot/gitea-token').exists()


def test_a_spent_credential_places_once(tmp_path: Path) -> None:
    host, root = _host(tmp_path), tmp_path / 'root'
    consent = _Consent(secretplace.subject(JUDGE_FILE, SECRET))
    secretplace.place(
        secretplace.declared(host),
        str(host.path),
        JUDGE_FILE,
        SECRET,
        redeem=consent,
        credential={},
        chown=_chown([]),
        root=root,
    )
    with pytest.raises(SecretRefused, match='does not consent'):
        secretplace.place(
            secretplace.declared(host),
            str(host.path),
            JUDGE_FILE,
            SECRET,
            redeem=consent,
            credential={},
            chown=_chown([]),
            root=root,
        )


def test_empty_content_is_refused(tmp_path: Path) -> None:
    host = _host(tmp_path)
    with pytest.raises(SecretRefused, match='no content on stdin'):
        secretplace.place(secretplace.declared(host), str(host.path), JUDGE_FILE, b'\n', redeem=_Consent(''),
                          credential={}, chown=_chown([]), root=tmp_path / 'root')  # fmt: skip


def test_the_subject_binds_both_the_path_and_the_content() -> None:
    one = secretplace.subject(JUDGE_FILE, SECRET)
    assert one != secretplace.subject('/etc/other', SECRET)
    assert one != secretplace.subject(JUDGE_FILE, SECRET + b'x')
    assert SECRET.decode().strip() not in json.dumps(secretplace.request(JUDGE_FILE, SECRET))


def test_the_declared_set_names_each_role_reader(tmp_path: Path) -> None:
    owners = secretplace.declared(_host(tmp_path))
    assert owners[JUDGE_FILE] == 'judge'
    assert owners[(tmp_path / 'creds').as_posix()] == 'promote'


def test_the_ops_cli_routes_secret_place_and_reads_stdin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    host = _host(tmp_path)
    seen: dict[str, object] = {}

    def fake_place(_owners: object, _source: str, path: str, content: bytes, **kwargs: object) -> str:
        seen.update(path=path, content=content, credential=kwargs['credential'])
        return 'placed'

    credential = tmp_path / 'cred.json'
    credential.write_text('{"id": "x"}', encoding='utf-8')
    monkeypatch.setattr(secretplace, 'place', fake_place)
    monkeypatch.setattr(redeemverbs, 'redeemer', lambda _config: lambda _action: _Consent(''))
    monkeypatch.setattr('sys.stdin', type('S', (), {'buffer': type('B', (), {'read': staticmethod(lambda: SECRET)})})())
    argv = ['--config', str(host.path), 'secret', 'place', '--path', JUDGE_FILE, '--credential', str(credential)]
    assert ops_main.main(argv) == 0
    assert seen == {'path': JUDGE_FILE, 'content': SECRET, 'credential': {'id': 'x'}}


def _reaching(tmp_path: Path) -> object:
    family = {'storage': {'remotes': {'results': {'type': 's3'}}}}
    machine = {'storage': {'reach': {'results': {'credentials_file': str(tmp_path / 'secrets' / 'results')}}}}
    return storage_declared(machine, family)


def test_a_workstation_places_the_credentials_file_its_machine_declares(tmp_path: Path) -> None:
    owners = secretplace.workstation_declared(_reaching(tmp_path), user='me')
    wanted = str(tmp_path / 'secrets' / 'results')
    assert owners == {wanted: 'me'}
    consent = _Consent(secretplace.subject(wanted, SECRET))
    said = secretplace.place(owners, 'the machine file', wanted, SECRET, redeem=consent, credential={},
                             chown=_chown([]))  # fmt: skip
    assert (tmp_path / 'secrets' / 'results').read_bytes() == SECRET
    assert 'owner me' in said


def test_a_workstation_refuses_a_path_its_machine_does_not_declare(tmp_path: Path) -> None:
    """PLANTED CONTROL: a file beside the declared one is never written, and the consent is never spent."""
    owners = secretplace.workstation_declared(_reaching(tmp_path), user='me')
    stray = str(tmp_path / 'secrets' / 'other')
    consent = _Consent(secretplace.subject(stray, SECRET))
    with pytest.raises(SecretRefused, match=r'not a secret file the machine file declares'):
        secretplace.place(owners, 'the machine file', stray, SECRET, redeem=consent, credential={}, chown=_chown([]))
    assert not consent.spent
    assert not (tmp_path / 'secrets' / 'other').exists()


def _entered(tmp_path: Path, *, asked: list[str], code_ok: bool = True, tty: bool = True) -> tuple[list[str], dict]:
    """``enter`` with a scripted terminal, a scripted issuer and a scripted remote listing."""
    answers = iter(['AKIA-planted', 'planted-secret-value'])
    seen: dict[str, Any] = {}

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return next(answers)

    def grant(request_file: Path) -> Path:
        seen['request'] = json.loads(request_file.read_text(encoding='utf-8'))
        if not code_ok:
            msg = 'the issuer refused the code'
            raise ConsentRefused(msg)
        held = tmp_path / 'held-1.json'
        held.write_text('{}', encoding='utf-8')
        return held

    def redeem(_found: Mapping[str, Any], wanted: str) -> None:
        if wanted != seen['request']['subject']:
            msg = 'not this subject'
            raise ConsentRefused(msg)

    said = secretplace.enter(
        str(tmp_path / 'secrets' / 'results'), storage=_reaching(tmp_path), ask=ask, tty=tty, grant=grant,
        requests=tmp_path / 'requests', check=lambda remote: f'{remote}: reached', redeem=redeem,
    )  # fmt: skip
    return said, seen


def test_enter_asks_each_transport_key_once_places_it_and_lists_the_remote(tmp_path: Path) -> None:
    asked: list[str] = []
    said, seen = _entered(tmp_path, asked=asked)
    placed = (tmp_path / 'secrets' / 'results').read_text(encoding='utf-8')
    assert placed == 'access_key_id = "AKIA-planted"\nsecret_access_key = "planted-secret-value"\n'
    assert asked == ['results access_key_id: ', 'results secret_access_key: ']
    assert seen['request'] == secretplace.request(str(tmp_path / 'secrets' / 'results'), placed.encode('utf-8'))
    assert said[-1] == 'results: reached'
    joined = '\n'.join(said) + json.dumps(seen) + (tmp_path / 'requests' / 'secret-results.request.json').read_text()
    assert 'planted-secret-value' not in joined
    assert 'AKIA-planted' not in joined


def test_enter_refuses_a_pipe_before_asking_anything(tmp_path: Path) -> None:
    """PLANTED CONTROL: no terminal -> nothing asked, nothing requested, nothing placed."""
    asked: list[str] = []
    with pytest.raises(SecretRefused, match=r'only at a terminal.*secretplace request'):
        _entered(tmp_path, asked=asked, tty=False)
    assert asked == []
    assert not (tmp_path / 'secrets' / 'results').exists()


def test_enter_with_a_refused_code_places_nothing(tmp_path: Path) -> None:
    """PLANTED CONTROL: the issuer refuses the code -> the secret file is never written."""
    with pytest.raises(ConsentRefused, match='refused the code'):
        _entered(tmp_path, asked=[], code_ok=False)
    assert not (tmp_path / 'secrets' / 'results').exists()


def test_enter_refuses_an_undeclared_path_before_asking(tmp_path: Path) -> None:
    """PLANTED CONTROL: a path no reached remote declares is refused before any key is asked."""
    asked: list[str] = []
    with pytest.raises(SecretRefused, match='not a secret file this machine declares'):
        secretplace.enter(
            str(tmp_path / 'secrets' / 'other'), storage=_reaching(tmp_path), ask=asked.append, tty=True,
            grant=lambda _f: tmp_path, requests=tmp_path, check=str,
        )  # fmt: skip
    assert asked == []
