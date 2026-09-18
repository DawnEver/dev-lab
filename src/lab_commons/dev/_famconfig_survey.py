r"""The READ half of the family-config mechanism: what a file SAYS, and what a delta declares.

SPLIT OUT OF :mod:`lab_commons.dev.famconfig` ON 2026-09-17, at the seam that module's own refactor
note named. `famconfig` is the WRITE half -- it renders, compares and refuses -- and it now imports
everything here. The dependency runs one way on purpose: measuring a file cannot require the
renderer, so the survey an adoption lane runs before touching a consumer has nothing to do with the
guard that will later judge it.

THE VOCABULARY TRAVELS WITH THE SURVEY rather than into a third module. :class:`Base` and
:class:`Delta` are what both halves talk through, and the survey CONSTRUCTS a `Delta` -- a module
holding two dataclasses and nothing else would be a split made to fit a line count rather than a
seam, which is the band deforming the code it measures.

Nothing here writes, renders or raises about rendering. The one refusal that lives here is
:class:`VacuousBase`, because a floor belongs beside the reading it refuses.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from lab_commons.dev._famconfig_rows import REPO_FLOOR, STAMP

__all__ = [
    'MIN_BASE_LINES',
    'Base',
    'Delta',
    'VacuousBase',
    'assert_base_floor',
    'delta_lines',
    'floating_subject',
    'fork_signals',
    'meaningful_lines',
    'measured_delta',
    'negated_base_lines',
    'positional_base_lines',
    'satisfies',
]

#: The smallest base that can carry a guarantee. ONE, because its subject is a table that read EMPTY:
#: the per-artefact counts are pinned in the data module, and pinning them twice would red on every
#: line the family agrees to share.
MIN_BASE_LINES: Final = 1


class VacuousBase(AssertionError):
    """A base held fewer lines than its floor, so rendering or checking it proves nothing."""


def assert_base_floor(reached: int, floor: int, what: str) -> None:
    """Refuse a base that read below *floor* lines -- an empty table renders a clean-looking file."""
    if reached < floor:
        msg = (
            f'the {what} base holds only {reached} lines, below the {floor} floor. A base that read '
            f'empty renders a file every consumer passes against, which is the vacuous green this '
            f'guard exists to refuse. Fix the table, do not lower the floor.'
        )
        raise VacuousBase(msg)


@dataclass(frozen=True, slots=True)
class Base:
    """One family artefact: its lines, how strictly they bind, and how a comment is spelled in it."""

    artefact: str
    lines: tuple[str, ...]
    mode: str
    comment: str = '#'

    @property
    def content_lines(self) -> tuple[str, ...]:
        """The base lines that CARRY something -- a blank renders as layout and cannot be absent.

        `meaningful_lines` strips blanks off the disk side, so comparing them would report every
        blank as a missing base line and bury the two that matter. Every reader of "is this line the
        base's" reads THIS, including :func:`lab_commons.dev.famconfig.delta_problems`, which until
        2026-09-17 was the one exception and reported a BLANK delta line as a re-statement.
        """
        return tuple(line for line in self.lines if line.strip())

    @property
    def stamp_lines(self) -> tuple[str, ...]:
        """The provenance block, in this artefact's own comment syntax."""
        return (
            f'{self.comment} {STAMP} from the family base for {self.artefact}.',
            f'{self.comment} Hand edits RED. The base is data in lab_commons.dev._famconfig_rows;',
            f"{self.comment} this repo's own lines are its declared delta. Change one, re-render, commit.",
        )

    def occurrences(self, line: str) -> int:
        """How many times *line* appears in this base -- the question an ANCHOR has to ask.

        A YAML base repeats its structural lines by construction (`    hooks:` twice here), so a
        position named by line text is only a position when the text occurs exactly once.
        """
        return self.lines.count(line)


@dataclass(frozen=True, slots=True)
class Delta:
    """What one repo adds to a base, where it adds it, and which base lines it drops WITH the reason.

    ``ceiling`` has no default on purpose. An escape hatch needs a ceiling rather than a reason, and a
    default ceiling is a ceiling nobody chose -- the number is the point at which this repo's delta
    has stopped being a delta, and only the repo can say where that is.

    ``anchored`` IS THE NESTED ADDITION, added 2026-09-17, and it is why `.pre-commit-config.yaml` is
    adoptable at all. ``added`` appends after the whole base, which cannot place a line INSIDE a
    rendered block -- and every hook a lab runs beyond the family's eleven, plus the `exclude:` one
    of them must hang on `trailing-whitespace`, lives exactly there. It maps a base line to the lines
    rendered immediately AFTER it.

    THE ALTERNATIVE WAS REFUSED, and naming it is the point: the block could instead be dropped and
    RESTATED in ``added``, which is the base copied into a place re-rendering no longer guards --
    precisely the fork :func:`fork_signals` exists to catch. An anchor copies nothing, so the base
    keeps owning its own lines, and a removal stays a ``dropped`` entry with a reason rather than
    becoming indistinguishable from an anchored block that quietly lost a row.
    """

    repo: str
    added: tuple[str, ...]
    dropped: Mapping[str, str]
    ceiling: int
    anchored: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


