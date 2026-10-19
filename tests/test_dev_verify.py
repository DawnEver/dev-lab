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
from types import SimpleNamespace
from typing import Final

import pytest
from _box_fake import ended

from lab_commons import box
from lab_commons.box import BOX_ENV, CPU_ENV, GB, INSIDE_ENV, Capacity, Demand, Refused, hold, write_ended
from lab_commons.compute import learned
from lab_commons.compute.model import Resources
from lab_commons.dev import forgerequest, localpart, platformparts, verify, verifybox
from lab_commons.dev.inflight import seat
from lab_commons.dev.logref import LogRef, UnverifiableLog, verify_log
from lab_commons.dev.platformparts import part_context, part_of
from lab_commons.dev.producer import PRODUCING_VAR, ProducerExit, producing
from lab_commons.dev.reports import (
    SKIP_CEILING,
    MalformedAllowance,
    StepReport,
    declared_skips,
    read_pytest,
    read_ruff,
    stale_declarations,
)
from lab_commons.dev.runcache import CachedRun, record, runs
from lab_commons.dev.verdict import Verdict
from lab_commons.dev.verify import EXIT_CODES, LEDGER_PLUGIN, PYTEST_ARGS, build_verdict, project_root
from lab_commons.dev.verify import _tee as tee_step
from lab_commons.hpc.needsets import BASE, Vocabulary
from lab_commons.hpc.records import read_record
from lab_commons.hpc.testcells import TestCell
from lab_commons.outcomes import Cell, Conclusion, Record, Status

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


@pytest.fixture(autouse=True)
def _fresh_family(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every ``main`` here judges a planted run, never this box's forge: the family check is its own file."""
    monkeypatch.setattr(verify, 'lock_freshness', lambda _root: None)


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
        assert verdict.result.outcome is Conclusion.PASS
        assert EXIT_CODES[verdict.result.outcome] == 0

    def test_a_failing_suite_fails_with_its_failures_named(self, log: Path) -> None:
        reports = (
            read_ruff('ruff check .', 0),
            read_ruff('ruff format --check .', 0),
            read_pytest(FAILING, returncode=1),
        )
        verdict = _verdict(reports, log)
        assert verdict.result.outcome is Conclusion.FAIL
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
        assert verdict.result.outcome is Conclusion.INCONCLUSIVE
        assert 'pytest' in verdict.result.reason, 'the silent step must be named, not counted'
        assert EXIT_CODES[verdict.result.outcome] == 3, 'the producer contract: 2 is a refused argv'
        assert EXIT_CODES[Conclusion.FAIL] != EXIT_CODES[Conclusion.INCONCLUSIVE], 'the two remedies differ'

    def test_a_step_that_never_launched_is_silent_by_name(self, log: Path) -> None:
        """``selected`` comes from the step NAMES, which is the only way ``silent`` means anything."""
        reports = (
            read_ruff('ruff check .', 0),
            StepReport(name='ruff format --check .'),
            read_pytest(CLEAN, returncode=0),
        )
        verdict = _verdict(reports, log)
        assert verdict.result.outcome is Conclusion.INCONCLUSIVE
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
                Conclusion.PASS,
            ),
            (
                ('tests/test_selected.py::test_a',),
                'SKIPPED tests/test_selected.py::test_a - unavailable\n20 passed, 1 skipped in 0.1s\n',
                Conclusion.INCONCLUSIVE,
            ),
            ((), '3 passed in 0.1s\n', Conclusion.INCONCLUSIVE),
            (('-v',), '3 passed in 0.1s\n', Conclusion.INCONCLUSIVE),
            (('-k', 'selected'), '3 passed in 0.1s\n', Conclusion.PASS),
            (('-m', 'selected'), '3 passed in 0.1s\n', Conclusion.PASS),
            (('--deselect', 'tests/test_other.py'), '3 passed in 0.1s\n', Conclusion.PASS),
            (('--deselect=tests/test_other.py',), '3 passed in 0.1s\n', Conclusion.PASS),
            (('--unknown-selection',), '3 passed in 0.1s\n', Conclusion.INCONCLUSIVE),
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

        def recorded_step(command, *, cwd, handle, extra_env=None) -> int:
            assert cwd == tmp_path
            commands.append(tuple(command))
            if 'pytest' in command:
                assert extra_env is not None
            text = output if 'pytest' in command else 'All checks passed!\n'
            handle.write(text)
            handle.flush()
            return 0

        monkeypatch.setattr(verify, 'boxed', _unboxed)
        monkeypatch.setattr(verify, '_tee', recorded_step)
        verdict = verify.run_verify(tmp_path, selection)
        expected_command = (sys.executable, '-m', 'pytest', *PYTEST_ARGS, *LEDGER_PLUGIN, *verify.OUTCOME_PLUGIN)
        assert commands[-1] == (*expected_command, *selection)
        assert verdict.selector.spec == ' '.join(('verify', *selection))
        assert verdict.result.outcome is expected
        if selection == ('--unknown-selection',):
            assert 'cannot establish skip census scope' in verdict.result.reason
        elif selection and selection != ('-v',) and expected is Conclusion.INCONCLUSIVE:
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

        monkeypatch.setattr(verify, 'boxed', _unboxed)
        monkeypatch.setattr(verify, '_tee', recorded_step)
        verdict = verify.run_verify(tmp_path)
        assert verdict.result.outcome is Conclusion.INCONCLUSIVE
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
        assert _verdict(clean, log).result.outcome is Conclusion.PASS
        planted = (*clean, StepReport(name='a step that never launched'))
        assert _verdict(planted, log).result.outcome is Conclusion.INCONCLUSIVE


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


