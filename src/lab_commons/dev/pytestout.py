r"""READING ONE TEST RUNNER'S STDOUT, and nothing about what the reading MEANS.

WHY THIS IS NOT :mod:`lab_commons.dev.reports`. That module's docstring says it holds "what each
verify step REPORTED", and its one public entry for this subject,
:func:`~lab_commons.dev.reports.read_pytest`, answers a
:class:`~lab_commons.dev.reports.StepReport` whose ``truncated`` set is already a VERDICT-facing
judgement: a skip ceiling, a shortfall, an exit-code table. A caller that wants a NUMBER -- how many
items were collected, what the last summary line said -- had to import an underscore, and importing
an underscore is not an adoption. So ``reports`` keeps the JUDGEMENT and this module publishes the
READINGS it judges.

MEASURED 2026-09-19 BEFORE IT WAS BUILT, because a kit module with one consumer is a fork wearing a
kit's clothes. ALL FOUR REPOS OF THE FAMILY READ A TEST RUNNER'S TRANSCRIPT, and the first reading of
that census was wrong in the safe direction: ``wdg-lab`` and ``optimi-lab`` hold no parser of their
own, which reads as "they do not do this" until their Makefiles are opened -- both run ``python -m
lab_commons.dev.verify``, so they have been reading pytest's stdout THROUGH this package all along
and simply never forked it. So the population is four consumers, of which TWO HELD A COPY: this
package in ``verify._CSI`` plus ``reports._COUNT``/``_COLLECTED``/``_summary_counts``, and
motronics-studio in ``scripts/gate/_transcript.py``. The two copies had SPLIT ON EVERY READING, each
side stronger somewhere, and the two repos with no copy silently inherited whichever half this
package happened to hold:

* THE ESCAPE GRAMMAR. ``verify._CSI`` spells ECMA-48's full CSI; the consumer's ``_ANSI`` was
  ``\x1b\[[0-9;]*m``, which leaves every cursor-motion and erase-line sequence in the text while
  claiming to have cleaned it. THIS FILE TAKES THE FULL GRAMMAR, so the consumer's adoption is an
  upgrade rather than a relocation.
* THE SUMMARY LINE. ``reports`` took the last line carrying any ``<count> <word>`` pair, ANCHORED
  ON NOTHING -- so ``!!! Interrupted: 3 errors during collection !!!`` reads as a summary line
  saying three errors. The consumer's pattern is anchored on the summary RULE (``^=*``, or bare
  under ``-q``). THIS FILE TAKES THE ANCHOR.
* THE TRUNCATION VOCABULARY. ``reports`` knew ``INTERNALERROR`` and pytest's interrupt banner; the
  consumer had seven more, each one a real incident, and a COLUMN rule separating a marker the RUN
  reported from one a TEST merely printed. THIS FILE TAKES BOTH.

THE FLOOR IS THE RETURN TYPE, and it is the whole reason this is a module rather than four regexes.
Every reader answers ``None`` for "the line was never printed" and never ``0``. A ``0`` collected,
a ``0`` failed or an empty count mapping is a GREEN OVER AN ABSENCE, and the incident that named it
is on record in both repos: a run whose ``conftest.py`` could not import collected nothing, printed
no summary, and was read by three separate readers as a clean pass on an empty selection.

NO VERDICT LIVES HERE. Nothing in this file knows what a tier, a wall, a stamp or an outcome is, and
the ``[census]`` grammar one consumer's own conftest emits stays with the conftest that writes it --
a reader belongs beside its writer, and pytest is the writer for everything on this page.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = [
    'TRUNCATION_MARKERS',
    'collected_count',
    'markers_in',
    'strip_ansi',
    'summary_body',
    'summary_counts',
]

#: ONE CSI escape, in ECMA-48's own grammar: ``ESC [``, then any number of PARAMETER bytes
#: (``0x30``-``0x3f``), then any number of INTERMEDIATE bytes (``0x20``-``0x2f``), then exactly one
#: FINAL byte (``0x40``-``0x7e``). SPELT OUT rather than written as "ESC and then whatever": a
#: pattern that eats anything after an ``ESC`` eats real content the first time a test prints one,
#: and the usual ``[^m]*m`` shorthand leaves every cursor-motion and erase-line sequence in the text
#: while claiming to have cleaned it. A LONE ``ESC``, and an ``ESC`` followed by anything that is
#: not this grammar, match nothing here and survive byte for byte.
_CSI: Final = re.compile(r'\x1b\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]')

#: The outcome words pytest's summary line is built from, as ONE list used by BOTH patterns below.
#: They were two lists in the consumer this came from, and the cost was measured 2026-08-29: the
#: line-shaped pattern knew ``passed|failed|error`` while the count-shaped one knew six more, so a
#: file whose every cell is a strict xfail ran clean, printed ``20 xfailed in 80.40s``, and was read
#: as having printed no summary at all -- which is the truncation signature. An all-skipped or
#: all-xfailed selection is ordinary, not exotic, and the instrument must not call one truncated.
_KINDS: Final = 'passed|failed|errors|error|skipped|xfailed|xpassed|deselected'

#: The summary line, decorated (``===== 3 passed in 1s =====``) or bare (``-q``), ANCHORED ON THE
#: RULE. The anchor is the reading, not decoration: without it the last line carrying any
#: ``<count> <word>`` pair wins, and ``!!! Interrupted: 3 errors during collection !!!`` is such a
#: line -- so a run that was CUT OFF answers a summary saying three errors, which is a number where
#: the truth is an absence.
_SUMMARY: Final = re.compile(rf'^=*\s*(?P<body>\d+ (?:{_KINDS})[^=\n]*?)\s*=*$', re.MULTILINE)

#: The ``<count> <word>`` pairs INSIDE one summary body. ``errors`` precedes ``error`` in
#: :data:`_KINDS` so the longer word wins the alternation; both normalise to ``error`` below.
_COUNT: Final = re.compile(rf'(?P<n>\d+) (?P<kind>{_KINDS})')

#: ``collected 307 items``, at the start of its line. xdist never prints it, which is why the reader
#: below answers ``None`` rather than ``0``.
_COLLECTED: Final = re.compile(r'^collected (?P<n>\d+) items?', re.MULTILINE)

#: Substrings that mean the run did not complete, whatever its exit code said. Each was a real
#: incident in one of the two repos that read a transcript: a worker killed at a timeout mark takes
#: its tests with it and xdist reports ``node down``; an ``INTERNALERROR`` aborts collection; a
#: Windows process-start failure (``0xC0000142``) means the box refused to fork a worker at all; and
#: a conftest that cannot import makes the suite exit having collected nothing, so the reader cannot
#: tell "the summary was never printed" from "there was nothing to summarise".
TRUNCATION_MARKERS: Final[tuple[str, ...]] = (
    'node down',
    'INTERNALERROR',
    'Not properly terminated',
    '0xC0000142',
    'MemoryError',
    'Killed',
    'ImportError while loading conftest',
    '+ Timeout +',
)


def strip_ansi(text: str) -> str:
    """``text`` with the terminal escapes removed, ONCE, before any pattern looks at it.

    A NAMED READER rather than an exported pattern, because the caller's job is "give me plain
    text" and never "hold a copy of the escape grammar". Every pattern on this page anchors on
    ``^=*`` or on a literal pytest word, and pytest puts its escape sequence BEFORE the leading
    ``=`` whenever it believes it has a terminal -- so a COMPLETE run reads as no summary.

    A LONE CARRIAGE RETURN IS LEFT ALONE: universal-newline translation already splits a progress
    bar into lines, which is ugly in a log and never fatal to a parse, and :data:`_CSI` cannot
    match it.
    """
    return _CSI.sub('', text)


def summary_body(text: str) -> str | None:
    """The body of the OUTER run's summary line, or ``None`` when no summary was printed at all.

    THE LAST MATCH, NOT THE FIRST. A suite that drives NESTED pytest runs from inside its own tests
    -- ``pytest_plugins = ['pytester']`` is enough -- replays each inner run's captured output in
    the failure section, ABOVE the outer run's summary, because the session doing the printing has
    not ended yet. Reading the first match lets a two-test toy fixture answer "how much did this run
    do": the accounted total comes out at the inner run's size while the collected count stays at
    the outer's, and the run reports INCOMPLETE having finished whole.

    ``None`` means "no summary was printed", which is not "zero".
    """
    found = list(_SUMMARY.finditer(text))
    return found[-1].group('body') if found else None


def summary_counts(text: str) -> dict[str, int] | None:
    """``{outcome word: count}`` from the summary line, or ``None`` when there was no summary.

    Built on :func:`summary_body` rather than on a second scan of the text, so the "which line is
    the summary" rule is stated ONCE. Two parsers for one line is how a verdict stamp and the tool
    that repaired it drifted apart in the consumer this came from, and a count that disagreed with
    the arithmetic beside it would be worse than no number.

    ``errors`` and ``error`` both answer under the key ``error``: a module that dies at IMPORT
    contributes an error and never a ``failed``, and a reader that knew only one spelling reported
    zero failures beside pytest's own ``5 passed, 1 error``.
    """
    body = summary_body(text)
    if body is None:
        return None
    counts: dict[str, int] = {}
    for found in _COUNT.finditer(body):
        word = found.group('kind')
        counts['error' if word.startswith('error') else word] = int(found.group('n'))
    return counts


def collected_count(text: str) -> int | None:
    """``collected N items`` -- the FIRST match -- or ``None`` when the line was never printed.

    THE FIRST, DELIBERATELY, and that is the same rule :func:`summary_body` states rather than its
    opposite: the outer session collects before any test can start a nested one, so its collection
    line comes first for exactly the reason its summary comes last. The outer session BRACKETS every
    inner one and both readers key off an end of that bracket.

    ``None`` is the floor. xdist never prints this line at all, and a ``0`` would read as a session
    that collected nothing -- a green over an absence.
    """
    found = _COLLECTED.search(text)
    return int(found.group('n')) if found else None


def _marker_is_the_runs_own(marker: str, text: str) -> bool:
    """Whether *marker* was reported BY the run rather than PRINTED BY one of its tests.

    THE COLUMN IS THE DISCRIMINATOR. pytest and xdist report an incomplete run in their own lines,
    unindented (``[gw3] node down: Not properly terminated``, ``INTERNALERROR> ...``). A marker a
    TEST put on screen arrives indented -- a source echo, a repr of a fixture -- or behind pytest's
    ``E `` assertion prefix. Scanning the whole text as one string cannot tell the instrument's
    voice from its subject's, and the first file to prove that was the acceptance test that quotes
    every marker by name: collecting it made every run report itself truncated.
    """
    for line in text.splitlines():
        if line[:1].isspace() or line.startswith('E '):
            continue
        if marker in line:
            return True
    return False


def markers_in(text: str) -> tuple[str, ...]:
    """The truncation markers this RUN reported, in :data:`TRUNCATION_MARKERS` order.

    The caller gets NAMES -- the thing a reader reports -- and never a pattern to re-apply. An empty
    tuple means no marker was found and says nothing about whether the run completed; that judgement
    needs the summary and the exit code too, and it is not this module's.
    """
    return tuple(marker for marker in TRUNCATION_MARKERS if _marker_is_the_runs_own(marker, text))
