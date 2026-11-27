"""A PART AS A FACT -- one ``tests/<part>`` status read as (part, env, policy), contract 1 (test identity).

:class:`Part` is what one settled status says; :meth:`Part.description` is the one spelling it posts and
:func:`facts_of` the one reading of it. A forge keeps only the latest status per context, so a commit's
HISTORY is read: a later post replaces only the fact of its own (part, env, policy). Re-exported by
:mod:`dev_lab.dev.platformparts`, whose docstring holds the description's grammar.

THE DESCRIPTION ALWAYS FITS THE FORGE'S 140 CHARACTERS (:data:`~dev_lab.dev.forgestatus.DESCRIPTION_LIMIT`), whatever
the number of parts (dev-lab#1083: with 11 parts ``hands=`` pushed ``policy=`` past the cap, every part read as "not
a settled part", and no merge could settle). Its fields are an unordered set of ``key=value`` words, so a status
posted in any order still reads (OLD-SHAPE-READER). :meth:`Part.description` writes the identity first and ``hands``
last; when the whole does not fit it cuts ``hands`` (then ``kept``) at whole entries and ends the list with ``+N``,
the N entries it could not hold -- named in full in the run record the status links (``handed``). A cut is never
silent: :attr:`Part.hands_more` carries N, and :mod:`dev_lab.dev.parthands` completes it from that record, or the
composition names it as a problem. A description that would not read back is refused before anything posts it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from lab_commons.outcomes import Conclusion

from dev_lab.dev.forgecontexts import CONTEXT_PREFIX, NOT_PARTS
from dev_lab.dev.forgestatus import CARRIED_FROM, CITED_FROM, DESCRIPTION_LIMIT, DOCS_ONLY, SAME_TREE, state_for
from dev_lab.dev.partrows import is_row
from dev_lab.dev.verdictenv import POLICY_CHARS

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from dev_lab.dev.forgestatus import CommitStatus

__all__ = ['RESULT', 'Part', 'cut_problems', 'facts_of', 'latest', 'parsed']

#: The forge state a settled part reads back as; ``error`` (INCONCLUSIVE) is never a settled part.
RESULT: Final = {state_for(result): result for result in (Conclusion.PASS, Conclusion.FAIL)}

#: The phrase a carried or cited part ENDS with; the words before it are ``key=value`` fields in any order.
_TAIL: Final = re.compile(
    r' (?:carried from (?P<carried>[0-9a-f]{12}): (?:docs-only|every outcome carried by footprint)'
    r'|cited from (?P<cited>[0-9a-f]{12}): same tree)$'
)
#: An entry list cut to fit ends ``+N``: the N entries the run record holds that the description could not.
_LIST: Final = r'(?:{entry},)*(?:{entry}|\+\d+)'
#: Every field a part description may carry, each value's grammar; ``scope``, ``ran`` and ``hands`` are required.
_FIELDS: Final = {
    'scope': re.compile(r'\w+'),
    'ran': re.compile(r'\d+'),
    'env': re.compile(r'[0-9a-f]+'),
    'policy': re.compile(r'[0-9a-f]+'),
    'kept': re.compile(_LIST.format(entry=r'[0-9a-f]{12}:\d+')),
    'hands': re.compile(r'-|' + _LIST.format(entry=r'[a-z0-9_+]+:\d+')),
}
_REQUIRED: Final = frozenset({'scope', 'ran', 'hands'})


def _fields(description: str) -> tuple[dict[str, str], str, str] | None:
    """``(fields, carried, cited)`` of a part *description*; ``None`` when it is not one (module docstring)."""
    tail = _TAIL.search(description)
    fields: dict[str, str] = {}
    for word in (description[: tail.start()] if tail else description).split(' '):
        key, _, value = word.partition('=')
        grammar = _FIELDS.get(key)
        if grammar is None or key in fields or not grammar.fullmatch(value):
            return None
        fields[key] = value
    if not fields.keys() >= _REQUIRED:
        return None
    return fields, (tail['carried'] or '') if tail else '', (tail['cited'] or '') if tail else ''


def _entries(text: str) -> tuple[dict[str, int], int]:
    """``(entries, how many more the record holds)`` of a ``name:count,...[,+N]`` list (``-`` or empty: none)."""
    if text in {'', '-'}:
        return {}, 0
    items = text.split(',')
    more = int(items.pop()[1:]) if items[-1].startswith('+') else 0
    return {name: int(count) for name, count in (item.split(':') for item in items)}, more


def _listed(entries: Mapping[str, int], keep: int, more: int) -> str:
    """The first *keep* of *entries* (sorted) as ``name:count``, then ``+N`` for the rest and *more*; ``''``: none."""
    ordered = [f'{name}:{count}' for name, count in sorted(entries.items())]
    rest = len(ordered) - keep + more
    return ','.join(ordered[:keep] + ([f'+{rest}'] if rest else []))


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
    hands_more: int = 0  # parts it hands to beyond `hands`: cut to fit the description, named in its run record
    kept_more: int = 0  # kept entries beyond `kept`, cut to fit the description (module docstring)

    @property
    def fact(self) -> tuple[str, str, str]:
        """``(part, env, policy)`` -- what makes two posts of one commit two facts (module docstring)."""
        return (self.platform, self.env, self.policy)

    @property
    def state(self) -> str:
        """The forge state its conclusion posts as (:func:`dev_lab.dev.forgestatus.state_for`)."""
        return state_for(self.result)

    def description(self, limit: int | None = DESCRIPTION_LIMIT) -> str:
        """The status description, within *limit* characters and always read back (module docstring).

        *limit* is the forge's cap for anything posted; ``None`` says the whole part, uncut -- what a reader that
        completed a cut from its run record holds in memory (:func:`dev_lab.dev.parthands.complete_hands`).

        Raises:
            ValueError: no cut makes it fit and read back as this part -- refused before anything posts it.

        """
        head = f'scope={self.scope} ran={self.ran}'
        head += f' env={self.env[:POLICY_CHARS]}' if self.env else ''
        head += f' policy={self.policy[:POLICY_CHARS]}' if self.policy else ''
        carried = f' {CARRIED_FROM} {self.carried}: {DOCS_ONLY}' if self.carried else ''
        tail = carried or (f' {CITED_FROM} {self.cited}: {SAME_TREE}' if self.cited else '')
        hands_keep, kept_keep = len(self.hands), len(self.kept)
        while True:
            kept = _listed(self.kept, kept_keep, self.kept_more)
            hands = _listed(self.hands, hands_keep, self.hands_more) or '-'
            said = f'{head}{f" kept={kept}" if kept else ""} hands={hands}{tail}'
            if limit is None or len(said) <= limit or not (hands_keep or kept_keep):
                break
            hands_keep, kept_keep = (hands_keep - 1, kept_keep) if hands_keep else (0, kept_keep - 1)
        read = _fields(said)
        fits = limit is None or len(said) <= limit
        if not fits or read is None or (read[1], read[2]) != (self.carried, self.cited):
            msg = f'the {self.platform} part cannot be said in {limit} characters that read back: {said!r}'
            raise ValueError(msg)
        return said


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
    read = _fields(status.description)
    if status.state not in RESULT or read is None or not is_row(name):
        return None
    fields, carried, cited = read
    hands, hands_more = _entries(fields['hands'])
    kept, kept_more = _entries(fields.get('kept', ''))
    return Part(
        platform=name,
        scope=fields['scope'],
        result=RESULT[status.state],
        ran=int(fields['ran']),
        hands=hands,
        carried=carried,
        cited=cited,
        kept=kept,
        env=fields.get('env', ''),
        policy=fields.get('policy', ''),
        hands_more=hands_more,
        kept_more=kept_more,
    )


def cut_problems(parts: Iterable[Part]) -> tuple[str, ...]:
    """Each of *parts* whose ``hands`` its description cut and nothing completed: a set of parts not yet known whole."""
    return tuple(
        f'{CONTEXT_PREFIX}{part.platform} hands {part.hands_more} more part(s) than its description could hold, and '
        'its run record was not read to name them: read the statuses through '
        'dev_lab.dev.parthands.part_statuses or part_history (dev-lab#1083)'
        for part in parts
        if part.hands_more
    )


def facts_of(statuses: Sequence[CommitStatus]) -> dict[tuple[str, str, str], Part]:
    """Every settled fact of *statuses*, keyed ``(part, env, policy)``: a later post replaces only its own key."""
    facts: dict[tuple[str, str, str], Part] = {}
    for status in statuses:
        if (part := parsed(status)) is not None:
            facts.pop(part.fact, None)  # re-inserted: the order of facts is the order of their latest posts
            facts[part.fact] = part
    return facts
