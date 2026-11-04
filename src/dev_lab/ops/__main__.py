"""``python -m dev_lab.ops --config <toml> <verb>``: the one door of every host role.

Verbs: ``install``, ``promote``, ``breakglass serve|enrol|tick``, ``backup export|pull``, ``access enrol``.

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


def _alert(config: OpsConfig, title: str, detail: str) -> None:
    Notifier(config.merged).send(
        Notice(
            title,
            host=host_label(config.merged.get('notify', {})),
            context=Context(service='dev_lab.ops'),
            findings=(detail,),
        )
    )


def _secret(path: str) -> str:
    return Path(path).read_text(encoding='utf-8').strip()


def _access(config: OpsConfig, *, force: bool) -> int:
    if config.access is None:
        emit(f'[ops] {config.path} enables no [ops.access]', err=True)
        return 2
    emit(access.enrol(config.access, force=force))
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


def _breakglass(config: OpsConfig, verb: str, *, force: bool) -> int:
    role = config.breakglass
    if role is None:
        emit(f'[ops] {config.path} enables no [ops.breakglass]', err=True)
        return 2
    if verb == 'enrol':
        secret = totp.enrol(Path(role.totp), force=force)
        emit(totp.uri(secret, issuer=role.issuer, account=role.account))
        emit(
            '[ops] scan this URI (e.g. `qrencode -t ANSIUTF8 <uri>`) into the Authenticator; it is shown once', err=True
        )
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
    verbs.add_parser('backup').add_argument('action', choices=('export', 'pull'))
    opened = verbs.add_parser('access')
    opened.add_argument('action', choices=('enrol',))
    opened.add_argument('--force', action='store_true', help='replace an existing secret')
    args = parser.parse_args(argv)
    try:
        config = load(args.config)
    except (ValueError, TypeError) as bad:
        emit(f'[ops] {bad}', err=True)
        return 2
    if args.verb == 'install':
        as_root = sys.platform != 'win32' and os.geteuid() == 0
        done = install.install(config, args.root, chown=shutil.chown if as_root else None)
        for path, state in done.paths.items():
            emit(f'{state:9} {path}')
        emit('\n'.join(['next, on the live host:', *(f'  {step}' for step in done.next_steps)]))
        return 0
    if args.verb == 'promote':
        failed = [o for o in promote.run(config) if o.state == 'failed']
        for outcome in failed:
            _alert(config, f'promote FAILED {outcome.repo}', outcome.detail)
        return 1 if failed else 0
    if args.verb == 'backup':
        return _backup(config, args.action)
    if args.verb == 'access':
        return _access(config, force=args.force)
    return _breakglass(config, args.action, force=args.force)


if __name__ == '__main__':
    sys.exit(main())