@pytest.fixture(autouse=True)
def _as_the_producer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Most tests here drive a FULL run, which only a producer ``forge serve`` spawned may take."""
    for name, value in producing(part_context(BASE), 'a' * 40).items():
        monkeypatch.setenv(name, value)


def test_a_full_run_outside_a_producer_is_refused_with_the_remedy(monkeypatch, tmp_path: Path, capsys) -> None:
    """VERDICTS-FROM-THE-FORGE: no claim, no full suite -- refused before anything runs or waits."""
    _cached(monkeypatch, tmp_path)
    monkeypatch.delenv(PRODUCING_VAR)
    monkeypatch.setattr(verify, 'run_verify', lambda *_a, **_k: pytest.fail('a full suite ran outside a producer'))
    assert verify.main(['--', '-q']) == ProducerExit.USAGE
    assert 'push; the forge produces the part' in capsys.readouterr().err


def test_a_selection_is_a_measure_needs_no_claim_and_waits_briefly(monkeypatch, tmp_path: Path) -> None:
    """THE CONTROL: a named path runs without a claim, on the short measure wait, never the producer's."""
    _cached(monkeypatch, tmp_path)
    monkeypatch.delenv(PRODUCING_VAR)
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests' / 'a.py').write_text('', encoding='utf-8')
    waits: list[float] = []
    monkeypatch.setattr(verify, 'run_verify', lambda *_a, wait_s, **_k: waits.append(wait_s) or _judged(tmp_path))
    assert verify.main(['--rerun', 'tests/a.py::test_x']) == ProducerExit.PASS
    assert waits == [verifybox.MEASURE_WAIT_S]


def test_only_an_argument_naming_the_tree_makes_a_run_targeted(tmp_path: Path) -> None:
    (tmp_path / 'tests').mkdir()
    assert verify.is_targeted(tmp_path, ('tests',))
    assert not verify.is_targeted(tmp_path, ('-k', 'tests_that_do_not_exist')), '-k narrows a full collection'
    assert not verify.is_targeted(tmp_path, ('-k', 'tests')), 'an option VALUE that happens to be a path'
    assert verify.is_targeted(tmp_path, ('-k', 'x', 'tests'))
    assert not verify.is_targeted(tmp_path, ('missing.py',))
    assert not verify.is_targeted(tmp_path, ())


def _judged(tmp_path: Path) -> Verdict:
    log = tmp_path / 'judged.log'
    log.write_text('ran\n', encoding='utf-8')
    report = StepReport(name='hooks', reported=('hooks',), failures=())
    return build_verdict((report,), tree='sha256:' + 'b' * 64, env='env:1', spec='verify', log=LogRef.of(log))


def _patched_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, heads: list[str], dirt: list[tuple[str, ...]]
) -> list:
    """Drive ``main`` with the run and the git readings replaced, recording what reaches the status queue."""
    posted: list = []
    (tmp_path / 'pyproject.toml').write_text('[tool.lab_commons.parts]\noutput = "out"\n', encoding='utf-8')
    monkeypatch.setattr(verify, 'project_root', lambda: tmp_path)
    monkeypatch.setattr(verify, 'box_directory', lambda: tmp_path / 'inflight')
    monkeypatch.setattr(verify, 'cache_path', lambda _root: tmp_path / 'runs.jsonl')
    monkeypatch.setattr(verify, 'run_verify', lambda *_a, **_k: _judged(tmp_path))
    monkeypatch.setattr(verify, 'head_sha', lambda _root: heads.pop(0))
    monkeypatch.setattr(verify, 'status_paths', lambda _root: dirt.pop(0))
    monkeypatch.setattr(localpart, 'read_cells', lambda _judged: ({'t::a': TestCell(Cell(Status.OK))}, frozenset()))
    monkeypatch.setattr(localpart, 'owners', lambda _root, _sha, reported, _collect: dict.fromkeys(reported, BASE))
    monkeypatch.setattr(localpart, 'present_here', lambda _root: frozenset({'windows'}))
    monkeypatch.setattr(localpart, 'local_record', lambda **fields: fields)
    monkeypatch.setattr(localpart, 'post_local', lambda _root, record, _directory: posted.append(record) or 'posted')
    assert verify.main([]) == EXIT_CODES[Conclusion.PASS]
    return posted


def test_a_judged_clean_run_posts_its_base_part_on_head(monkeypatch, tmp_path: Path) -> None:
    posted = _patched_main(monkeypatch, tmp_path, heads=['a' * 40, 'a' * 40], dirt=[(), ()])
    assert [(record['sha'], record['part'], record['scope']) for record in posted] == [('a' * 40, BASE, 'full')]


