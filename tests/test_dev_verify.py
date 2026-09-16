"""``lab_commons.dev.verify`` and ``.reports`` — the parser that must not read an interrupted run as a pass.

ONE SUITE FOR TWO MODULES, because they are one mechanism split at a seam rather than two features:
``reports`` decides what a step's output MEANS and ``verify`` runs the processes that produce it,
and every test below drives the pair the way the entry point does.

THE DECISIVE TEST IS THE MEASURED ONE. 2026-09-15, ``optimi_lab`` as configured collected 307 tests,
hit 3 collection errors, printed ``Interrupted`` and ran ZERO of them -- and the same invocation
printed a ``307 passed``-shaped line. ``INTERRUPTED`` below is that output, with BOTH halves in it
on purpose: a parser that looks for the good news finds it there. So the assertion is not merely
"this is not a PASS" but the stronger pair -- it is INCONCLUSIVE, and it is not FAIL either, because
a run that executed nothing has nobody to blame.

THE FIXTURES ARE STRING CONSTANTS, not live subprocesses. The subject here is the READING of
pytest's output, and a live run would test this box's pytest instead: the interrupted case in
particular cannot be produced on demand, which is exactly why it went unnoticed in the first place.
The steps that DO shell out (:func:`~lab_commons.dev.verify.project_root`, ``_tee``) are covered
against this checkout rather than against a double.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from lab_commons.dev.logref import LogRef, verify_log
from lab_commons.dev.reports import (
    SKIP_CEILING,
    MalformedAllowance,
    StepReport,
    declared_skips,
    read_pytest,
    read_ruff,
)
from lab_commons.dev.verdict import Outcome
from lab_commons.dev.verify import EXIT_CODES, PYTEST_ARGS, build_verdict, project_root
from lab_commons.dev.verify import _tee as tee_step

#: A clean run, in the shape pytest's ``-q`` footer prints it.
CLEAN = '.' * 70 + '\n307 passed in 12.3s\n'

#: A red run. The short summary NAMES the three, which is what lets a FAIL be actionable.
FAILING = """=========================== short test summary info ============================
FAILED tests/test_units.py::test_a_bare_float_is_refused - AssertionError: assert None
FAILED tests/test_paths.py::test_the_root_is_the_checkout - KeyError: 'root'
FAILED tests/test_log.py::test_emit_writes_one_line - AssertionError
3 failed, 304 passed in 14.8s
"""

#: THE MEASURED CASE: a collection error, an ``Interrupted`` banner, and a clean-looking count line
#: in ONE output. Anything that reads the last line and stops calls this a pass.
INTERRUPTED = """==================================== ERRORS ====================================
ERROR tests/test_optimiser.py - ModuleNotFoundError: No module named 'optimi'
!!!!!!!!!!!!!!!!!!! Interrupted: 3 errors during collection !!!!!!!!!!!!!!!!!!!!
collected 307 items / 3 errors
307 passed in 0.44s
"""

#: A run that said nothing at all -- a segfault, a killed worker, a wrapper that swallowed stdout.
SILENT = ''

#: A run whose summary names failures the output never attributes to a node id.
UNNAMED = '2 failed, 40 passed in 3.1s\n'

#: A run with skips, in the shape ``-rs`` prints them: the count grouped at ONE location, because
#: pytest groups a skip by (file, line, reason) and there is no node id in the line to match.
SKIPPING = """=========================== short test summary info ============================
SKIPPED [2] tests/test_vendor.py:31: needs the vendor engine
300 passed, 2 skipped in 9.0s
"""

#: The same run WITHOUT ``-rs``: the skips are counted and not one of them is named.
COUNTED_NOT_NAMED = '300 passed, 2 skipped in 9.0s\n'

#: A suite that skipped itself into a green verdict. Every skip here could be declared, and the
#: ceiling is the only thing between this text and a PASS over five executed tests.
MOSTLY_SKIPPED = """=========================== short test summary info ============================
SKIPPED [20] tests/test_vendor.py:31: needs the vendor engine
5 passed, 20 skipped in 1.0s
"""

#: The location prefix that covers every skip in :data:`SKIPPING`.
VENDOR = 'tests/test_vendor.py'


def _verdict(reports: tuple[StepReport, ...], log: Path):
    """Build a verdict over *reports*, with the two plumbing fields held constant.

    A helper rather than a fixture because two of these tests want DIFFERENT reports over the same
    tree and env, and the point of every one of them is the reports.
    """
    return build_verdict(reports, tree='sha256:deadbeef', env='cafe1234', spec='verify', log=LogRef.of(log))


@pytest.fixture
def log(tmp_path: Path) -> Path:
    path = tmp_path / 'verify.log'
    path.write_text('$ ruff check .\nAll checks passed!\n', encoding='utf-8')
    return path


class TestReadingPytest:
    def test_a_clean_run_reports_and_names_nothing(self) -> None:
        """The settling case: a summary, no failures, and nothing that could have cut it short."""
        report = read_pytest(CLEAN, returncode=0)
        assert report.truncated == ()
        assert report.failures == ()
        assert report.reported == ('pytest',)

    def test_a_failing_run_names_every_failure(self) -> None:
        """A red verdict that cannot say WHICH test was red is the refusal a count pin is."""
        report = read_pytest(FAILING, returncode=1)
        assert report.truncated == ()
        assert report.failures == (
            'tests/test_units.py::test_a_bare_float_is_refused',
            'tests/test_paths.py::test_the_root_is_the_checkout',
            'tests/test_log.py::test_emit_writes_one_line',
        )
        assert set(report.failures) <= set(report.reported), 'a named failure must be a node that reported'

    def test_the_interrupted_run_is_not_a_pass_and_is_not_a_fail(self) -> None:
        """THE MEASURED CASE. 307 collected, 3 collection errors, zero run, "307 passed" printed."""
        report = read_pytest(INTERRUPTED, returncode=2)
        assert report.reported == (), 'nothing reported an outcome, so nothing may be promoted'
        assert report.failures == (), 'a run that executed nothing has no failure to attribute'
        joined = ' | '.join(report.truncated)
        assert 'interrupted' in joined
        assert '3 error(s) during collection' in joined

    def test_output_with_no_summary_line_cannot_settle(self) -> None:
        """An empty output is a run that said nothing, which is not a run that found nothing wrong."""
        report = read_pytest(SILENT, returncode=0)
        assert 'no parsable summary line' in ' | '.join(report.truncated)

    def test_a_summary_that_outnumbers_its_named_failures_cannot_settle(self) -> None:
        """A summary naming 2 failures over zero node ids is a FAIL that cannot say what it blames."""
        report = read_pytest(UNNAMED, returncode=1)
        assert 'names 2 failure(s) and the output names 0 node id(s)' in ' | '.join(report.truncated)

    def test_a_run_that_executed_nothing_cannot_settle(self) -> None:
        """The floor under the skip allowance: a suite may not skip its way to a green verdict."""
        report = read_pytest('40 deselected in 0.4s\n', returncode=0)
        assert 'executed nothing it could be judged on' in ' | '.join(report.truncated)

    @pytest.mark.parametrize('code', [2, 3, 4, 5, -9])
    def test_every_exit_code_that_is_not_a_result_truncates(self, code: int) -> None:
        """0 and 1 are the only two exit codes that describe a run which reached its tests."""
        assert read_pytest(CLEAN, returncode=code).truncated != ()


class TestReadingRuff:
    def test_a_clean_step_reports_itself(self) -> None:
        assert read_ruff('ruff check .', 0) == StepReport(name='ruff check .', reported=('ruff check .',))

    def test_violations_are_a_named_failure(self) -> None:
        assert read_ruff('ruff check .', 1).failures == ('ruff check .',)

    def test_ruff_erroring_is_not_ruff_reporting(self) -> None:
        """A config ruff could not read is the same non-zero to a shell as a dirty tree. Not here."""
        report = read_ruff('ruff check .', 2)
        assert report.failures == ()
        assert 'ruff erroring rather than ruff reporting' in ' | '.join(report.truncated)


class TestTheSkipRatchet:
    """BOTH DIRECTIONS, and the default that leaves every repo where it already was.

    The allowance exists because the strict reading -- any skip truncates -- is correct and
    unusable across four repos: a tool that answers INCONCLUSIVE on every invocation forever stops
    being read, and a refusal nobody reads is routed around rather than fixed. What makes the
    allowance a ratchet rather than a loophole is that BOTH sides refuse, and that declaring
    nothing is exactly today's behaviour.
    """

    def test_pytest_is_always_asked_to_name_its_skips(self) -> None:
        """The skip letter is load-bearing: a count cannot say WHICH test went quiet.

        Asserted as MEMBERSHIP of the report set rather than as the literal ``-rs``, which is what
        this line used to read. That spelling pinned the whole set to skips-and-nothing-else, so it
        agreed with a `verify` that never asked pytest to name a failure -- and it went green
        throughout, because it was checking the flag against itself rather than against what the
        parser downstream needs. The letters each have their own reason; see `PYTEST_ARGS`.
        """
        assert 's' in PYTEST_ARGS[0] and PYTEST_ARGS[0].startswith('-r')

    def test_a_declared_skip_lets_the_run_settle(self) -> None:
        assert read_pytest(SKIPPING, returncode=0, allowed_skips=(VENDOR,)).truncated == ()

    def test_an_undeclared_skip_truncates_and_is_named(self) -> None:
        """Forward side. The node location is in the reason, not a number of them."""
        reasons = ' | '.join(read_pytest(SKIPPING, returncode=0).truncated)
        assert 'skipped and not declared' in reasons
        assert 'tests/test_vendor.py:31' in reasons

    def test_a_declared_skip_that_did_not_happen_truncates_and_is_named(self) -> None:
        """The other side. Without it the list only ever grows, which is a waiver nothing uses."""
        allowed = (VENDOR, 'tests/test_retired.py')
        reasons = ' | '.join(read_pytest(SKIPPING, returncode=0, allowed_skips=allowed).truncated)
        assert 'declared in allowed_skips and NOT skipped' in reasons
        assert 'tests/test_retired.py' in reasons
        assert 'tests/test_vendor.py' not in reasons.split('NOT skipped')[1]

    def test_a_prefix_covers_a_file_and_an_exact_location_pins_one_site(self) -> None:
        """ONE spelling, said twice: entries are location PREFIXES, never node ids."""
        assert read_pytest(SKIPPING, returncode=0, allowed_skips=('tests/test_vendor.py:31',)).truncated == ()
        assert read_pytest(SKIPPING, returncode=0, allowed_skips=('tests/test_vendor.py:99',)).truncated != ()

    def test_a_windows_spelled_location_matches_a_posix_declaration(self) -> None:
        """MEASURED 2026-09-16: pytest prints ``tests\\test_vendor.py:4`` on Windows, ``tests/...``
        on Linux. One declaration is committed for both, so the comparison normalises -- otherwise
        the same repo settles on one box and truncates on the other, which is not a verdict.
        """
        windows = SKIPPING.replace('tests/test_vendor.py', 'tests\\test_vendor.py')
        assert read_pytest(windows, returncode=0, allowed_skips=(VENDOR,)).truncated == ()
        assert 'tests/test_vendor.py:31' in ' | '.join(read_pytest(windows, returncode=0).truncated)

    def test_skips_that_were_counted_but_not_named_truncate(self) -> None:
        """The naming floor: an allowance cannot be checked against skips nobody reported."""
        reasons = ' | '.join(read_pytest(COUNTED_NOT_NAMED, returncode=0, allowed_skips=(VENDOR,)).truncated)
        assert 'the short summary names 0' in reasons
        assert '-rs' in reasons

    def test_the_ceiling_refuses_a_suite_that_skipped_itself_green(self) -> None:
        """An escape hatch needs a CEILING, not just a reason -- and this one is a ratio."""
        reasons = ' | '.join(read_pytest(MOSTLY_SKIPPED, returncode=0, allowed_skips=(VENDOR,)).truncated)
        assert f'above the {SKIP_CEILING:.0%} ceiling' in reasons


class TestTheDeclaration:
    """Reading ``[tool.lab_commons.verify] allowed_skips`` out of a project's own pyproject."""

    def _write(self, root: Path, body: str) -> Path:
        (root / 'pyproject.toml').write_text(body, encoding='utf-8')
        return root

    def test_a_project_with_no_pyproject_declares_nothing(self, tmp_path: Path) -> None:
        assert declared_skips(tmp_path) == ()

    def test_a_pyproject_with_no_verify_table_behaves_exactly_as_today(self, tmp_path: Path) -> None:
        """The default that matters: a repo that declares nothing is unchanged, byte for byte."""
        root = self._write(tmp_path, '[project]\nname = "thing"\n\n[tool.ruff]\nline-length = 120\n')
        assert declared_skips(root) == ()
        assert read_pytest(SKIPPING, returncode=0, allowed_skips=declared_skips(root)).truncated != ()

    def test_a_declared_list_is_read_sorted_and_deduplicated(self, tmp_path: Path) -> None:
        root = self._write(
            tmp_path,
            '[tool.lab_commons.verify]\nallowed_skips = ["tests/b.py", "tests/a.py", "tests/b.py"]\n',
        )
        assert declared_skips(root) == ('tests/a.py', 'tests/b.py')

    @pytest.mark.parametrize(
        'body',
        [
            '[tool.lab_commons.verify]\nallowed_skips = "tests/a.py"\n',
            '[tool.lab_commons.verify]\nallowed_skips = [1, 2]\n',
            '[tool.lab_commons.verify]\nallowed_skips = ["tests/a.py", ""]\n',
        ],
        ids=['a bare string', 'a list of integers', 'a list holding an empty entry'],
    )
    def test_a_malformed_allowance_is_refused_rather_than_defaulted(self, tmp_path: Path, body: str) -> None:
        """NOT an empty set. A declaration nobody could parse exempts nothing while its author
        believes it exempted everything -- and the author never finds out, because the tool is
        green either way.
        """
        with pytest.raises(MalformedAllowance, match='not a list of non-empty strings'):
            declared_skips(self._write(tmp_path, body))


