r"""The READ half of the family-config body: what a FILE says, and what an ENGINE resolved.

SPLIT OUT OF :mod:`lab_commons.dev.famtests.configrender` at the seam
:mod:`lab_commons.dev._famconfig_survey` already runs on one layer down, and for the same reason:
everything here is a READING and everything there is a VERDICT. A reading answers "what is in this
file" or "what did the engine say"; a verdict adds a floor, compares against a declaration and names
a remedy. Keeping them apart is what lets a consumer parametrize on a reading -- ``reopenings`` and
``stage_partition`` are pure and can be asserted on directly -- without going through an assert that
has already decided what the answer should have been.

THE ONE REFUSAL THAT LIVES HERE IS :class:`UnresolvedHooks`, because a floor belongs beside the
reading it refuses rather than beside the caller that happens to hit it.

``None`` IS NEVER THE EMPTY RESULT in this module. :func:`declared_hook_ids` answers ``None`` for a
file it could not read and a frozenset for one that declares nothing, and collapsing the two is how
a missing artefact reports as a repo that simply declares no hooks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from lab_commons.dev.famconfig import Base, Delta

__all__ = [
    'HookStages',
    'Reopening',
    'StagePartition',
    'StageResolver',
    'UnresolvedHooks',
    'assert_floor',
    'declared_hook_ids',
    'reopenings',
    'resolved_stages',
    'stage_partition',
]

#: How a resolved hook table is spelled here: id -> the stages it actually runs at.
type HookStages = dict[str, frozenset[str]]

#: How a ``.pre-commit-config.yaml`` spells a hook id. A prefix rather than a parse, because the
#: family's guarantee is about the ids a reader can SEE in the file, and a YAML parser would also
#: need a YAML dependency this layer does not have.
_ID_PREFIX = '- id: '


class UnresolvedHooks(AssertionError):
    """The stage engine did not answer, or answered below its floor. NEVER an empty table.

    Its own exception rather than a bare assertion because the two failures it covers have different
    remedies -- fix the engine, or fix the config -- and both are distinct from "the declaration
    disagrees with the measurement", which is what the assert itself reports.
    """


class StageResolver(Protocol):
    """The engine that resolves a config into hooks. Supplied by the consumer; see the module docstring."""

    def __call__(self, config: Path) -> Iterable[object]:
        """Return objects carrying an ``id`` and a ``stages`` iterable, for the config at *config*."""
        ...


@dataclass(frozen=True)
class StagePartition:
    """One resolved hook table, split the two ways a stage adoption has to be read.

    Attributes:
        narrowed: hooks the base's ``default_stages`` reduced to ``pre-commit`` alone.
        pre_push: hooks that still reach ``pre-push``.
        total: how many hooks the engine resolved, so a reader can see the scan was not empty.

    """

    narrowed: frozenset[str]
    pre_push: frozenset[str]
    total: int


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


def declared_hook_ids(config: Path) -> frozenset[str] | None:
    """Every hook id spelled in *config*, or ``None`` when the file could not be read.

    ``None`` is NOT the empty set. A config that is not there names no ids and denies none either,
    and collapsing the two is how a missing file reports as a repo that declares nothing.
    """
    try:
        text = config.read_text(encoding='utf-8')
    except OSError:
        return None
    return frozenset(
        line.strip().removeprefix(_ID_PREFIX) for line in text.splitlines() if line.strip().startswith(_ID_PREFIX)
    )


def resolved_stages(config: Path, *, resolve: StageResolver) -> HookStages:
    """Which stages each hook runs at, according to the engine the git hook itself runs.

    An engine that RAISES is reported as unresolved rather than as an empty table: a question that
    could not be asked and a question answered "none" are different facts, and only one of them is
    consistent with a declaration that everything narrowed.
    """
    try:
        hooks = tuple(resolve(config))
    except Exception as failure:
        msg = f'the stage engine could not load {config}: {failure!r}. Nothing was measured.'
        raise UnresolvedHooks(msg) from failure
    return {str(hook.id): frozenset(hook.stages) for hook in hooks}


def stage_partition(hooks: HookStages) -> StagePartition:
    """Split a resolved table the two ways a stage adoption has to be read. PURE over its argument."""
    return StagePartition(
        narrowed=frozenset(name for name, stages in hooks.items() if stages == frozenset({'pre-commit'})),
        pre_push=frozenset(name for name, stages in hooks.items() if 'pre-push' in stages),
        total=len(hooks),
    )
