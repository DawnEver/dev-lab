"""The one emergency bypass of ``INTEGRATION-TAKES-ONLY-FORGE-MERGES``, kept in the history it bypassed.

User ruling 2026-10-19: with ``[tool.dev_lab.integrator] pr_merges_since`` declared, the integration
branch moves only by the forge merging a pull request -- so a broken forge could never be fixed. A direct
push is admitted (:mod:`dev_lab.dev.sessionbranch`) only when EVERY new first-parent commit carries a
``Break-Glass: <reason>`` trailer with a non-empty reason. Nothing else opens it -- no env var, no config
flag -- so every use is in the history it bypassed:

* the commit-msg hook (:mod:`dev_lab.dev.mergeaudit`) refuses the trailer with an empty reason;
* every ``forge serve`` tick keeps one ``integration`` issue per break-glass commit past the declared start
  (:func:`notices`), naming the commit and its reason. It closes when ``pr_merges_since`` is moved past it
  -- by a pull request, which is the follow-up the use owes.

BREAK-GLASS BYPASSES THE FORGE'S MERGE, NEVER THE REVIEW (user ruling 2026-10-31, every PR must get a review,
after lab-commons #11 and dev-lab #3 landed by Break-Glass with none). Every head a Break-Glass push lands -- a
merge's PR head, else the commit itself -- needs a POSTED review (:func:`unreviewed`): its latest
:data:`~dev_lab.dev.forgecontexts.REVIEW_CONTEXT` is ``success`` and no hold is pending -- the ONE predicate the
merge reads too (:mod:`dev_lab.dev.reviewgate`), and only a success the FORGE wrote counts (D11): a head the forge's
review never reached waits for :data:`~dev_lab.dev.reviewgate.RERUN`. A forge that cannot be read refuses: a push
needs the forge, so a forge down for reads is down for the push too.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

from dev_lab.dev.forgealarm import INTEGRATION, Alarm
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.forgework import client_for
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.reviewgate import forge_posted, review_missing

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client
    from dev_lab.dev.lanepolicy import Policy

__all__ = ['BREAK_GLASS', 'empty_reason', 'forge_unreviewed', 'notices', 'reason', 'unreviewed']

#: The trailer that admits a direct push to the integration branch, with its reason as the value.
BREAK_GLASS: Final = 'Break-Glass'

_TRAILER: Final = re.compile(rf'^{BREAK_GLASS}:(.*)$', re.MULTILINE)
_GIT: Final = shutil.which('git') or 'git'
_RECORD: Final = '\x1e'


def _value(message: str) -> str | None:
    found = _TRAILER.findall(message)
    return found[-1].strip() if found else None


def reason(message: str) -> str:
    """The non-empty ``Break-Glass:`` reason *message* carries (its last such trailer); ``''`` when none."""
    return _value(message) or ''


def empty_reason(message: str) -> bool:
    """Whether *message* carries a ``Break-Glass:`` trailer with no reason -- refused at commit-msg."""
    return _value(message) == ''


def notices(root: Path, policy: Policy, repo: str) -> list[Alarm]:
    """One ``integration`` alarm per break-glass commit of ``origin/<integration>`` past ``pr_merges_since``."""
    if not policy.pr_merges_since:
        return []
    done = _door.run(
        [_GIT, '-C', str(root), 'log', '--first-parent', f'--format=%H%n%an%n%B{_RECORD}',
         f'refs/remotes/origin/{policy.integration}', f'^{policy.pr_merges_since}'],
        capture_output=True, text=True, encoding='utf-8', check=False, timeout=120,
    )  # fmt: skip
    if done.returncode != 0:
        msg = f'cannot read the history of origin/{policy.integration}: {done.stderr.strip()}'
        raise OSError(msg)
    found = []
    for entry in filter(str.strip, done.stdout.split(_RECORD)):
        sha, _, rest = entry.strip().partition('\n')
        author, _, message = rest.partition('\n')
        if why := reason(message):
            subject = f'{policy.integration} took break-glass commit {sha[:12]}'
            body = (
                f'{sha} was pushed directly to {policy.integration} by {author}, past the forge merge flow: {why}. '
                f'Follow up with a pull request for anything beyond the emergency fix, then move '
                f'[tool.dev_lab.integrator] pr_merges_since past it to close this notice.'
            )
            found.append(Alarm(INTEGRATION, repo, subject, body, about=f'break-glass {sha[:12]}'))
    return found


def unreviewed(client: Client, head: str, *, base: str) -> str | None:
    """Why *head* carries no FORGE-posted review on *client*'s forge, or ``None``: the one predicate (reviewgate).

    *base* is the integration branch whose declaration, with *head*'s, says who the forge is.
    """
    return review_missing(status_list(client, head), forge_posted(client, head, base=base))


def forge_unreviewed(root: Path, head: str) -> str | None:
    """:func:`unreviewed` on *root*'s origin forge; a forge that cannot be read is a reason, never a pass."""
    try:
        return unreviewed(client_for(root), head, base=load_policy(root).integration)
    except (ForgeCallFailed, OSError, ValueError) as failed:
        return f'the forge cannot be read ({type(failed).__name__}: {failed})'