class TestTheVerdict:
    def test_three_clean_steps_pass(self, log: Path) -> None:
        reports = (
            read_ruff('ruff check .', 0),
            read_ruff('ruff format --check .', 0),
            read_pytest(CLEAN, returncode=0),
        )
        verdict = _verdict(reports, log)
        assert verdict.result.outcome is Outcome.PASS
        assert EXIT_CODES[verdict.result.outcome] == 0

    def test_a_failing_suite_fails_with_its_failures_named(self, log: Path) -> None:
        reports = (
            read_ruff('ruff check .', 0),
            read_ruff('ruff format --check .', 0),
            read_pytest(FAILING, returncode=1),
        )
        verdict = _verdict(reports, log)
        assert verdict.result.outcome is Outcome.FAIL
        assert 'tests/test_paths.py::test_the_root_is_the_checkout' in verdict.result.failures
        assert EXIT_CODES[verdict.result.outcome] == 1

    def test_the_interrupted_suite_leaves_the_whole_verdict_inconclusive(self, log: Path) -> None:
        """Two green steps cannot promote a third that never ran -- and the exit code says so."""
        reports = (
            read_ruff('ruff check .', 0),
            read_ruff('ruff format --check .', 0),
            read_pytest(INTERRUPTED, returncode=2),
        )
        verdict = _verdict(reports, log)
        assert verdict.result.outcome is Outcome.INCONCLUSIVE
        assert 'pytest' in verdict.result.reason, 'the silent step must be named, not counted'
        assert EXIT_CODES[verdict.result.outcome] == 2
        assert EXIT_CODES[Outcome.FAIL] != EXIT_CODES[Outcome.INCONCLUSIVE], 'the two remedies differ'

    def test_a_step_that_never_launched_is_silent_by_name(self, log: Path) -> None:
        """``selected`` comes from the step NAMES, which is the only way ``silent`` means anything."""
        reports = (
            read_ruff('ruff check .', 0),
            StepReport(name='ruff format --check .'),
            read_pytest(CLEAN, returncode=0),
        )
        verdict = _verdict(reports, log)
        assert verdict.result.outcome is Outcome.INCONCLUSIVE
        assert 'silent: ruff format --check .' in verdict.result.reason

    def test_the_verdict_stamps_a_log_a_later_reader_can_check(self, log: Path) -> None:
        """The stamp is the only artifact a reader who was not there gets, so it round-trips."""
        verdict = _verdict((read_ruff('ruff check .', 0), read_pytest(CLEAN, returncode=0)), log)
        verdict.stamp()
        citation = verify_log(log)
        assert citation.result == 'pass'
        assert citation.tree == 'sha256:deadbeef'
        assert citation.spec == 'verify'


