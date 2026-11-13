"""The ops verbs a host role runs: install, promote, judge, probe, backup, access and breakglass.

Split out of :mod:`dev_lab.ops.__main__` (the one door's parser and routing); each verb is that docstring's. Every
verb alerts through :func:`alert`, every ``[alerts]`` channel.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from lab_commons.log import emit

from dev_lab.dev.forge import forge_of_url
from dev_lab.dev.forgework import Client
from dev_lab.ops import (
    access,
    backup,
    breakglass,
    consentverbs,
    install,
    judge,
    offsite,
    probe,
    promote,
    sshkey,
    totp,
)
from dev_lab.ops.config import OpsConfig
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.issuer import Issuer
from dev_lab.ops.consentrole import Consent
from dev_lab.supervise.alert import Notifier
from dev_lab.supervise.notice import Context, Notice, host_label

__all__ = [
    'access_verb',
    'alert',
    'backup_verb',
    'breakglass_verb',
    'install_verb',
    'judge_verb',
    'probe_verb',
    'promote_verb',
    'show',
]


def alert(config: OpsConfig, title: str, detail: str) -> bool:
    """Send through every ``[alerts]`` channel; whether any channel took it."""
    return any(
        delivery.ok
        for delivery in Notifier(config.merged).send(
            Notice(
                title,
                host=host_label(config.merged.get('notify', {})),
                context=Context(service='dev_lab.ops'),
                findings=(detail,),
            )
        )
    )


def _secret(path: str) -> str:
    """The stripped text of the secret file at *path*."""
    return Path(path).read_text(encoding='utf-8').strip()


def show(link: str, *, uri_only: bool) -> None:
    """The enrolment to the enrolling terminal only (stdout, never a log): a QR to scan, or the bare URI."""
    if uri_only:
        emit(link)
        return
    drawn = totp.qr(link)
    if drawn is None:
        emit(link)
        emit('[ops] no QR: install dev-lab[ops] (segno) to draw one; scan or type this URI, it is shown once', err=True)
        return
    emit(drawn)
    emit('[ops] scan this QR into the Authenticator; it is shown once (--uri prints the bare URI instead)', err=True)


def install_verb(config: OpsConfig, root: Path) -> int:
    """``install``: render this host's role files (as root: owned as the role declares); 2 when refused."""
    as_root = sys.platform != 'win32' and os.geteuid() == 0
    try:
        done = install.install(config, root, chown=shutil.chown if as_root else None)
    except ValueError as refused:
        emit(f'[ops install] refused: {refused}', err=True)
        return 2
    for path, state in done.paths.items():
        emit(f'{state:9} {path}')
    emit('\n'.join(['next, on the live host:', *(f'  {step}' for step in done.next_steps)]))
    return 0


def promote_verb(config: OpsConfig) -> int:
    """``promote``: one promotion pass; each failed repo alerted."""
    failed = [o for o in promote.run(config) if o.state == 'failed']
    for outcome in failed:
        alert(config, f'promote FAILED {outcome.repo}', outcome.detail)
    return 1 if failed else 0


def judge_verb(config: OpsConfig) -> int:
    """``judge``: one judging pass over ``[ops.judge]`` repos; each failed repo alerted."""
    if config.judge is None:
        emit(f'[ops] {config.path} enables no [ops.judge]', err=True)
        return 2
    failed = [o for o in judge.run(config) if o.state == 'failed']
    for outcome in failed:
        alert(config, f'judge FAILED {outcome.repo}', outcome.detail)
    return 1 if failed else 0


def _read_input(source: str) -> str:
    """A secret from a file, or stdin for ``-``: never an argument, which a process listing would show."""
    return sys.stdin.read() if source == '-' else Path(source).read_text(encoding='utf-8')


def access_verb(config: OpsConfig, action: str, *, force: bool, uri_only: bool, secret_from: str) -> int:
    """``access enrol|adopt``: the access second factor, shown only to the enrolling terminal."""
    if config.access is None:
        emit(f'[ops] {config.path} enables no [ops.access]', err=True)
        return 2
    try:
        if action == 'adopt':
            emit(access.adopt(config, _read_input(secret_from)))
        else:
            show(access.enrol(config, force=force), uri_only=uri_only)
    except (totp.TotpRefused, ValueError, OSError) as refused:
        emit(f'[ops access] refused: {refused}', err=True)
        return 2
    return 0


def backup_verb(config: OpsConfig, verb: str) -> int:
    """``backup export|pull``: one backup pass; a failure alerted."""
    role = config.backup
    if role is None or not (role.dumpers if verb == 'export' else role.source):
        emit(f'[ops] {config.path} declares no backup {verb} side', err=True)
        return 2
    try:
        if verb == 'export':
            backup.export(role, sys.stdout.buffer)
            return 0
        kept = backup.pull(role, datetime.now(UTC))
        files = sorted(path for path in kept.iterdir())
        if role.offsite is not None:
            offsite.upload(role.offsite, offsite.AwsCli(role.offsite), kept.name, files)
        emit(f'[ops backup] kept {kept} ({len(files)} file(s))' + (', off-site copied' if role.offsite else ''))
    except (backup.BackupRefused, OSError, ValueError) as failed:
        emit(f'[ops backup] {failed}', err=True)
        alert(config, f'backup {verb} FAILED', str(failed))
        return 1
    return 0


def _issuer(config: OpsConfig, role: Consent) -> Issuer:
    """The consent issuer of *role*, alerting through this host's channels."""
    return consentverbs.issuer(role, alert=lambda title, detail: alert(config, title, detail))


def breakglass_verb(config: OpsConfig, verb: str) -> int:
    """``breakglass serve|tick``: the break-glass wave server, or one tick of it."""
    role = config.breakglass
    if role is None:
        emit(f'[ops] {config.path} enables no [ops.breakglass]', err=True)
        return 2
    try:
        verifier, register = consentverbs.ends(config, alert=lambda title, detail: alert(config, title, detail))
    except ConsentRefused as refused:
        emit(f'refused: {refused}', err=True)
        return 2
    server = breakglass.Server(
        config,
        forge_for=lambda url: breakglass.ClientForge(url, breakglass.credential(role, url, secret=_secret)),
        alert=lambda title, detail: alert(config, title, detail),
        now=time.time,
        consent_key=verifier,
        register=register,
        key=sshkey.fingerprint(os.environ.get(sshkey.ENV, '')),
    )
    try:
        said = server.tick() if verb == 'tick' else server.handle(sys.stdin.readline())
    except breakglass.BreakglassRefused as refused:
        emit(f'refused: {refused}', err=True)
        return 2
    emit(said)
    return 0


def probe_verb(config: OpsConfig) -> int:
    """``probe``: one probe pass, each line said; its findings alerted."""
    role = config.probe
    if role is None:
        emit(f'[ops] {config.path} enables no [ops.probe]', err=True)
        return 2
    for line in probe.run(
        config,
        lambda url: Client(forge_of_url(url), _secret(role.token_file(url))),
        lambda title, detail: alert(config, title, detail),
    ):
        emit(f'[ops probe] {line}')
    return 0