def delta_lines(delta: Delta) -> tuple[str, ...]:
    """Every line *delta* contributes, appended or anchored, in one sequence.

    The ceiling and the anti-fork scan both read THIS rather than ``added``: a line that did not
    count because of where it sits would be an escape hatch with no ceiling, and one the fork scan
    could not see would be the base re-forming in the half nobody looks at.
    """
    return tuple(delta.added) + tuple(line for lines in delta.anchored.values() for line in lines)


def meaningful_lines(text: str, comment: str) -> tuple[str, ...]:
    """*text*'s lines with blanks and whole-line comments removed, each stripped of trailing space.

    Leading whitespace is KEPT: a Makefile recipe is a tab, and a YAML nesting level is two spaces,
    so a comparison that stripped the left margin would call two different files equal.
    """
    return tuple(line.rstrip() for line in text.splitlines() if line.strip() and not line.strip().startswith(comment))


def satisfies(required: str, live: Sequence[str]) -> bool:
    """Whether *required* is met by one of *live* -- a TARGET HEADER matching by its name only.

    MEASURED, AND THIS IS WHY THE FUNCTION EXISTS RATHER THAN AN ``in``. A first cut compared headers
    literally and called `all:` absent from all three consumers, `install-dev:` absent from wdg-lab
    and `verify:` absent from two -- every one a false positive, because a Makefile target carries its
    prerequisites on the same line (`all: install-dev lint test`), and a contract over target NAMES
    that reds on that is a contract about punctuation. So a base line ending in a colon matches by
    PREFIX and everything else exactly, which keeps the recipe lines byte-checked.
    """
    if required.endswith(':'):
        return any(line == required or line.startswith(required + ' ') for line in live)
    return required in live


def recipe_blocks(lines: Sequence[str]) -> dict[str, tuple[str, ...]]:
    """``{header: its indented lines}``, derived from ORDER -- never from a second hand-written table.

    A block opens on an UNINDENTED line and continues through every indented line after it. That is
    the whole grammar this needs, and it is deliberately not a Makefile parser: the only question is
    which lines BELONG to which header, which is what :func:`satisfies` cannot see because it is a
    predicate over one line at a time.

    Deriving the blocks from the base's own line order is what keeps this from being a declaration
    that can drift -- a recipe moved under a different target in the base moves here in the same
    edit. An artefact with no indentation at all, a ``.gitignore``, yields blocks that are all empty,
    so :func:`unbound_recipes` has nothing to say about it and says nothing.
    """
    blocks: dict[str, tuple[str, ...]] = {}
    header: str | None = None
    for line in lines:
        if line[:1].isspace():
            if header is not None:
                blocks[header] = (*blocks[header], line)
        else:
            header = line
            blocks.setdefault(header, ())
    return blocks


def unbound_recipes(required: Sequence[str], live: Sequence[str]) -> tuple[str, ...]:
    """Base recipe lines present in *live* but NOT under the header they sit under in *required*.

    THE HOLE THIS CLOSES, MEASURED 2026-09-18 against the live Makefile base. :func:`satisfies`
    matches a colon-terminated base line by TARGET NAME ALONE, and every other base line by
    membership ANYWHERE in the file. Each is right on its own, and together they cannot see an
    ASSOCIATION: a Makefile whose ``verify:`` is followed by nothing, with
    ``python -m lab_commons.dev.verify`` sitting under ``all:`` instead, satisfies BOTH base lines
    and reports INSTALLED. ``make verify`` then does nothing, and under ``REQUIRED`` nothing else
    byte-checks that recipe.

    It is the recipe-shaped twin of the count pin: ``REQUIRED`` can see a target DISAPPEAR and cannot
    see one GUTTED -- and gutted is the state a reader is least likely to look for, because the
    target is right there in the file.

    TWO THINGS ARE DELIBERATELY NOT REPORTED HERE, and both are the same rule: one defect, one voice.
    A header MISSING entirely is already a missing base line. And a recipe line that is nowhere in the
    file at all is already a missing base line too -- reporting it would also make the message UNTRUE,
    since it says the line is in the file. So the complaint fires only when the recipe really is
    present and really is under something else, which is the state no other arm can see.

    Args:
        required: the base's content lines, IN ORDER, so the association can be derived at all.
        live: the file's meaningful lines, in order.

    Returns:
        One complaint per orphaned recipe line, sorted, naming the header it belongs under.

    """
    wanted = recipe_blocks(required)
    found = recipe_blocks(live)
    anywhere = set(live)
    problems: list[str] = []
    for header, recipes in wanted.items():
        if not recipes or not any(satisfies(header, (name,)) for name in found):
            continue
        under = {line for name, lines in found.items() if satisfies(header, (name,)) for line in lines}
        problems.extend(
            f'{line!r} is in the file but not under {header!r} -- the target is present and its recipe is '
            f'not, so it runs and does nothing'
            for line in recipes
            if line in anywhere and line not in under
        )
    return tuple(sorted(problems))


