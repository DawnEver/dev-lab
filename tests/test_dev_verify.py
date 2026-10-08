"""``lab_commons.dev.verify`` and ``.reports`` — the parser that must not read an interrupted run as a pass.

ONE SUITE FOR TWO MODULES, because they are one mechanism split at a seam rather than two features:
``reports`` decides what a step's output MEANS and ``verify`` runs the processes that produce it,
and every test below drives the pair the way the entry point does.

THE DECISIVE TEST IS THE MEASURED ONE. 2026-09-15, ``consumer_c`` as configured collected 307 tests,
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

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Final

import pytest

from lab_commons.dev import verify
from lab_commons.dev.inflight import claim_path
from lab_commons.dev.logref import LogRef, verify_log
from lab_commons.dev.reports import (
    SKIP_CEILING,
    MalformedAllowance,
    StepReport,
    declared_skips,
    read_pytest,
    read_ruff,
    stale_declarations,
)
from lab_commons.dev.verdict import Outcome, Verdict
from lab_commons.dev.verdictledger import Entry, entries, outcomes_dir, record, run_test_id
from lab_commons.dev.verify import EXIT_CODES, LEDGER_PLUGIN, PYTEST_ARGS, build_verdict, project_root
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
ERROR tests/test_optimiser.py - ModuleNotFoundError: No module named 'consumer-c'
!!!!!!!!!!!!!!!!!!! Interrupted: 3 errors during collection !!!!!!!!!!!!!!!!!!!!
collected 307 items / 3 errors
307 passed in 0.44s
"""

#: A run that said nothing at all -- a segfault, a killed worker, a wrapper that swallowed stdout.
SILENT = ''

#: A run whose summary names failures the output never attributes to a node id.
UNNAMED = '2 failed, 40 passed in 3.1s\n'

#: A run with skips, in the shape ``verify`` asks pytest for: ONE LINE PER SKIP, naming the NODE ID.
#: MEASURED 2026-10-07 against the installed pytest: ``--no-fold-skipped`` turns the grouped
#: ``SKIPPED [2] tests/test_vendor.py:31: reason`` into ``SKIPPED <node id> - <reason>``, which is
#: ``_pytest.terminal.show_skipped_unfolded``. The folded line is the one that carries a LINE NUMBER
#: and no node id, and a line number is what moves when an unrelated edit inserts a comment above it.
SKIPPING = """=========================== short test summary info ============================
SKIPPED tests/test_vendor.py::test_a - needs the vendor engine
SKIPPED tests/test_vendor.py::test_b - needs the vendor engine
300 passed, 2 skipped in 9.0s
"""

#: The same run WITHOUT ``-rs``: the skips are counted and not one of them is named.
COUNTED_NOT_NAMED = '300 passed, 2 skipped in 9.0s\n'

#: A suite that skipped itself into a green verdict. Every skip here could be declared, and the
#: ceiling is the only thing between this text and a PASS over five executed tests.
MOSTLY_SKIPPED = (
    """=========================== short test summary info ============================
"""
    + ''.join(f'SKIPPED tests/test_vendor.py::test_{n} - needs the vendor engine\n' for n in range(20))
    + """5 passed, 20 skipped in 1.0s
"""
)

#: The MODULE, which is a prefix of every node id inside it.
VENDOR = 'tests/test_vendor.py'

#: The two node ids :data:`SKIPPING` reports, spelled the way the allowance has to.
VENDOR_A = 'tests/test_vendor.py::test_a'
VENDOR_B = 'tests/test_vendor.py::test_b'


