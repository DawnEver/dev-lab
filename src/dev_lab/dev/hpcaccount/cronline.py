"""AN ACCOUNT'S CRONTAB: its ONE marked tick line derived from the ``[deploy]`` declaration, merged and checked.

ONE-LOGIN-POLLER (user ruling 2026-11-27): an HPC login node runs exactly one cron poller per account. Split from
:mod:`dev_lab.dev.hpcaccount.spec` at the module-size band (2026-11-28): the spec is the declaration, this is the
crontab text it renders to. Pure; :mod:`dev_lab.dev.hpcaccount.steps` writes it.
"""

from __future__ import annotations

import re
import zlib
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from dev_lab.dev.hpcaccount.spec import Deployment, tick_command, ticked

__all__ = ['MARK', 'TICK_LINE', 'cron_lines', 'crontab_refusal', 'deployed', 'merge_crontab']

#: Every crontab line this tool owns ends with this comment plus :data:`TICK_LINE`.
MARK: Final = '# lab-commons-deploy:'

#: What follows :data:`MARK` on an account's ONE cron line (ONE-LOGIN-POLLER, user ruling 2026-11-27): one tick that
#: loops over every ticked repo under one lock, :data:`~dev_lab.dev.hpcaccount.spec.TICK_LOCK`, logging to
#: :data:`~dev_lab.dev.hpcaccount.spec.TICK_LOG`.
TICK_LINE: Final = 'tick'
#: An UNMARKED crontab line running family code (the kit, lab-commons, a tick): a second poller the one line replaces.
_FAMILY_CRON: Final = re.compile(r'dev_lab\.|lab_commons|hpcaccount')
#: An unmarked line a previous deploy wrote: it runs the deploy's own verb. The deploy replaces it; any other
#: :data:`_FAMILY_CRON` line is FOREIGN, its holder's to delete.
_DEPLOYED_CRON: Final = re.compile(r'dev_lab\.dev\.hpcaccount')


def cron_lines(
    spec: Deployment,
    home: Path,
    *,
    serves: bool | None = None,
    slurm: Sequence[str] = (),
    setup: Sequence[str] = (),
) -> list[str]:
    """The account's ONE marked line (ONE-LOGIN-POLLER): one tick of every ticked repo, every ``[schedule] tick``.

    One login-node poller per account (user ruling 2026-11-27): the line runs ONE ``hpcaccount tick`` naming every
    repo :func:`~dev_lab.dev.hpcaccount.spec.ticked` returns, under the one lock
    :data:`~dev_lab.dev.hpcaccount.spec.TICK_LOCK`; none ticked, no line. The minute offset is
    derived from *home* (one per account), so accounts sharing a forge tick staggered rather than in lockstep.
    """
    repos = ticked(spec, serves=serves)
    if not repos:
        return []
    step = spec.tick // 60
    minute = f'{zlib.crc32(str(home).encode()) % step}-59/{step}'
    command = tick_command(spec, home, repos, log=True, slurm=slurm, setup=setup)
    return [f'{minute} * * * * {command} {MARK}{TICK_LINE}']


def crontab_refusal(text: str) -> str:
    """``''`` when crontab *text* holds at most one marked line and no unmarked family line; else why, naming each.

    ONE-LOGIN-POLLER (user ruling 2026-11-27): an HPC login node runs exactly one cron poller per account. Every door
    that writes or reads the crontab asks this (``deploy`` and ``ci-resume`` through
    :func:`dev_lab.dev.hpcaccount.steps.crontab`, ``look crontab``). A commented-out line runs nothing and is skipped.
    """
    live = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    marked = [line for line in live if MARK in line]
    strays = [line for line in live if MARK not in line and _FAMILY_CRON.search(line)]
    named = [*(marked if len(marked) > 1 else []), *strays]
    if not named:
        return ''
    each = '; '.join(f'`{line}`' for line in named)
    return (
        f'ONE-LOGIN-POLLER: an account runs exactly one cron poller, the line marked {MARK}{TICK_LINE}; this crontab '
        f'holds {len(marked)} marked and {len(strays)} unmarked family line(s): {each} -- the door: `hpcaccount '
        'deploy` writes the one line and replaces every line a deploy wrote (marked, or running '
        "dev_lab.dev.hpcaccount); any other family line is foreign and deleted from the account's crontab by its "
        'holder (`hpcaccount look --account <user> crontab` names it)'
    )


def deployed(line: str) -> bool:
    """Whether crontab *line* is one a deploy wrote: marked, or a live line running the deploy's own verb."""
    live = line.strip() and not line.lstrip().startswith('#')
    return MARK in line or bool(live and _DEPLOYED_CRON.search(line))


def merge_crontab(current: str, lines: Sequence[str]) -> str:
    """*current* without any line a deploy wrote (:func:`deployed`), plus *lines*; every other line kept in place.

    An older deploy's lines (seven per-repo marked lines on ezztz, 2026-11-27) are REPLACED by the one tick, never
    refused; a foreign family line survives the merge, so :func:`crontab_refusal` names it.
    """
    kept = [line for line in current.splitlines() if not deployed(line)]
    text = '\n'.join([*kept, *lines])
    return text + '\n' if text else ''
