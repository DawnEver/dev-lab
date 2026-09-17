"""The always-loaded rule pages, ratcheted PER PAGE and capped in TOTAL -- both, because each is blind.

WHAT ``.claude/rules/**`` IS. Prose re-read on every turn, so every line is a cost paid on every
request. Two constraints keep it honest and they are not the same constraint:

* A PER-PAGE RATCHET is a NAMED SET, and it is the reading a total cannot give. A total says only
  that the sum moved; it cannot say WHICH page grew, so a rule migrating from one page to another --
  which changes nothing about the cost and hides the movement -- is absorbed in silence, and a page
  growing inside whatever slack the sum happens to have is absorbed too. The family has paid for this
  reading twice already: a count pin read ``mec transient: 2``, a merge silently dropped a
  restriction, the table delivered 1, and the pin was LOWERED to 1 with a note explaining why. The
  pin was right and the table was wrong, and an integer could not say so.
* A TOTAL CEILING is what the named set cannot give back. Once every page carries its own pin, each
  pin is its own local decision and NOTHING caps their sum: five new pages at 40 lines each are five
  separately reasonable arrivals and one always-loaded document nobody chose the size of. The ceiling
  is the escape hatch's ceiling -- the same shape ``DEBT``/``DEBT_CEILING`` already uses for oversized
  modules, where the names are the population and the sum is the budget.

So this module supplies BOTH and neither replaces the other. Adopting only the ratchet is how a
budget grows one justified page at a time; adopting only the ceiling is how a page grows inside
someone else's shrink.

THE RATCHET IS TWO-SIDED IN ALL FOUR DIRECTIONS, because a ratchet with one side is how a capability
vanishes quietly: a page that GREW reds, a page that SHRANK reds until its pin follows in the same
edit, a page that ARRIVED unpinned reds, and a pin naming a page that is GONE reds. The last two are
the ones left out, and they are the waiver-nothing-uses half: budget freed by a deletion is paid back
in the edit that freed it rather than banked as slack for the next arrival.

WIDTH IS NOT MEASURED HERE, AND THAT IS A DECISION RATHER THAN AN OMISSION. A line-count pin is one
unit per line no matter how long the line is, so a rewrite can double a page's width while LOWERING
its count -- but :mod:`lab_commons.dev.docwidth` already owns exactly that dimension over exactly this
corpus (``.claude/rules/`` is one of its :data:`~lab_commons.dev.docwidth.INJECTED_PREFIXES`), with
its own ceiling, its own named set of over-width sites and its own floor. A second width scan here
would be two statements of one rule, which is the drift a shared body exists to remove. A repo
adopting this body wants the docwidth guard as well; it does not want it twice.

EVERY REPO-SHAPED FACT ARRIVES AS A KEYWORD WITH NO DEFAULT -- the pages, the root they are named
relative to, the pins, the ceiling, the floor. optimi-lab is the only repo with a measurement today
and wdg-lab has none, so a default would hand three repos one repo's answer and then report it as
measured. Even WHICH FILES ARE PAGES is the consumer's: this repo takes them from git (a file in one
working copy is not a file the fleet has), optimi-lab walks the directory, and neither is wrong for
the other.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

__all__ = [
    'VacuousPageScan',
    'assert_rules_ratchet',
    'budget_overrun',
    'page_lines',
    'ratchet_breaks',
]


class VacuousPageScan(AssertionError):
    """A scan reached fewer pages than its floor, so finding nothing proves nothing."""


def page_lines(paths: Iterable[Path], *, root: Path) -> dict[str, int]:
    """THE READING: ``{repo-relative POSIX path: line count}`` for every page in *paths*.

    Args:
        paths: the pages to read -- the consumer's corpus, from git or from a walk.
        root: what the keys are named relative to. A path outside it keeps its own spelling, so a
            page planted in a ``tmp_path`` is still readable in a refusal message.

    Returns:
        One entry per page, sorted by key.

    """
    out = {
        (path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()): len(
            path.read_text(encoding='utf-8').splitlines()
        )
        for path in paths
    }
    return dict(sorted(out.items()))


def ratchet_breaks(measured: Mapping[str, int], *, pinned: Mapping[str, int]) -> dict[str, str]:
    """THE COMPARISON, all four movements at once -- pure over its arguments, so a control can drive it.

    Args:
        measured: what :func:`page_lines` read.
        pinned: the consumer's declaration, page to the line count it may not exceed.

    Returns:
        ``{page: what moved}``, empty when the set and every count agree.

    """
    breaks: dict[str, str] = {}
    for page, lines in sorted(measured.items()):
        if page not in pinned:
            breaks[page] = f'{lines} lines and unpinned -- an always-loaded page nobody budgeted'
        elif lines > pinned[page]:
            breaks[page] = f'grew {pinned[page]} -> {lines}; spend an existing line rather than raising the pin'
        elif lines < pinned[page]:
            breaks[page] = f'shrank {pinned[page]} -> {lines}; lower the pin in this same edit'
    for page in sorted(set(pinned) - set(measured)):
        breaks[page] = 'pinned and gone -- delete the pin with the page, or the waiver outlives it'
    return breaks


def budget_overrun(measured: Mapping[str, int], *, ceiling: int) -> str | None:
    """THE CEILING over the sum of *measured*, or ``None`` when it fits.

    The half the per-page ratchet cannot see: every pin is a local decision, and a set of individually
    reasonable pins still sums to a document nobody sized on purpose.

    Args:
        measured: what :func:`page_lines` read.
        ceiling: the total always-loaded budget. It may only go DOWN.

    Returns:
        The refusal text, or ``None`` when the total fits.

    """
    total = sum(measured.values())
    if total <= ceiling:
        return None
    return (
        f'{total} lines of always-loaded rules across {len(measured)} page(s), above the {ceiling} '
        f'ceiling. Mechanism belongs in the code that enforces it and reasoning in .claude/memory/; a '
        f'new page is paid for out of this budget rather than added beside it.'
    )


def assert_rules_ratchet(
    *,
    pages: Iterable[Path],
    root: Path,
    pinned: Mapping[str, int],
    ceiling: int,
    floor: int,
) -> dict[str, int]:
    """THE CHECK a consumer calls: the floor, then the named set, then the budget -- in that order.

    The floor comes first on purpose. A ratchet over a directory the walk did not enter reports
    exactly what a compressed one reports, so an unread corpus is refused rather than passed, and the
    two later verdicts are only given once the reading is known to be a reading.

    Args:
        pages: the consumer's always-loaded pages.
        root: what the pins are keyed by -- see :func:`page_lines`.
        pinned: page to its measured line count.
        ceiling: the total budget across every page.
        floor: the smallest scan that may report at all.

    Returns:
        The measurement, so a caller can print it or assert further on it.

    Raises:
        VacuousPageScan: fewer than *floor* pages were reached.
        AssertionError: the named set moved, or the total is over the ceiling.

    """
    measured = page_lines(pages, root=root)
    if len(measured) < floor:
        msg = (
            f'the rules-page scan reached {len(measured)} page(s), below the {floor} floor. Finding '
            f'NOTHING is vacuous rather than green: an empty page set and a compressed one are the '
            f'same clean result. Fix the corpus -- do not lower the floor.'
        )
        raise VacuousPageScan(msg)
    breaks = ratchet_breaks(measured, pinned=pinned)
    if breaks:
        moved = '; '.join(f'{page}: {why}' for page, why in breaks.items())
        msg = (
            f'the always-loaded rule set moved: {moved}. Every line here is read on every turn, so '
            f'the way past a pin is to spend an existing line, never to raise the number.'
        )
        raise AssertionError(msg)
    overrun = budget_overrun(measured, ceiling=ceiling)
    if overrun is not None:
        raise AssertionError(overrun)
    return measured
