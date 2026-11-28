"""SHORT-LIVED SSH USER CERTIFICATES: the consent issuer's TOTP proof, turned into a login the family's hosts admit.

User ruling 2026-11-28 (#1058). The user's TOTP code stays the human proof; the issuer
(:meth:`dev_lab.ops.consent.issuer.Issuer.certify`) exchanges a LIVE credential it issued for an OpenSSH user
certificate over the caller's public key, signed by the CA key it alone holds (``[ops.ssh_ca] key``). A host the
family administers trusts the CA's public key -- ONE row, ``[ops.ssh_ca] public_key`` -- through sshd's
``TrustedUserCAKeys``, rendered here by :func:`files` for :mod:`dev_lab.ops.install`. Shared cluster accounts are out
of scope: their sshd is not ours to configure, so they stay on keys.

LIFETIME. A certificate lives ``min(ttl, the credential's remaining life)`` -- ``[ops.ssh_ca] ttl`` is a declared
duration (``"1 h"``), and a wave's or a hold's credential bounds it from above, so a certificate never outlives the
consent it rides on. CLOCK SKEW: sshd has no tolerance of its own, so the issuer BACKDATES ``valid_after`` by
:data:`SKEW_S` (a host clock up to that far behind still admits it) and never extends ``valid_before`` (a host clock
ahead by *d* shortens the certificate by *d*).

REVOCATION is the short lifetime, plus the KRL row ``[ops.ssh_ca] revoked``: key ids (the credential id a certificate
is named by) rendered as a KRL spec, compiled on the host by ``ssh-keygen -k`` (:func:`steps`) before sshd reloads
-- sshd refuses EVERY key while its ``RevokedKeys`` file is absent.

N/N-1. ``accept_keys = true`` (N-1, the rollout) leaves each account's listed keys open beside the CA; ``false``
(N) renders ``AuthorizedKeysFile none`` for every account in ``principals``, so only a certificate opens it.

:func:`admits` is sshd's decision, checked offline: what a client runs before it presents a certificate, so an
expired or wrong one is refused by name instead of as ssh's bare ``Permission denied``.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Sequence
from typing import Final

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    SSHCertificate,
    SSHCertificateBuilder,
    SSHCertificateType,
    load_ssh_public_identity,
    load_ssh_public_key,
)

from dev_lab.ops.access import KEYS_DIR
from dev_lab.ops.consentrole import SshCa

__all__ = [
    'CA_FILE',
    'DROP_IN',
    'EXTENSIONS',
    'KRL_FILE',
    'SKEW_S',
    'SPEC_FILE',
    'CertRefused',
    'admits',
    'files',
    'public_line',
    'sign_certificate',
    'steps',
]

#: How far behind a host's clock may be and still admit a fresh certificate: ``valid_after`` is backdated by it.
SKEW_S: Final = 120.0
#: The CA public key sshd trusts, the KRL spec rendered from the row, and the KRL ``ssh-keygen -k`` compiles from it.
CA_FILE: Final = f'{KEYS_DIR}/user_ca.pub'
SPEC_FILE: Final = f'{KEYS_DIR}/revoked.spec'
KRL_FILE: Final = f'{KEYS_DIR}/revoked.krl'
#: The drop-in, numbered before every account's ``Match`` block so its global lines are read first.
DROP_IN: Final = 'etc/ssh/sshd_config.d/59-dev-lab-ops-ssh-ca.conf'
#: The extensions a certificate carries: a pty (the access account's second factor is typed) and local forwarding
#: (``ssh -J``); each account's ``Match`` block narrows further. No agent or X11 forwarding, no user rc.
EXTENSIONS: Final = ('permit-port-forwarding', 'permit-pty')
#: One account name: what a principal is (sshd matches it against the login name).
_ACCOUNT: Final = re.compile(r'[a-z_][a-z0-9_-]{0,31}')


class CertRefused(ValueError):
    """A certificate sshd would refuse, or a CA row that would render a lie; the message names why."""


def public_line(key: Ed25519PrivateKey) -> str:
    """*key*'s public half as one OpenSSH line (``ssh-ed25519 <base64>``): the ``[ops.ssh_ca] public_key`` row."""
    return key.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()


def _blob(line: str) -> bytes:
    parts = line.split()
    try:
        return base64.b64decode(parts[1], validate=True) if len(parts) >= 2 else b''  # noqa: PLR2004
    except binascii.Error, ValueError:
        return b''