class TestTheRoot:
    def test_the_root_is_this_checkout(self) -> None:
        """Asked of git, against the REAL repo -- a marker walk would answer for a nested package."""
        assert project_root(Path(__file__).parent) == Path(__file__).resolve().parents[1]

    def test_a_directory_outside_any_checkout_is_refused(self, tmp_path: Path) -> None:
        """Refused rather than guessed: a fallback root is a well-formed verdict about another tree."""
        with pytest.raises(SystemExit, match='could not find a git checkout'):
            project_root(tmp_path)


class TestTheTee:
    def test_the_first_line_reaches_the_log_before_the_slow_step_exits(self, tmp_path: Path) -> None:
        """THE CONTROL FOR THE STREAMING DEFECT, MEASURED 2026-09-16 on wdg-lab.

        A run sat 26+ minutes with nothing in its log but the two ruff lines while pytest was
        genuinely working the whole time -- the log's mtime was frozen, and settling whether the run
        was alive needed sampling the process's CPU counter from outside, a diagnosis nobody should
        need for their own ``verify``. ``.claude/rules/workflow.md`` states the property this test
        pins: "Tell slow from dead by PROGRESS PER WORKER, never by whether the run as a whole is
        still writing."

        Asserting only the FINAL log content (the shape every other test in this file uses) passes
        just as happily against the broken version -- both write everything eventually. So this test
        watches the log WHILE the step is still running, from a second thread. It plants a real
        subprocess rather than a fixture, because the defect was in the plumbing (``_tee``'s own
        flushing and the child's own stdout buffering), not in anything that could be modelled as a
        string.

        THE ASSERTION IS AN ORDERING, NOT A DEADLINE, and that is deliberate. It used to be a 1.1s
        watch against a 1.2s sleep -- a 100ms wall-clock margin, on a box that routinely runs
        several gates at once, and it flaked there once already. A margin that thin does not measure
        streaming, it measures scheduler luck, and a flaky guard is a guard somebody disables. So
        the child now BLOCKS on a sentinel file that the watcher writes only after it has SEEN the
        first line in the log: the step cannot exit until that observation has happened, so no
        timing holds the property up. The bound that remains is a generous liveness stop, not the
        property -- against the buffered version the first line never lands while the child runs,
        the watcher releases the child anyway so the test terminates instead of hanging, and the
        flag it failed to set is what reds.
        """
        script = tmp_path / 'slow_step.py'
        release = tmp_path / 'release'
        script.write_text(
            'import pathlib, time\n'
            "print('first line', flush=True)\n"
            f'release = pathlib.Path({str(release)!r})\n'
            'deadline = time.monotonic() + 10.0\n'
            'while not release.exists() and time.monotonic() < deadline:\n'
            '    time.sleep(0.02)\n'
            "print('second line', flush=True)\n",
            encoding='utf-8',
        )
        log = tmp_path / 'log.txt'
        seen_first_before_second_printed = False

        def watch() -> None:
            nonlocal seen_first_before_second_printed
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                if log.exists() and 'first line' in log.read_text(encoding='utf-8'):
                    seen_first_before_second_printed = True
                    break
                time.sleep(0.02)
            release.write_text('go', encoding='utf-8')

        watcher = threading.Thread(target=watch)
        with log.open('w', encoding='utf-8') as handle:
            watcher.start()
            code = tee_step([sys.executable, str(script)], cwd=tmp_path, handle=handle)
        watcher.join()

        assert code == 0
        assert seen_first_before_second_printed, (
            'the first line must be visible in the log WHILE the step is still running, not only '
            'after it exits -- a reader watching a slow step must see it, not have to guess'
        )
        written = log.read_text(encoding='utf-8')
        assert 'first line' in written
        assert 'second line' in written


