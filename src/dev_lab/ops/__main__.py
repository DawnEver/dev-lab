"""``python -m dev_lab.ops --config <toml> <verb>``: the one door of every host role.

Verbs: ``install``, ``promote``, ``breakglass serve|enrol|tick``, ``backup export|pull``, ``access enrol|adopt``.

Exit codes: 0 done, 1 a failure (alerted), 2 refused. ``install --root <dir>`` renders into a test root.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from lab_commons.log import emit

from dev_lab.ops import access, backup, breakglass, install, offsite, promote, sshkey, totp
from dev_lab.ops.config import OpsConfig, load
from dev_lab.supervise.alert import Notifier
from dev_lab.supervise.notice import Context, Notice, host_label

__all__ = ['main']


def _alert(config: OpsConfig, title: str, detail: str) -> bool:
    """Send *title* on every configured channel; whether any delivered it."""
    deliveries = Notifier(config.merged).send(
        Notice(
            title,
            host=host_label(config.merged.get('notify', {})),
            context=Context(service='dev_lab.ops'),
            findings=(detail,),
        )
    )
    return any(delivery.ok for delivery in deliveries)


def _secret(path: str) -> str:
    return Path(path).read_text(encoding='utf-8').strip()


def _show(link: str, *, uri_only: bool) -> None:
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


def _install(config: OpsConfig, root: Path) -> int:
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


def _read_input(source: str) -> str:
    """A secret from a file, or stdin for ``-``: never an argument, which a process listing would show."""
    return sys.stdin.read() if source == '-' else Path(source).read_text(encoding='utf-8')


def _access(config: OpsConfig, action: str, *, force: bool, uri_only: bool, secret_from: str) -> int:
    if config.access is None:
        emit(f'[ops] {config.path} enables no [ops.access]', err=True)
        return 2
    try:
        if action == 'adopt':
            emit(access.adopt(config, _read_input(secret_from)))
        else:
            _show(access.enrol(config, force=force), uri_only=uri_only)
    except (totp.TotpRefused, ValueError, OSError) as refused:
        emit(f'[ops access] refused: {refused}', err=True)
        return 2
    return 0


def _backup(config: OpsConfig, verb: str) -> int:
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
        _alert(config, f'backup {verb} FAILED', str(failed))
        return 1
    return 0


def _breakglass(config: OpsConfig, verb: str, *, force: bool, uri_only: bool) -> int:
    role = config.breakglass
    if role is None:
        emit(f'[ops] {config.path} enables no [ops.breakglass]', err=True)
        return 2
    if verb == 'enrol':
        secret = totp.enrol(Path(role.totp), force=force)
        _show(totp.uri(secret, issuer=role.issuer, account=role.account), uri_only=uri_only)
        return 0
    server = breakglass.Server(
        config,
        forge_for=lambda url: breakglass.ClientForge(url, _secret(role.token_file(url))),
        alert=lambda title, detail: _alert(config, title, detail),
        now=time.time,
        key=sshkey.fingerprint(os.environ.get(sshkey.ENV, '')),
    )
    try:
        said = server.tick() if verb == 'tick' else server.handle(sys.stdin.readline())
    except breakglass.BreakglassRefused as refused:
        emit(f'refused: {refused}', err=True)
        return 2
    emit(said)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Route one verb; see the module docstring."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.ops', description=__doc__.splitlines()[0])
    parser.add_argument('--config', type=Path, required=True)
    verbs = parser.add_subparsers(dest='verb', required=True)
    verbs.add_parser('install').add_argument('--root', type=Path, default=Path('/'))
    verbs.add_parser('promote')
    glass = verbs.add_parser('breakglass')
    glass.add_argument('action', choices=('serve', 'enrol', 'tick'))
    glass.add_argument('--force', action='store_true', help='enrol: replace an existing secret')
    glass.add_argument('--uri', action='store_true', help='enrol: print the otpauth URI, not its QR')
    verbs.add_parser('backup').add_argument('action', choices=('export', 'pull'))
    opened = verbs.add_parser('access')
    opened.add_argument('action', choices=('enrol', 'adopt'))
    opened.add_argument('--force', action='store_true', help='replace an existing secret')
    opened.add_argument('--uri', action='store_true', help='print the otpauth URI, not its QR')
    opened.add_argument('--secret-file', default='-', help="adopt: the host's existing base32 secret (- reads stdin)")
    args = parser.parse_args(argv)
    try:
        config = load(args.config)
    except (ValueError, TypeError) as bad:
        emit(f'[ops] {bad}', err=True)
        return 2
    if args.verb == 'install':
        return _install(config, args.root)
    if args.verb == 'promote':
        failed = [o for o in promote.run(config) if o.state == 'failed']
        for outcome in failed:
            _alert(config, f'promote FAILED {outcome.repo}', outcome.detail)
        return 1 if failed else 0
    if args.verb == 'backup':
        return _backup(config, args.action)
    if args.verb == 'access':
        return _access(config, args.action, force=args.force, uri_only=args.uri, secret_from=args.secret_file)
    return _breakglass(config, args.action, force=args.force, uri_only=args.uri)


if __name__ == '__main__':
    sys.exit(main())
