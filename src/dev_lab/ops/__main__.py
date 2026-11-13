"""``python -m dev_lab.ops --config <toml> <verb>``: the one door of every host role.

Verbs: ``install``, ``promote``, ``judge``, ``upgrade [--sha S --credential F | --subject]`` (:mod:`.upgrade`),
``probe``, ``breakglass serve|tick``,
``consent serve|enrol|keygen|ready`` (:mod:`dev_lab.ops.consentverbs`), ``backup export|pull``,
``access enrol|adopt``, ``disk``, ``clean`` (:mod:`dev_lab.ops.disk`), ``config apply|tick``
(:mod:`dev_lab.ops.configdoor`), ``forge account ensure`` and ``forge token mint`` (:mod:`dev_lab.ops.forgeaccounts`),
``forge protect plan|apply`` (:mod:`dev_lab.ops.forgeprotection`).

Exit codes: 0 done, 1 a failure (alerted), 2 refused. ``install --root <dir>`` renders into a test root.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from lab_commons.log import emit

from dev_lab.ops import (
    alertless,
    configverbs,
    consentverbs,
    disk,
    forgeaccounts,
    githubwho,
    secretplace,
)
from dev_lab.ops.config import load
from dev_lab.ops.hostverbs import (
    access_verb,
    alert,
    backup_verb,
    breakglass_verb,
    install_verb,
    judge_verb,
    probe_verb,
    promote_verb,
    show,
)
from dev_lab.ops.redeemverbs import forge_verb, redeemer, secret_place, upgrade_verb

__all__ = ['main']


def main(argv: Sequence[str] | None = None) -> int:
    """Route one verb; see the module docstring."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.ops', description=__doc__.splitlines()[0])
    parser.add_argument('--config', type=Path, required=True)
    parser.set_defaults(action=None, subject=False)  # every verb form reads both (alertless.sends_no_alert)
    verbs = parser.add_subparsers(dest='verb', required=True)
    verbs.add_parser('install').add_argument('--root', type=Path, default=Path('/'))
    verbs.add_parser('promote')
    verbs.add_parser('judge', help='one judging pass over [ops.judge] repos')
    upgrading = verbs.add_parser('upgrade', help='install dev-lab at the tip of [ops.upgrade] ref')
    upgrading.add_argument('--sha', default='', help='a plan step: the tip sha its ops.upgrade grant names')
    upgrading.add_argument('--credential', default='', help='a plan step: a single-use ops.upgrade credential')
    upgrading.add_argument('--subject', action='store_true', help="print the ref's tip sha a grant names; no install")
    verbs.add_parser('probe')
    glass = verbs.add_parser('breakglass')
    glass.add_argument('action', choices=('serve', 'tick'))
    issuing = verbs.add_parser('consent')
    issuing.add_argument('action', choices=consentverbs.VERBS)
    issuing.add_argument('--force', action='store_true', help='enrol / keygen: replace an existing secret / key')
    issuing.add_argument('--uri', action='store_true', help='enrol: print the otpauth URI, not its QR')
    verbs.add_parser('backup').add_argument('action', choices=('export', 'pull'))
    opened = verbs.add_parser('access')
    opened.add_argument('action', choices=('enrol', 'adopt'))
    opened.add_argument('--force', action='store_true', help='replace an existing secret')
    opened.add_argument('--uri', action='store_true', help='print the otpauth URI, not its QR')
    opened.add_argument('--secret-file', default='-', help="adopt: the host's existing base32 secret (- reads stdin)")
    configured = verbs.add_parser('config', help='change this host config through the one door')
    configured.add_argument('action', choices=('apply', 'tick'))
    configured.add_argument(
        '--from', dest='candidate', type=Path, default=None, help='a local candidate file'
    )  # default: the [ops.config] source
    configured.add_argument('--credential', default='', help='an ops.config consent credential (boundary keys)')
    configured.add_argument('--subject', action='store_true', help="apply: print the candidate's consent subject only")
    forgeaccounts.add_parser(verbs)
    secretplace.add_parser(verbs)
    githubwho.add_parser(verbs)
    for name in ('disk', 'clean'):
        sized = verbs.add_parser(name)
        sized.add_argument('--gitea-data', default=disk.DEFAULT_GITEA_DATA)
        sized.add_argument('--journal-max-mb', type=int, default=disk.DEFAULT_JOURNAL_MAX_MB)
    args = parser.parse_args(argv)
    if args.verb in {'disk', 'clean'}:  # read only the disk: no role config is needed to measure or free it
        sized = disk.measure(args.gitea_data) if args.verb == 'disk' else None
        return sized if sized is not None else disk.clean(args.gitea_data, args.journal_max_mb)
    try:
        config = load(args.config, alerts=not alertless.sends_no_alert(args))
    except (ValueError, TypeError) as bad:
        emit(f'[ops] {bad}', err=True)
        return 2
    if args.verb == 'install':
        return install_verb(config, args.root)
    if args.verb == 'promote':
        return promote_verb(config)
    verbs_of: dict[str, Callable[[], int]] = {
        'backup': lambda: backup_verb(config, args.action),
        'access': lambda: access_verb(
            config, args.action, force=args.force, uri_only=args.uri, secret_from=args.secret_file
        ),
        'probe': lambda: probe_verb(config),
        'breakglass': lambda: breakglass_verb(config, args.action),
        'consent': lambda: consentverbs.run(
            config,
            args.action,
            force=args.force,
            alert=lambda title, detail: alert(config, title, detail),
            show=lambda link: show(link, uri_only=args.uri),
        ),
        'judge': lambda: judge_verb(config),
        'upgrade': lambda: upgrade_verb(config, args),
        'config': lambda: (
            configverbs.tick(config, alert=lambda title, detail: alert(config, title, detail))
            if args.action == 'tick'
            else configverbs.apply(
                config,
                args.candidate,
                args.credential,
                alert=lambda title, detail: alert(config, title, detail),
                redeemer=lambda: redeemer(config),
                subject=args.subject,
            )
        ),
        'forge': lambda: forge_verb(config, args),
        'secret': lambda: secret_place(config, args),
        'github': lambda: githubwho.run(config, args),
    }
    return verbs_of[args.verb]()


if __name__ == '__main__':
    sys.exit(main())
