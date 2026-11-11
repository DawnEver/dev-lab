"""``ops consent serve|enrol|keygen|ready``: the consent issuer's verbs, and the readiness every verifier answers.

Split out of :mod:`dev_lab.ops.__main__` (2026-11-11, MODULE-SIZE-ALARM), as :mod:`dev_lab.ops.configverbs` was:
the issuer's rules live in :mod:`dev_lab.ops.consent`; this module builds the issuer from a host's ``[ops.consent]``
and routes the verbs. ``ready`` is asked BEFORE a code is spent (:mod:`dev_lab.dev.planrun`): whether a consented
verb on this host could verify a credential and register its use.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from lab_commons.log import emit

from dev_lab.ops import totp
from dev_lab.ops.config import Consent, OpsConfig
from dev_lab.ops.consent import serve
from dev_lab.ops.consent.client import Register, public_key, remote_register
from dev_lab.ops.consent.credential import ConsentRefused, public_text
from dev_lab.ops.consent.issuer import Issuer, keygen

__all__ = ['VERBS', 'issuer', 'ready', 'run']

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
                  role.lockout_after, role.lockout_minutes, locked)  # fmt: skip


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


def ready(config: OpsConfig, *, alert: Alert) -> int:
    """``consent ready``: 0 when a consented verb here could verify AND register; 2 names the blocker."""
    try:
        key, _ = ends(config, alert=alert)
    except ConsentRefused as refused:
        emit(f'refused: {refused}', err=True)
        return 2
    where = 'the local issuer' if config.consent is not None else f'{config.consent_client.endpoint} over ssh'
    emit(f'[ops consent] ready: key {public_text(key)[:12]}, uses register at {where}')
    return 0


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
