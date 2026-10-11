r"""The READ half of the family-config body: what a FILE says.

SPLIT OUT OF :mod:`lab_commons.dev.famtests.configrender` at the seam
:mod:`lab_commons.dev._famconfig_survey` already runs on one layer down: everything here is a READING and
everything there is a VERDICT that adds a floor, compares against a declaration and names a remedy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lab_commons.dev.famconfig import Base, Delta

__all__ = [
    'Reopening',
    'assert_floor',
    'reopenings',
]


@dataclass(frozen=True)
class Reopening:
    """What a ``.gitignore`` delta does to the base ABOVE it, given last-match-wins ordering.

    EVERY FIELD HERE IS POSITIONAL, and that had to be corrected rather than assumed. This reading
    reduced ``added`` to SETS and asked whether a closing line existed ANYWHERE -- but last-match-wins
    is a statement about ORDER, and a set cannot hold one. A closure written above the re-inclusion it
    is meant to close reads identically to one written below it, and only one of them is correct.

    Attributes:
        base_directories: the directory rules the base excludes -- the floor's subject.
        bare: delta lines re-stating a slashed base rule without its slash, a different RULE.
        reopened: negations re-including a base directory that no LATER delta line closes again.
        unsealed: delta lines that re-state a base directory rule and are then defeated by a subtree
            re-inclusion BELOW them. The closure exists, so a presence test passes; it is in the
            wrong place, so the rule is open. This is the incident a sibling repo's `.gitignore`
            records -- a `.pyc` under `.claude/memory/` was TRACKED because a re-inclusion brought
            back what the cache rule had excluded.

    """

    base_directories: tuple[str, ...]
    bare: tuple[str, ...]
    reopened: tuple[str, ...]
    unsealed: tuple[str, ...]


def assert_floor(reached: int, floor: int, what: str) -> None:
    """Refuse a reading below *floor*. Finding nothing is vacuous rather than green."""
    if reached < floor:
        msg = (
            f'{what}: read {reached}, below the {floor} floor. A scan that found nothing agrees with every '
            f'claim made about it, so this is INCONCLUSIVE rather than clean. Fix what is read, never the floor.'
        )
        raise AssertionError(msg)


def _stem(line: str) -> str:
    """The directory a rule NAMES, stripped of the negation, the wildcards and the trailing slash."""
    return line.lstrip('!').rstrip('/*').lstrip('*/')


def reopenings(base: Base, delta: Delta) -> Reopening:
    """What *delta* does to *base*'s directory rules under last-match-wins. PURE over its arguments.

    ORDER IS READ, NOT MEMBERSHIP. A closing line counts for a negation only when it comes AFTER it,
    and a re-statement of a base rule counts for nothing below a later subtree re-inclusion. The
    older reading compared sets and so answered the same for both orderings of the same two lines.

    A SUBTREE RE-INCLUSION IS THE ONE THAT REOPENS A FLOATING RULE -- a negation ending in a wildcard
    brings back everything underneath it, including the cache directories a base rule excludes at any
    depth. A negation naming ONE FILE re-includes that path and nothing under it, so it owes no
    closure; reporting it would need a waiver, and a waiver is how a guard like this gets lost.
    """
    directories = tuple(line for line in base.content_lines if line.endswith('/'))
    stems = {_stem(line) for line in directories}
    added = tuple(delta.added)
    bare = tuple(line for line in added if not line.startswith('!') and line.lstrip('*/') in stems)
    closures = tuple((index, line) for index, line in enumerate(added) if not line.startswith('!'))
    deep = tuple(index for index, line in enumerate(added) if line.startswith('!') and line.endswith('*'))
    reopened = tuple(
        line
        for index, line in enumerate(added)
        if line.startswith('!')
        and _stem(line) in stems
        and not any(after > index and _stem(closing) == _stem(line) for after, closing in closures)
    )
    unsealed = tuple(
        line
        for index, line in closures
        if line.endswith('/') and _stem(line) in stems and any(after > index for after in deep)
    )
    return Reopening(base_directories=directories, bare=bare, reopened=reopened, unsealed=unsealed)
