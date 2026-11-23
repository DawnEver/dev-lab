"""A CLUSTER ACCOUNT AS A ``forge serve`` HOST: ``python -m dev_lab.dev.hpcaccount deploy|tick|allocate``.

The three ``lab_commons.hpc`` verbs that launched the forge, moved here with it (dev-lab cut-over,
2026-10-22) so lab-commons never reaches the dev system:

* ``deploy [--dry-run|--remove]`` (:mod:`~dev_lab.dev.hpcaccount.deploy`) makes this account's login host a
  ``forge serve`` host in one run; its data is :mod:`~dev_lab.dev.hpcaccount.spec`, its account checks
  :mod:`~dev_lab.dev.hpcaccount.account` and :mod:`~dev_lab.dev.hpcaccount.checks`, its steps
  :mod:`~dev_lab.dev.hpcaccount.steps`, its host check :mod:`~dev_lab.dev.hpcaccount.deployhost`, its declaration
  :mod:`~dev_lab.dev.hpcaccount.declaration`.
* ``tick <repo>... [--lock <path> --wall-minutes <m>]`` (:mod:`~dev_lab.dev.hpcaccount.tick`) is one cron tick: the
  host refreshes the kit (this package's checkout) and the repo, then the kit's ``forge serve`` runs in the repo's
  checkout -- under the lock and within the wall the cron line names (:mod:`~dev_lab.dev.hpcaccount.tickwall`).
* ``allocate --until <iso> [name=cpus/mem_gb ...] [--borrow <direction>] | --show | --clear``
  (:mod:`~dev_lab.dev.hpcaccount.allocate`) writes, prints or deletes the ONE expiring allocation record on the forge
  (:mod:`lab_commons.hpc.allocation`); the forge's own submits read it (:mod:`dev_lab.dev.forgeslurm`).

* ``deploy-fleet [--account <user>]... [--dry-run]`` (:mod:`~dev_lab.dev.hpcaccount.fleet`) starts, over the transport,
  every declared account's own ``deploy``, one log per account.
* ``drift-fleet (--cluster <name> | --account <user>)...`` (:mod:`~dev_lab.dev.hpcaccount.accountset`) runs, on each
  selected account, its own read-only ``drift`` (:mod:`~dev_lab.dev.hpcaccount.drift`): what the account holds that
  its config source cannot render. Neither filter given is refused. Nothing on an account is backed up: the config
  source is the truth, an account its render (user ruling 2026-11-16).
* ``ci-pause-fleet`` / ``ci-resume-fleet`` (same filters; :mod:`~dev_lab.dev.hpcaccount.cipause`) stop and restart
  the forge CI cron of the selected VERIFICATION accounts around maintenance: a pause refuses while the account
  drifts, then removes only the marked lines; never a Slurm job. While CI-PAUSED, ``deploy`` and ``deploy-fleet``
  refuse the account (:mod:`~dev_lab.dev.hpcaccount.cimark`).
* ``forget --repo <url> --row <key> (--account <user>... | --fleet) [--dry-run]``
  (:mod:`~dev_lab.dev.hpcaccount.forget`) runs lab-commons' ``learned forget`` of one row on each account.
* ``retention (--account <user>... | --fleet) [--apply]`` (:mod:`~dev_lab.dev.hpcaccount.storage`) prints each
  account's quota (files and blocks), whether its serve ticks, and its OWN in-flight-aware retention report (a dry
  run, or the deletion with ``--apply``).
* ``credential <user@host> --login <forge login> [--url <repo url>]`` < token
  (:mod:`~dev_lab.dev.hpcaccount.credential`) places one minted forge token in the account's ``~/.git-credentials``
  (a role's named ``config_reader``: in its own ``~/.git-credentials.reader``) and confirms the forge answers as
  that login.
* ``look --account <user> {processes|ticks|log <repo>|crontab}`` (:mod:`~dev_lab.dev.hpcaccount.look`) is a
  READ-ONLY look at one account through its rate-limited key ssh: a closed set of reads, no free-form command.
* Every remote step above goes through ONE transport, :mod:`~dev_lab.dev.hpcaccount.transport`: the dest's held
  session (:mod:`dev_lab.dev.sshhold`) when one is live, else key-only ssh; a second-factor host with none is refused
  naming ``python -m dev_lab.dev.sshhold open <dest> --hours H``.

WHICH ACCOUNTS A SESSION MAY TOUCH (HPC-ACCESS-BY-ROLE, user correction 2026-11-12): every verb loads through
:func:`~dev_lab.dev.hpcaccount.division.reached_machine` -- the grants this machine's ``[hpc] reach`` holds, plus the
verification accounts when THIS SESSION holds the integrator role (:mod:`~dev_lab.dev.hpcaccount.session`, a consent
credential); any other account is refused by name.

EVERY ACCOUNT DECLARES ITS ROLE (user ruling 2026-11-06), ``[deploy] role`` in its own machine file
(:mod:`~dev_lab.dev.hpcaccount.spec`): only a ``verification`` account (a Forge Verification account) runs the serve
cron; a ``research`` account is deployed for research and never carries one. Undeclared, ``deploy`` refuses.
The workstation is the source of the division (user rulings 2026-11-09): each ``[[hpc.grant]]`` ``role`` and what
a role does, ``[hpc.roles]`` (:mod:`~dev_lab.dev.hpcaccount.division`), which ``deploy-fleet`` passes on.

Everything else about the cluster -- plan, submit, run, gather, clean -- stays ``python -m lab_commons.hpc``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lab_commons.hpc.retired import refusal as retired_refusal
from lab_commons.log import emit

__all__ = ['main']

_USAGE = (
    'usage: python -m dev_lab.dev.hpcaccount '
    '{deploy [...] | deploy-fleet [...] | drift[-fleet] [...] | ci-pause[-fleet] [...] | '
    'ci-resume[-fleet] [...] | forget [...] | retention [...] | credential [...] | keys [...] | look [...] | '
    'tick <repo>... [--lock <path> --wall-minutes <m>] | allocate [...]}'
)


def main(argv: list[str] | None = None) -> int:
    """Dispatch one verb (``tick`` needs a repo); a retired verb is refused naming its door, else the verbs."""
    from dev_lab.dev.hpcaccount import (  # noqa: PLC0415 -- the package imports no verb
        accountset,
        allocate,
        cipause,
        credential,
        deploy,
        drift,
        fleet,
        forget,
        keys,
        look,
        storage,
    )

    argv = sys.argv[1:] if argv is None else argv
    verb, rest = (argv[0], argv[1:]) if argv else ('', [])
    verbs = {
        'ci-pause': cipause.main_pause,
        'ci-resume': cipause.main_resume,
        'ci-pause-fleet': lambda rest: accountset.main_fleet(
            rest, verb='ci-pause', ci_only=True, flags=('--dry-run', '--discard-drift')
        ),
        'ci-resume-fleet': lambda rest: accountset.main_fleet(
            rest, verb='ci-resume', ci_only=True, flags=('--dry-run',), sourced=False
        ),
        'drift': drift.main,
        'drift-fleet': lambda rest: accountset.main_fleet(rest, verb='drift', flags=('--dry-run', '--discard-drift')),
        'credential': credential.main,
        'keys': keys.main,
        'look': look.main,
        'deploy': deploy.main,
        'deploy-fleet': fleet.main,
        'forget': forget.main,
        'retention': storage.main,
        'allocate': allocate.allocate,
    }
    if verb in verbs:
        return verbs[verb](rest)
    if verb == 'tick' and rest:
        return _tick(rest)
    emit(retired_refusal('dev_lab.dev.hpcaccount', verb) or _USAGE, err=True)
    return 2


def _tick(argv: list[str]) -> int:
    """``tick <repo>... [--lock <path> --wall-minutes <m>]``: unlocked and unbounded without ``--lock``."""
    from dev_lab.dev.hpcaccount import tick, tickwall  # noqa: PLC0415 -- the package imports no verb
    from dev_lab.dev.hpcaccount.spec import DEFAULT_TICK_WALL_MINUTES  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount tick')
    parser.add_argument('repos', nargs='+')
    parser.add_argument('--lock', type=Path, help="this tick's lock; its holder record is written beside it")
    parser.add_argument('--wall-minutes', type=int, default=DEFAULT_TICK_WALL_MINUTES)
    args = parser.parse_args(argv)
    probed: dict[str, bool] = {}  # one probe per tool per tick, however many repos it serves

    def body(wall: tickwall.Wall | None) -> int:
        return max(tick.tick(name, home=Path.home(), probed=probed, wall=wall) for name in args.repos)

    if args.lock is None:
        return body(None)
    return tickwall.locked(args.lock, ' '.join(args.repos), args.wall_minutes * 60.0, body)
