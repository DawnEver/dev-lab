r"""``lab_commons.dev._logdistil`` — the log is parsed without being held, and nothing else moves.

THE REPRODUCTION, MEASURED 2026-09-18. ``run_verify`` read the WHOLE log back with
``path.read_text()`` and then ran six regexes over it. A 400,000-line / 80.8 MB run completes in
11.8 s at ``rc=0``; a 31 MB stand-in of that shape measured 93.3 MB resident from the read and
104.6 MB through the parse, because the text is decoded once and ``splitlines()``-ed twice more.
A genuinely runaway run was a ``MemoryError`` and NO verdict -- the same defect class as the cp1252
crash of ``50bf819``, arriving by a different road: the runner is what separates PASS from FAIL from
INCONCLUSIVE, so a failure here removes the ability to answer rather than corrupting one answer.

TWO DIRECTIONS, AND THE SECOND IS THE ONE THAT MATTERS MOST. An oversize log must be ANSWERED rather
than crash -- and an ORDINARY log must parse to exactly the report it parsed to yesterday. Without
that second half, a "fix" that dropped one line in ten would pass the first test and quietly lose a
red. It is checked against a REAL pytest run teed through the REAL ``_tee``, both ways, comparing the
whole-text parse this replaced against the streamed one.

AND A RATCHET, because the distillation is only safe while it stays WIDER than the parser.
``PARSE_SHAPES`` is the NAMED SET of shapes ``reports`` consults, read out of its SOURCE rather than
listed by hand, with both sides of a :mod:`lab_commons.dev.floors` floor. A pattern added there reds
here until it has a representative line proved to survive; a pattern deleted there reds too, so the
representative cannot outlive the shape it stands for.
"""

from __future__ import annotations

import ast
import contextlib
import io
import sys
from pathlib import Path

from _arch_corpus import ROOT

from lab_commons.dev._logdistil import Distillate, distil, distil_log, relevant
from lab_commons.dev.floors import assert_floor, assert_floor_still_binds
from lab_commons.dev.reports import StepReport, read_pytest
from lab_commons.dev.verify import _PYTEST_BANNER, _tee

#: The banner ``verify`` writes between the ruff half of a log and the pytest half.
BANNER = _PYTEST_BANNER

#: Every shape :func:`~lab_commons.dev.reports.read_pytest` consults, mapped to a line that carries
#: it. MEASURED 2026-09-18 by reading ``reports.py``: six module-level ``re.compile`` patterns plus
#: one literal ``'INTERNALERROR' in text``. The VALUES are what the distillation has to keep, and the
#: KEYS are checked against the module's own source below, so this cannot drift into a list of shapes
#: somebody remembered.
PARSE_SHAPES: dict[str, str] = {
    '_COLLECTED': 'collected 307 items / 3 errors',
    '_COLLECTION_ERRORS': '3 errors during collection',
    '_COUNT': '=========== 3 failed, 304 passed, 2 xfailed in 14.8s ===========',
    '_FAILED_NODE': 'FAILED tests/test_units.py::test_a_bare_float_is_refused - AssertionError',
    '_INTERRUPTED': '!!!!!!! Interrupted: 3 errors during collection !!!!!!!',
    '_SKIPPED': 'SKIPPED [1] tests/test_vendor.py:31: needs the vendor',
    'INTERNALERROR': 'INTERNALERROR> Traceback (most recent call last):',
}

#: The floor under the shape scan. MEASURED 2026-09-18: 7 shapes. Finding NOTHING in a source file is
#: what a successful parse of the WRONG file also looks like, so the scan needs a number under it.
SHAPE_FLOOR = 5

#: The other side. A parser that grew from 7 shapes to 13 without this file noticing is a filter
#: measured against a module that no longer exists; the remedy is to RE-MEASURE, never to widen.
SHAPE_HEADROOM = 4

#: Lines of noise for the oversize control. Not 400,000: the subject is RESIDENT SIZE rather than
#: throughput, so the plant only has to be far larger than the evidence buried in it, and this one
#: runs in about a second while pinning a ratio of the same order.
NOISE_LINES = 120_000


