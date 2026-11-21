"""``<verb>-fleet (--cluster <name> | --account <user>)...`` -- start one on-account verb on each SELECTED account.

The launcher of ``drift-fleet``, ``ci-pause-fleet`` and ``ci-resume-fleet``: the accounts are the declared fleet's
``[[hpc.grant]]`` tables (:func:`dev_lab.dev.hpcaccount.division.reached_machine`), each reached through the same
transport and layer target as ``deploy-fleet`` (:mod:`dev_lab.dev.hpcaccount.fleet`), one log per account under
``~/.cache/dev-lab/<yy>/<mm>/<dd>/<verb>-fleet/``. A run naming neither filter is refused: the whole fleet is never
selected by default. Both filters select the accounts matching both; an undeclared cluster or account is refused
before any ssh.

Every verb but ``ci-resume`` (whose lines come from the account's own declaration) is passed ``--from <clone>
--host <cluster>-<user>``: the config-source clone ``deploy-fleet``'s render already fetches
(:func:`~dev_lab.dev.hpcaccount.fleet.account_clone`), never the account's own ``[devhost] source``, which may name a
path of another machine.

``ci-pause-fleet`` / ``ci-resume-fleet --credential <id>`` redeem, HERE and before any account is started, a granted
:data:`~dev_lab.dev.hpcaccount.cicron.ACTION` credential whose subject is the one cluster and the sorted accounts this
run would start (:mod:`~dev_lab.dev.hpcaccount.cicron`); a selection spanning two clusters, or a credential naming
another cluster, account set or direction, starts nothing. A ``--dry-run`` spends nothing.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from lab_commons import config as machineconfig
from lab_commons.hpc.grants import Grant
from lab_commons.log import emit

from dev_lab.dev.datedlog import dated_log
from dev_lab.dev.hpcaccount import cicron
from dev_lab.dev.hpcaccount.division import division_of, reached_machine
from dev_lab.dev.hpcaccount.fleet import (
    ConfigSource,
    Launch,
    account_clone,
    account_host,
    config_source_of,
    layer_refusal,
    layer_target,
)
from dev_lab.dev.hpcaccount.target import Target, in_checkout
from dev_lab.dev.hpcaccount.transport import describe, start

__all__ = ['consent_of', 'main_fleet', 'select', 'start_on_selected']

#: ``chosen grants -> None`` when the run may start them, else why it is refused (nothing started).
type Consent = Callable[[Sequence[Grant]], str | None]

_BASE: Final = '.cache/dev-lab'


def select(grants: Sequence[Grant], accounts: Sequence[str], clusters: Sequence[str]) -> list[Grant] | str:
    """The first grant of each account matching every given filter; else why the selection is refused."""
    if not (accounts or clusters):
        return 'name at least one --cluster or --account: the whole fleet is never selected by default'
    if unknown := sorted(set(accounts) - {g.user for g in grants}):
        return f'{unknown} not in the declared fleet'
    if unknown := sorted(set(clusters) - {g.cluster_name for g in grants}):
        return f'cluster(s) {unknown} not in the declared fleet'
    chosen: dict[str, Grant] = {}
    for grant in grants:
        if (not accounts or grant.user in accounts) and (not clusters or grant.cluster_name in clusters):
            chosen.setdefault(grant.user, grant)
    return list(chosen.values()) or 'no declared account matches both --cluster and --account'


def start_on_selected(
    grants: Sequence[Grant],
    accounts: Sequence[str],
    clusters: Sequence[str],
    *,
    home: Path,
    source: ConfigSource,
    say: Callable[[str], None],
    verb: str,
    launch: Launch = start,
    args: Sequence[str] = (),
    serving_only: Callable[[Target], bool] | None = None,
    sourced: bool = True,
    consent: Consent | None = None,
) -> int:
    """Start ``<verb> --from <clone> --host <name> <args>`` on each selected account; 2 when any is refused.

    With *serving_only*, an account it rejects is skipped when a ``--cluster`` selected it and refused when named by
    ``--account``: a research account has no CI cron by design. *sourced* passes ``--from`` and ``--host``. With
    *consent*, the accounts about to start are admitted by it first, or none is started.
    """
    chosen = select(grants, accounts, clusters)
    if isinstance(chosen, str):
        say(f'{verb}-fleet: refused -- {chosen}')
        return 2
    refused = 0
    ready: list[tuple[Grant, Target]] = []
    for grant in chosen:
        target = layer_refusal(grant, source) or layer_target(grant, source)
        if isinstance(target, str):
            say(target)
            refused += 1
            continue
        if serving_only is not None and not serving_only(target):
            say(f'{grant.user} ({target.role or "role undeclared"}): {verb} skipped -- no CI cron by design')
            refused += grant.user in accounts
            continue
        ready.append((grant, target))
    if consent is not None and (why := consent([grant for grant, _ in ready])):
        say(f'{verb}-fleet: refused, no account started -- {why}')
        return 2
    for grant, target in ready:
        dest = f'{grant.user}@{target.host}'
        clone = account_clone(target, source).as_posix()
        named = ['--from', clone, '--host', account_host(grant)] if sourced else []
        argv = ['-m', 'dev_lab.dev.hpcaccount', verb, *named, *args]
        command = in_checkout(target, argv)
        path = dated_log(home, f'{grant.user}.log', base=_BASE, kind=f'{verb}-fleet')
        say(f'{grant.user} ({grant.cluster_name}): started {describe(dest, command)}  log {path}')
        with path.open('a', encoding='utf-8') as log:
            launch(dest, command, log)
    return 2 if refused else 0


def consent_of(verb: str, ident: str, redeem_with: cicron.Redeem | None = None) -> Consent:
    """The :data:`Consent` redeeming credential *ident* for one cluster's accounts about to run *verb*."""

    def admitted(grants: Sequence[Grant]) -> str | None:
        clusters = sorted({grant.cluster_name for grant in grants})
        if len(clusters) != 1:
            return f'a {cicron.ACTION} credential consents to one cluster; this run would start {clusters or "none"}'
        wanted = cicron.subject(verb, clusters[0], [grant.user for grant in grants])
        return cicron.spend(ident, wanted, redeem_with=redeem_with)

    return admitted