def sign_certificate(
    ca: Ed25519PrivateKey, public: str, *, key_id: str, principals: Sequence[str], now: float, ttl: float, serial: int
) -> str:
    """An OpenSSH USER certificate over *public* (a key line), valid ``[now - SKEW_S, now + ttl]``; one line."""
    builder = (
        SSHCertificateBuilder()
        .public_key(load_ssh_public_key(public.encode()))  # type: ignore[arg-type]
        .type(SSHCertificateType.USER)
        .key_id(key_id.encode())
        .valid_principals([principal.encode() for principal in principals])
        .valid_after(int(now - SKEW_S))
        .valid_before(int(now + ttl))
        .serial(serial)
    )
    for name in EXTENSIONS:
        builder = builder.add_extension(name.encode(), b'')
    return builder.sign(ca).public_bytes().decode()


def admits(cert: str, *, ca_public: str | None, account: str, now: float, revoked: Sequence[str] = ()) -> None:
    """Refuse *cert* as sshd would for a login as *account* at *now*: CA, type, principal, window, KRL row.

    *ca_public* ``None`` skips the CA's identity (a client that holds no ``[ops.ssh_ca]`` row; the host still checks).

    Raises:
        CertRefused: the first reason, each naming its door.

    """
    try:
        found = load_ssh_public_identity(cert.strip().encode())
    except (ValueError, TypeError) as bad:
        msg = 'not an OpenSSH certificate line; ask the issuer for one (consent ssh-cert)'
        raise CertRefused(msg) from bad
    if not isinstance(found, SSHCertificate):
        msg = 'a plain public key, not a certificate; ask the issuer for one (consent ssh-cert)'
        raise CertRefused(msg)
    try:
        found.verify_cert_signature()
    except Exception as bad:  # cryptography raises InvalidSignature, or ValueError for a foreign key type
        msg = 'the certificate signature does not verify'
        raise CertRefused(msg) from bad
    if ca_public is not None and _blob(
        found.signature_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()
    ) != _blob(ca_public):
        msg = 'the certificate is signed by another CA than [ops.ssh_ca] public_key; ask this issuer for one'
        raise CertRefused(msg)
    if found.type != SSHCertificateType.USER:
        msg = 'a host certificate, not a user certificate'
        raise CertRefused(msg)
    if account.encode() not in found.valid_principals:
        names = sorted(p.decode() for p in found.valid_principals)
        msg = f'the certificate names no principal {account!r} (it names {names}); ask for one naming it'
        raise CertRefused(msg)
    if now < found.valid_after:
        msg = f'the certificate is not valid yet ({found.valid_after - now:.0f} s early): a clock is wrong'
        raise CertRefused(msg)
    if now >= found.valid_before:
        msg = f'the certificate expired {now - found.valid_before:.0f} s ago; a new consent code issues another'
        raise CertRefused(msg)
    if found.key_id.decode() in revoked:
        msg = f'the certificate {found.key_id.decode()!r} is revoked ([ops.ssh_ca] revoked)'
        raise CertRefused(msg)


def _checked(role: SshCa) -> None:
    if not role.public_key.startswith('ssh-ed25519 ') or len(_blob(role.public_key)) == 0:
        msg = '[ops.ssh_ca] public_key must be one "ssh-ed25519 <base64>" line (consent ca-keygen prints it)'
        raise ValueError(msg)
    if not role.principals or (bad := [p for p in role.principals if not _ACCOUNT.fullmatch(p)]):
        msg = f'[ops.ssh_ca] principals must be a non-empty list of account names; refused {role.principals}'
        raise ValueError(msg)
    if bad := [ident for ident in role.revoked if not ident or set(ident) & set('\n\r')]:
        msg = f'[ops.ssh_ca] revoked holds certificate key ids, one line each; refused {bad}'
        raise ValueError(msg)


def files(role: SshCa) -> dict[str, str]:
    """The CA public key, the KRL spec and the sshd drop-in trusting both, by root-relative path.

    Raises:
        ValueError: the row would render a lie (:func:`_checked`).

    """
    _checked(role)
    drop_in = f'TrustedUserCAKeys {CA_FILE}\nRevokedKeys {KRL_FILE}\n'
    return {
        CA_FILE.lstrip('/'): role.public_key + '\n',
        SPEC_FILE.lstrip('/'): ''.join(f'id: {ident}\n' for ident in role.revoked),
        DROP_IN: drop_in,
    }


def steps() -> list[str]:
    """Compile the KRL from its spec -- the step that must precede any sshd reload."""
    return [f'ssh-keygen -k -f {KRL_FILE} -s {CA_FILE} {SPEC_FILE}']
