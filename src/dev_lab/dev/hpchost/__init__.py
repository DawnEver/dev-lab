"""A CLUSTER ACCOUNT AS A ``forge serve`` HOST: ``python -m dev_lab.dev.hpchost deploy|tick|allocate``.

The three ``lab_commons.hpc`` verbs that launched the forge, moved here with it (dev-lab cut-over,
2026-10-22) so lab-commons never reaches the dev system:

* ``deploy [--dry-run|--remove]`` (:mod:`~dev_lab.dev.hpchost.deploy`) makes this account's login host a
  ``forge serve`` host in one run; its data is :mod:`~dev_lab.dev.hpchost.spec`, its account checks
  :mod:`~dev_lab.dev.hpchost.account` and :mod:`~dev_lab.dev.hpchost.checks`, its steps
  :mod:`~dev_lab.dev.hpchost.steps`.
* ``tick <repo>...`` (:mod:`~dev_lab.dev.hpchost.tick`) is one cron tick: the host refreshes the kit (this
  package's checkout) and the repo, then the kit's ``forge serve`` runs in the repo's checkout.
* ``allocate --until <iso> name=cpus/mem_gb ... | --show | --clear`` (:mod:`~dev_lab.dev.hpchost.allocate`)
  writes, prints or deletes the ONE expiring allocation record on the forge
  (:mod:`lab_commons.hpc.allocation`); the forge's own submits read it (:mod:`dev_lab.dev.forgeslurm`).

* ``deploy-fleet [--account <user>]... [--dry-run]`` (:mod:`~dev_lab.dev.hpchost.fleet`) starts, detached over ssh,
  every declared account's own ``deploy``, one log per account.

Everything else about the cluster -- plan, submit, run, gather, clean -- stays ``python -m lab_commons.hpc``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from lab_commons.log import emit

__all__ = ['main']

_USAGE = 'usage: python -m dev_lab.dev.hpchost {deploy [...] | deploy-fleet [...] | tick <repo>... | allocate [...]}'


def main(argv: list[str] | None = None) -> int:
    """Dispatch ``deploy``, ``tick <repo>...`` or ``allocate``; anything else is refused naming the verbs."""
    from dev_lab.dev.hpchost import allocate, deploy, fleet, tick  # noqa: PLC0415 -- the package imports no verb

    argv = sys.argv[1:] if argv is None else argv
    verb, rest = (argv[0], argv[1:]) if argv else ('', [])
    if verb == 'deploy':
        return deploy.main(rest)
    if verb == 'deploy-fleet':
        return fleet.main(rest)
    if verb == 'allocate':
        return allocate.allocate(rest)
    if verb == 'tick' and rest:
        probed: dict[str, bool] = {}  # one probe per tool per tick, however many repos it serves
        return max(tick.tick(name, home=Path.home(), probed=probed) for name in rest)
    emit(_USAGE, err=True)
    return 2