def test_a_dirty_tree_queues_nothing_and_keeps_the_exit_code(monkeypatch, tmp_path: Path) -> None:
    posted = _patched_main(monkeypatch, tmp_path, heads=['a' * 40, 'a' * 40], dirt=[('M src/x.py',), ('M src/x.py',)])
    assert posted == []


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
    monkeypatch.setattr(verify, 'cache_path', lambda _root: tmp_path / 'runs.jsonl')
    monkeypatch.setattr(verify, 'run_verify', lambda *_a, **_k: pytest.fail('the duplicate ran the suite'))
    key = verify.run_key(root, ('tests/a.py',))
    answer = {'code': EXIT_CODES[Conclusion.FAIL], 'lines': ['[verdict] result=fail', 'verify: fail (1 failed)']}
    (box / f'{key.digest()}.r1.result').write_text(json.dumps(answer), encoding='utf-8')
    with hold(Demand(0, 0, 60, {seat(key): 1}), 'leader', 1, key=f'{seat(key)}:r1'):
        assert verify.main(['tests/a.py']) == EXIT_CODES[Conclusion.FAIL]


def test_the_run_key_is_the_tree_the_env_and_the_selection(tmp_path: Path) -> None:
    """Two selections are two runs; the same selection on the same tree is one."""
    assert verify.run_key(tmp_path, ('a',)) == verify.run_key(tmp_path, ('a',))
    assert verify.run_key(tmp_path, ('a',)) != verify.run_key(tmp_path, ('b',))


def _cached(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Route ``main`` at a planted root, inflight directory and run cache; returns the cache path."""
    cache = tmp_path / 'runs.jsonl'
    monkeypatch.setattr(verify, 'project_root', lambda: tmp_path)
    monkeypatch.setattr(verify, 'box_directory', lambda: tmp_path / 'inflight')
    monkeypatch.setattr(verify, 'cache_path', lambda _root: cache)
    monkeypatch.setattr(verify, 'head_sha', lambda _root: 'a' * 40)
    monkeypatch.setattr(verify, 'status_paths', lambda _root: ())
    return cache


def _unposted(monkeypatch: pytest.MonkeyPatch) -> None:
    """A producer's run whose posting is not the subject: both doors to the forge answer without a call."""
    monkeypatch.setattr(verify, 'post_part', lambda *_a, **_k: 'posted')
    monkeypatch.setattr(verify, 'post_cited', lambda *_a, **_k: 'posted')


def _plant(cache: Path, key: verify.RunKey, result: str) -> None:
    record(cache, CachedRun(key.tree, key.env, key.selector, result, '', 'x.log'))


def test_a_selection_the_cache_already_judged_is_cited_and_not_run(monkeypatch, tmp_path: Path) -> None:
    """THE LOOKUP BEFORE THE RUN: a cached FAIL on this key is the answer, and nothing runs."""
    _unposted(monkeypatch)
    cache = _cached(monkeypatch, tmp_path)
    monkeypatch.setattr(verify, 'run_verify', lambda *_a, **_k: pytest.fail('a judged selection ran again'))
    _plant(cache, verify.run_key(tmp_path, ('tests/a.py',)), 'FAIL')
    assert verify.main(['tests/a.py']) == EXIT_CODES[Conclusion.FAIL]


def test_rerun_ignores_the_cache(monkeypatch, tmp_path: Path) -> None:
    _unposted(monkeypatch)
    cache = _cached(monkeypatch, tmp_path)
    _plant(cache, verify.run_key(tmp_path, ()), 'FAIL')
    monkeypatch.setattr(verify, 'run_verify', lambda *_a, **_k: _judged(tmp_path))
    assert verify.main(['--rerun']) == EXIT_CODES[Conclusion.PASS]


def test_a_promoted_run_is_cached_with_its_commit(monkeypatch, tmp_path: Path) -> None:
    """The one writer: after promotion, the run's key, result and commit enter the cache."""
    _unposted(monkeypatch)
    cache = _cached(monkeypatch, tmp_path)
    monkeypatch.setattr(verify, 'run_verify', lambda *_a, **_k: _judged(tmp_path))
    assert verify.main([]) == EXIT_CODES[Conclusion.PASS]
    key = verify.run_key(tmp_path, ())
    assert [(run.tree, run.selector, run.result, run.commit) for run in runs(cache)] == [
        (key.tree, key.selector, 'PASS', 'a' * 40)
    ]


def test_an_inconclusive_run_is_not_cached_and_posts_no_part(monkeypatch, tmp_path: Path) -> None:
    """PLANTED: nobody-knows never enters the cache, so it can never be cited, and is no part."""
    cache = _cached(monkeypatch, tmp_path)
    log = tmp_path / 'cut.log'
    log.write_text('ran\n', encoding='utf-8')
    cut = StepReport(name='pytest', reported=(), failures=(), truncated=('the wall fired',))
    verdict = build_verdict((cut,), tree='sha256:' + 'b' * 64, env='env:1', spec='verify', log=LogRef.of(log))
    monkeypatch.setattr(verify, 'run_verify', lambda *_a, **_k: verdict)
    assert verify.main([]) == EXIT_CODES[Conclusion.INCONCLUSIVE]
    assert runs(cache) == ()
    unsettled = localpart.post_part(tmp_path, log, 'a' * 40, (), settled=verdict.result.outcome.settled)
    assert unsettled == 'part: not posted -- an INCONCLUSIVE run is no part'


def _postable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, judged: dict[str, str]) -> list[Path]:
    """Route posting at a planted repo whose judged log has *judged* (id -> status) beside it; the records posted."""
    (tmp_path / 'pyproject.toml').write_text('[tool.lab_commons.parts]\noutput = "out"\n', encoding='utf-8')
    record = Record(tmp_path / 'judged.outcomes' / 'cells.jsonl')
    for node, status in judged.items():
        record.outcome(node, Cell(Status(status)))
    monkeypatch.setattr(localpart, 'vocabulary_at', lambda _root, _sha: Vocabulary())
    posted: list[Path] = []
    monkeypatch.setattr(localpart, 'post', lambda _root, path: posted.append(path) or 'posted')
    return posted


