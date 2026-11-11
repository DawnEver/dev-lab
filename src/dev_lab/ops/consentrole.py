"""The ``[ops]`` roles that hold the cluster's TOTP: the consent issuer, a host's client of it, the access account.

Plain declarations read by :func:`dev_lab.ops.config.load`; each states its fields once, as
:mod:`dev_lab.ops.backuprole` does for the backup roles.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ['Access', 'Consent', 'ConsentClient']


@dataclass(frozen=True)
class Consent:
    """The consent ISSUER (:mod:`dev_lab.ops.consent.issuer`): the cluster's TOTP seed, its signing key, its ledger.

    ``account`` is the restricted ssh account whose ForceCommand is ``consent serve``, ``keys`` its ssh keys; ``totp``
    the cluster's ONE TOTP secret (base32, root 600); ``key`` the Ed25519 private key (PEM, root 600); ``state`` the
    directory of the append-only ledger, the last accepted TOTP step and the lockout. ``issuer`` names it in each
    credential and labels the Authenticator entry; ``lockout_after`` consecutive wrong codes refuse every code for
    ``lockout_minutes`` (:mod:`dev_lab.ops.lockout`).
    """

    account: str
    totp: str
    key: str
    state: str
    keys: tuple[str, ...] = ()
    issuer: str = 'forge consent'
    lockout_after: int = 5
    lockout_minutes: float = 15.0


@dataclass(frozen=True)
class ConsentClient:
    """Where a host that is NOT the issuer verifies and registers a consent (:mod:`dev_lab.ops.consent.client`).

    ``endpoint`` is the issuer's ``<account>@<host>`` (its ForceCommand ``consent serve``), ``identity`` the ssh key
    this host's root signs in with (empty: ssh's default), ``known_hosts`` the file the issuer's host key is checked
    against strictly (empty: ssh's default) -- both may live in the ops user's home, made by that user and readable
    by root, since root keeps no ``~/.ssh`` -- and ``public_key`` the issuer's (empty: the packaged ``issuer.pub``).
    Read from THIS file, never root's machine file: an ops verb runs as root under ``sudo``.
    """

    endpoint: str
    public_key: str = ''
    identity: str = ''
    known_hosts: str = ''

    def table(self) -> dict[str, str]:
        """The client table :func:`~dev_lab.ops.consent.client.public_key` and ``remote_register`` read."""
        return {
            'endpoint': self.endpoint,
            'public_key': self.public_key,
            'identity': self.identity,
            'known_hosts': self.known_hosts,
        }


@dataclass(frozen=True)
class Access:
    """The troubleshooting account: ssh key AND a TOTP code (pam_oath), sudo limited to declared commands.

    ``keys`` are its ssh keys, ``oath`` the root-only pam_oath users file, ``commands`` what sudo may run (each a full
    command line, ``*`` as sudoers reads it), ``issuer`` the Authenticator's label. ``permit_open`` is the
    ``host:port`` targets the account may forward to (``ssh -J`` through this host); empty, it forwards nothing.
    ``totp`` is the host's ONE TOTP secret (base32, root 600); empty, the consent issuer's ``totp`` is it. ``oath``
    is DERIVED from it at install, never a second secret.
    """

    account: str
    keys: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    permit_open: tuple[str, ...] = ()
    totp: str = ''
    oath: str = '/etc/dev-lab/ops/users.oath'
    issuer: str = 'forge ops'
