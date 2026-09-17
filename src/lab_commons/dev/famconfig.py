r"""The family's config artefacts as ONE BASE PLUS A NAMED DELTA, and a guard that reds on a hand edit.

THE DEFECT THIS CLOSES. `.gitignore`, `.pre-commit-config.yaml` and `Makefile` are hand-maintained
three times each across the consumers of this package, and the shared halves are large and boring --
the counts, and what each was measured over, are in :mod:`lab_commons.dev._famconfig_rows`, which is
DATA and computes nothing. Nothing links the copies, so a fix in one is a fix in one.

THE SHAPE. A repo declares a :class:`Delta` -- what it ADDS, WHERE, and which base lines it DROPS
with a reason -- and :func:`render` produces the file. :func:`inspect_file` re-renders from the LIVE
base and delta and compares against disk, so a hand edit reds instead of drifting. A consumer
therefore has exactly two states, which is this refactor's premise: it reads the family artefact, or
it declares its delta. There is no third state where a local edit quietly wins.

THIS MODULE IS THE WRITE HALF. The vocabulary (:class:`Base`, :class:`Delta`), the line readings and
the survey live in :mod:`lab_commons.dev._famconfig_survey` and are re-exported here, so the surface
a consumer imports is one name. The import runs one way: measuring a file does not need the renderer.

WHAT A DELTA MAY SAY, and this was the design question rather than a detail. A delta that can only
APPEND cannot express "not this one", so the first repo that genuinely does not want a base line
hand-edits the rendered file, and from that moment the guard is theatre. So a drop is expressible --
but it is a MAPPING from the dropped line to its reason, never a set, because a removal and a drift
are the same bytes on disk and only the DECLARATION can tell them apart. The rendering prints the
drop as a comment, so the removal is legible to a reader of the artefact and not only to a reader of
this package.

AND AN APPEND CANNOT REACH INSIDE A BLOCK, which is the same limit pointing the other way and it
blocked `.pre-commit-config.yaml` in both labs until 2026-09-17. Their extra `pre-commit-hooks` ids,
and the `exclude:` one of them must hang on `trailing-whitespace`, belong INSIDE the entry the base
renders. So an addition may be ANCHORED to a base line -- see :attr:`Delta.anchored` for why that was
preferred to dropping the block and restating it, which is a fork wearing a workaround as a disguise.
An anchor names a position by a base line's TEXT, so it is refused when the base does not have that
line, when the base has it more than once, and when the same delta also drops it.

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
  with no drop declaring it, and a drop or an anchor naming a line the base lacks is refused, so a
  stale declaration cannot outlive its subject either;
* a delta cannot silently grow into a fork -- every delta carries a CEILING counting its anchored
  lines too, a delta re-stating a base CONTENT line is refused at render time, and
  :func:`fork_signals` names any line EVERY consumer's delta holds, because that is the base
  re-forming where nobody is looking at it.

`[tool.ruff]` IS NOT HERE. It is the fourth config artefact the family census names and it belongs to
the stage widening this repo's select to the consumers' 58 selectors; two renderers on one artefact
while that sweep is live is a trap rather than a seam. Nothing checks that absence, which is exactly
what makes saying it out loud the only thing holding it.
"""

from __future__ import annotations

from collections.abc import Sequence
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
from lab_commons.dev._famconfig_survey import (
    MIN_BASE_LINES,
    Base,
    Delta,
    VacuousBase,
    assert_base_floor,
    delta_lines,
    fork_signals,
    meaningful_lines,
    measured_delta,
    satisfies,
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
    'delta_lines',
    'delta_problems',
    'fork_signals',
    'inspect_file',
    'meaningful_lines',
    'measured_delta',
    'render',
    'rendered_lines',
    'satisfies',
]

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


class ForkedDelta(ValueError):
    """A delta drops or anchors a line the base cannot carry, re-states one it has, or over-runs."""


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


