r"""What makes a DECLARATION illegal: every refusal the family-config mechanism can raise.

SPLIT OUT OF :mod:`lab_commons.dev.famconfig` ON 2026-09-18, when the ordering arm took that module
past this repo's 400-line band. The seam is the one its own first sentence names -- "one base plus a
named delta, AND A GUARD THAT REDS" -- so the renderer, the comparison and the file statuses stay
there and every way a declaration can be refused is here.

THE TEST OF THE SEAM IS THE IMPORT DIRECTION, and it runs one way: a refusal reads a `Base` and a
`Delta` and answers, and it never renders. `famconfig` re-exports every name below, so the surface a
consumer imports is still one module.

THE TWO REFUSALS ARE ABOUT DIFFERENT THINGS, which is why they are separate exceptions rather than
one. :class:`ForkedDelta` is about a DELTA -- it drops, anchors or re-states something the base
cannot carry, or it over-runs its ceiling. :class:`PositionalBase` is about the BASE, and it is the
newer half: an anchor points ONE way, so every base line renders before every delta line, and in a
last-match-wins artefact a line whose only contribution is its POSITION therefore cannot be a base
line at all. `fork_signals` -- the anti-fork arm one layer over -- would argue FOR promoting exactly
such a line, because every consumer's delta holds it. These two arms disagree on purpose.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lab_commons.dev._famconfig_rows import ORDER_SENSITIVE_ARTEFACTS
from lab_commons.dev._famconfig_survey import delta_lines, negated_base_lines, positional_base_lines

if TYPE_CHECKING:
    from lab_commons.dev._famconfig_survey import Base, Delta

__all__ = [
    'ForkedDelta',
    'PositionalBase',
    'assert_base_is_order_free',
    'delta_problems',
]


class ForkedDelta(ValueError):
    """A delta drops or anchors a line the base cannot carry, re-states one it has, or over-runs."""


class PositionalBase(ValueError):
    """A base for a last-match-wins artefact holds a line whose only contribution is its POSITION."""


def assert_base_is_order_free(base: Base) -> None:
    """Refuse a base that needs an ordering this table cannot express. The one-way anchor's other half.

    :attr:`Delta.anchored` renders delta lines AFTER a named base line and there is no expression for
    the reverse, so every base line precedes every delta line. In a LAST-MATCH-WINS artefact that
    makes a re-ignore unpromotable: it would render above the negation it was written to close, and
    the file would go quietly back to the behaviour the re-ignore was added to fix.

    TWO SHAPES ARE REFUSED, and they are blind to each other. A RE-IGNORE excludes a strict subset of
    what a floating base rule already excludes, so its only contribution is position. A NEGATION
    excludes nothing at all, so the subsumption reading reports it clean -- and it is the likelier
    promotion of the two, because a `.claude` allow-list is twenty consecutive negations that every
    consumer holds.

    THE NEGATION ARM IS THE COMPLETE ONE, and the re-ignore arm is the sharper proxy kept beside it.
    Two `.gitignore` rules can only DISAGREE about a path if one of them re-includes, so a base
    holding no negation is order-free whatever else it holds -- while a re-ignore promoted out of a
    consumer is caught by the subsumption reading with the line named, which is a better refusal than
    "some later negation might have existed". Both fire, and neither is the other's fallback.

    WHICH ARTEFACTS THIS BINDS ON IS DATA -- :data:`ORDER_SENSITIVE_ARTEFACTS`, artefact to its
    floating-rule floor -- so a base outside that map is not silently skipped but declared
    order-insensitive, and adding a second one is a decision somebody typed with its own floor.
    """
    floor = ORDER_SENSITIVE_ARTEFACTS.get(base.artefact)
    if floor is None:
        return
    negated = negated_base_lines(base)
    if negated:
        msg = (
            f'the {base.artefact} base holds {list(negated)}, and a negation re-includes paths some '
            f'EARLIER rule excluded. This table is stored sorted and `!` sorts below every character '
            f'a rule starts with, so the line renders ABOVE the rule it re-includes from and does '
            f'nothing; the anchor points one way, so no delta can push it down either. Leave it in '
            f"the repo's Delta, below the blanket rule it opens a hole in."
        )
        raise PositionalBase(msg)
    positional = positional_base_lines(base, floating_floor=floor)
    if positional:
        msg = (
            f'the {base.artefact} base holds {list(positional)}, and each excludes a strict subset of '
            f'what a floating base rule already excludes. A rule that adds no path can only be adding '
            f'ORDER -- a re-ignore written below a negation to win a last-match-wins argument -- and '
            f'this base renders before every delta line, so the order it needs is unreachable here. '
            f"Leave it in the repo's Delta, BELOW the negation it closes."
        )
        raise PositionalBase(msg)


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