def source_shapes() -> set[str]:
    """Every parse shape ``reports.py`` consults, read out of its AST rather than out of memory.

    Two kinds, because the module has two: a module-level name bound to a ``re.compile(...)`` call,
    and a bare substring tested with ``in`` against the pytest text. Both are shapes a line has to
    survive the distillation to be seen by, so both belong in the same set.
    """
    tree = ast.parse((ROOT / 'src' / 'lab_commons' / 'dev' / 'reports.py').read_text(encoding='utf-8'))
    found: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        value = node.value
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        compiled = (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and value.func.attr == 'compile'
            and isinstance(value.func.value, ast.Name)
            and value.func.value.id == 're'
        )
        if compiled:
            found |= {t.id for t in targets if isinstance(t, ast.Name)}
    for node in ast.walk(tree):
        literal_in = (
            isinstance(node, ast.Compare)
            and any(isinstance(op, ast.In) for op in node.ops)
            and isinstance(node.left, ast.Constant)
            and isinstance(node.left.value, str)
        )
        if literal_in:
            found.add(node.left.value)
    return found


class TestTheShapeSetIsARatchet:
    def test_the_representatives_are_exactly_the_shapes_the_parser_consults(self) -> None:
        """BOTH SIDES, over a NAMED SET rather than a count, with the floor first."""
        live = source_shapes()
        assert_floor(len(live), floor=SHAPE_FLOOR, what='pytest parse shape')
        assert_floor_still_binds(len(live), floor=SHAPE_FLOOR, headroom=SHAPE_HEADROOM, what='pytest parse shape')
        assert live == set(PARSE_SHAPES), (
            f'consulted by reports.py and with no representative line here: {sorted(live - set(PARSE_SHAPES))} '
            f'-- add one and prove it survives the distillation, or the filter is narrower than the '
            f'parser and a line it drops is a verdict nobody can read. Represented here and no longer '
            f'consulted: {sorted(set(PARSE_SHAPES) - live)} -- delete it in the same edit that removed '
            f'the shape; a waiver nothing uses is a hole that reads as a decision.'
        )

    def test_every_shape_survives_the_distillation(self) -> None:
        """THE PROPERTY THE WHOLE DESIGN RESTS ON: the filter is WIDER than the parser, never narrower."""
        dropped = sorted(name for name, line in PARSE_SHAPES.items() if not relevant(line))
        assert dropped == [], f'the distillation would drop the only line carrying these shapes: {dropped}'

    def test_the_filter_is_not_vacuous(self) -> None:
        """THE FLOOR ON THE FILTER ITSELF: a predicate that keeps everything proves nothing above."""
        assert not relevant('tests/test_noise.py::test_0 some verbose diagnostic line of output')
        assert not relevant('  where 1 = len([1])')


class TestTheBannerSplit:
    def test_only_the_last_pytest_half_survives(self) -> None:
        """The streaming equivalent of ``whole.rpartition(banner)[2]``, checked as such."""
        whole = f'FAILED ruff/half.py::not_pytest\n{BANNER}FAILED real/half.py::test_a\n1 failed in 1s\n'
        assert distil(whole.splitlines(keepends=True), banner=BANNER).text == whole.rpartition(BANNER)[2]

    def test_a_log_with_no_banner_keeps_everything_parsable(self) -> None:
        """A half-written log -- the step died before the banner -- still answers what it has."""
        got = distil(['FAILED a.py::test_a\n', 'noise\n'], banner=BANNER)
        assert got.text == 'FAILED a.py::test_a\n'
        assert (got.read, got.kept) == (2, 1)


