"""THE DENSITY METER a placement roster judges a row with -- the reading, never the verdict.

WHAT IT MEASURES. Given a Python module's source it answers two numbers: ``own``, the lines that are
neither prose nor a delegation to a declared home, and ``hits``, the ones naming something that exists
only in this checkout's world. A file mostly ours by that reading belongs to this repo; a file that is
mostly wiring is a BINDER and belongs here too, on size; anything else is a mechanism wearing a repo's
name.

WHY IT IS FAMILY. Measured across the four rosters listed in
:mod:`lab_commons.dev.famtests._placement_readings` -- two labs and motronics' two -- this half is the
one that is IDENTICAL. Same AST-and-token prose blanker, same delegation subtraction, same count, same
percentage. The labs carry ONE delegation home where motronics carries a SET, and ONE hit signal where
motronics carries TWO; both differences are in the signatures here rather than in a branch.

``Density.justified`` IS DELETED ON PURPOSE, AND A CONSUMER ALREADY PAID FOR IT. All four rosters wrote
``justified`` as a property closing over their own module-level bars -- and motronics' tests roster had
to write the function out by hand, because the inherited property closed over the ``scripts/`` roster's
ceiling of 40 while the tests module DECLARED 50, so tests-tree rows were judged by a bar bounded on a
different tree. Two rows read between the two ceilings and caught it. Here the bars are ARGUMENTS to
:func:`justified`, and there is nothing for a meter to close over.

THE VACUITY THIS MODULE REFUSES IS ITS OWN: a signal set that can never fire, and a signal that always
does. An empty alternation matches at position zero on every line, so a meter built from an empty
vocabulary reads every file in the tree as entirely one repo's -- and a meter with no signals at all
reports 0.00% everywhere, which is the reading a genuine misclassification gives. Both raise
:exc:`NoSignals`. An empty ``delegation_homes`` is NOT in that class and is legal: a repo that has
adopted nothing from the family yet has a true answer to that question.

WHAT IT CANNOT SEE, stated so a reader does not supply "everything". It counts LINES, not meaning; a
repo fact spelled as a bare number or a bare string path is invisible to a noun scan, which is why
:func:`measure_density` takes a SEQUENCE of signals rather than one; and a non-Python file has no AST,
so it cannot be measured here at all. The consumer NAMES the rows it cannot measure, and that named set
is the ceiling on the exemption.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence

__all__ = [
    'Density',
    'NoSignals',
    'assert_readings_convict',
    'assert_the_meter_still_convicts',
    'code_and_delegation',
    'code_only',
    'justified',
    'measure_density',
    'meter_readings',
    'noun_pattern',
    'nouns_in',
]


class NoSignals(AssertionError):
    """A meter was handed nothing that can ever fire, so every density it reports is foregone."""


@dataclass(frozen=True)
class Density:
    """What the density arm measured about one file. A READING, never a verdict.

    There is deliberately no ``justified`` property. The bars it would close over are the repo's, and
    a meter carrying them decides a row by whichever module it was imported from -- see the module
    docstring for the consumer that paid for exactly that. :func:`justified` takes them as arguments.
    """

    #: Code lines that are neither prose nor a delegation to a declared home.
    own: int
    #: Of those, the ones a signal fired on.
    hits: int

    @property
    def percent(self) -> float:
        """Hits as a percentage of own lines. A file with no own lines reads 0.0 rather than raising."""
        return 100.0 * self.hits / self.own if self.own else 0.0


def noun_pattern(nouns: Sequence[str], *, match_identifier_parts: bool) -> re.Pattern[str]:
    """The alternation a repo's nouns are matched by, with its boundary policy DECLARED.

    Args:
        nouns: this repo's vocabulary. NO DEFAULT and no fallback: an empty vocabulary compiles to an
            empty alternation, which matches at position zero on EVERY line, so a guessed default
            would read the whole tree as saturated with one repo's nouns.
        match_identifier_parts: whether a noun may match a PART of an identifier. NO DEFAULT, because
            the family does not agree and both answers are defended in writing. Both labs and one
            motronics roster match WHOLE identifiers (underscore is a letter), so ``xdist`` does not
            fire inside ``xdist_width``; motronics' scripts roster widened to identifier PARTS on
            2026-09-17 after measuring ``scripts/gate/width.py`` at 0.00% with ``xdist`` sitting
            inside ``xdist_width`` -- a noun is a part of an identifier at least as often as the
            whole. Under BOTH answers letters and digits are never separators, so ``delegate`` never
            fires on ``gate`` and ``meshgrid`` never fires on ``mesh``; plain substring matching is
            not on offer, and the family has already paid for it once.

    Returns:
        A case-insensitive compiled pattern whose group 1 is the noun that matched.

    Raises:
        NoSignals: *nouns* is empty.

    """
    if not nouns:
        msg = (
            'a noun vocabulary of zero words compiles to an empty alternation, which matches at '
            'position zero on every line: the meter would read every file as entirely this repo`s. '
            'Declare the repo`s nouns, or do not run the density arm at all.'
        )
        raise NoSignals(msg)
    separator = '' if match_identifier_parts else '_'
    guard = f'[A-Za-z0-9{separator}]'
    return re.compile(f'(?<!{guard})(' + '|'.join(nouns) + f')(?!{guard})', re.IGNORECASE)


def code_only(source: str) -> list[str]:
    """*source*'s non-blank lines with docstrings and comments BLANKED rather than removed.

    Blanked in place, so a line holding code AND a trailing comment keeps its code and loses only the
    comment, and no column moves. This is the reading behind every code-only question the four rosters
    ask -- the ``MOVES`` converse and the density measurement both -- and it is what separates a file
    that IS about this repo from one that merely TALKS about it.
    """
    return code_and_delegation(source, delegation_homes=())[0]


def code_and_delegation(source: str, *, delegation_homes: Collection[str]) -> tuple[list[str], set[str]]:
    """:func:`code_only`'s lines, plus the names bound from a DECLARED delegation home.

    WHY DELEGATION IS A DECLARED SET AND NOT AN OPEN QUESTION. "Does this line hand work outside the
    file's own responsibility?" cannot be asked without a declaration: ``import re`` hands work outside
    the file too, and counting it would read every module as a binder.

    Args:
        source: Python source.
        delegation_homes: top-level names whose imports are delegation rather than this file's own
            mechanism -- the family package, plus any local mechanism siblings the repo declares. NO
            DEFAULT, and the defect it closes was measured 2026-09-17: motronics'
            ``scripts/gate/_anchors.py`` re-pointed at ``lab_commons.dev.shards`` and its ``own`` count
            went 39 -> 40 across that one commit with no new mechanism in it, because the family import
            read as the file's own. Read as delegation the same two revisions measure 39 -> 31. The
            meter scored a completed migration as new local code, and did so to every such re-point --
            the one direction this measurement must not be blind in. An EMPTY collection is legal and
            means what it says: this repo delegates to nothing yet.

    Returns:
        ``(lines, bound)`` -- the blanked non-blank lines, and the names delegation brought in.

    """
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, 'body', None)
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) or not body:
            continue
        head = body[0]
        if isinstance(head, ast.Expr) and isinstance(head.value, ast.Constant) and isinstance(head.value.value, str):
            docstrings.add((head.lineno, head.col_offset))

    lines = source.splitlines()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        prose = token.type == tokenize.COMMENT or (token.type == tokenize.STRING and token.start in docstrings)
        if not prose:
            continue
        (first, start_col), (last, end_col) = token.start, token.end
        for row in range(first, last + 1):
            text = lines[row - 1]
            begin = start_col if row == first else 0
            end = end_col if row == last else len(text)
            lines[row - 1] = text[:begin] + ' ' * (end - begin) + text[end:]

    return [line for line in lines if line.strip()], _bound_from(tree, frozenset(delegation_homes))


def _bound_from(tree: ast.Module, homes: frozenset[str]) -> set[str]:
    """Every name an import from a declared home binds, plus the home's own spelling.

    The home itself is added because a dotted call site spells it (``lab_commons.dev.shards.take``)
    while the alias alone would miss the line.
    """
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            hit = homes.intersection((node.module or '').split('.'))
            if hit:
                bound.update(alias.asname or alias.name for alias in node.names)
                bound.update(hit)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split('.')
                hit = homes.intersection(parts)
                if hit:
                    bound.add(alias.asname or parts[-1])
                    bound.update(hit)
    return bound


def nouns_in(text: str, *, noun: re.Pattern[str]) -> set[str]:
    """Every noun *noun* finds in *text*, lower-cased -- the HIT reading, evidence and not a verdict.

    Handed a WHOLE file it is the generous reading a ``STAYS`` claim is checked against, because a
    file whose docstring says which fact it is about has said something true. Handed the joined lines
    of :func:`code_only` it is the strict reading a ``MOVES`` claim must survive.

    THE ASYMMETRY IS DELIBERATE AND MEASURED ON BOTH SIDES. Reading prose for the converse refused
    three CORRECT ``MOVES`` rows on wdg-lab's first run, and in motronics' tests tree it would make
    ``MOVES`` unsayable for the whole tree, because every guard there explains the defect it pins and
    so names the project in prose while its mechanism names nothing. Reading code for the HIT test
    would refuse files whose claim really is carried by a sentence. Which reading a property takes is
    the property's business; this function takes the text it is given.
    """
    return {match.group(1).lower() for match in noun.finditer(text)}


def measure_density(source: str, *, signals: Sequence[re.Pattern[str]], delegation_homes: Collection[str]) -> Density:
    """The whole density measurement, on TEXT, so a control can plant a shape instead of a file.

    Args:
        source: Python source. A non-Python row has no AST and cannot be measured here at all; the
            consumer NAMES those rows, and that named set is the ceiling on the exemption.
        signals: the patterns whose match makes a line THIS repo's. A line carrying ANY of them counts
            once. Both labs pass one, the noun alternation; motronics passes two, the second being an
            alternation over the BASENAMES its own manifest declares ours -- a path is the shape a noun
            cannot be, and four measured witnesses drove it. NO DEFAULT.
        delegation_homes: see :func:`code_and_delegation`.

    Returns:
        The reading. Judging it is :func:`justified`'s job, with the repo's bars.

    Raises:
        NoSignals: *signals* is empty, or holds a pattern matching the empty string. Either makes every
            reading foregone -- zero in the first case, one hundred in the second -- and neither is
            refused anywhere else.

    """
    if not signals:
        msg = (
            'a density meter with no signals reports 0.00% for every file in the tree, which is the '
            'reading a genuine misclassification gives. A scan that can never fire is vacuous rather '
            'than green.'
        )
        raise NoSignals(msg)
    for pattern in signals:
        if pattern.search(''):
            msg = (
                f'the signal {pattern.pattern!r} matches the empty string, so it fires on every line '
                f'and every file reads as entirely this repo`s. An empty alternation is the usual '
                f'cause; build it with `noun_pattern`, which refuses the empty vocabulary.'
            )
            raise NoSignals(msg)

    code, delegated = code_and_delegation(source, delegation_homes=delegation_homes)
    if delegated:
        delegation = re.compile(
            r'(?<![A-Za-z0-9_])(' + '|'.join(re.escape(name) for name in sorted(delegated)) + r')(?![A-Za-z0-9_])'
        )
        own = [line for line in code if not delegation.search(line)]
    else:
        # Nothing was bound, so there is nothing to subtract. Building the alternation anyway gives an
        # empty group, which matches at position zero on every line and would read EVERY file in the
        # tree as a binder -- the same vacuity `signals` is checked for above.
        own = list(code)
    return Density(own=len(own), hits=sum(1 for line in own if any(p.search(line) for p in signals)))


def justified(density: Density, *, ceiling: int, minimum_pct: float) -> bool:
    """Whether a row clears its repo's bars -- justified by being OURS or a BINDER, nothing between.

    Args:
        density: the reading.
        ceiling: the largest ``own`` line count a file may have and still be admitted as a BINDER on
            size alone. NO DEFAULT -- three rosters measured 50 and one measured 40, over intervals
            that exclude each other's value.
        minimum_pct: the hit percentage a file above the ceiling must reach. NO DEFAULT for the same
            reason, even though all four rosters agree on 3.0: four independent measurements of a
            number are evidence FOR the number, not a licence to stop measuring it.

    Returns:
        ``True`` when the row is admitted.

    """
    return density.own <= ceiling or density.percent >= minimum_pct


def meter_readings(*, noun_witness: str, delegation_home: str) -> dict[str, Density]:
    """PLANT the three shapes the meter exists to tell apart, and MEASURE them. No judgement.

    Split from :func:`assert_the_meter_still_convicts` so the judging half can be driven over readings
    a test SUPPLIES. A control that can only ever be handed the shipped meter's own output cannot be
    shown to fail, and an assertion nobody has seen fire is a declaration rather than a guard.

    Args:
        noun_witness: one word from this repo's own vocabulary. NO DEFAULT -- the kit cannot plant a
            line matching a repo's nouns without knowing one, and inventing a witness here would drive
            the meter over the kit's idea of a noun instead of the repo's.
        delegation_home: one name from this repo's own ``delegation_homes``. NO DEFAULT, same reason.

    Returns:
        ``{'prose': ..., 'dense': ..., 'binder': ...}`` -- a file that only TALKS about the witness, one
        whose CODE names it, and one that does nothing but delegate.

    """
    signals = (noun_pattern((re.escape(noun_witness),), match_identifier_parts=False),)
    homes = (delegation_home,)
    plants = {
        'prose': f'"""A module all about {noun_witness}."""\n\nvalue = 1\nother = 2\n',
        'dense': f'value = {noun_witness}\nother = 2\n',
        'binder': f'from {delegation_home} import helper\n\nhelper(1)\nhelper(2)\n',
    }
    return {name: measure_density(source, signals=signals, delegation_homes=homes) for name, source in plants.items()}


def assert_readings_convict(readings: Mapping[str, Density], *, noun_witness: str, delegation_home: str) -> None:
    """JUDGE :func:`meter_readings`' output -- the half a test can drive with a wrong answer.

    Pure over its argument, so the control below drives THIS function rather than re-implementing it
    and agreeing with itself.

    Raises:
        AssertionError: the readings say the meter stopped separating prose from code, delegation from
            own mechanism, or a hit from a miss.

    """
    two_code_lines = 2
    prose, dense, binder = readings['prose'], readings['dense'], readings['binder']

    if prose.own != two_code_lines or dense.own != two_code_lines:
        msg = (
            f'the code reader no longer counts two code lines as two: prose={prose!r}, dense={dense!r}. '
            f'Every density in the tree is measured against that count.'
        )
        raise AssertionError(msg)
    if prose.hits:
        msg = (
            f'PROSE BOUGHT DENSITY: {prose!r}. A file that merely TALKS about {noun_witness!r} now '
            f'measures as being about it, which is the generosity the HIT reading owns and the density '
            f'reading must refuse.'
        )
        raise AssertionError(msg)
    if dense.hits != 1:
        msg = (
            f'THE METER STOPPED CONVICTING: {dense!r}. A code line naming {noun_witness!r} is no longer '
            f'a hit, so every file in the tree reads as generic and every MOVES row would pass.'
        )
        raise AssertionError(msg)
    if binder.own:
        msg = (
            f'DELEGATION IS BEING COUNTED AS OWN MECHANISM: {binder!r}. Lines handing work to '
            f'{delegation_home!r} are this file`s wiring, not its mechanism, and counting them scores a '
            f'completed migration as new local code -- measured on a real re-point as 39 -> 40 where '
            f'the honest reading is 39 -> 31.'
        )
        raise AssertionError(msg)


def assert_the_meter_still_convicts(*, noun_witness: str, delegation_home: str) -> None:
    """DRIVE the installed meter over a planted shape, all three ways, in the CONSUMER'S own words.

    WHAT THIS IS FOR. A meter reading everything as this repo's and a meter reading nothing as this
    repo's both pass a one-sided test, and the second is indistinguishable from a tree of honest
    binders. The family has already paid for the unseen half of exactly this shape: three repos ran an
    agent-hook engine that had drifted from the shipped one, and they agreed again only because
    somebody re-installed it.

    Args:
        noun_witness: see :func:`meter_readings`. NO DEFAULT.
        delegation_home: see :func:`meter_readings`. NO DEFAULT.

    Raises:
        AssertionError: the meter no longer separates prose from code, delegation from own mechanism,
            or a hit from a miss.

    """
    assert_readings_convict(
        meter_readings(noun_witness=noun_witness, delegation_home=delegation_home),
        noun_witness=noun_witness,
        delegation_home=delegation_home,
    )