def _posted_part(posted: list[Path]) -> tuple[Conclusion, int]:
    (path,) = posted
    assert 'out' in path.parts, 'the record is written under [tool.lab_commons.parts] output'
    part = part_of(read_record(path))
    return part.result, part.ran


def test_a_fresh_pass_posts_a_part_covering_what_it_judged(monkeypatch, tmp_path: Path) -> None:
    """Live 2026-10-11 (lab-commons ff3106e): a full windows verify posted nothing -- its record covered no test."""
    posted = _postable(monkeypatch, tmp_path, {'t::a': 'ok', 't::b': 'ok'})
    _cached(monkeypatch, tmp_path)
    monkeypatch.setattr(verify, 'run_verify', lambda *_a, **_k: _judged(tmp_path))
    assert verify.main([]) == ProducerExit.PASS
    assert _posted_part(posted) == (Conclusion.PASS, 2)


def test_a_cited_pass_posts_the_cited_runs_part(monkeypatch, tmp_path: Path) -> None:
    """Live 2026-10-11: CITED PASS exited 0 and posted nothing, so serve released it; the cache holds the evidence."""
    posted = _postable(monkeypatch, tmp_path, {'t::a': 'ok'})
    cache = _cached(monkeypatch, tmp_path)
    monkeypatch.setattr(verify, 'run_verify', lambda *_a, **_k: pytest.fail('a cited selection ran again'))
    key = verify.run_key(tmp_path, ())
    run = CachedRun(key.tree, key.env, key.selector, 'PASS', 'a' * 40, f'{tmp_path / "judged.log"}@sha256:x@1')
    record(cache, run)
    assert verify.main([]) == ProducerExit.PASS
    assert _posted_part(posted) == (Conclusion.PASS, 1)


def test_a_run_that_judged_no_test_still_posts_no_part(monkeypatch, tmp_path: Path) -> None:
    """PLANTED CONTROL: an empty selection is refused by name, never posted as a pass."""
    _postable(monkeypatch, tmp_path, {})
    monkeypatch.setattr(localpart, 'post', platformparts.post)
    said = localpart.post_part(tmp_path, tmp_path / 'judged.log', 'a' * 40, (), settled=True)
    assert 'covers no test' in said


def _unboxed(_root: Path, argv: list[str], **_k: object) -> tuple[list[str], Path | None]:
    """The pytest step as given: these tests are about what verify JUDGES, not the box it runs in."""
    return argv, None


#: Why the box refused the step (the ``--outcome`` record ``lab_commons.box.__main__`` writes).
_REFUSED_WHY: Final = 'cpu: wants 4 of 3; verify:other (pid 7) holds 3 until 2026-10-15T00:00:00+00:00'


def _refusing(_root: Path, argv: list[str], *, outcome: Path, **_k: object) -> tuple[list[str], Path]:
    """The box refused the pytest step: its record says so, whatever code the step exits with."""
    write_ended(outcome, Refused(_REFUSED_WHY))
    return argv, outcome


def _unreadable(_path: Path) -> LogRef:
    msg = 'the log is empty'
    raise UnverifiableLog(msg)


def _planted_steps(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, pytest_text: str, pytest_code: int) -> None:
    """Run the REAL ``main`` and ``run_verify`` with the seat free, the hooks clean and the steps planted."""
    _cached(monkeypatch, tmp_path)
    (tmp_path / 'tests').mkdir()
    monkeypatch.setattr(verify, 'lock_freshness', lambda _root: None)
    monkeypatch.setattr(verify, 'boxed', _unboxed)
    clean = StepReport(name='hooks', reported=('hooks',), failures=())
    monkeypatch.setattr(verify, 'read_hooks', lambda _root, **_kw: clean)

    def tee(command: list[str], *, handle: io.TextIOBase, **_where: object) -> int:
        is_pytest = 'pytest' in command
        handle.write(pytest_text if is_pytest else '')
        return pytest_code if is_pytest else 0

    monkeypatch.setattr(verify, '_tee', tee)