class TestAnOrdinaryLogParsesByteIdentically:
    """DIRECTION TWO, against a REAL pytest run teed through the REAL ``_tee`` into a REAL log.

    A fixture string would prove the two code paths agree about a fixture. This proves they agree
    about what ``verify`` actually writes, which is the only text either of them is ever handed.
    """

    def _real_log(self, tmp_path: Path, body: str, *, noise: int = 0) -> tuple[Path, int]:
        suite = tmp_path / 'suite'
        suite.mkdir()
        (suite / 'test_planted.py').write_text(body, encoding='utf-8')
        log = tmp_path / 'verify.log'
        with log.open('w', encoding='utf-8') as handle, contextlib.redirect_stdout(io.StringIO()):
            handle.write(BANNER)
            code = _tee(
                [sys.executable, '-m', 'pytest', '-rfEs', '-p', 'no:cacheprovider', str(suite)],
                cwd=tmp_path,
                handle=handle,
            )
            if noise:
                handle.write('tests/test_noise.py::test_0 a verbose diagnostic line of output\n' * noise)
        return log, code

    #: A suite with greens, one red and one skip, so the summary line, the short summary, the failure
    #: node ids and the skip ratchet are ALL exercised by one real log. TWENTY greens rather than one:
    #: a single skip out of three tests is 33%, over ``SKIP_CEILING``, and the report would truncate
    #: on the ceiling instead of ever reaching the red this comparison is about.
    SUITE = (
        'import pytest\n\n\n'
        + ''.join(f'def test_green_{n}():\n    assert True\n\n\n' for n in range(20))
        + 'def test_red():\n    assert 0\n\n\n'
        + "@pytest.mark.skip(reason='needs the vendor')\ndef test_grey():\n    pass\n"
    )

    #: The planted skip, DECLARED. An undeclared skip truncates -- that is the ratchet working, and
    #: it would hide the red this comparison exists to find.
    ALLOWED = ('suite/test_planted.py',)

    def test_the_streamed_parse_equals_the_whole_text_parse(self, tmp_path: Path) -> None:
        log, code = self._real_log(tmp_path, self.SUITE)
        whole = log.read_text(encoding='utf-8', errors='replace')
        before = read_pytest(whole.rpartition(BANNER)[2], returncode=code, allowed_skips=self.ALLOWED)
        distillate = distil_log(log, banner=BANNER)
        after = distillate.annotate(read_pytest(distillate.text, returncode=code, allowed_skips=self.ALLOWED))
        assert after == before, 'an ordinary log must parse to exactly the report it parsed to before'
        assert 'test_planted.py::test_red' in ' '.join(after.failures + after.truncated), (
            'the floor on this comparison: both sides must have SEEN the planted red, or two identical '
            'nothings would compare equal'
        )

    def test_an_oversize_log_is_answered_rather_than_held(self, tmp_path: Path) -> None:
        """DIRECTION ONE, and it pins the RATIO rather than a byte count at one operating point."""
        log, code = self._real_log(tmp_path, self.SUITE, noise=NOISE_LINES)
        distillate = distil_log(log, banner=BANNER)
        report = distillate.annotate(read_pytest(distillate.text, returncode=code, allowed_skips=self.ALLOWED))
        assert distillate.read > NOISE_LINES, 'the plant must actually be oversize, or this proves nothing'
        assert len(distillate.text) * 100 < log.stat().st_size, (
            f'resident text must track the EVIDENCE and not the noise: {len(distillate.text)} chars '
            f'held out of a {log.stat().st_size}-byte log'
        )
        assert 'test_planted.py::test_red' in ' '.join(report.failures + report.truncated), (
            'and the red buried under the noise must still be found -- a tail window is what would have lost it'
        )


class TestTheRefusalIsDiagnosed:
    def test_a_half_that_distils_to_nothing_names_what_it_read(self) -> None:
        """A refusal must be DIAGNOSED, and this is the one reason only the distillate can give.

        "pytest printed no parsable summary line" is TRUE of the distillate and MISLEADING about the
        log, so what was read is named and the log is named as the place to look.
        """
        distillate = distil(['noise\n'] * 400_000, banner=BANNER)
        assert (distillate.text, distillate.kept) == ('', 0)
        annotated = distillate.annotate(read_pytest(distillate.text, returncode=0))
        assert '400000 line(s)' in ' '.join(annotated.truncated)
        assert 'read the log itself' in ' '.join(annotated.truncated)

    def test_a_report_over_a_log_that_kept_something_is_returned_untouched(self) -> None:
        """THE OTHER SIDE: annotate may add a reason in exactly one case and in no other."""
        report = StepReport(name='pytest', reported=('pytest',))
        assert Distillate(text='1 passed\n', read=1, kept=1).annotate(report) is report
        assert Distillate(text='', read=0, kept=0).annotate(report) is report