class TestThePlantedControl:
    def test_a_planted_interruption_flips_a_clean_text(self) -> None:
        """THE CONTROL, and it has both halves: the guard fires on the plant and not on the clean text.

        The plant is the SMALLEST edit that matters -- the same clean output with the banner pytest
        prints when it stops early -- so what this proves is that the banner is what the parser is
        reading, and not some other difference between two hand-written fixtures.
        """
        assert read_pytest(CLEAN, returncode=0).truncated == (), 'the floor: the clean text must settle'
        planted = CLEAN + '!!!!!!!!!!!!!!!!!!! Interrupted: 3 errors during collection !!!!!!!!!!!!!!!!!!!!\n'
        assert read_pytest(planted, returncode=0).truncated != (), 'the banner alone must refuse promotion'

    def test_a_planted_skip_on_either_side_of_the_allowance_is_refused(self) -> None:
        """THE CONTROL FOR THE RATCHET, with its floor and both of its sides.

        The floor first -- the declared-and-observed case must SETTLE, or "it refuses everything"
        would pass for "it refuses the right things". Then each side is planted separately, so a
        ratchet that had quietly lost one half cannot hide behind the other.
        """
        assert read_pytest(SKIPPING, returncode=0, allowed_skips=(VENDOR,)).truncated == ()
        assert read_pytest(SKIPPING, returncode=0, allowed_skips=()).truncated != (), 'undeclared must refuse'
        stale = read_pytest(SKIPPING, returncode=0, allowed_skips=(VENDOR, 'tests/planted.py'))
        assert stale.truncated != (), 'a declaration nothing used must refuse'

    def test_the_pytest_flags_ASK_FOR_the_names_every_check_compares(self) -> None:
        """THE REGRESSION THIS FILE DID NOT CATCH, and the reason it did not.

        Every fixture here hands :func:`read_pytest` a text that ALREADY contains its ``FAILED``
        lines, so the parser was always tested against output no real invocation produced. The flag
        that decides whether pytest emits those lines lives in `verify.py` and was never asserted --
        so `PYTEST_ARGS` could ask for skips alone, and did, and every red run in every repo came
        back INCONCLUSIVE ("nobody knows") instead of FAIL ("these tests failed"). MEASURED on
        optimi-lab before the fix: `2 failed, 130 passed` read as `the summary names 2 failure(s)
        and the output names 0 node id(s)`.

        The lesson is narrow and worth keeping: a parser tested only on synthetic input asserts the
        SHAPE it was handed, never that anything produces that shape. This closes the gap by pinning
        the request rather than the response -- `f` and `E` and `s` are each here because a check
        below compares NAMES, and a name pytest was not asked to print cannot be compared.
        """
        assert 'f' in PYTEST_ARGS[0], 'without -rf pytest names no FAILED line and every red run reads INCONCLUSIVE'
        assert 'E' in PYTEST_ARGS[0], 'without -rE an errored test is counted and never named'
        assert 's' in PYTEST_ARGS[0], 'without -rs the two-sided skip ratchet has only a number to check'
        assert PYTEST_ARGS[0].startswith('-r'), 'these letters are only meaningful as a -r report set'

    def test_a_failing_run_settles_as_FAIL_and_names_which_test(self) -> None:
        """The property the flags buy, asserted end to end rather than trusted.

        A red suite must reach FAIL -- a settled verdict a caller can act on -- and carry the node
        id with it. If this ever returns INCONCLUSIVE again, the failures stopped being named.
        """
        report = read_pytest(FAILING, returncode=1)
        assert report.truncated == (), f'a plainly-failing run must SETTLE, not truncate: {report.truncated}'
        assert report.failures, 'a failing run that names no test is the defect the -r set exists to prevent'

    def test_a_planted_uncovered_step_cannot_be_promoted(self, log: Path) -> None:
        """The other half of the control, at the verdict level rather than the parser level."""
        clean = (read_ruff('ruff check .', 0), read_pytest(CLEAN, returncode=0))
        assert _verdict(clean, log).result.outcome is Outcome.PASS
        planted = (*clean, StepReport(name='a step that never launched'))
        assert _verdict(planted, log).result.outcome is Outcome.INCONCLUSIVE