def _verdict(reports: tuple[StepReport, ...], log: Path) -> Verdict:
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
        assert 's' in PYTEST_ARGS[0]
        assert PYTEST_ARGS[0].startswith('-r')

    def test_pytest_is_asked_for_skips_that_carry_a_node_id(self) -> None:
        """THE OTHER HALF OF ``-rs``, AND IT IS A SEPARATE DECISION.

        MEASURED 2026-10-07 in the installed pytest: ``-rs`` FOLDS the skip summary, and the folded
        line -- ``SKIPPED [2] tests/test_vendor.py:31: needs the vendor`` -- groups skips by
        (file, line, reason). There is no node id in it to match, so every allowance keyed on that
        text is keyed on a LINE NUMBER. ``--no-fold-skipped`` is the documented option that turns
        the same summary into ``SKIPPED <node id> - <reason>``, and a node id is what does not move
        when an unrelated edit inserts five lines above a skip.
        """
        assert '--no-fold-skipped' in PYTEST_ARGS

    def test_a_declared_skip_lets_the_run_settle(self) -> None:
        assert read_pytest(SKIPPING, returncode=0, allowed_skips=(VENDOR,)).truncated == ()

    def test_an_undeclared_skip_truncates_and_is_named(self) -> None:
        """Forward side, and the remedy is printable: the message carries the strings to paste."""
        reasons = ' | '.join(read_pytest(SKIPPING, returncode=0).truncated)
        assert 'skipped and not declared' in reasons
        assert VENDOR_A in reasons
        assert VENDOR_B in reasons

    def test_a_declared_skip_that_did_not_happen_truncates_and_is_named(self) -> None:
        """The other side. Without it the list only ever grows, which is a waiver nothing uses."""
        allowed = (VENDOR, 'tests/test_retired.py::test_a')
        reasons = ' | '.join(read_pytest(SKIPPING, returncode=0, allowed_skips=allowed).truncated)
        assert 'declared in allowed_skips and NOT skipped' in reasons
        assert 'tests/test_retired.py::test_a' in reasons
        assert VENDOR not in reasons.split('NOT skipped')[1]

    def test_a_module_prefix_covers_every_node_in_it_and_a_node_id_pins_one(self) -> None:
        """ONE spelling, said twice: a module prefix covers every test in it, a node id pins one."""
        assert read_pytest(SKIPPING, returncode=0, allowed_skips=(VENDOR,)).truncated == ()
        assert read_pytest(SKIPPING, returncode=0, allowed_skips=(VENDOR_A, VENDOR_B)).truncated == ()
        pinned = ' | '.join(read_pytest(SKIPPING, returncode=0, allowed_skips=(VENDOR_A,)).truncated)
        named = pinned.split('allowed_skips:')[1].split('. A skip')[0].strip()
        assert named == VENDOR_B, 'a pin on one test leaves exactly the other one undeclared'

    def test_a_pin_survives_every_line_above_it_moving(self) -> None:
        """THE DEFECT, restated as the property that fixed it.

        MEASURED in consumer-b: a five-line comment inserted into a test file moved a skip from ``:101``
        to ``:106`` and silently invalidated a pin that had just been re-measured -- and the same
        list read 18 rows in one checkout, 20 in a second and 21 in a third. A node id is the name
        of the test, so the edit that moves the line cannot reach it.
        """
        moved = SKIPPING.replace('test_a', 'test_a')  # the node id is what pytest reports
        assert read_pytest(moved, returncode=0, allowed_skips=(VENDOR_A, VENDOR_B)).truncated == ()
        # And the SHAPE the folded summary prints is not silently read as a node id. It carries a
        # LINE and a bracket count, so no allowance can cover it and the naming floor is what says
        # so -- which is the loud half of the contract: a pytest that folded again would refuse,
        # never quietly re-key every declaration to a line number.
        folded = 'SKIPPED [2] tests/test_vendor.py:31: needs the vendor engine\n300 passed, 2 skipped in 9.0s\n'
        reasons = ' | '.join(read_pytest(folded, returncode=0, allowed_skips=(VENDOR,)).truncated)
        assert 'the short summary names 0' in reasons, (
            'a folded summary names no test, so it must refuse rather than match the bracket count'
        )

    def test_a_windows_spelled_node_id_matches_a_posix_declaration(self) -> None:
        r"""MEASURED 2026-09-16: the separator differs by platform.

        pytest prints ``tests\test_vendor.py`` on Windows and ``tests/...`` on Linux. One
        declaration is committed for both, so the comparison normalises -- otherwise the same repo
        settles on one box and truncates on the other, which is not a verdict.
        """
        windows = SKIPPING.replace('tests/test_vendor.py', 'tests\\test_vendor.py')
        assert read_pytest(windows, returncode=0, allowed_skips=(VENDOR,)).truncated == ()
        assert VENDOR_A in ' | '.join(read_pytest(windows, returncode=0).truncated)

    def test_a_line_a_test_printed_is_not_read_as_a_skip(self) -> None:
        """``-s`` IS IN THE FAMILY'S addopts: a test's own stdout lands in the same log.

        MEASURED in consumer-b's ``[tool.pytest.ini_options]``, which passes ``-s``. A pattern that
        took any line beginning with the word would read a printed report as an undeclared skip, and
        the run would refuse over a line nothing skipped. Every node id pytest builds names a ``.py``
        path, so the shape is asked for and the printed line fails it.
        """
        printed = 'SKIPPED three cases the vendor does not cover\n300 passed in 9.0s\n'
        reasons = read_pytest(printed, returncode=0, allowed_skips=()).truncated
        assert not any('skipped and not declared' in reason for reason in reasons), reasons

    def test_skips_that_were_counted_but_not_named_truncate(self) -> None:
        """The naming floor: an allowance cannot be checked against skips nobody reported."""
        reasons = ' | '.join(read_pytest(COUNTED_NOT_NAMED, returncode=0, allowed_skips=(VENDOR,)).truncated)
        assert 'the short summary names 0' in reasons
        assert '--no-fold-skipped' in reasons

    def test_the_ceiling_refuses_a_suite_that_skipped_itself_green(self) -> None:
        """An escape hatch needs a CEILING, not just a reason -- and this one is a ratio."""
        reasons = ' | '.join(read_pytest(MOSTLY_SKIPPED, returncode=0, allowed_skips=(VENDOR,)).truncated)
        assert f'above the {SKIP_CEILING:.0%} ceiling' in reasons


