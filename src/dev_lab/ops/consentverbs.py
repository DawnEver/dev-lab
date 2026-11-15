"""``ops consent serve|enrol|keygen|ready``: the consent issuer's verbs, and the readiness every verifier answers.

Split out of :mod:`dev_lab.ops.__main__` (2026-11-11, MODULE-SIZE-ALARM), as :mod:`dev_lab.ops.configverbs` was:
the issuer's rules live in :mod:`dev_lab.ops.consent`; this module builds the issuer from a host's ``[ops.consent]``
and routes the verbs. ``ready`` is asked BEFORE a code is spent (:mod:`dev_lab.dev.planrun`): whether a consented
verb on this host could verify a credential and register its use.
"""

from __future__ import annotations

import getpass
import os
import stat
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from lab_commons.log import emit

from dev_lab.ops import totp
from dev_lab.ops.config import OpsConfig
from dev_lab.ops.consent import serve
from dev_lab.ops.consent.client import Register, public_key, remote_register
from dev_lab.ops.consent.credential import ConsentRefused, public_text
from dev_lab.ops.consent.issuer import Issuer, keygen
from dev_lab.ops.consentrole import Consent

__all__ = ['VERBS', 'issuer', 'ready', 'run', 'visible']

#: Every ``ops consent`` verb.
VERBS = ('serve', 'enrol', 'keygen', 'ready')

#: Raise one alert ``(title, detail)`` through the host's channels.
type Alert = Callable[[str, str], object]


def issuer(role: Consent, *, alert: Alert) -> Issuer:
    """The issuer *role* declares; the lockout's start is alerted."""

    def locked(until: float) -> None:
        when = datetime.fromtimestamp(until, UTC).isoformat(timespec='seconds')
        alert('consent LOCKED OUT', f'{role.lockout_after} wrong codes; every code refused until {when}')

    return Issuer(Path(role.totp), Path(role.key), Path(role.state), role.issuer, time.time,
                  role.lockout_after, role.lockout_minutes, locked, role.max_grants)  # fmt: skip


def ends(config: OpsConfig, *, alert: Alert) -> tuple[Ed25519PublicKey, Register]:
    """The verifier key and the register: the local issuer's, else the issuer's over ssh per ``[ops.consent_client]``.

    Raises:
        ConsentRefused: neither ``[ops.consent]`` nor ``[ops.consent_client]`` is declared, or no key is reachable.

    """
    if config.consent is not None:
        found = issuer(config.consent, alert=alert)
        return found.public(), found.register
    if config.consent_client is None:
        msg = (
            f'{config.path} declares neither [ops.consent] (the issuer) nor [ops.consent_client] '
            'endpoint = "<account>@<issuer host>" (with public_key, identity): no consent can be verified here'
        )
        raise ConsentRefused(msg)  # fmt: skip
    table = config.consent_client.table()
    return public_key(table), remote_register(table)


def visible(key: Path) -> None:
    """Prove the issuer's private *key* is in place by ``stat`` alone: present, a regular file, mode 600 on POSIX.

    ``consent ready`` runs unprivileged (the ops user over ssh), and the key is root 600: OPENING it can only fail
    there, so readiness never reads it -- ``stat`` needs search permission on its directory and nothing more.

    Raises:
        ConsentRefused: the key is missing, not a regular file, open to group/other, or its directory unsearchable.

    """
    try:
        found = key.stat()
    except FileNotFoundError as missing:
        msg = f'issuer key missing: {key}; `ops consent keygen` (as root) makes it'
        raise ConsentRefused(msg) from missing
    except PermissionError as hidden:
        msg = f'issuer key not visible to {getpass.getuser()}: {key}; grant search (o+x) on {key.parent}'
        raise ConsentRefused(msg) from hidden
    if not stat.S_ISREG(found.st_mode):
        msg = f'issuer key is not a regular file: {key}'
        raise ConsentRefused(msg)
    if os.name == 'posix' and found.st_mode & 0o077:
        msg = f'issuer key {key} is mode {stat.S_IMODE(found.st_mode):o}, not 600: chmod 600 it as root'
        raise ConsentRefused(msg)


def ready(config: OpsConfig, *, alert: Alert) -> int:
    """``consent ready``: 0 when a consented verb here could verify AND register; 2 names the blocker.

    At the issuer the private key is only STATTED (:func:`visible`) and the key shown is the PUBLISHED one a client
    verifies against (``[ops.consent_client] public_key``, else the machine file's or the packaged one).
    """
    try:
        if config.consent is None:
            key, _ = ends(config, alert=alert)
        else:
            visible(Path(config.consent.key))
            key = _published(config)
    except ConsentRefused as refused:
        emit(f'refused: {refused}', err=True)
        return 2
    where = 'the local issuer' if config.consent is not None else f'{config.consent_client.endpoint} over ssh'
    shown = 'no published key declared here' if key is None else f'key {public_text(key)[:12]}'
    emit(f'[ops consent] ready: {shown}, uses register at {where}')
    return 0


def _published(config: OpsConfig) -> Ed25519PublicKey | None:
    """The issuer's PUBLISHED key, or None when this host declares none.

    The issuer signs with its private key, so a host that declares no public key is still ready -- requiring it
    deadlocked the config apply that would declare it (forge-a1, 2026-11-12).
    """
    try:
        return public_key(None if config.consent_client is None else config.consent_client.table())
    except ConsentRefused:
        return None


def run(config: OpsConfig, verb: str, *, force: bool, alert: Alert, show: Callable[[str], None]) -> int:
    """Route one verb of :data:`VERBS`; *show* displays an enrolment's otpauth URI (as a QR or the bare URI)."""
    if verb == 'ready':
        return ready(config, alert=alert)
    role = config.consent
    if role is None:
        emit(f'[ops] {config.path} enables no [ops.consent]', err=True)
        return 2
    try:
        if verb == 'enrol':
            show(totp.uri(totp.enrol(Path(role.totp), force=force), issuer=role.issuer, account=role.account))
        elif verb == 'keygen':  # the PUBLIC key goes to every verifier: [consent] public_key, or the package
            emit(public_text(keygen(Path(role.key), force=force).public_key()))
        else:
            emit(serve.handle(issuer(role, alert=alert), sys.stdin.readline()))
    except (ConsentRefused, totp.TotpRefused) as refused:
        emit(f'refused: {refused}', err=True)
        return 2
    return 0