@pytest.mark.parametrize(
    ('path', 'pytest_text', 'pytest_code', 'plant'),
    [
        ('box refused', '', 1, ('boxed', _refusing)),
        ('empty selection', 'no tests ran in 0.01s\n', 5, None),
        ('unusable log', '1 passed in 0.1s\n', 0, ('LogRef', SimpleNamespace(of=_unreadable))),
    ],
)
def test_every_inconclusive_path_exits_3_through_the_producer_contract(
    monkeypatch, tmp_path: Path, path: str, pytest_text: str, *, pytest_code: int, plant: tuple | None
) -> None:
    """LIVE 2026-10-11: a held-box verify printed `inconclusive` and a `verify && push` chain went on.

    INCONCLUSIVE is ``ProducerExit.INCONCLUSIVE`` (3) on every path: never 0 (a chain proceeds), never 1
    (a red nobody measured -- what ``raise SystemExit(<str>)`` exits with).
    """
    _planted_steps(monkeypatch, tmp_path, pytest_text=pytest_text, pytest_code=pytest_code)
    if plant is not None:
        monkeypatch.setattr(verify, *plant)
    assert verify.main(['--rerun']) == ProducerExit.INCONCLUSIVE, path


def test_a_planted_clean_run_through_the_same_harness_exits_0(monkeypatch, tmp_path: Path) -> None:
    """THE CONTROL for the paths above: the harness can say PASS, so their 3 is each path's own."""
    _unposted(monkeypatch)
    _planted_steps(monkeypatch, tmp_path, pytest_text='1 passed in 0.1s\n', pytest_code=0)
    assert verify.main(['--rerun']) == ProducerExit.PASS


