"""``python -m dev_lab.ops --config <toml> <verb>``: the one door of every host role.

Verbs: ``install``, ``promote``, ``judge``, ``upgrade``, ``probe``, ``breakglass serve|tick``,
``consent serve|enrol|keygen``, ``backup export|pull``, ``access enrol|adopt``, ``disk``, ``clean``
(:mod:`dev_lab.ops.disk`), ``config apply`` (:mod:`dev_lab.ops.configdoor`).

Exit codes: 0 done, 1 a failure (alerted), 2 refused. ``install --root <dir>`` renders into a test root.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from lab_commons.log import emit

from dev_lab.dev.forge import forge_of_url
from dev_lab.dev.forgework import Client
from dev_lab.ops import (
    access,
    backup,
    breakglass,
    configdoor,
    disk,
    install,
    judge,
    offsite,
    probe,
    promote,
    sshkey,
    totp,
    upgrade,
)
from dev_lab.ops.config import Consent, OpsConfig, load
from dev_lab.ops.consent import serve as consent_serve
from dev_lab.ops.consent.client import public_key, redeem
from dev_lab.ops.consent.credential import ConsentRefused, public_text
from dev_lab.ops.consent.issuer import Issuer, keygen
from dev_lab.supervise.alert import Notifier
from dev_lab.supervise.notice import Context, Notice, host_label

__all__ = ['main']


def _alert(config: OpsConfig, title: str, detail: str) -> bool:
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


def _promote(config: OpsConfig) -> int:
    failed = [o for o in promote.run(config) if o.state == 'failed']
    for outcome in failed:
        _alert(config, f'promote FAILED {outcome.repo}', outcome.detail)
    return 1 if failed else 0


def _judge(config: OpsConfig) -> int:
    if config.judge is None:
        emit(f'[ops] {config.path} enables no [ops.judge]', err=True)
        return 2
    failed = [o for o in judge.run(config) if o.state == 'failed']
    for outcome in failed:
        _alert(config, f'judge FAILED {outcome.repo}', outcome.detail)
    return 1 if failed else 0


def _upgrade(config: OpsConfig) -> int:
    if config.upgrade is None:
        emit(f'[ops] {config.path} enables no [ops.upgrade]', err=True)
        return 2
    code, said = upgrade.run(config)
    emit(f'[ops upgrade] {said}', err=code != 0)
    return 0 if code == 0 else 1


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


def _issuer(config: OpsConfig, role: Consent) -> Issuer:
    def locked(until: float) -> None:
        when = datetime.fromtimestamp(until, UTC).isoformat(timespec='seconds')
        _alert(config, 'consent LOCKED OUT', f'{role.lockout_after} wrong codes; every code refused until {when}')

    return Issuer(Path(role.totp), Path(role.key), Path(role.state), role.issuer, time.time,
                  role.lockout_after, role.lockout_minutes, locked)  # fmt: skip


def _consent(config: OpsConfig, verb: str, *, force: bool, uri_only: bool) -> int:
    role = config.consent
    if role is None:
        emit(f'[ops] {config.path} enables no [ops.consent]', err=True)
        return 2
    try:
        if verb == 'enrol':
            secret = totp.enrol(Path(role.totp), force=force)
            _show(totp.uri(secret, issuer=role.issuer, account=role.account), uri_only=uri_only)
        elif verb == 'keygen':  # the PUBLIC key goes to every verifier: [consent] public_key, or the package
            emit(public_text(keygen(Path(role.key), force=force).public_key()))
        else:
            emit(consent_serve.handle(_issuer(config, role), sys.stdin.readline()))
    except (ConsentRefused, totp.TotpRefused) as refused:
        emit(f'refused: {refused}', err=True)
        return 2
    return 0


def _unreachable(_credential: object, _amount: int) -> object:
    msg = 'this host enables no [ops.consent] issuer'
    raise ConnectionError(msg)


def _breakglass(config: OpsConfig, verb: str) -> int:
    role = config.breakglass
    if role is None:
        emit(f'[ops] {config.path} enables no [ops.breakglass]', err=True)
        return 2
    issuer = _issuer(config, config.consent) if config.consent is not None else None
    try:
        verifier = issuer.public() if issuer is not None else public_key()
    except ConsentRefused as refused:
        emit(f'refused: {refused}', err=True)
        return 2
    server = breakglass.Server(
        config,
        forge_for=lambda url: breakglass.ClientForge(url, _secret(role.token_file(url))),
        alert=lambda title, detail: _alert(config, title, detail),
        now=time.time,
        consent_key=verifier,
        register=issuer.register if issuer is not None else _unreachable,
        key=sshkey.fingerprint(os.environ.get(sshkey.ENV, '')),
    )
    try:
        said = server.tick() if verb == 'tick' else server.handle(sys.stdin.readline())
    except breakglass.BreakglassRefused as refused:
        emit(f'refused: {refused}', err=True)
        return 2
    emit(said)
    return 0


def _config_apply(config: OpsConfig, candidate: Path, credential: str) -> int:
    """``config apply --from <file> [--credential <file>]``: the one config door (:mod:`dev_lab.ops.configdoor`)."""
    redeem_ = None
    granted = None
    if credential:
        role = config.consent
        issuer = _issuer(config, role) if role is not None else None
        try:
            verifier = issuer.public() if issuer is not None else public_key()
        except ConsentRefused as refused:
            emit(f'refused: {refused}', err=True)
            return 2
        granted = json.loads(Path(credential).read_text(encoding='utf-8'))

        def redeem_(found: dict) -> str:
            return redeem(
                found,
                action=configdoor.ACTION,
                key=verifier,
                register=issuer.register if issuer is not None else _unreachable,
                now=time.time(),
            ).subject

    try:
        done = configdoor.apply(
            config.path, candidate.read_text(encoding='utf-8'), loads=load, checks=upgrade.checks(config),
            run=upgrade.run_check, redeem=redeem_, credential=granted,
        )  # fmt: skip
    except (configdoor.ConfigRefused, ConsentRefused) as refused:
        emit(f'refused: {refused}', err=True)
        return 2
    if not done.changed:
        emit('[ops config] unchanged')
        return 0
    emit(f'[ops config] applied; changed {list(done.changed)}; boundary {list(done.boundary)}; backup {done.backup}')
    _alert(config, 'config applied', f'changed {list(done.changed)}; boundary {list(done.boundary)}')
    return 0


def _probe(config: OpsConfig) -> int:
    role = config.probe
    if role is None:
        emit(f'[ops] {config.path} enables no [ops.probe]', err=True)
        return 2
    for line in probe.run(
        config,
        lambda url: Client(forge_of_url(url), _secret(role.token_file(url))),
        lambda title, detail: _alert(config, title, detail),
    ):
        emit(f'[ops probe] {line}')
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Route one verb; see the module docstring."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.ops', description=__doc__.splitlines()[0])
    parser.add_argument('--config', type=Path, required=True)
    verbs = parser.add_subparsers(dest='verb', required=True)
    verbs.add_parser('install').add_argument('--root', type=Path, default=Path('/'))
    verbs.add_parser('promote')
    verbs.add_parser('judge', help='one judging pass over [ops.judge] repos')
    verbs.add_parser('upgrade', help='install dev-lab at the tip of [ops.upgrade] ref; takes no argument')
    verbs.add_parser('probe')
    glass = verbs.add_parser('breakglass')
    glass.add_argument('action', choices=('serve', 'tick'))
    issuing = verbs.add_parser('consent')
    issuing.add_argument('action', choices=('serve', 'enrol', 'keygen'))
    issuing.add_argument('--force', action='store_true', help='enrol / keygen: replace an existing secret / key')
    issuing.add_argument('--uri', action='store_true', help='enrol: print the otpauth URI, not its QR')
    verbs.add_parser('backup').add_argument('action', choices=('export', 'pull'))
    opened = verbs.add_parser('access')
    opened.add_argument('action', choices=('enrol', 'adopt'))
    opened.add_argument('--force', action='store_true', help='replace an existing secret')
    opened.add_argument('--uri', action='store_true', help='print the otpauth URI, not its QR')
    opened.add_argument('--secret-file', default='-', help="adopt: the host's existing base32 secret (- reads stdin)")
    configured = verbs.add_parser('config', help='change this host config through the one door')
    configured.add_argument('action', choices=('apply',))
    configured.add_argument('--from', dest='candidate', type=Path, required=True, help='the reviewed candidate file')
    configured.add_argument('--credential', default='', help='an ops.config consent credential (boundary keys)')
    for name in ('disk', 'clean'):
        sized = verbs.add_parser(name)
        sized.add_argument('--gitea-data', default=disk.DEFAULT_GITEA_DATA)
        sized.add_argument('--journal-max-mb', type=int, default=disk.DEFAULT_JOURNAL_MAX_MB)
    args = parser.parse_args(argv)
    if args.verb in {'disk', 'clean'}:  # read only the disk: no role config is needed to measure or free it
        return (
            disk.measure(args.gitea_data) if args.verb == 'disk' else disk.clean(args.gitea_data, args.journal_max_mb)
        )
    try:
        config = load(args.config)
    except (ValueError, TypeError) as bad:
        emit(f'[ops] {bad}', err=True)
        return 2
    if args.verb == 'install':
        return _install(config, args.root)
    if args.verb == 'promote':
        return _promote(config)
    verbs_of: dict[str, Callable[[], int]] = {
        'backup': lambda: _backup(config, args.action),
        'access': lambda: _access(
            config, args.action, force=args.force, uri_only=args.uri, secret_from=args.secret_file
        ),
        'probe': lambda: _probe(config),
        'breakglass': lambda: _breakglass(config, args.action),
        'consent': lambda: _consent(config, args.action, force=args.force, uri_only=args.uri),
        'judge': lambda: _judge(config),
        'upgrade': lambda: _upgrade(config),
        'config': lambda: _config_apply(config, args.candidate, args.credential),
    }
    return verbs_of[args.verb]()


if __name__ == '__main__':
    sys.exit(main())