def measured_delta(path: Path, base: Base, repo: str) -> Delta:
    """What *path* would have to declare, today, to be a rendering of *base*.

    The survey half, READ-ONLY: how an adoption lane sizes the change in a consumer before touching
    it, and how :func:`fork_signals` gets real deltas. The ceiling it returns is the measurement
    itself -- a starting point, not a decision; stating one is the act that makes it a ceiling.

    It returns an APPENDING delta and never an anchored one, because where a measured line belongs is
    a judgement about the artefact's grammar that reading the file cannot make. Deciding it is the
    adoption commit's job, which is also why this returns a starting point rather than an answer.
    """
    live = meaningful_lines(path.read_text(encoding='utf-8'), base.comment) if path.is_file() else ()
    added = tuple(line for line in live if not any(satisfies(base_line, (line,)) for base_line in base.content_lines))
    dropped = {
        line: 'MEASURED: absent from the file on disk at survey time'
        for line in base.content_lines
        if not satisfies(line, live)
    }
    return Delta(repo=repo, added=added, dropped=dropped, ceiling=len(added))


def floating_subject(line: str) -> str | None:
    """The path suffix a `**/`-prefixed rule matches at ANY depth, or ``None`` if *line* is not one.

    `**/__pycache__/` answers `/__pycache__/` -- it excludes a directory of that name wherever it
    sits, so EVERY rule ending in that suffix names a subset of what it already names. `**/log/*.log`
    answers ``None``: it carries a path of its own below the wildcard, so it is a rule about a
    LOCATION and a deeper rule can genuinely narrow it. `**/temp/**` answers ``None`` for the same
    reason from the other end.
    """
    if not line.startswith('**/'):
        return None
    rest = line[3:]
    return None if '/' in rest.rstrip('/') else '/' + rest


def negated_base_lines(base: Base) -> tuple[str, ...]:
    """Base lines that RE-INCLUDE rather than exclude -- a `.gitignore` negation. PURE.

    THE OTHER HALF OF THE SORTED TABLE'S PROSE. `_famconfig_rows` justifies storing its `.gitignore`
    sorted with "order-insensitive apart from negations, AND THE BASE DECLARES NONE"; the re-ignore
    arm mechanised the first clause and this one mechanises the second. A negation is meaningful only
    BELOW the rule it re-includes from, and `!` sorts below every character a rule can start with, so
    a negation in this table renders above its own subject and does nothing -- and the anchor points
    one way, so no delta can move it down.

    :func:`positional_base_lines` cannot see this line and never could: it reads a rule as a SET OF
    PATHS and asks what subsumes it, while a negation excludes no paths at all, so nothing subsumes
    it and it is reported clean.
    """
    return tuple(line for line in base.content_lines if line.startswith('!'))


def positional_base_lines(base: Base, *, floating_floor: int) -> tuple[str, ...]:
    """Base lines that carry NO set of paths a floating sibling does not already carry. PURE.

    THE READING THAT GIVES THE SORTED BASE ITS MECHANISM. `_famconfig_rows` stores its `.gitignore`
    table sorted, on the stated ground that the file is order-insensitive apart from negations and
    the base declares none. Nothing checked that, and a `Delta` cannot fix it after the fact: anchors
    point one way only, so every base line renders BEFORE every delta line and a base line that needs
    to come last has no way to say so.

    A rule that is a strict subset of a floating rule already in the base excludes nothing new. Its
    only possible contribution is POSITION -- it is a RE-IGNORE, written below a negation to win a
    last-match-wins argument -- and position is exactly what a sorted table cannot carry. So the
    reading is over the base ALONE and needs no delta, which is what makes it bind on a promotion out
    of a repo nobody surveyed.

    *floating_floor* has NO default. How many floating rules a base carries is a fact about that base,
    and a scan that found none would report subsumption nowhere and read exactly like a clean table.
    """
    subjects = {line: subject for line in base.content_lines if (subject := floating_subject(line))}
    assert_base_floor(len(subjects), floating_floor, f'{base.artefact} floating-rule')
    return tuple(
        line
        for line in base.content_lines
        if any(line != floater and line.endswith(subject) for floater, subject in subjects.items())
    )


def fork_signals(deltas: Sequence[Delta], floor: int = REPO_FLOOR) -> tuple[str, ...]:
    """Lines that EVERY delta contributes -- the base re-forming where no base line can guard it.

    The anti-fork arm, and the reason it takes a floor: a comparison over one delta finds every line
    it holds, and a comparison over zero finds nothing and reads exactly like agreement.
    """
    if len(deltas) < floor:
        msg = (
            f'fork_signals read {len(deltas)} delta(s), below the {floor} floor. Comparing fewer '
            f'deltas than the family has repos cannot say whether a line is shared; finding nothing '
            f'there is vacuous rather than green.'
        )
        raise VacuousBase(msg)
    shared = set(delta_lines(deltas[0]))
    for delta in deltas[1:]:
        shared &= set(delta_lines(delta))
    return tuple(
        f'every delta adds {line!r} -- {len(deltas)} repos declaring one line is a base line that was '
        f'never promoted. Move it into lab_commons.dev._famconfig_rows.'
        for line in sorted(shared)
    )
