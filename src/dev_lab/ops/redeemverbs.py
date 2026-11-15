"""The ops verbs whose consent is REDEEMED on this host: ``upgrade``, ``forge`` and ``secret place``.

Split out of :mod:`dev_lab.ops.__main__` (the one door's parser and routing); each verb is that docstring's.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path

from lab_commons.log import emit

from dev_lab.ops import (
    consentverbs,
    forgeaccounts,
    forgeprotection,
    forgewho,
    secretplace,
    upgrade,
    upgradefollow,
)
from dev_lab.ops.config import OpsConfig
from dev_lab.ops.consent.client import redeem
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.hostverbs import alert

__all__ = ['forge_verb', 'redeemer', 'secret_place', 'upgrade_verb']


def redeemer(config: OpsConfig) -> Callable[[str], forgeaccounts.Redeem]:
    """``action -> redeem(credential, subject)``: the use registered once the credential names *subject*.

    Raises:
        ConsentRefused: no verifier key is reachable.

    """
    key, register = consentverbs.ends(config, alert=lambda title, detail: alert(config, title, detail))
    return lambda action: (
        lambda found, subject: redeem(found, action=action, subject=subject, key=key, register=register,
                                      now=time.time())
    )  # fmt: skip


def forge_verb(config: OpsConfig, args: argparse.Namespace) -> int:
    """``forge account ensure`` / ``forge token mint`` (:mod:`dev_lab.ops.forgeaccounts`), consented here."""
    if args.kind == 'token' and args.action == 'whoami':
        return forgewho.run(config, args)
    if config.forge is None:
        emit(f'[ops] {config.path} enables no [ops.forge]', err=True)
        return 2
    if args.kind == 'protect':  # plan reads no consent key; apply builds its redeemer when it spends
        return forgeprotection.run(config.forge, args, lambda: redeemer(config))
    try:
        redeem_for = redeemer(config)
    except ConsentRefused as refused:
        emit(f'refused: {refused}', err=True)
        return 2
    return forgeaccounts.run_verb(config.forge, args, redeem_for)


def secret_place(config: OpsConfig, args: argparse.Namespace) -> int:
    """``secret place`` (:mod:`dev_lab.ops.secretplace`): the content on stdin, the consent redeemed here."""
    if args.subject:  # what a preflight compares with the plan's grant; nothing is placed
        emit(secretplace.subject(args.path, sys.stdin.buffer.read()))
        return 0
    if not args.credential:
        emit('refused: secret place needs --credential (or --subject)', err=True)
        return 2
    try:
        granted = json.loads(Path(args.credential).read_text(encoding='utf-8'))
        said = secretplace.place(config, args.path, sys.stdin.buffer.read(), redeem=redeemer(config)(
            secretplace.ACTION), credential=granted, chown=shutil.chown)  # fmt: skip
    except (secretplace.SecretRefused, ConsentRefused, OSError, ValueError) as refused:
        emit(f'refused: {refused}', err=True)
        return 2
    emit(said)
    return 0


def upgrade_verb(config: OpsConfig, args: argparse.Namespace) -> int:
    """``upgrade``: install ``[ops.upgrade]``'s tip (a credential redeemed here, or ``--follow``); or the subject."""
    if config.upgrade is None:
        emit(f'[ops] {config.path} enables no [ops.upgrade]', err=True)
        return 2
    try:
        if args.follow:  # the timer: authorized by the declaration, never a credential
            code, said = upgradefollow.follow(config, alert=lambda title, detail: alert(config, title, detail))
            emit(f'[ops upgrade --follow] {said}', err=code != 0)
            return code
        if args.subject:  # what a preflight compares with the plan's ops.upgrade grant; nothing is installed
            emit(upgrade.subject(config))
            return 0
        if args.sha or args.credential:
            if not (args.sha and args.credential):
                emit(f'[ops upgrade] refused: --sha and --credential come together ({upgrade.ACTION})', err=True)
                return 2
            granted = json.loads(Path(args.credential).read_text(encoding='utf-8'))
            code, said = upgrade.planned(config, args.sha, redeem=redeemer(config)(upgrade.ACTION), credential=granted)
        else:
            code, said = upgrade.run(config)
    except (ConsentRefused, OSError, ValueError) as refused:
        emit(f'[ops upgrade] refused: {refused}', err=True)
        return 2
    emit(f'[ops upgrade] {said}', err=code != 0)
    return 0 if code == 0 else 1
