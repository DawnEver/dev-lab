"""A PART AS A FACT -- one ``tests/<part>`` status read as (part, env, policy), contract 1 (test identity).

:class:`Part` is what one settled status says; :meth:`Part.description` is the one spelling it posts and
:func:`facts_of` the one reading of it. A forge keeps only the latest status per context, so a commit's
HISTORY is read: a later post replaces only the fact of its own (part, env, policy). Re-exported by
:mod:`dev_lab.dev.platformparts`, whose docstring holds the description's grammar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from lab_commons.outcomes import Conclusion

from dev_lab.dev.forgecontexts import CONTEXT_PREFIX, NOT_PARTS
from dev_lab.dev.forgestatus import CARRIED_FROM, CITED_FROM, DOCS_ONLY, SAME_TREE, state_for
from dev_lab.dev.partrows import is_row
from dev_lab.dev.verdictenv import POLICY_CHARS

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dev_lab.dev.forgestatus import CommitStatus

__all__ = ['RESULT', 'Part', 'facts_of', 'latest', 'parsed']

#: The forge state a settled part reads back as; ``error`` (INCONCLUSIVE) is never a settled part.
RESULT: Final = {state_for(result): result for result in (Conclusion.PASS, Conclusion.FAIL)}

_DESCRIPTION: Final = re.compile(
    r'^scope=(?P<scope>\w+) ran=(?P<ran>\d+) '
    r'hands=(?P<hands>-|[a-z0-9_+]+:\d+(?:,[a-z0-9_+]+:\d+)*)'
    r'(?: env=(?P<env>[0-9a-f]+))?(?: policy=(?P<policy>[0-9a-f]+))?'
    r'(?: kept=(?P<kept>[0-9a-f]{12}:\d+(?:,[0-9a-f]{12}:\d+)*))?'
    r'(?: carried from (?P<carried>[0-9a-f]{12}): (?:docs-only|every outcome carried by footprint))?'
    r'(?: cited from (?P<cited>[0-9a-f]{12}): same tree)?$'
)


@dataclass(frozen=True)
class Part:
    """One part's result for a commit, as the forge holds it; *platform* is the part's name (its need-set)."""

    platform: str
    scope: str
    result: Conclusion
    ran: int
    hands: dict[str, int] = field(default_factory=dict)
    carried: str = ''  # the sha12 this verdict was judged at, when it is carried (dev_lab.dev.forgecarry)
    kept: dict[str, int] = field(default_factory=dict)  # outcomes carried in, per sha12 they ran at; never in ran
    cited: str = ''  # the sha12 whose stored record of the SAME tree this verdict cites (dev_lab.dev.verdictstore)
    env: str = ''  # the env key (POLICY_CHARS hex) of the run that judged it -- the SOURCE run's when carried or cited
    policy: str = ''  # the policy version (dev_lab.dev.verdictenv.verdict_policy) it was judged by

    @property
    def fact(self) -> tuple[str, str, str]:
        """``(part, env, policy)`` -- what makes two posts of one commit two facts (module docstring)."""
        return (self.platform, self.env, self.policy)

    @property
    def state(self) -> str:
        """The forge state its conclusion posts as (:func:`dev_lab.dev.forgestatus.state_for`)."""
        return state_for(self.result)

    def description(self) -> str:
        """The status description: ``scope= ran= hands=`` (module docstring)."""
        hands = ','.join(f'{name}:{count}' for name, count in sorted(self.hands.items())) or '-'
        kept = ' kept=' + ','.join(f'{sha}:{count}' for sha, count in sorted(self.kept.items())) if self.kept else ''
        carried = f' {CARRIED_FROM} {self.carried}: {DOCS_ONLY}' if self.carried else ''
        cited = f' {CITED_FROM} {self.cited}: {SAME_TREE}' if self.cited else ''
        env = f' env={self.env[:POLICY_CHARS]}' if self.env else ''
        policy = f' policy={self.policy[:POLICY_CHARS]}' if self.policy else ''
        return f'scope={self.scope} ran={self.ran} hands={hands}{env}{policy}{kept}{carried}{cited}'


def latest(statuses: Sequence[CommitStatus]) -> list[CommitStatus]:
    """The latest status per context of *statuses* (a list or a history, oldest first)."""
    latest: dict[str, CommitStatus] = {}
    for status in statuses:
        latest.pop(status.context, None)
        latest[status.context] = status
    return list(latest.values())


def parsed(status: CommitStatus) -> Part | None:
    """The settled part *status* says; ``None`` when it says none (a claim, an ``error``, a foreign description)."""
    if not status.context.startswith(CONTEXT_PREFIX) or status.context in NOT_PARTS:
        return None
    name = status.context.removeprefix(CONTEXT_PREFIX)
    found = _DESCRIPTION.match(status.description)
    if status.state not in RESULT or found is None or not is_row(name):
        return None
    hands = {} if found['hands'] == '-' else dict(item.split(':') for item in found['hands'].split(','))
    return Part(
        platform=name,
        scope=found['scope'],
        result=RESULT[status.state],
        ran=int(found['ran']),
        hands={owner: int(count) for owner, count in hands.items()},
        carried=found['carried'] or '',
        cited=found['cited'] or '',
        kept={sha: int(n) for sha, n in (one.split(':') for one in filter(None, (found['kept'] or '').split(',')))},
        env=found['env'] or '',
        policy=found['policy'] or '',
    )


def facts_of(statuses: Sequence[CommitStatus]) -> dict[tuple[str, str, str], Part]:
    """Every settled fact of *statuses*, keyed ``(part, env, policy)``: a later post replaces only its own key."""
    facts: dict[tuple[str, str, str], Part] = {}
    for status in statuses:
        if (part := parsed(status)) is not None:
            facts.pop(part.fact, None)  # re-inserted: the order of facts is the order of their latest posts
            facts[part.fact] = part
    return facts
