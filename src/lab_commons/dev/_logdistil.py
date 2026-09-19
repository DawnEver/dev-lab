r"""Reading the pytest half of a verify LOG without ever holding the log. Pure, plus one ``open()``.

MEASURED 2026-09-18, and it is the same defect class as the cp1252 crash fixed in ``50bf819``
arriving by a different road: the runner is the thing that separates PASS from FAIL from
INCONCLUSIVE, so a failure here does not corrupt one answer, it removes the ability to answer.
``run_verify`` did ``path.read_text()`` over the WHOLE log and then ran six regexes across it. A
400,000-line / 80.8 MB run completes in 11.8 s at ``rc=0``; a 31 MB stand-in of the same shape
measured 93.3 MB resident from the read alone and 104.6 MB through the parse, because the text is
decoded once and then ``splitlines()``-ed twice more. Linear, no ceiling, no streaming read. A
genuinely runaway run is a ``MemoryError`` and NO verdict.

WHY NOT A SIZE CEILING, which is this family's usual answer. A ceiling refuses rather than guesses,
and a refusal is honest -- but the number is a guess with nothing behind it, and its failure mode is
the one :mod:`lab_commons.dev.reports` already argues against for skips: a tool that answers
INCONCLUSIVE on every invocation stops being read, and a refusal nobody reads gets routed around
instead of fixed. A big-but-honest suite would be permanently unverifiable in whichever repo owns
it. And ``LAB_CZ_BASE_REF`` is the worked example of what the DEFAULT for such a number costs.

WHY NOT A TAIL WINDOW. Cheap, and it can miss a ``FAILED`` line scrolled out by 80 MB of noise --
which converts a real red into a PASS. That is the one direction this family never accepts.

SO THE THIRD ANSWER, AND IT NEEDS NO NUMBER AT ALL. Every shape the pytest parser reads is confined
to ONE LINE -- six compiled patterns, four of them already ``^``-anchored or ``re.MULTILINE``, plus
one ``'INTERNALERROR' in text``. So the log is read line by line and only the lines that could carry
one of those shapes are kept. THE DEFECT WAS THAT RESIDENT MEMORY TRACKED THE NOISE; AFTER THIS IT
TRACKS THE EVIDENCE, which is proportional to the size of the run and is the honest bill. Nothing is
refused, so nothing is guessed, and there is no default for anyone to inherit.

THE FILTER IS DELIBERATELY WIDER THAN THE PARSER, and that asymmetry is the safety argument. It
tests plain SUBSTRINGS -- :data:`KEEP_TOKENS` -- where the parser tests a grammar, so every line any
pattern in :mod:`lab_commons.dev.reports` can match contains at least one token and is kept, while
lines that merely mention one cost a few bytes and change no answer. Order and the banner reset are
preserved exactly, so ``_summary_counts``'s LAST-matching-line reading and ``_COLLECTED``'s FIRST
one both land on the line they would have landed on in the whole text.

WHAT KEEPS THAT TRUE IS A RATCHET, NOT THIS PARAGRAPH. ``tests/test_dev_logdistil.py`` pins the
NAMED SET of shapes ``reports`` consults, read out of its source, with both sides of a
:mod:`lab_commons.dev.floors` floor: a new pattern there reds here until a representative line for it
is added and shown to survive the distillation.

PRIVATE ON PURPOSE. The SHAPES belong to ``reports``, which is about what output MEANS; the LOG
belongs to ``verify``, which is about processes and files. This is the seam between the two and no
consumer outside them has any business holding it, so it carries no published surface, no provenance
row and no inventory bullet.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

from lab_commons.dev.pytestout import TRUNCATION_MARKERS
from lab_commons.dev.reports import StepReport

__all__ = ['KEEP_TOKENS', 'Distillate', 'distil', 'distil_log', 'relevant']

#: Every substring that puts a line within reach of a shape
#: :func:`~lab_commons.dev.reports.read_pytest` reads. A SUBSTRING SET rather than the patterns
#: themselves, so the filter can only ever be WIDER than the parser: ``xfailed`` contains ``failed``,
#: ``xpassed`` contains ``passed`` and ``errors`` contains ``error``, so the whole summary vocabulary
#: is covered by its stems; ``INTERNALERROR`` and an ``ERROR`` node line are both covered by
#: ``ERROR``; and ``N errors during collection`` is covered twice over. Re-compiling ``reports``'s own
#: patterns here would put the identical grammar in two files and make a drift in either one silent.
#:
#: THE TRUNCATION VOCABULARY IS DERIVED AND NOT TYPED, 2026-09-19, and the ratchet in
#: ``tests/test_dev_logdistil.py`` is what forced it. When ``read_pytest`` grew from one literal
#: (``INTERNALERROR``) to :data:`~lab_commons.dev.pytestout.TRUNCATION_MARKERS`, the stems above
#: covered exactly one of the eight: ``node down``, ``Not properly terminated``, ``0xC0000142``,
#: ``MemoryError``, ``Killed``, ``ImportError while loading conftest`` and ``+ Timeout +`` carry
#: neither ``ERROR`` nor ``error``, so the filter would have DROPPED the only line naming why a run
#: died and the parser would have reported a clean absence. Spelling them here by hand would be the
#: same drift one edit later, so the tuple is taken from the module that owns it.
KEEP_TOKENS: Final[tuple[str, ...]] = (
    'ERROR',
    'FAILED',
    'Interrupted',
    'KeyboardInterrupt',
    'SKIPPED',
    'collected',
    'deselected',
    'error',
    'failed',
    'passed',
    'skipped',
    *TRUNCATION_MARKERS,
)

#: pytest rules its stop-early banners off in exclamation marks, and
#: ``lab_commons.dev.reports._INTERRUPTED`` begins ``^!+\s*`` -- whose ``\s`` can cross a newline.
#: Keeping any line that STARTS with one costs nothing, and it is what stops a banner split across
#: two lines from surviving only in half.
_BANNER_LEAD: Final = '!'


def relevant(line: str) -> bool:
    """Could *line* carry a shape the pytest parser reads? Wider than the parser, never narrower."""
    return line.startswith(_BANNER_LEAD) or any(token in line for token in KEEP_TOKENS)


@dataclass(frozen=True, slots=True)
class Distillate:
    """The pytest half of a log, reduced to the lines a parser could read, and what that cost.

    ``read`` and ``kept`` are carried rather than thrown away because a reduction nobody can size is
    a reduction nobody can check: the two numbers are what let a reader see that 400,000 lines came
    down to two, and what :meth:`annotate` turns into a DIAGNOSIS in the one case that needs one.
    """

    #: The kept lines, in the order the log had them, each newline-terminated.
    text: str
    #: How many lines the pytest half held -- the whole bill, noise included.
    read: int
    #: How many of them a parser could read.
    kept: int

    def annotate(self, report: StepReport) -> StepReport:
        """Add the one truncation reason only this object can give, and otherwise change nothing.

        A REFUSAL MUST BE DIAGNOSED. ``read_pytest`` over an empty text already says "pytest printed
        no parsable summary line", which is TRUE of the distillate and MISLEADING about the log: a
        reader is sent to look for output that may be sitting right there in 400,000 lines of it. So
        when the half held lines and none survived, what was read is named, and the log is named as
        the place to look. Every other case is returned untouched, which is what makes "the ordinary
        parse is byte-identical to today" a checkable claim rather than a hope.
        """
        if self.kept or not self.read:
            return report
        reason = (
            f'the pytest half of the log held {self.read} line(s) and NOT ONE of them carried a shape '
            f'this parser reads. The log is read line by line and only parsable lines are held, so the '
            f'run printed output of a kind nothing here knows how to judge -- read the log itself '
            f'rather than re-running, because a second run will distil to the same nothing.'
        )
        return replace(report, truncated=(*report.truncated, reason))


def distil(lines: Iterable[str], *, banner: str) -> Distillate:
    """Reduce *lines* to the pytest half's parsable lines. Pure over an ITERABLE, so it never opens.

    The banner reset is the streaming equivalent of ``whole.rpartition(banner)[2]``, which is what
    this replaced: clearing on EVERY occurrence leaves exactly what followed the LAST one. It is
    matched INSIDE the line rather than against it, so a child that printed the banner with something
    in front of it splits here exactly where ``rpartition`` split it.
    """
    marker = banner.rstrip('\n')
    kept: list[str] = []
    read = 0
    for raw in lines:
        line = raw
        if marker and marker in line:
            kept.clear()
            read = 0
            line = line.rpartition(marker)[2]
            if not line.strip():
                continue
        read += 1
        if relevant(line):
            kept.append(line if line.endswith('\n') else line + '\n')
    return Distillate(text=''.join(kept), read=read, kept=len(kept))


def distil_log(path: Path, *, banner: str) -> Distillate:
    """:func:`distil` over the file at *path*, streamed -- one line resident at a time, never the log.

    ``errors='replace'`` matches both the whole-file read this replaced and the encoding ``_tee``
    wrote with, so a log that already survived a mis-decode is read here exactly as it was before.
    """
    with path.open('r', encoding='utf-8', errors='replace') as handle:
        return distil(handle, banner=banner)