def test_a_held_box_exits_3_from_a_real_process(tmp_path: Path) -> None:
    """THE SHELL'S VIEW of the lock-wait path: ``verify && push`` must stop, so the PROCESS exits 3.

    A child holds every core of a PRIVATE box ledger, and a second ``python -m lab_commons.dev.verify
    --lock-wait-s 0`` runs against that ledger: its pytest step is refused by the box. Its selection is its
    own, so the run key differs from any enclosing verify and it cannot attach to it.
    """
    records = {'LAB_COMMONS_RESOURCE_DIR': str(tmp_path), BOX_ENV: str(tmp_path / 'box.sqlite')}
    holder = subprocess.Popen(
        [sys.executable, '-c', _HOLD_SEAT],
        env=os.environ | records,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == 'held', 'the planted holder never took the light seats'
        done = subprocess.run(
            [
                sys.executable,
                '-m',
                'lab_commons.dev.verify',
                '--rerun',
                '--lock-wait-s',
                '0',
                '--',
                'tests/test_dev_verify.py',
                '-k',
                'held_box_probe',
            ],
            cwd=Path(__file__).resolve().parents[1],
            env={name: value for name, value in os.environ.items() if name not in {PRODUCING_VAR, INSIDE_ENV}}
            | records,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=600,
            check=False,
        )
    finally:
        holder.kill()
        holder.wait(timeout=30)
    assert done.returncode == ProducerExit.INCONCLUSIVE, done.stdout + done.stderr
    assert 'this box is held and nothing was measured' in done.stderr
    assert 'planted-holder' in done.stderr, 'the refusal names the holder'


#: A child that claims EVERY core of its box ledger and holds them until killed.
_HOLD_SEAT: Final = (
    'import math, time\n'
    'from lab_commons.box import Capacity, Demand, hold\n'
    'from lab_commons.box.supply import Reading\n'
    'size = Capacity.read()\n'
    'cores = math.floor(size.cpu)\n'
    # a quiet reading, so the planted holder is ALWAYS admitted however loaded the machine running it is
    'whole = Reading(size.cpu + size.kept_cpu, size.cpu + size.kept_cpu, 2**40, 2**40)\n'
    "with hold(Demand(cpu=cores, mem_gb=0.5, wall_s=600, seats={}), 'planted-holder', 5, key='planted',\n"
    '          read=lambda _pids: whole):\n'
    "    print('held', flush=True)\n"
    '    time.sleep(600)\n'
)


def test_a_producer_told_its_part_runs_exactly_its_need_set_and_posts_it_alone(monkeypatch, tmp_path: Path) -> None:
    """``verify --part femm`` is the declared producer's form: one -m selecting the need-set, one part posted."""
    _cached(monkeypatch, tmp_path)
    declared = '[tool.lab_commons.parts]\noutput = "out"\n[tool.lab_commons.tests]\nresources = ["femm", "jmag"]\n'
    (tmp_path / 'pyproject.toml').write_text(declared, encoding='utf-8')
    for name, value in producing(part_context('femm'), 'a' * 40).items():
        monkeypatch.setenv(name, value)
    ran: list[tuple[str, ...]] = []
    monkeypatch.setattr(verify, 'run_verify', lambda _root, arguments, **_k: ran.append(arguments) or _judged(tmp_path))
    posts: list[tuple[tuple[str, ...], str]] = []

    def post(*_a: object, arguments: tuple[str, ...], part: str, **_k: object) -> str:
        posts.append((arguments, part))
        return 'posted'

    monkeypatch.setattr(verify, 'post_part', post)
    assert verify.main(['--part', 'femm']) == ProducerExit.PASS
    assert ran == [('-m', 'femm and not jmag')]
    assert posts == [((), 'femm')], 'its own selection is the part, of scope full'


def test_a_part_the_declaration_cannot_have_is_refused_before_it_runs(monkeypatch, tmp_path: Path, capsys) -> None:
    """PLANTED CONTROL: a need-set naming an undeclared resource selects nothing a test can carry."""
    _cached(monkeypatch, tmp_path)
    (tmp_path / 'pyproject.toml').write_text('[tool.lab_commons.tests]\nresources = ["femm"]\n', encoding='utf-8')
    for name, value in producing(part_context('matlab'), 'a' * 40).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(verify, 'run_verify', lambda *_a, **_k: pytest.fail('a refused part ran'))
    assert verify.main(['--part', 'matlab']) == ProducerExit.USAGE
    assert "needs ['matlab']" in capsys.readouterr().err


def _boxed_on(monkeypatch: pytest.MonkeyPatch, cpu: float, *, xdist: bool, free_gb: float = 16.0) -> None:
    monkeypatch.delenv(INSIDE_ENV, raising=False)
    monkeypatch.setenv(PRODUCING_VAR, 'tests/base@planted')  # naming a part is not being in the box
    box = Capacity(cpu=cpu, mem_bytes=16 * GB, seats={})
    monkeypatch.setattr(verifybox.Capacity, 'read', staticmethod(lambda: box))
    monkeypatch.setattr(verifybox, 'free_room', lambda size: Resources(cpu=size.cpu, mem_gb=free_gb))
    monkeypatch.setattr(verifybox, 'xdist_installed', lambda: xdist)
    monkeypatch.setattr(verifybox, 'refresh_checkout', lambda _root: 0)  # no forge in a unit test


def _claimed(argv: list[str]) -> tuple[str, list[str]]:
    """The cores the box claim declares, and the pytest argv it runs."""
    return argv[argv.index('--cpu') + 1], argv[argv.index('--') + 1 :]


def test_a_selection_runs_its_pytest_step_in_the_box_and_a_producer_never_twice(monkeypatch) -> None:
    """The step is held to its declared claim; a tree the box ALREADY holds (a producer) is not claimed twice."""
    _boxed_on(monkeypatch, 2.0, xdist=True)
    argv, record = verifybox.boxed(Path('r'), ['py', '-m', 'pytest'], queue_s=5, outcome=Path('o.json'))
    assert argv[1:4] == ['-m', 'lab_commons.box', 'run']
    assert _claimed(argv) == ('2', ['py', '-m', 'pytest', '-n', '2']), 'capped at the box, -n built from it'
    assert argv[argv.index('--queue-s') + 1] == '5'
    assert record == Path('o.json')
    assert argv[argv.index('--outcome') + 1] == 'o.json'
    monkeypatch.setenv(INSIDE_ENV, 'forge:tests/base')
    reboxed = verifybox.boxed(Path('r'), ['py'], queue_s=5, outcome=Path('o.json'))
    assert reboxed == (['py'], None), 'PLANTED CONTROL: a boxed tree is not reboxed'


@pytest.mark.parametrize(
    ('xdist', 'given', 'cores', 'runs'),
    [
        (True, [], '4', ['-n', '4']),
        (False, [], '1', []),
        (True, ['-n0'], '1', ['-n0']),
        (True, ['-n', '2'], '2', ['-n', '2']),
        (True, ['--numprocesses=3'], '3', ['--numprocesses=3']),
        (True, ['-n', 'auto'], '4', ['-n', 'auto']),
        (True, ['-p', 'no:xdist'], '1', ['-p', 'no:xdist']),
    ],
)
def test_a_selection_declares_the_workers_its_pytest_runs(monkeypatch, xdist, given, cores, runs) -> None:
    """Declared == used: the claim's cores ARE the -n the step runs (one interpreter when serial).

    PLANTED CONTROLS: without xdist, ``-n0`` and ``-p no:xdist`` all run ONE interpreter and claim one
    core, never the cap; an explicit width is the caller's and is declared as given.
    """
    _boxed_on(monkeypatch, 16.0, xdist=xdist)
    argv, _record = verifybox.boxed(Path('r'), ['py', '-m', 'pytest', *given], queue_s=5, outcome=Path('o.json'))
    assert _claimed(argv) == (cores, ['py', '-m', 'pytest', *runs])


@pytest.mark.parametrize(
    ('xdist', 'given', 'runs'),
    [
        (True, ['-n', 'auto'], ['-n', 'auto', '-n', '3']),
        (True, [], ['-n', '3']),
        (False, [], []),
        (True, ['-p', 'no:xdist'], ['-p', 'no:xdist']),
    ],
)
def test_a_producer_inside_the_box_runs_the_width_it_was_admitted_at(monkeypatch, xdist, given, runs) -> None:
    """Declared == used inside a claim: the part's pytest runs as many workers as its claim declared cores.

    A configured ``-n auto`` (a repository's addopts) is the WHOLE box, not the claim, so the declared cores are
    appended last and win. PLANTED CONTROLS: no xdist and ``-p no:xdist`` run one interpreter, nothing appended.
    """
    _boxed_on(monkeypatch, 16.0, xdist=xdist)
    monkeypatch.setenv(INSIDE_ENV, 'forge:tests/base')
    monkeypatch.setenv(CPU_ENV, '3')
    argv, record = verifybox.boxed(Path('r'), ['py', *given], queue_s=5, outcome=Path('o.json'))
    assert (argv, record) == (['py', *runs], None), 'not reboxed, and sized to the claim'


def test_a_selection_runs_the_width_its_files_and_free_memory_hold(monkeypatch, tmp_path: Path) -> None:
    """THE DECLARATION THAT LIED: a 1-file selection asked SELECTION_CPU workers it could never use.

    The width is :func:`learned.fit_width` of SELECTION_CPU, the files selected and the FREE room, and the -n
    the step runs IS the cores it declares. PLANTED CONTROL: a box with plenty runs the full width.
    """
    (tmp_path / 'tests').mkdir()
    for name in ('a', 'b', 'c', 'd', 'e', 'f'):
        (tmp_path / 'tests' / f'test_{name}.py').write_text('', encoding='utf-8')
    monkeypatch.setattr(verifybox, 'origin_url', lambda _root: 'https://g/none.git')
    _boxed_on(monkeypatch, 16.0, xdist=True)
    one, _ = verifybox.boxed(tmp_path, ['py', '-m', 'pytest', 'tests/test_a.py'], queue_s=5, outcome=Path('o.json'))
    assert _claimed(one) == ('1', ['py', '-m', 'pytest', 'tests/test_a.py', '-n', '1']), 'one file, one worker'
    full, _ = verifybox.boxed(tmp_path, ['py', '-m', 'pytest', 'tests'], queue_s=5, outcome=Path('o.json'))
    assert _claimed(full)[0] == str(verifybox.SELECTION_CPU), 'PLANTED CONTROL: plenty runs the full width'
    _boxed_on(monkeypatch, 16.0, xdist=True, free_gb=1.6)
    starved, _ = verifybox.boxed(tmp_path, ['py', '-m', 'pytest', 'tests'], queue_s=5, outcome=Path('o.json'))
    assert _claimed(starved) == ('1', ['py', '-m', 'pytest', 'tests', '-n', '1']), '1.6 GB free holds one 1 GB worker'
    assert starved[starved.index('--mem-gb') + 1] == '1', 'declared at the width it runs'


def test_the_box_ending_the_pytest_step_is_named_never_read_as_a_verdict(tmp_path: Path) -> None:
    """The box's RECORD decides: refused raises naming the holder, killed and crashed are truncations."""
    record = tmp_path / 'step.outcome.json'
    assert 'box crashed' in verifybox.ended_in_the_box(record)[0], 'no record: the box itself died'
    write_ended(record, Refused(_REFUSED_WHY))
    with pytest.raises(Refused, match='verify:other'):
        verifybox.ended_in_the_box(record)
    write_ended(record, ended(-9, 'memory'))
    (killed,) = verifybox.ended_in_the_box(record)
    assert 'the box killed pytest' in killed
    assert verifybox.ended_in_the_box(None) == (), 'a step the box did not run is judged by pytest'


@pytest.mark.parametrize('own', [69, 137])
def test_pytest_exiting_a_former_box_sentinel_is_judged_by_pytest(tmp_path: Path, own: int) -> None:
    """PLANTED (SR-20261015-002): a step exiting 69 or 137 ITSELF was read as refused or killed by the box."""
    record = tmp_path / 'step.outcome.json'
    write_ended(record, ended(own))
    assert verifybox.ended_in_the_box(record) == ()


def test_a_selection_declares_the_memory_its_files_measured_never_a_fixed_figure(tmp_path: Path) -> None:
    """D4/D5: each worker at the worst selected file's peak x the box headroom; an unmeasured file at its siblings'.

    PLANTED CONTROL: a repository with nothing measured falls back to the per-task floor, never to 8 GB.
    """
    (tmp_path / 'tests' / 'u').mkdir(parents=True)
    for name in ('test_a.py', 'test_b.py', 'test_new.py'):
        (tmp_path / 'tests' / 'u' / name).write_text('', encoding='utf-8')
    files = verifybox.selection_files(tmp_path, ['py', '-m', 'pytest', 'tests/u', '-q'])
    assert files == ('tests/u/test_a.py', 'tests/u/test_b.py', 'tests/u/test_new.py')
    assert verifybox.selection_files(tmp_path, ['tests/u/test_a.py::t']) == ('tests/u/test_a.py',)
    learned.learn_peaks('https://g/v.git', {'tests/u/test_a.py': 1024.0, 'tests/u/test_b.py': 2048.0})
    assert verifybox.selection_mem_gb('https://g/v.git', ['tests/u/test_a.py'], 2) == 2 * 1.0 * learned.BOX_HEADROOM
    assert verifybox.selection_mem_gb('https://g/v.git', ['tests/u/test_new.py'], 1) == 1.5 * learned.BOX_HEADROOM
    assert verifybox.selection_mem_gb('https://g/none.git', ['tests/x.py'], 4) == 4.0, 'the 1 GB floor per worker'


def test_a_selection_learns_its_whole_tree_peak_and_a_memory_kill_grows_it(tmp_path: Path, monkeypatch) -> None:
    """Per-file peaks under-price one process running many files: the box's own measurement of the tree wins.

    PLANTED CONTROL: a run that exited on its own teaches its peak once; the kill teaches twice the limit.
    """
    monkeypatch.setattr(verifybox, '_repo', lambda _root: 'https://g/w.git')
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests' / 'test_a.py').write_text('', encoding='utf-8')
    files = verifybox.selection_files(tmp_path, ['tests'])
    record = tmp_path / 'o.json'
    write_ended(record, box.ProcessEnd(-9, 'memory', 2 * GB, 1.0, 10.0, 'fake', 'k', None))
    verifybox.learn_ended(tmp_path, ['tests'], record)
    killed = verifybox.selection_mem_gb('https://g/w.git', files, 1)
    assert killed == pytest.approx(2 * 2 * learned.BOX_HEADROOM, abs=1e-6)  # GB: the 2 GB limit, doubled
    write_ended(record, box.ProcessEnd(0, 'exit', 3 * GB, 1.0, 10.0, 'fake', 'k', None))
    verifybox.learn_ended(tmp_path, ['tests'], record)
    assert verifybox.selection_mem_gb('https://g/w.git', files, 1) == pytest.approx(3 * learned.BOX_HEADROOM, abs=1e-6)
    verifybox.learn_ended(tmp_path, ['tests'], None)  # a step the box did not run teaches nothing


def test_a_refused_selection_names_the_offer_to_another_host(tmp_path: Path, monkeypatch) -> None:
    """D5: the refusal prints the exact `forge request tests` command; a dirty tree cannot be offered."""
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests' / 'test_a.py').write_text('', encoding='utf-8')
    monkeypatch.setattr(forgerequest, 'status_paths', lambda _root: ())
    offer = forgerequest.offer_line(tmp_path, 'b' * 40, ('tests/test_a.py',))
    assert f'python -m lab_commons.dev.forge request tests --sha {"b" * 40} --paths tests/test_a.py' in offer
    monkeypatch.setattr(forgerequest, 'status_paths', lambda _root: ('tests/test_a.py',))
    assert 'cannot be offered' in forgerequest.offer_line(tmp_path, 'b' * 40, ('tests/test_a.py',)), 'PLANTED: dirty'


def test_a_local_measure_posts_no_part_and_the_producer_still_does(monkeypatch, tmp_path: Path) -> None:
    """VERDICTS-FROM-THE-FORGE. Live 2026-10-17/18: a local measure posted tests/base on integrate/main shas.

    A selection outside the producer serve spawned reaches no status call, on a clean unmoved HEAD; the
    PLANTED CONTROL is the same clean run inside the producer, which posts.
    """
    posted = _postable(monkeypatch, tmp_path, {'t::a': 'ok'})
    _cached(monkeypatch, tmp_path)
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests' / 'a.py').write_text('', encoding='utf-8')
    monkeypatch.setattr(verify, 'run_verify', lambda *_a, **_k: _judged(tmp_path))
    monkeypatch.delenv(PRODUCING_VAR)
    assert verify.main(['--rerun', 'tests/a.py']) == ProducerExit.PASS
    assert posted == [], 'a local measure is never a verdict'
    for name, value in producing(part_context(BASE), 'a' * 40).items():
        monkeypatch.setenv(name, value)
    assert verify.main(['--rerun']) == ProducerExit.PASS
    assert _posted_part(posted) == (Conclusion.PASS, 1)


def test_a_cited_measure_outside_the_producer_posts_nothing(monkeypatch, tmp_path: Path) -> None:
    """The cited path is the other door to the forge, and is shut the same way."""
    posted = _postable(monkeypatch, tmp_path, {'t::a': 'ok'})
    cache = _cached(monkeypatch, tmp_path)
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests' / 'a.py').write_text('', encoding='utf-8')
    monkeypatch.delenv(PRODUCING_VAR)
    monkeypatch.setattr(verify, 'run_verify', lambda *_a, **_k: pytest.fail('a cited selection ran again'))
    key = verify.run_key(tmp_path, ('tests/a.py',))
    run = CachedRun(key.tree, key.env, key.selector, 'PASS', 'a' * 40, f'{tmp_path / "judged.log"}@sha256:x@1')
    record(cache, run)
    assert verify.main(['tests/a.py']) == ProducerExit.PASS
    assert posted == []
