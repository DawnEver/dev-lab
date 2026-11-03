"""``python -m dev_lab.ops --config <toml> install|promote|breakglass serve|enrol|tick``: the one door.

Exit codes: 0 done, 1 a failure (alerted), 2 refused. ``install --root <dir>`` renders into a test root.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from lab_commons.log import emit

from dev_lab.dev.forgemerge import merge
from dev_lab.dev.forgework import client_for
from dev_lab.ops import breakglass, install, promote, totp
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


class _ForgeAs:
    """:class:`breakglass.Forge` over the forge client of one clone, presenting the break-glass identity's token."""

    def __init__(self, root: Path, token: str) -> None:
        self._client = client_for(root, token=token)

    def pull(self, number: int) -> tuple[str, str, str]:
        found = self._client.pr_view(number)
        return found.state, found.base, found.head_sha

    def comment(self, number: int, body: str) -> None:
        self._client.issue_comment(number, body)

    def merge(self, number: int, *, head: str, message: str) -> None:
        merge(self._client, number, head=head, message=message, delete_branch=False)


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
        forge_for=lambda root: _ForgeAs(root, Path(role.token).read_text(encoding='utf-8').strip()),
        alert=lambda title, detail: _alert(config, title, detail),
        now=time.time,
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
    args = parser.parse_args(argv)
    try:
        config = load(args.config)
    except (ValueError, TypeError) as bad:
        emit(f'[ops] {bad}', err=True)
        return 2
    if args.verb == 'install':
        done = install.install(config, args.root)
        for path, state in done.paths.items():
            emit(f'{state:9} {path}')
        emit('\n'.join(['next, on the live host:', *(f'  {step}' for step in done.next_steps)]))
        return 0
    if args.verb == 'promote':
        failed = [o for o in promote.run(config) if o.state == 'failed']
        for outcome in failed:
            _alert(config, f'promote FAILED {outcome.repo}', outcome.detail)
        return 1 if failed else 0
    return _breakglass(config, args.action, force=args.force)


if __name__ == '__main__':
    sys.exit(main())
