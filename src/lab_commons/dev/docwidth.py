"""The family's ONE per-line WIDTH ceiling for every document injected into an agent's context.

THE DEFECT, MEASURED 2026-09-16, by the user, across four repos' injected docs (``AGENTS.md``,
``CLAUDE.md``, ``.claude/rules/**``, memory excluded)::

    repo          docs   lines>100  lines>120   max column
    motronics       26      79         68          786
    wdg-lab         25      30         19          223
    lab-commons      2       0          0           99
    optimi-lab       2       0          0           99

An existing LINE-COUNT ratchet (motronics' own) pins how many lines a page may have and sums the
pins into one ceiling -- and a line is one unit of that pin NO MATTER HOW LONG IT IS. One page there
is 32 lines with a maximum column of 694; a rewrite could double that page's width while LOWERING
its line count, and a line-count ratchet would read the change as an improvement. **The pin counts
the wrong thing** -- a declaration measuring something other than what it claims is this family's
own dominant defect, found sitting inside the mechanism built to catch exactly that shape elsewhere.
This module is the missing dimension: it caps the LENGTH of each line, alongside the count.

THE THRESHOLD IS 120, and the reason is that it is not a new number. Every repo in this family
already sets ``line-length = 120`` in its ``[tool.ruff]`` config for CODE; using the same number for
PROSE gives the family one width constant instead of two. It is not chosen to just miss today's
worst case either -- lab-commons and optimi-lab already sit at a measured maximum of 99 columns,
comfortably inside 120, so the ceiling refuses real over-width prose rather than rubber-stamping
whatever a repo currently contains.

WHAT COUNTS AS AN "INJECTED DOCUMENT" IS DATA, NOT A HARDCODED GUESS ABOUT FOUR REPOS. The measured
corpus above is one reasonable definition -- ``AGENTS.md`` and ``CLAUDE.md`` by basename anywhere in
the tree, plus everything under ``.claude/rules/`` -- and it is exactly what :data:`INJECTED_BASENAMES`
and :data:`INJECTED_PREFIXES` encode. But whether a given repo actually injects all of those, or
injects something else besides, is that repo's own business: :func:`is_injected_doc` takes the three
sets as parameters with these as defaults, so a consumer with a different corpus (a ``docs-src/dev/``
tree that is also always-loaded, say) overrides them rather than being guessed for. ``.claude/memory/``
is excluded by default for the same reason the CJK guard excludes it: a dated memory entry is not
prose an agent is handed on every turn.

THE RATCHET SHAPE IS THE SAME ONE THIS MODULE'S SIBLING, :mod:`lab_commons.dev.cjk`, ALREADY USES,
because it is the same problem: a population already over a fresh ceiling cannot be fixed in one
commit, so this module supplies the scan, the corpus definition and the floor, and each adopting
repo supplies its own declaration -- a named set of ``path:line`` sites still over width, which may
only shrink. A site found and undeclared reds; a declared site no longer over width is an ORPHANED
waiver and reds too, exactly like an unused CJK exemption.

BINARY AND UNDECODABLE FILES ARE SKIPPED, NAMED, for the same reason as the CJK scan: a file that
cannot be read as UTF-8 text is not evidence of a compliant one.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, NamedTuple

__all__ = [
    'INJECTED_BASENAMES',
    'INJECTED_EXEMPT_PREFIXES',
    'INJECTED_PREFIXES',
    'WIDTH_CEILING',
    'Overwidth',
    'VacuousWidthScan',
    'WidthScan',
    'assert_width_floor',
    'injected_docs',
    'is_injected_doc',
    'line_widths',
    'scan_widths',
    'width_ratchet',
    'width_remedy',
]

#: One width constant for the whole family: every repo already sets ``line-length = 120`` for code,
#: so prose gets the same number rather than a second one nobody chose on purpose.
WIDTH_CEILING: Final = 120

#: The default injected-document corpus, as three separate DATA sets rather than one glob, so a
#: consumer can widen or narrow exactly one of them without re-deriving the others. See the module
#: docstring for the 2026-09-16 measurement that produced this default.
INJECTED_BASENAMES: Final[frozenset[str]] = frozenset({'AGENTS.md', 'CLAUDE.md'})
INJECTED_PREFIXES: Final[tuple[str, ...]] = ('.claude/rules/',)
INJECTED_EXEMPT_PREFIXES: Final[tuple[str, ...]] = ('.claude/memory/',)


class VacuousWidthScan(RuntimeError):
    """A scan reached fewer files than its floor, so finding nothing proves nothing."""


class Overwidth(NamedTuple):
    """One line past the ceiling, at the place a reader will find it: ``(path, line, width)``."""

    path: str
    line: int
    width: int


@dataclass(frozen=True, slots=True)
class WidthScan:
    """What a width scan found, together with what it could not read.

    *overwidth* is every line past :data:`WIDTH_CEILING` (or a caller's own ceiling). *undecodable*
    names every file that could not be read as UTF-8 text, so "no over-width lines" and "the file
    could not be read" stay distinguishable facts.
    """

    overwidth: tuple[Overwidth, ...]
    files_read: int
    undecodable: tuple[str, ...]

    def __iter__(self) -> Iterator[Overwidth]:
        return iter(self.overwidth)


def _under(name: str, prefixes: Collection[str]) -> bool:
    """Whether *name* sits under one of *prefixes* ANYWHERE in the path, not only at the root.

    Checked both at the root (``name.startswith(prefix)``) and as a nested SEGMENT
    (``f'/{prefix}'`` in *name*), for the same measured reason as
    :func:`lab_commons.dev.cjk.exempted`: motronics-studio's ``.claude/rules/`` pages are SCOPED per
    module (``src/motronics/hamilton/.claude/rules/femm.md``, ``scripts/.claude/rules/scripts.md``,
    every ``src/motronics/*/.claude/rules/MEMORY.md``), and a root-only prefix would silently miss
    every one of them -- the width ceiling would then cover nothing that repo actually injects. The
    leading ``/`` is what keeps ``notrules/x`` from matching ``rules/``: the prefix must start a path
    SEGMENT.
    """
    return any(name.startswith(prefix) or f'/{prefix}' in name for prefix in prefixes)


def is_injected_doc(
    name: str,
    *,
    basenames: Collection[str] = INJECTED_BASENAMES,
    prefixes: Collection[str] = INJECTED_PREFIXES,
    exempt_prefixes: Collection[str] = INJECTED_EXEMPT_PREFIXES,
) -> bool:
    """Whether *name* (a repo-relative POSIX path) is a document this family injects into an agent.

    Exemption is checked FIRST, so ``.claude/rules/memory/x.md``-shaped paths cannot be reached by
    widening the prefix set without a corresponding, deliberate narrowing of the exemption. Both the
    exemption and the prefix are matched as a path SEGMENT anywhere in *name* (:func:`_under`), never
    only at the root -- see its docstring for the measured nested-page layout that requires this.
    """
    if _under(name, exempt_prefixes):
        return False
    if Path(name).name in basenames:
        return True
    return _under(name, prefixes)


def injected_docs(
    paths: Iterable[str],
    *,
    basenames: Collection[str] = INJECTED_BASENAMES,
    prefixes: Collection[str] = INJECTED_PREFIXES,
    exempt_prefixes: Collection[str] = INJECTED_EXEMPT_PREFIXES,
) -> tuple[str, ...]:
    """*paths* (repo-relative POSIX strings, e.g. from ``tracked_files``) narrowed to injected docs."""
    return tuple(
        sorted(
            path
            for path in paths
            if is_injected_doc(path, basenames=basenames, prefixes=prefixes, exempt_prefixes=exempt_prefixes)
        )
    )


def line_widths(text: str) -> tuple[tuple[int, int], ...]:
    """Every ``(line, width)`` in *text*, 1-based, one row per line whatever its width."""
    return tuple((number, len(line)) for number, line in enumerate(text.splitlines(), start=1))


def _named(path: Path, base: Path | None) -> str:
    """*path* as the record names it: as given, or relative to *base* when one was declared."""
    if base is None:
        return path.as_posix()
    resolved = path.resolve()
    if resolved != base and base not in resolved.parents:
        msg = f'{path} is not under {base}, so it cannot be named relative to it.'
        raise ValueError(msg)
    return resolved.relative_to(base).as_posix()


def scan_widths(paths: Iterable[Path | str], *, ceiling: int = WIDTH_CEILING, root: Path | None = None) -> WidthScan:
    """Every line in *paths* past *ceiling* columns. Never raises a verdict, only reports.

    *paths* is the caller's own list and is never walked, for the reason
    :func:`lab_commons.dev.cjk.scan_files` gives at the same seam: a control can drive this real
    function against a planted tree instead of a re-implementation that agrees with itself.

    Raises:
        ValueError: *root* was declared and a path is not under it.
        OSError: a file could not be opened.

    """
    overwidth: list[Overwidth] = []
    undecodable: list[str] = []
    base = Path(root).resolve() if root is not None else None
    read = 0
    for item in paths:
        path = Path(item)
        named = _named(path, base)
        try:
            text = path.read_bytes().decode('utf-8')
        except UnicodeDecodeError:
            undecodable.append(named)
            continue
        read += 1
        overwidth.extend(Overwidth(named, line, width) for line, width in line_widths(text) if width > ceiling)
    return WidthScan(overwidth=tuple(sorted(overwidth)), files_read=read, undecodable=tuple(sorted(undecodable)))


def assert_width_floor(reached: int, floor: int, what: str = 'injected-doc width') -> None:
    """Raise unless *reached* (a scan's ``files_read``) meets *floor* -- naming what was scanned."""
    if reached < floor:
        msg = (
            f'the {what} scan reached only {reached} file(s), below the {floor} floor. Finding no '
            f'over-width line is vacuous rather than clean: a clean tree and an unread one produce the '
            f'same empty result, and only one of them means the guard held. Fix the file list, do not '
            f'lower the floor.'
        )
        raise VacuousWidthScan(msg)


def width_remedy(overwidth: Overwidth, ceiling: int = WIDTH_CEILING) -> str:
    """One refusal line for *overwidth* -- the exact file:line, the measured width, and the remedy."""
    return (
        f'{overwidth.path}:{overwidth.line}: line is {overwidth.width} columns, above the {ceiling}-column '
        f'ceiling every repo in this family already sets for code. Wrap it to fit, or split the point it '
        f'is making across more than one line -- a page rewritten narrower may grow in LINE COUNT and '
        f'that is the trade this ceiling exists to allow.'
    )


def width_ratchet(overwidth: Sequence[Overwidth], declared: Collection[str]) -> tuple[str, ...]:
    """BOTH SIDES of the width ratchet, keyed the same way :func:`lab_commons.dev.cjk.ratchet` is.

    *declared* is the adopting repo's own named set of ``path:line`` sites it still carries an
    over-width line at. A site found here and not declared refuses, naming the remedy; a declared
    site no longer found refuses too, because an unused waiver reads as a decision nobody made.
    """
    by_site = {f'{o.path}:{o.line}': o for o in overwidth}
    found = frozenset(by_site)
    pinned = frozenset(declared)
    problems = [f'UNDECLARED overwidth line -- {width_remedy(by_site[site])}' for site in sorted(found - pinned)]
    problems.extend(
        f'ORPHANED overwidth declaration {site!r} -- the line is no longer over width; remove it from the '
        f'declared set in this same commit.'
        for site in sorted(pinned - found)
    )
    return tuple(problems)