def main_fleet(
    argv: Sequence[str], *, verb: str, ci_only: bool = False, flags: Sequence[str] = (), sourced: bool = True
) -> int:
    """Parse ``<verb>-fleet`` and start *verb* on each selected account; *ci_only* skips non-serving roles.

    A *ci_only* verb takes ``--credential <id>``: the consent redeemed for the accounts it starts (module docstring).

    *flags* are the on-account verb's own switches this fleet verb forwards when given (``--dry-run`` ...).
    """
    parser = argparse.ArgumentParser(prog=f'dev_lab.dev.hpcaccount {verb}-fleet', description=f'{verb} accounts')
    parser.add_argument('--cluster', action='append', default=[], help='every account of one cluster (repeatable)')
    parser.add_argument('--account', action='append', default=[], help='one account of the fleet (repeatable)')
    for flag in flags:
        parser.add_argument(
            flag, action='append_const', const=flag, dest='forwarded', help=f"forwarded to each account's {verb}"
        )
    parser.set_defaults(credential=None, forwarded=None)
    if ci_only:
        parser.add_argument('--credential', help=f'the id of a granted {cicron.ACTION} credential, redeemed here')
    args = parser.parse_args(list(argv))
    given = set(args.forwarded or ())
    forwarded = [flag for flag in flags if flag in given]
    try:
        machine = reached_machine(args.account)
        source = config_source_of(machineconfig.machine())
    except (PermissionError, LookupError, ValueError) as refused:
        emit(f'{verb}-fleet: refused -- {refused}')
        return 2
    roles = division_of(machine).roles
    consent = (
        consent_of(verb, args.credential) if args.credential is not None and '--dry-run' not in forwarded else None
    )
    return start_on_selected(
        machine.grants, args.account, args.cluster, home=Path.home(), source=source, say=emit, verb=verb,
        args=forwarded, sourced=sourced, consent=consent,
        serving_only=(lambda t: bool(roles.get(t.role, {}).get('serves'))) if ci_only else None,
    )  # fmt: skip