def delta_problems(base: Base, delta: Delta) -> tuple[str, ...]:
    """Every way *delta* is not a delta of *base* -- pure over its arguments.

    EVERY COMPARISON IS AGAINST ``content_lines``, and that is the 2026-09-17 correction rather than
    a detail: this function read ``base.lines`` while the other four sites read ``content_lines``, so
    a delta line equal to a base BLANK was reported as re-stating the base. A blank is layout and
    carries nothing to copy, so it cannot be the fork the refusal exists for.

    THE STRUCTURAL LINES ARE STILL REFUSED AND THAT IS NOT THE SAME BUG. `    hooks:` is a content
    line, so it stays refused -- a second copy of a rendered block IS the base re-forming inside the
    delta. The remedy is an ANCHOR, which copies nothing, and the refusal names it.
    """
    out: list[str] = []
    known = set(base.content_lines)
    out += [
        f'{delta.repo} drops {line!r} from the {base.artefact} base, and the base does not have that '
        f'line. Delete the drop in the edit that removed the base line; a drop that outlives its '
        f'subject reads as a decision and refuses nothing.'
        for line in sorted(set(delta.dropped) - known)
    ]
    out += [
        f'{delta.repo} adds {line!r} to {base.artefact}, and the base already has it. A delta that '
        f're-states the base is the base copied into a place the guard does not re-render. If the '
        f'line was restated only to reach a position inside a rendered block, that is what a '
        f'Delta.anchored entry is for: anchor the new lines to the base line they belong under, and '
        f'copy nothing.'
        for line in sorted(set(delta_lines(delta)) & known)
    ]
    out += _anchor_problems(base, delta, known)
    if len(delta_lines(delta)) > delta.ceiling:
        out.append(
            f'{delta.repo} adds {len(delta_lines(delta))} lines to {base.artefact}, past its ceiling '
            f'of {delta.ceiling}. Raise the ceiling with the reason, or move what is shared into the '
            f'base. Anchored lines count here too, or anchoring would be a ceiling nobody chose.'
        )
    out += [
        f'{delta.repo} drops {line!r} from {base.artefact} with an empty reason. A removal and a '
        f'drift are the same bytes on disk; the reason is the only thing that tells them apart.'
        for line, reason in sorted(delta.dropped.items())
        if not reason.strip()
    ]
    return tuple(out)


def _anchor_problems(base: Base, delta: Delta, known: set[str]) -> list[str]:
    """Every way an anchor fails to name ONE live position in *base*.

    Three refusals, and each is the anchor's half of a ratchet the drops already have: an anchor on a
    line the base lacks (a declaration outliving its subject), an anchor on a line the base repeats
    (a position that is not a position -- the YAML base holds `    hooks:` twice, so picking one
    silently would be a coin flip the reader cannot see), and an anchor on a line the same delta
    drops (two declarations contradicting each other). The empty anchor is the fourth and it is the
    ratchet's other side: an anchor that adds nothing is a waiver nothing uses.
    """
    out: list[str] = []
    for line, added in sorted(delta.anchored.items()):
        if line not in known:
            out.append(
                f'{delta.repo} anchors {len(added)} line(s) to {line!r} in {base.artefact}, and the '
                f'base does not have that line. An anchor names a position by the text of a base '
                f'line, so it dies with the line it names -- move it, or delete it.'
            )
            continue
        if base.occurrences(line) > 1:
            out.append(
                f'{delta.repo} anchors to {line!r} in {base.artefact}, and the base has it '
                f'{base.occurrences(line)} times. That names no position. Anchor to a line that '
                f'occurs once -- a hook id, not a structural key.'
            )
        if line in delta.dropped:
            out.append(
                f'{delta.repo} drops it and anchors to it: {line!r} in {base.artefact}. One '
                f'declaration says the line goes and the other hangs content off it.'
            )
        if not added:
            out.append(
                f'{delta.repo} anchors no lines to {line!r} in {base.artefact}. An anchor that adds '
                f'nothing is a waiver nothing uses -- delete the entry.'
            )
    return out


def rendered_lines(base: Base, delta: Delta) -> tuple[str, ...]:
    """The file *base* plus *delta* produces, as lines, stamp included.

    A dropped base line is rendered as a COMMENT naming the repo and the reason, in place. That is
    what makes a removal legible to somebody reading the artefact rather than only to somebody
    reading this package -- a deletion that leaves no trace in the file is indistinguishable from the
    line never having been in the base. An anchored block gets the same treatment for the same
    reason: a comment at the anchor's own indentation says whose lines follow and how many, so the
    reader of the artefact can see where the base stops and the repo starts.
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
        anchored = delta.anchored.get(line, ())
        if anchored:
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f'{indent}{base.comment} {delta.repo} delta, anchored here: {len(anchored)} line(s)')
            out += list(anchored)
    if delta.added:
        out += ['', f'{base.comment} --- {delta.repo} delta, {len(delta.added)} of {delta.ceiling} allowed ---']
        out += list(delta.added)
    return tuple(out)


def render(base: Base, delta: Delta) -> str:
    """:func:`rendered_lines` as text, newline-terminated."""
    return '\n'.join(rendered_lines(base, delta)) + '\n'


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
