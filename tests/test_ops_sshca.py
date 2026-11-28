"""Issuer-signed short-lived ssh user certificates (#1058): every refusal sits beside its planted control.

The CA and user keys here are generated per test in a temporary directory; no real key is read, none is printed.
OpenSSH's own ``ssh-keygen`` is the reference where the check is OpenSSH's (a KRL query, a certificate's parse).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from _ops_fixtures import NOW, RFC_KEY, code, config
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from dev_lab.dev import remote
from dev_lab.ops import sshca
from dev_lab.ops.config import load
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.issuer import Issuer, keygen
from dev_lab.ops.consentrole import SshCa
from dev_lab.ops.install import files, install
from dev_lab.ops.totp import STEP

_SSH_KEYGEN = shutil.which('ssh-keygen') or ''
needs_openssh = pytest.mark.skipif(not _SSH_KEYGEN, reason='OpenSSH ssh-keygen is the reference and is absent')
WAVE = {'action': 'breakglass.wave', 'subject': 'dev-lab wave', 'params': {'hours': 4, 'max_merges': 3}}


def _public(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()


@pytest.fixture
def ca() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


@pytest.fixture
def user() -> str:
    return _public(Ed25519PrivateKey.generate())


def _role(ca: Ed25519PrivateKey, **extra: object) -> SshCa:
    return SshCa(public_key=sshca.public_line(ca), principals=('consent', 'breakglass'), **extra)  # type: ignore[arg-type]


def _cert(ca: Ed25519PrivateKey, user: str, *, principals: tuple[str, ...] = ('consent',), ttl: float = 600.0) -> str:
    return sshca.sign_certificate(ca, user, key_id='cred-1', principals=principals, now=NOW, ttl=ttl, serial=7)


def test_a_live_certificate_for_its_principal_is_admitted(ca: Ed25519PrivateKey, user: str) -> None:
    sshca.admits(_cert(ca, user), ca_public=sshca.public_line(ca), account='consent', now=NOW + 60)


def test_an_expired_certificate_is_refused(ca: Ed25519PrivateKey, user: str) -> None:
    cert, public = _cert(ca, user, ttl=600.0), sshca.public_line(ca)
    sshca.admits(cert, ca_public=public, account='consent', now=NOW + 599)  # the control: one second before
    with pytest.raises(sshca.CertRefused, match='expired'):
        sshca.admits(cert, ca_public=public, account='consent', now=NOW + 601)


def test_the_skew_backdates_the_start_and_never_extends_the_end(ca: Ed25519PrivateKey, user: str) -> None:
    cert, public = _cert(ca, user), sshca.public_line(ca)
    sshca.admits(cert, ca_public=public, account='consent', now=NOW - sshca.SKEW_S + 1)  # a host clock behind
    with pytest.raises(sshca.CertRefused, match='not valid yet'):
        sshca.admits(cert, ca_public=public, account='consent', now=NOW - sshca.SKEW_S - 1)


def test_a_wrong_principal_is_refused(ca: Ed25519PrivateKey, user: str) -> None:
    cert, public = _cert(ca, user, principals=('consent',)), sshca.public_line(ca)
    sshca.admits(cert, ca_public=public, account='consent', now=NOW)  # the control
    with pytest.raises(sshca.CertRefused, match="principal 'breakglass'"):
        sshca.admits(cert, ca_public=public, account='breakglass', now=NOW)


def test_another_ca_is_refused(ca: Ed25519PrivateKey, user: str) -> None:
    other = sshca.public_line(Ed25519PrivateKey.generate())
    with pytest.raises(sshca.CertRefused, match='another CA'):
        sshca.admits(_cert(ca, user), ca_public=other, account='consent', now=NOW)


def test_a_revoked_key_id_is_refused(ca: Ed25519PrivateKey, user: str) -> None:
    cert, public = _cert(ca, user), sshca.public_line(ca)
    sshca.admits(cert, ca_public=public, account='consent', now=NOW, revoked=('cred-2',))  # the control
    with pytest.raises(sshca.CertRefused, match='revoked'):
        sshca.admits(cert, ca_public=public, account='consent', now=NOW, revoked=('cred-1',))


@needs_openssh
def test_openssh_reads_the_certificate_and_the_rendered_krl_revokes_it(
    tmp_path: Path, ca: Ed25519PrivateKey, user: str
) -> None:
    cert = tmp_path / 'user-cert.pub'
    cert.write_text(_cert(ca, user) + '\n', encoding='utf-8')
    said = subprocess.run([_SSH_KEYGEN, '-L', '-f', str(cert)], capture_output=True, text=True, check=True).stdout
    assert 'user certificate' in said
    assert 'Key ID: "cred-1"' in said
    for revoked, verdict in ((('cred-1',), 'REVOKED'), (('cred-2',), 'ok')):  # the KRL row, and its control
        rendered = sshca.files(_role(ca, revoked=revoked))
        ca_pub, spec, krl = tmp_path / 'ca.pub', tmp_path / 'revoked.spec', tmp_path / 'revoked.krl'
        ca_pub.write_text(rendered[sshca.CA_FILE.lstrip('/')], encoding='utf-8')
        spec.write_text(rendered[sshca.SPEC_FILE.lstrip('/')], encoding='utf-8')
        subprocess.run([_SSH_KEYGEN, '-k', '-f', str(krl), '-s', str(ca_pub), str(spec)], capture_output=True,
                       check=True)  # fmt: skip
        query = subprocess.run(
            [_SSH_KEYGEN, '-Q', '-f', str(krl), str(cert)], capture_output=True, text=True, check=False
        )
        assert verdict in query.stdout, query.stdout
        krl.unlink()


def _host_with_ca(tmp_path: Path, block: str) -> Path:
    host = config(tmp_path, [], extra=block)
    return host.path


def _ca_block(ca: Ed25519PrivateKey, *, accept_keys: bool) -> str:
    return (
        f'\n[ops.ssh_ca]\npublic_key = "{sshca.public_line(ca)}"\nprincipals = ["consent", "breakglass"]\n'
        f'revoked = ["cred-9"]\naccept_keys = {str(accept_keys).lower()}\nttl = "2 h"\n'
    )


def test_n_minus_1_accepts_both_the_ca_and_the_listed_keys(tmp_path: Path, ca: Ed25519PrivateKey) -> None:
    host = load(_host_with_ca(tmp_path, _ca_block(ca, accept_keys=True)), environ={})
    assert host.ssh_ca is not None
    assert host.ssh_ca.ttl == 7200.0  # declared with its unit, held in seconds
    rendered = files(host)
    drop_in = rendered[sshca.DROP_IN]
    assert f'TrustedUserCAKeys {sshca.CA_FILE}' in drop_in
    assert f'RevokedKeys {sshca.KRL_FILE}' in drop_in
    assert rendered[sshca.CA_FILE.lstrip('/')] == sshca.public_line(ca) + '\n'
    assert rendered[sshca.SPEC_FILE.lstrip('/')] == 'id: cred-9\n'
    consent = rendered['etc/ssh/sshd_config.d/60-dev-lab-ops-consent.conf']
    assert 'AuthorizedKeysFile /etc/dev-lab/ops/consent.keys' in consent  # N-1: the keys still open it


def test_n_drops_the_listed_keys_of_a_certified_account(tmp_path: Path, ca: Ed25519PrivateKey) -> None:
    rendered = files(load(_host_with_ca(tmp_path, _ca_block(ca, accept_keys=False)), environ={}))
    assert 'AuthorizedKeysFile none' in rendered['etc/ssh/sshd_config.d/60-dev-lab-ops-consent.conf']
    assert f'TrustedUserCAKeys {sshca.CA_FILE}' in rendered[sshca.DROP_IN]


def test_no_ca_declared_renders_no_ca(tmp_path: Path) -> None:
    rendered = files(config(tmp_path, []))
    assert sshca.DROP_IN not in rendered
    assert (
        'AuthorizedKeysFile /etc/dev-lab/ops/consent.keys'
        in rendered['etc/ssh/sshd_config.d/60-dev-lab-ops-consent.conf']
    )


def test_the_krl_is_built_before_sshd_reloads(tmp_path: Path, ca: Ed25519PrivateKey) -> None:
    steps = install(load(_host_with_ca(tmp_path, _ca_block(ca, accept_keys=True)), environ={}), tmp_path / 'root')
    built = next(i for i, step in enumerate(steps.next_steps) if step.startswith('ssh-keygen -k'))
    reload = next(i for i, step in enumerate(steps.next_steps) if 'reload ssh' in step)
    assert built < reload  # sshd refuses every key while its RevokedKeys file is absent


def test_a_ca_principal_must_be_one_account(ca: Ed25519PrivateKey) -> None:
    with pytest.raises(ValueError, match='principals'):
        sshca.files(SshCa(public_key=sshca.public_line(ca), principals=('consent,root',)))
    with pytest.raises(ValueError, match='public_key'):
        sshca.files(SshCa(public_key='ssh-ed25519 notbase64!', principals=('consent',)))


class _Issuer:
    def __init__(self, tmp: Path, role: SshCa) -> None:
        (tmp / 'totp').write_text(RFC_KEY + '\n', encoding='utf-8')
        keygen(tmp / 'consent.key')
        self.clock = [NOW]
        self.issuer = Issuer(tmp / 'totp', tmp / 'consent.key', tmp / 'state', 'test issuer', lambda: self.clock[0],
                             ca=role)  # fmt: skip

    def code(self) -> str:
        return code(int((self.clock[0] - NOW) // STEP))


def test_the_issuer_certifies_a_live_credential_within_its_life(tmp_path: Path, user: str) -> None:
    ca_key = keygen(tmp_path / 'ca.key')
    host = _Issuer(
        tmp_path,
        SshCa(public_key=sshca.public_line(ca_key), principals=('consent',), ttl=3600.0, key=str(tmp_path / 'ca.key')),
    )
    credential = host.issuer.issue(WAVE, host.code())  # a wave credential lives 300 s by default
    cert = host.issuer.certify(credential, user, ['consent'])
    sshca.admits(cert, ca_public=sshca.public_line(ca_key), account='consent', now=NOW + 1)
    left = credential['expires'] - NOW
    with pytest.raises(sshca.CertRefused, match='expired'):  # never longer than the credential it rides on
        sshca.admits(cert, ca_public=sshca.public_line(ca_key), account='consent', now=NOW + left + 1)
    ledger = (tmp_path / 'state' / 'ledger.jsonl').read_text(encoding='utf-8')
    event = json.loads(ledger.splitlines()[-1])
    assert event['event'] == 'certified'
    assert event['id'] == credential['id']
    assert user.split()[1] not in ledger  # the ledger never holds key material


def test_the_issuer_refuses_an_undeclared_principal_and_a_dead_credential(tmp_path: Path, user: str) -> None:
    ca_key = keygen(tmp_path / 'ca.key')
    host = _Issuer(
        tmp_path, SshCa(public_key=sshca.public_line(ca_key), principals=('consent',), key=str(tmp_path / 'ca.key'))
    )
    credential = host.issuer.issue(WAVE, host.code())
    with pytest.raises(ConsentRefused, match='root'):
        host.issuer.certify(credential, user, ['root'])
    host.clock[0] = credential['expires'] + 3600
    with pytest.raises(ConsentRefused, match='expired'):
        host.issuer.certify(credential, user, ['consent'])


def test_an_issuer_with_no_ca_refuses_by_name(tmp_path: Path, user: str) -> None:
    host = _Issuer(tmp_path, SshCa(public_key='', principals=()))
    host.issuer.ca = None
    credential = host.issuer.issue(WAVE, host.code())
    with pytest.raises(ConsentRefused, match=r'\[ops.ssh_ca\]'):
        host.issuer.certify(credential, user, ['consent'])


def test_the_client_presents_its_certificate_explicitly(tmp_path: Path) -> None:
    cert = tmp_path / 'c-cert.pub'
    argv = remote.ssh_argv('consent@forge.example', 'true', batch=True, host_keys={}, certificate=str(cert))
    assert argv[argv.index(f'CertificateFile={cert}') - 1] == '-o'
    assert not any('CertificateFile' in word for word in remote.ssh_argv('a@b.example', 'true', batch=True,
                                                                           host_keys={}))  # fmt: skip