class TestTheVanishedSubjectArm:
    """THE ARM THE RUNTIME RATCHET CANNOT BE, and the sibling of ``_debt.COST_IS_CONDITIONAL``.

    consumer-b's own docstring names the shape and says why it has to exist: *"a reason for a marker
    nobody carries is a hole ... A declaration whose subject left must leave with it."*
    ``COST_IS_CONDITIONAL`` has that arm as a test of its own. ``allowed_skips`` did not, because a
    LOCATION cannot be checked without a run -- nothing but pytest knows which line a skip is
    reported at. A node id CAN be: it names a file and a test that either exist or do not.

    The measured harm this closes is consumer-b's own note -- an entry pinned at ``:39`` while the
    marker sat at ``:48``, an *"allowance for a location that no longer exists"*, and every verdict
    from a checkout with no clone reading INCONCLUSIVE until somebody re-measured by hand.
    """

    #: A planted test module, used as the SUBJECT every direction below is taken against.
    BODY: Final = (
        'import pytest\n\n\n'
        '@pytest.mark.skipif(True, reason="no vendor")\n'
        'def test_grey() -> None: ...\n\n\n'
        'class TestGroup:\n'
        '    def test_inside(self) -> None: ...\n'
    )

    def _tree(self, tmp_path: Path) -> Path:
        (tmp_path / 'tests' / 'unit').mkdir(parents=True)
        (tmp_path / 'tests' / 'unit' / 'test_vendor.py').write_text(self.BODY, encoding='utf-8')
        return tmp_path

    def test_a_declaration_whose_file_is_gone_is_refused(self, tmp_path: Path) -> None:
        root = self._tree(tmp_path)
        (root / 'tests' / 'unit' / 'test_vendor.py').unlink()
        assert stale_declarations(root, (VENDOR_A,)) == (VENDOR_A,)

    def test_a_declaration_whose_test_is_gone_is_refused(self, tmp_path: Path) -> None:
        """The half a file check alone cannot see: the file is there and the subject is not."""
        root = self._tree(tmp_path)
        assert stale_declarations(root, ('tests/unit/test_vendor.py::test_deleted',)) == (
            'tests/unit/test_vendor.py::test_deleted',
        )

    def test_a_declaration_whose_subject_is_there_is_not_refused(self, tmp_path: Path) -> None:
        """THE OTHER DIRECTION, or an arm that refuses everything passes the two tests above."""
        root = self._tree(tmp_path)
        live = (
            'tests/unit/test_vendor.py',
            'tests/unit/test_vendor.py::test_grey',
            'tests/unit/test_vendor.py::test_grey[one-1]',
            'tests/unit/test_vendor.py::TestGroup::test_inside',
        )
        assert stale_declarations(root, live) == ()

    def test_a_declaration_that_reaches_outside_the_checkout_is_refused(self, tmp_path: Path) -> None:
        """An allowance is written by the repo it governs and names nothing outside it."""
        root = self._tree(tmp_path)
        outside = tmp_path / 'outside.py'
        outside.write_text('def test_a() -> None: ...\n', encoding='utf-8')
        assert stale_declarations(root, ('../outside.py::test_a',)) == ('../outside.py::test_a',)

    def test_the_arm_needs_no_run_at_all(self, tmp_path: Path) -> None:
        """It reads the tree, which is why it binds on an invocation that selected one test.

        ``_skip_shortfall``'s stale arm is gated on a COMPLETE suite census -- a selected run cannot
        judge another test's allowance retired -- so without this the hole is open on every targeted
        invocation, which is most of them.
        """
        root = self._tree(tmp_path)
        assert read_pytest(SKIPPING, returncode=0, allowed_skips=(), complete_skip_census=False).truncated != ()
        assert stale_declarations(root, ()) == ()


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
        """NOT an empty set.

        A declaration nobody could parse exempts nothing while its author believes it exempted
        everything -- and the author never finds out, because the tool is
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
        """THE CONTROL FOR THE STREAMING DEFECT, MEASURED 2026-09-16 on consumer-b.

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
    @pytest.mark.parametrize(
        ('selection', 'output', 'expected'),
        [
            (
                ('tests/test_selected.py::test_a', 'tests/test_selected.py::test_b', 'tests/test_selected.py::test_c'),
                '3 passed in 0.1s\n',
                Outcome.PASS,
            ),
            (
                ('tests/test_selected.py::test_a',),
                'SKIPPED tests/test_selected.py::test_a - unavailable\n20 passed, 1 skipped in 0.1s\n',
                Outcome.INCONCLUSIVE,
            ),
            ((), '3 passed in 0.1s\n', Outcome.INCONCLUSIVE),
            (('-v',), '3 passed in 0.1s\n', Outcome.INCONCLUSIVE),
            (('-k', 'selected'), '3 passed in 0.1s\n', Outcome.PASS),
            (('-m', 'selected'), '3 passed in 0.1s\n', Outcome.PASS),
            (('--deselect', 'tests/test_other.py'), '3 passed in 0.1s\n', Outcome.PASS),
            (('--deselect=tests/test_other.py',), '3 passed in 0.1s\n', Outcome.PASS),
            (('--unknown-selection',), '3 passed in 0.1s\n', Outcome.INCONCLUSIVE),
        ],
        ids=[
            'three-nodes-not-a-global-census',
            'scoped-undeclared-skip',
            'full-stale',
            'verbose-is-still-full',
            'keyword-scope',
            'marker-scope',
            'deselect-scope',
            'inline-deselect-scope',
            'unknown-scope-refuses',
        ],
    )
    def test_verify_judges_skip_retirement_only_from_a_complete_census(
        self, tmp_path, monkeypatch, selection, output, expected
    ) -> None:
        """Drive the real runner/parser boundary; only process execution is a recorded-output double.

        The three-node selection reproduces the WDG 2026-10-05 raw-three-pass refusal. Another
        file's declaration cannot be called retired by a run that never selected it. Conversely,
        narrowing the selection cannot admit an observed undeclared skip, and a display flag
        cannot disable the full-suite reverse ratchet.
        """
        subprocess.run(
            [shutil.which('git') or 'git', 'init', '-q', str(tmp_path)],
            check=True,
            capture_output=True,
            timeout=60,
        )
        (tmp_path / 'pyproject.toml').write_text(
            '[tool.lab_commons.verify]\nallowed_skips = ["tests/test_other.py"]\n', encoding='utf-8'
        )
        # THE DECLARED SUBJECT IS PLANTED, because `stale_declarations` refuses one whose file is gone
        # before any step launches -- and this control is about the SCOPE of the runtime ratchet, not
        # about a vanished subject. Left unplanted, every case below would truncate for the same
        # unrelated reason and the parameterisation would stop distinguishing anything.
        (tmp_path / 'tests').mkdir()
        (tmp_path / 'tests' / 'test_other.py').write_text('def test_a() -> None: ...\n', encoding='utf-8')
        commands = []

        def no_seat(_stack, _what, **_kwargs: object) -> None:
            return None

        def recorded_step(command, *, cwd, handle, extra_env=None) -> int:
            assert cwd == tmp_path
            commands.append(tuple(command))
            if 'pytest' in command:
                assert extra_env is not None
            text = output if 'pytest' in command else 'All checks passed!\n'
            handle.write(text)
            handle.flush()
            return 0

        monkeypatch.setattr(verify, 'hold_the_box', no_seat)
        monkeypatch.setattr(verify, '_tee', recorded_step)
        verdict = verify.run_verify(tmp_path, selection)
        expected_command = (sys.executable, '-m', 'pytest', *PYTEST_ARGS, *LEDGER_PLUGIN, *verify.OUTCOME_PLUGIN)
        assert commands[-1] == (*expected_command, *selection)
        assert verdict.selector.spec == ' '.join(('verify', *selection))
        assert verdict.result.outcome is expected
        if selection == ('--unknown-selection',):
            assert 'cannot establish skip census scope' in verdict.result.reason
        elif selection and selection != ('-v',) and expected is Outcome.INCONCLUSIVE:
            assert 'not declared' in verdict.result.reason
        if not selection or selection == ('-v',):
            assert 'NOT skipped' in verdict.result.reason

    def test_a_declaration_whose_subject_left_refuses_before_anything_launches(self, tmp_path, monkeypatch) -> None:
        """THE WIRING, AND IT IS THE HALF THAT MAKES `stale_declarations` MORE THAN A READER.

        Driven through the REAL ``run_verify``: a checkout whose only declaration names a test that
        is not there must refuse, and it must refuse WITHOUT the pytest step having run -- that is
        the whole difference between this arm and the runtime ratchet, which needs a complete suite
        census and a completed run to say anything at all.
        """
        subprocess.run(
            [shutil.which('git') or 'git', 'init', '-q', str(tmp_path)],
            check=True,
            capture_output=True,
            timeout=60,
        )
        (tmp_path / 'pyproject.toml').write_text(
            '[tool.lab_commons.verify]\nallowed_skips = ["tests/test_gone.py::test_vanished"]\n', encoding='utf-8'
        )
        launched: list[tuple[str, ...]] = []

        def recorded_step(command, *, cwd, handle, extra_env=None) -> int:
            assert cwd == tmp_path
            launched.append(tuple(command))
            if 'pytest' in command:
                assert extra_env is not None
            handle.write('1 passed in 0.1s\n')
            handle.flush()
            return 0

        monkeypatch.setattr(verify, 'hold_the_box', lambda _stack, _what, **_kwargs: None)
        monkeypatch.setattr(verify, '_tee', recorded_step)
        verdict = verify.run_verify(tmp_path)
        assert verdict.result.outcome is Outcome.INCONCLUSIVE
        assert 'tests/test_gone.py::test_vanished' in verdict.result.reason
        assert 'allowed_skips' in verdict.result.reason
        pytest_step = [command for command in launched if 'pytest' in command]
        assert pytest_step, 'the run must still have reached pytest -- the refusal is added, not an early exit'

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
        consumer-c before the fix: `2 failed, 130 passed` read as `the summary names 2 failure(s)
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


class TestTheTeeOnAConsoleThatCannotCarryTheCharacter:
    """THE WHOLE CHAIN, planted: a child's character must not cost the run its verdict.

    THE REPRODUCTION, 2026-09-18. A consumer-b verify died with
    ``UnicodeEncodeError: 'charmap' codec can't encode character '\u2713'`` inside
    ``_tee -> lab_commons.log.emit``, on a cp1252 stdout. The run then had no verdict AND no log --
    the one state ``workflow.md`` says proves nothing. ``TestEmitOnAConsoleThatCannotCarryTheCharacter``
    in ``test_log.py`` controls the writer; this controls the PLUMBING around it, with a real child
    process, because that is where the character enters.

    IT ALSO PINS THE TWO PROMISES APART, which is the substantive claim of the fix. The LOG is
    opened utf-8 and keeps the character byte for byte -- it is the evidence a ``log=sha256:...``
    citation is re-read from. The CONSOLE is a VIEW of that log and may lose a glyph to ``?``. Only
    one of the two is evidence, so only one of them has to be lossless.
    """

    def test_a_planted_non_cp1252_character_leaves_a_verdict_and_a_lossless_log(self, tmp_path: Path) -> None:
        script = tmp_path / 'loud_step.py'
        script.write_text("print('spinner \u2713 done')\n", encoding='utf-8')
        log = tmp_path / 'log.txt'
        console = io.TextIOWrapper(io.BytesIO(), encoding='cp1252', newline='')

        with log.open('w', encoding='utf-8') as handle, contextlib.redirect_stdout(console):
            code = tee_step([sys.executable, str(script)], cwd=tmp_path, handle=handle)

        assert code == 0, 'the step must still report its own exit code rather than dying in the tee'
        assert 'spinner ✓ done' in log.read_text(encoding='utf-8'), 'the evidence keeps every byte'
        assert b'spinner ? done' in console.buffer.getvalue(), 'the view degrades, in the place it degraded'


class TestTheTeeOnAColouredStep:
    r"""THE WHOLE CHAIN, planted: a coloured FAIL must stay a FAIL, and nothing else may change.

    THE REPRODUCTION, 2026-09-18, driven through the REAL reader. ``read_pytest`` over a short
    summary whose ``FAILED`` carries pytest's own ``--color=yes`` escapes answered
    ``truncated=('the summary names 1 failure(s) and the output names 0 node id(s)...',)`` -- a
    genuine red arriving as an INCONCLUSIVE, because ``_FAILED_NODE`` is anchored at ``^FAILED``
    and ``\x1b[31mFAILED`` does not start there. That is every red in every repo which colours its
    output, and the direction is SAFE, which is why it went unnoticed. ``_tee`` now strips CSI, so
    the log, the console and the parser all read ONE text.

    THREE DIRECTIONS, and the second and third are what make the first mean anything: the coloured
    line must be caught, a PLAIN line must still come through byte for byte, and a line holding a
    literal ``ESC`` that is not a CSI sequence must not be mangled by a pattern that eats
    "anything after an ESC".
    """

    #: The exact bytes pytest prints for a failure under ``--color=yes`` -- MEASURED 2026-09-18 with
    #: ``FORCE_COLOR=1`` on this box rather than hand-written. The node id is ITSELF wrapped, which is
    #: why loosening the anchor would have produced a FAIL naming a test that does not exist.
    COLOURED = (
        '\x1b[31mFAILED\x1b[0m test_c.py::\x1b[1mtest_a\x1b[0m - assert 0\n'
        '\x1b[31m==== \x1b[31m\x1b[1m1 failed\x1b[0m, \x1b[32m1 passed\x1b[0m\x1b[31m in 0.3s\x1b[0m ====\n'
    )

    #: The same run with no colour at all: what the log has always held, and what must not move.
    PLAIN = 'FAILED test_c.py::test_a - assert 0\n==== 1 failed, 1 passed in 0.3s ====\n'

    def _teed(self, tmp_path: Path, text: str) -> str:
        """Drive the REAL ``_tee`` over a real child printing *text*, and answer what the LOG holds."""
        script = tmp_path / 'coloured_step.py'
        script.write_text(f'import sys\nsys.stdout.write({text!r})\n', encoding='utf-8')
        log = tmp_path / 'log.txt'
        with log.open('w', encoding='utf-8') as handle, contextlib.redirect_stdout(io.StringIO()):
            assert tee_step([sys.executable, str(script)], cwd=tmp_path, handle=handle) == 0
        return log.read_text(encoding='utf-8')

    def test_the_parser_reads_a_raw_coloured_red_as_a_refusal(self) -> None:
        """THE FLOOR: the defect is real AT THE PARSER, so stripping upstream is not a no-op."""
        assert read_pytest(self.PLAIN, returncode=1).failures == ('test_c.py::test_a',)
        assert read_pytest(self.COLOURED, returncode=1).truncated != (), (
            'if the raw coloured text already parsed cleanly there would be nothing here to fix, and '
            'every assertion below would pass for the wrong reason'
        )

    def test_a_planted_coloured_failure_is_named_after_the_tee(self, tmp_path: Path) -> None:
        """DIRECTION ONE: through the real plumbing the red is a red, and it NAMES its node id."""
        report = read_pytest(self._teed(tmp_path, self.COLOURED), returncode=1)
        assert report.truncated == (), f'a coloured red must settle as a FAIL, not truncate: {report.truncated}'
        assert report.failures == ('test_c.py::test_a',), 'and the node id must be the one that failed, unwrapped'

    def test_a_plain_step_is_teed_byte_for_byte(self, tmp_path: Path) -> None:
        """DIRECTION TWO, and without it a lossy re-encode would have passed direction one.

        The log is the citable evidence. A fix that reached every line and changed ANY of them would
        rewrite what four repos' ``log=sha256:...@lines`` citations are re-read from.
        """
        banner = f'$ {sys.executable} {tmp_path / "coloured_step.py"}\n'
        assert self._teed(tmp_path, self.PLAIN) == banner + self.PLAIN

    def test_a_literal_escape_in_legitimate_content_survives(self, tmp_path: Path) -> None:
        r"""DIRECTION THREE: CSI is a GRAMMAR, and a lone ESC is content rather than a sequence.

        A test asserting on ``\x1b`` -- this repo has one for the console writer -- prints it, and a
        pattern eating "ESC and then whatever" would silently delete the rest of that line from the
        evidence. The carriage return is in the same plant: universal-newline translation splits it
        into lines, which is ugly and never fatal, and that behaviour predates this fix.
        """
        content = "FAILED t.py::test_esc - AssertionError: assert '\x1b' == '\x1bnot a csi'\n"
        assert self._teed(tmp_path, content).endswith(content), 'a lone ESC is not a CSI sequence and is not eaten'
        teed = self._teed(tmp_path, 'progress 1\rprogress 2\ndone\n')
        assert 'progress 1' in teed, 'a bare CR still splits into lines rather than being swallowed'
        assert 'progress 2' in teed
        assert 'done' in teed


def _judged(tmp_path: Path) -> Verdict:
    log = tmp_path / 'judged.log'
    log.write_text('ran\n', encoding='utf-8')
    report = StepReport(name='hooks', reported=('hooks',), failures=())
    return build_verdict((report,), tree='sha256:' + 'b' * 64, env='env:1', spec='verify', log=LogRef.of(log))


def _patched_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, heads: list[str], dirt: list[tuple[str, ...]]
) -> list:
    """Drive ``main`` with the run and the git readings replaced, recording what reaches ``publish``."""
    posted: list = []
    monkeypatch.setattr(verify, 'project_root', lambda: tmp_path)
    monkeypatch.setattr(verify, 'box_directory', lambda: tmp_path / 'inflight')
    monkeypatch.setattr(verify, 'ledger_path', lambda _root: tmp_path / 'ledger.jsonl')
    monkeypatch.setattr(verify, 'run_verify', lambda *_a, **_k: _judged(tmp_path))
    monkeypatch.setattr(verify, 'head_sha', lambda _root: heads.pop(0))
    monkeypatch.setattr(verify, 'status_paths', lambda _root: dirt.pop(0))
    monkeypatch.setattr(
        verify, 'publish', lambda _root, v, *, context, commit: posted.append((v, context, commit)) or 'status: x'
    )
    assert verify.main([]) == EXIT_CODES[Outcome.PASS]
    return posted


def test_a_judged_run_on_a_clean_unmoved_tree_publishes_lab_gate_on_head(monkeypatch, tmp_path: Path) -> None:
    posted = _patched_main(monkeypatch, tmp_path, heads=['a' * 40, 'a' * 40], dirt=[(), ()])
    assert [(context, commit) for _v, context, commit in posted] == [('lab/gate', 'a' * 40)]


def test_a_dirty_tree_publishes_on_no_commit_and_keeps_the_exit_code(monkeypatch, tmp_path: Path) -> None:
    posted = _patched_main(monkeypatch, tmp_path, heads=['a' * 40, 'a' * 40], dirt=[('M src/x.py',), ('M src/x.py',)])
    assert [commit for _v, _c, commit in posted] == [None]


def test_every_verify_run_loads_the_durations_ledger_plugin() -> None:
    """A targeted run records too: the ledger is a plugin verify passes, not a conftest binding."""
    assert LEDGER_PLUGIN == ('-p', 'lab_commons.dev.durations')


def test_a_duplicate_verify_attaches_to_the_run_in_flight_and_never_runs(monkeypatch, tmp_path: Path) -> None:
    """THE 95-OF-98 PATTERN: a second verify of the same key reads the leader's answer and runs nothing."""
    root, box = tmp_path / 'root', tmp_path / 'inflight'
    root.mkdir()
    box.mkdir()
    monkeypatch.setattr(verify, 'project_root', lambda: root)
    monkeypatch.setattr(verify, 'box_directory', lambda: box)
    monkeypatch.setattr(verify, 'ledger_path', lambda _root: tmp_path / 'ledger.jsonl')
    monkeypatch.setattr(verify, 'run_verify', lambda *_a, **_k: pytest.fail('the duplicate ran the suite'))
    key = verify.run_key(root, ('tests/a.py',))
    claim_path(box, key).write_text(json.dumps({'pid': os.getpid(), 'run': 'r1'}), encoding='utf-8')
    answer = {'code': EXIT_CODES[Outcome.FAIL], 'lines': ['[verdict] result=fail', 'verify: fail (1 failed)']}
    (box / f'{key.digest()}.r1.result').write_text(json.dumps(answer), encoding='utf-8')
    assert verify.main(['--no-status', 'tests/a.py']) == EXIT_CODES[Outcome.FAIL]


def test_the_run_key_is_the_tree_the_env_and_the_selection(tmp_path: Path) -> None:
    """Two selections are two runs; the same selection on the same tree is one."""
    assert verify.run_key(tmp_path, ('a',)) == verify.run_key(tmp_path, ('a',))
    assert verify.run_key(tmp_path, ('a',)) != verify.run_key(tmp_path, ('b',))


def _ledgered(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Route ``main`` at a planted root, inflight directory and ledger; returns the ledger path."""
    ledger = tmp_path / 'ledger.jsonl'
    monkeypatch.setattr(verify, 'project_root', lambda: tmp_path)
    monkeypatch.setattr(verify, 'box_directory', lambda: tmp_path / 'inflight')
    monkeypatch.setattr(verify, 'ledger_path', lambda _root: ledger)
    monkeypatch.setattr(verify, 'head_sha', lambda _root: 'a' * 40)
    monkeypatch.setattr(verify, 'status_paths', lambda _root: ())
    return ledger


def test_a_selection_the_ledger_already_judged_is_cited_and_not_run(monkeypatch, tmp_path: Path) -> None:
    """THE LOOKUP BEFORE THE RUN: a recorded FAIL on this key is the answer, and nothing runs."""
    ledger = _ledgered(monkeypatch, tmp_path)
    monkeypatch.setattr(verify, 'run_verify', lambda *_a, **_k: pytest.fail('a judged selection ran again'))
    key = verify.run_key(tmp_path, ('tests/a.py',))
    entry = Entry(key.tree, key.env, run_test_id(key.selector), 'FAIL', tier='verify', commit='', log='x.log')
    record(ledger, [entry])
    assert verify.main(['--no-status', 'tests/a.py']) == EXIT_CODES[Outcome.FAIL]


def test_rerun_ignores_the_ledger(monkeypatch, tmp_path: Path) -> None:
    ledger = _ledgered(monkeypatch, tmp_path)
    key = verify.run_key(tmp_path, ())
    record(ledger, [Entry(key.tree, key.env, run_test_id(key.selector), 'FAIL', tier='verify', commit='', log='x')])
    monkeypatch.setattr(verify, 'run_verify', lambda *_a, **_k: _judged(tmp_path))
    assert verify.main(['--no-status', '--rerun']) == EXIT_CODES[Outcome.PASS]


def test_a_promoted_run_records_itself_and_every_test_outcome(monkeypatch, tmp_path: Path) -> None:
    """The ONE writer: after promotion, the run's key and each node id's outcome enter the ledger."""
    ledger = _ledgered(monkeypatch, tmp_path)
    judged = _judged(tmp_path)
    outcomes = outcomes_dir(judged.log.path)
    outcomes.mkdir()
    (outcomes / 'outcomes.json').write_text(json.dumps({'tests/a.py::t': 'PASS'}), encoding='utf-8')
    monkeypatch.setattr(verify, 'run_verify', lambda *_a, **_k: judged)
    assert verify.main(['--no-status']) == EXIT_CODES[Outcome.PASS]
    key = verify.run_key(tmp_path, ())
    recorded = {(row.test, row.result, row.commit) for row in entries(ledger)}
    assert recorded == {(run_test_id(key.selector), 'PASS', 'a' * 40), ('tests/a.py::t', 'PASS', 'a' * 40)}
    assert {row.tree for row in entries(ledger)} == {key.tree}


def test_an_inconclusive_run_records_nothing(monkeypatch, tmp_path: Path) -> None:
    """PLANTED: nobody-knows never enters the ledger, so it can never be cited."""
    ledger = _ledgered(monkeypatch, tmp_path)
    log = tmp_path / 'cut.log'
    log.write_text('ran\n', encoding='utf-8')
    cut = StepReport(name='pytest', reported=(), failures=(), truncated=('the wall fired',))
    verdict = build_verdict((cut,), tree='sha256:' + 'b' * 64, env='env:1', spec='verify', log=LogRef.of(log))
    monkeypatch.setattr(verify, 'run_verify', lambda *_a, **_k: verdict)
    assert verify.main(['--no-status']) == EXIT_CODES[Outcome.INCONCLUSIVE]
    assert entries(ledger) == ()
