"""A CLUSTER ACCOUNT AS A ``forge serve`` HOST: ``python -m dev_lab.dev.hpcaccount deploy|tick|allocate``.

The three ``lab_commons.hpc`` verbs that launched the forge, moved here with it (dev-lab cut-over,
2026-10-22) so lab-commons never reaches the dev system:

* ``deploy [--dry-run|--remove]`` (:mod:`~dev_lab.dev.hpcaccount.deploy`) makes this account's login host a
  ``forge serve`` host in one run; its data is :mod:`~dev_lab.dev.hpcaccount.spec`, its account checks
  :mod:`~dev_lab.dev.hpcaccount.account` and :mod:`~dev_lab.dev.hpcaccount.checks`, its steps
  :mod:`~dev_lab.dev.hpcaccount.steps`.
* ``tick <repo>...`` (:mod:`~dev_lab.dev.hpcaccount.tick`) is one cron tick: the host refreshes the kit (this
  package's checkout) and the repo, then the kit's ``forge serve`` runs in the repo's checkout.
* ``allocate --until <iso> [name=cpus/mem_gb ...] [--borrow <direction>] | --show | --clear``
  (:mod:`~dev_lab.dev.hpcaccount.allocate`) writes, prints or deletes the ONE expiring allocation record on the forge
  (:mod:`lab_commons.hpc.allocation`); the forge's own submits read it (:mod:`dev_lab.dev.forgeslurm`).

* ``deploy-fleet [--account <user>]... [--dry-run]`` (:mod:`~dev_lab.dev.hpcaccount.fleet`) starts, detached over ssh,
  every declared account's own ``deploy``, one log per account.
* ``forget --repo <url> --row <key> (--account <user>... | --fleet) [--dry-run]``
  (:mod:`~dev_lab.dev.hpcaccount.forget`) runs lab-commons' ``learned forget`` of one row on each account.
* ``retention (--account <user>... | --fleet) [--apply]`` (:mod:`~dev_lab.dev.hpcaccount.storage`) prints each
  account's quota (files and blocks), whether its serve ticks, and its OWN in-flight-aware retention report (a dry
  run, or the deletion with ``--apply``).
* ``credential <user@host> --login <forge login> [--url <repo url>]`` < token
  (:mod:`~dev_lab.dev.hpcaccount.credential`) places one minted forge token in the account's ``~/.git-credentials``
  and confirms the forge answers as that login.

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

import sys
from pathlib import Path

from lab_commons.log import emit

__all__ = ['main']

_USAGE = (
    'usage: python -m dev_lab.dev.hpcaccount '
    '{deploy [...] | deploy-fleet [...] | forget [...] | retention [...] | credential [...] | '
    'tick <repo>... | allocate [...]}'
)


def main(argv: list[str] | None = None) -> int:
    """Dispatch one verb (``tick`` needs a repo); anything else is refused naming the verbs."""
    from dev_lab.dev.hpcaccount import allocate, credential, deploy, fleet, forget, storage, tick  # noqa: PLC0415 -- the package imports no verb

    argv = sys.argv[1:] if argv is None else argv
    verb, rest = (argv[0], argv[1:]) if argv else ('', [])
    verbs = {
        'credential': credential.main,
        'deploy': deploy.main,
        'deploy-fleet': fleet.main,
        'forget': forget.main,
        'retention': storage.main,
        'allocate': allocate.allocate,
    }
    if verb in verbs:
        return verbs[verb](rest)
    if verb == 'tick' and rest:
        probed: dict[str, bool] = {}  # one probe per tool per tick, however many repos it serves
        return max(tick.tick(name, home=Path.home(), probed=probed) for name in rest)
    emit(_USAGE, err=True)
    return 2
