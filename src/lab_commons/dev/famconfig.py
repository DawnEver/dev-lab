r"""The family's config artefacts as ONE BASE PLUS A NAMED DELTA, and a guard that reds on a hand edit.

THE DEFECT THIS CLOSES. `.gitignore`, `.pre-commit-config.yaml` and `Makefile` are hand-maintained
three times each across the consumers of this package, and the shared halves are large and boring --
the counts, and what each was measured over, are in :mod:`lab_commons.dev._famconfig_rows`, which is
DATA and computes nothing. Nothing links the copies, so a fix in one is a fix in one.

THE SHAPE. A repo declares a :class:`Delta` -- what it ADDS, and which base lines it DROPS with a
reason -- and :func:`render` produces the file. :func:`inspect_file` re-renders from the LIVE base
and delta and compares against disk, so a hand edit reds instead of drifting. A consumer therefore
has exactly two states, which is this refactor's premise: it reads the family artefact, or it
declares its delta. There is no third state where a local edit quietly wins.

WHAT A DELTA MAY SAY, and this was the design question rather than a detail. A delta that can only
APPEND cannot express "not this one", so the first repo that genuinely does not want a base line
hand-edits the rendered file, and from that moment the guard is theatre. So a drop is expressible --
but it is a MAPPING from the dropped line to its reason, never a set, because a removal and a drift
are the same bytes on disk and only the DECLARATION can tell them apart. The rendering prints the
drop as a comment, so the removal is legible to a reader of the artefact and not only to a reader of
this package.

THE STAMP, AND WHAT IT DELIBERATELY DOES NOT CARRY. A rendered file opens with a provenance block --
the shape :mod:`lab_commons.dev.agent_guard` proves out on the hook engine, where an unstamped copy
and a stale one need different remedies and bytes-differ cannot tell them apart. The block names the
renderer and nothing else: no version, no date, no digest. A timestamp would make every re-render a
diff, which is how a generated file earns the reputation that justifies editing it by hand; and a
stored digest can itself go stale, while re-rendering from the live base cannot.

RENDERED VERSUS REQUIRED, and the Makefile is why there are two modes. Its shared targets share a
NAME and no RECIPE, so a rendered family Makefile would assert a portability that does not exist.
:data:`REQUIRED` says the base lines must be PRESENT, :data:`RENDERED` demands byte equality, and
naming the weaker mode is what stops it reaching `.gitignore` out of convenience.

A RATCHET HAS TWO SIDES, and both are mechanised rather than described:

* a base line cannot silently vanish -- :func:`inspect_file` reds on a base line absent from disk
  with no drop declaring it, and a drop naming a line the base lacks is refused, so a stale drop
  cannot outlive its subject either;
* a delta cannot silently grow into a fork -- every delta carries a CEILING, a delta re-stating a
  base line is refused at render time, and :func:`fork_signals` names any line EVERY consumer's
  delta holds, because that is the base re-forming where nobody is looking at it.

`[tool.ruff]` IS NOT HERE. It is the fourth config artefact the family census names and it belongs to
the stage widening this repo's select to the consumers' 58 selectors; two renderers on one artefact
while that sweep is live is a trap rather than a seam. Nothing checks that absence, which is exactly
what makes saying it out loud the only thing holding it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lab_commons.dev._famconfig_rows import BASES as _BASE_LINES
from lab_commons.dev._famconfig_rows import (
    GITIGNORE_FLOOR,
    HOOK_ID_CORE,
    MAKE_TARGET_CORE,
    REPO_FLOOR,
    STAMP,
)

__all__ = [
    'ABSENT',
    'BASES',
    'DRIFTED',
    'FOREIGN',
    'GITIGNORE_FLOOR',
    'HOOK_ID_CORE',
    'INSTALLED',
    'MAKE_TARGET_CORE',
    'MIN_BASE_LINES',
    'RENDERED',
    'REPO_FLOOR',
    'REQUIRED',
    'STAMP',
    'ArtefactReport',
    'Base',
    'Delta',
    'ForkedDelta',
    'VacuousBase',
    'artefact_base',
    'assert_base_floor',
    'delta_problems',
    'fork_signals',
    'inspect_file',
    'measured_delta',
    'render',
    'rendered_lines',
    'satisfies',
]

#: The smallest base that can carry a guarantee. ONE, because its subject is a table that read EMPTY:
#: the per-artefact counts are pinned in the data module, and pinning them twice would red on every
#: line the family agrees to share.
MIN_BASE_LINES: Final = 1

#: MODE. The file must equal base-plus-delta byte for byte.
RENDERED: Final = 'RENDERED'
#: MODE. The base lines must be PRESENT and the rest of the file is the repo's. The weaker of the
#: two, named so that applying it is a decision somebody typed.
REQUIRED: Final = 'REQUIRED'
#: STATUS. No file at the path -- every guarantee the base carries is absent, not merely unchecked.
ABSENT: Final = 'ABSENT'
#: STATUS. The file on disk is what the live base and delta render.
INSTALLED: Final = 'INSTALLED'
#: STATUS. Stamped by this renderer, and its bytes differ from what base and delta now produce.
DRIFTED: Final = 'DRIFTED'
#: STATUS. Unstamped and not what the base renders -- somebody's own file, which rendering would clobber.
FOREIGN: Final = 'FOREIGN'


class VacuousBase(AssertionError):
    """A base held fewer lines than its floor, so rendering or checking it proves nothing."""


class ForkedDelta(ValueError):
    """A delta drops a line the base does not have, re-states one it does, or exceeds its ceiling."""


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
        blank as a missing base line and bury the two that matter.
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


#: Every artefact, by name. Built from the data table rather than restated, so a base added there
#: arrives here and a base deleted there cannot leave a live entry behind.
BASES: Final[dict[str, Base]] = {
    '.gitignore': Base('.gitignore', _BASE_LINES['.gitignore'], RENDERED),
    '.pre-commit-config.yaml': Base('.pre-commit-config.yaml', _BASE_LINES['.pre-commit-config.yaml'], RENDERED),
    'Makefile': Base('Makefile', _BASE_LINES['Makefile'], REQUIRED),
}


def artefact_base(artefact: str) -> Base:
    """The base for *artefact*, or a refusal naming the ones that exist.

    A lookup rather than an attribute so that an artefact this package does not own fails HERE, with
    the set it could have meant, instead of at the point a caller indexes ``None``.
    """
    try:
        return BASES[artefact]
    except KeyError:
        msg = (
            f'no family base for {artefact!r}. Declared artefacts: {sorted(BASES)}. A config file '
            f'with no base is not shared by default -- add the row to lab_commons.dev._famconfig_rows '
            f'with the measurement that says it is shared.'
        )
        raise ForkedDelta(msg) from None


@dataclass(frozen=True, slots=True)
class Delta:
    """What one repo adds to a base, and which base lines it drops WITH the reason it drops them.

    ``ceiling`` has no default on purpose. An escape hatch needs a ceiling rather than a reason, and a
    default ceiling is a ceiling nobody chose -- the number is the point at which this repo's delta
    has stopped being a delta, and only the repo can say where that is.
    """

    repo: str
    added: tuple[str, ...]
    dropped: Mapping[str, str]
    ceiling: int


def delta_problems(base: Base, delta: Delta) -> tuple[str, ...]:
    """Every way *delta* is not a delta of *base* -- pure over its arguments.

    Three refusals, and each is one half of a ratchet: a drop naming a line the base does not have
    (so a drop cannot outlive its base line), an addition that re-states a base line (so the base
    cannot be duplicated into the delta and then edited there), and a delta past its own ceiling.
    """
    out: list[str] = []
    known = set(base.lines)
    out += [
        f'{delta.repo} drops {line!r} from the {base.artefact} base, and the base does not have that '
        f'line. Delete the drop in the edit that removed the base line; a drop that outlives its '
        f'subject reads as a decision and refuses nothing.'
        for line in sorted(set(delta.dropped) - known)
    ]
    out += [
        f'{delta.repo} adds {line!r} to {base.artefact}, and the base already has it. A delta that '
        f're-states the base is the base copied into a place the guard does not re-render.'
        for line in sorted(set(delta.added) & known)
    ]
    if len(delta.added) > delta.ceiling:
        out.append(
            f'{delta.repo} adds {len(delta.added)} lines to {base.artefact}, past its ceiling of '
            f'{delta.ceiling}. Raise the ceiling with the reason, or move what is shared into the base.'
        )
    out += [
        f'{delta.repo} drops {line!r} from {base.artefact} with an empty reason. A removal and a '
        f'drift are the same bytes on disk; the reason is the only thing that tells them apart.'
        for line, reason in sorted(delta.dropped.items())
        if not reason.strip()
    ]
    return tuple(out)


def rendered_lines(base: Base, delta: Delta) -> tuple[str, ...]:
    """The file *base* plus *delta* produces, as lines, stamp included.

    A dropped base line is rendered as a COMMENT naming the repo and the reason, in place. That is
    what makes a removal legible to somebody reading the artefact rather than only to somebody
    reading this package -- a deletion that leaves no trace in the file is indistinguishable from the
    line never having been in the base.
    """
    problems = delta_problems(base, delta)
    if problems:
        raise ForkedDelta('\n'.join(problems))
    assert_base_floor(len(base.lines), MIN_BASE_LINES, base.artefact)
    out = [*base.stamp_lines, '']
    for line in base.lines:
        reason = delta.dropped.get(line)
        if reason is None:
            out.append(line)
        else:
            out.append(f'{base.comment} dropped from the base by {delta.repo}: {line} -- {reason}')
    if delta.added:
        out += ['', f'{base.comment} --- {delta.repo} delta, {len(delta.added)} of {delta.ceiling} allowed ---']
        out += list(delta.added)
    return tuple(out)


def render(base: Base, delta: Delta) -> str:
    """:func:`rendered_lines` as text, newline-terminated."""
    return '\n'.join(rendered_lines(base, delta)) + '\n'


def meaningful_lines(text: str, comment: str) -> tuple[str, ...]:
    """*text*'s lines with blanks and whole-line comments removed, each stripped of trailing space.

    Leading whitespace is KEPT: a Makefile recipe is a tab, and a YAML nesting level is two spaces,
    so a comparison that stripped the left margin would call two different files equal.
    """
    return tuple(line.rstrip() for line in text.splitlines() if line.strip() and not line.strip().startswith(comment))


@dataclass(frozen=True, slots=True)
class ArtefactReport:
    """One artefact in one repo: where it is, what state it is in, and which lines say so."""

    artefact: str
    path: Path
    status: str
    detail: str
    offending: tuple[str, ...]

    @property
    def ok(self) -> bool:
        """Whether the file on disk is what the live base and delta say it should be."""
        return self.status == INSTALLED


def inspect_file(path: Path, base: Base, delta: Delta) -> ArtefactReport:
    """Compare the file at *path* against what *base* and *delta* render RIGHT NOW.

    Re-rendering rather than comparing a stored digest is the whole mechanism: no recorded answer can
    go stale, so a base edited here moves every consumer's verdict on the next run.
    """
    if not path.is_file():
        detail = f'no {base.artefact} here -- the base guarantees nothing at this path, it is absent rather than clean'
        return ArtefactReport(base.artefact, path, ABSENT, detail, ())
    text = path.read_text(encoding='utf-8')
    live = meaningful_lines(text, base.comment)
    if base.mode == REQUIRED:
        return _required_report(path, base, delta, live)
    expected = rendered_lines(base, delta)
    if text == render(base, delta):
        return ArtefactReport(base.artefact, path, INSTALLED, f'{len(expected)} lines, as rendered', ())
    offending = _line_differences(meaningful_lines('\n'.join(expected), base.comment), live)
    if STAMP not in text:
        detail = (
            f'unstamped and not what the base renders: a {base.artefact} this package did not write. '
            f'Rendering over it would clobber it -- declare its lines as a Delta first.'
        )
        return ArtefactReport(base.artefact, path, FOREIGN, detail, offending)
    detail = (
        f'stamped by this renderer and {len(offending)} line(s) differ from what the live base and '
        f"{delta.repo}'s delta produce. Re-render; if the edit was wanted, it is a delta line or a "
        f'declared drop, and both of those live in code.'
    )
    return ArtefactReport(base.artefact, path, DRIFTED, detail, offending)


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


def _required_report(path: Path, base: Base, delta: Delta, live: tuple[str, ...]) -> ArtefactReport:
    """The weaker mode: every base line present, unless a drop declares it gone."""
    problems = delta_problems(base, delta)
    if problems:
        raise ForkedDelta('\n'.join(problems))
    missing = tuple(line for line in base.content_lines if line not in delta.dropped and not satisfies(line, live))
    resurrected = tuple(line for line in delta.dropped if satisfies(line, live))
    offending = missing + resurrected
    if not offending:
        return ArtefactReport(base.artefact, path, INSTALLED, f'all {len(base.content_lines)} base lines present', ())
    detail = (
        f'{len(missing)} base line(s) absent with no declared drop, {len(resurrected)} declared drop(s) '
        f'present after all. A base line may leave this file only through a Delta.dropped entry that '
        f'says why, and a drop that is contradicted by the file is a declaration that lies.'
    )
    return ArtefactReport(base.artefact, path, DRIFTED, detail, offending)


def _line_differences(expected: Sequence[str], live: Sequence[str]) -> tuple[str, ...]:
    """Which meaningful lines are missing from disk and which are there uninvited."""
    out = [f'missing: {line}' for line in expected if line not in live]
    out += [f'unexpected: {line}' for line in live if line not in expected]
    return tuple(out)


def measured_delta(path: Path, base: Base, repo: str) -> Delta:
    """What *path* would have to declare, today, to be a rendering of *base*.

    The survey half, READ-ONLY: how an adoption lane sizes the change in a consumer before touching
    it, and how :func:`fork_signals` gets real deltas. The ceiling it returns is the measurement
    itself -- a starting point, not a decision; stating one is the act that makes it a ceiling.
    """
    live = meaningful_lines(path.read_text(encoding='utf-8'), base.comment) if path.is_file() else ()
    added = tuple(line for line in live if not any(satisfies(base_line, (line,)) for base_line in base.content_lines))
    dropped = {
        line: 'MEASURED: absent from the file on disk at survey time'
        for line in base.content_lines
        if not satisfies(line, live)
    }
    return Delta(repo=repo, added=added, dropped=dropped, ceiling=len(added))


def fork_signals(deltas: Sequence[Delta], floor: int = REPO_FLOOR) -> tuple[str, ...]:
    """Lines that EVERY delta adds -- the base re-forming where no base line can guard it.

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
    shared = set(deltas[0].added)
    for delta in deltas[1:]:
        shared &= set(delta.added)
    return tuple(
        f'every delta adds {line!r} -- {len(deltas)} repos declaring one line is a base line that was '
        f'never promoted. Move it into lab_commons.dev._famconfig_rows.'
        for line in sorted(shared)
    )
