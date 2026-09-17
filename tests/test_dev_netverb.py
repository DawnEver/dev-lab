"""``lab_commons.dev.netverb`` -- the retry loop driven against REAL subprocesses, both directions.

NOTHING UNDER TEST IS MOCKED. Every case below runs a real interpreter as a real child process,
which is the only shape that can fail for the right reason: the thing being claimed is what the loop
does with a process's exit code and output, and a fake process can be made to agree with any
implementation. The ONE substitution is ``sleep`` -- the clock is not the subject, and a suite that
really waited three seconds per retry would be nine seconds of nothing per case.

THE ATTEMPT COUNT IS ASSERTED FROM THE CHILD'S OWN SIDE, through a counter file each invocation
increments. That is the whole point of the non-retryable case: an implementation that retried a
rejected ref and happened to fail identically would produce an identical REPORT, so only a count the
CHILD kept can tell "it was not retried" from "it was retried and lost again".

BOTH DIRECTIONS, EVERYWHERE. A failure that clears is retried and reported RECOVERED; a failure that
does not clear stops at the bound; a refusal stops at ONE; a success is not retried at all. And the
classification table is driven from both ends -- every retryable row, every permanent row -- with a
floor under the scan so a table that went empty cannot read as green.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from lab_commons.dev._netverb_rows import ROWS
from lab_commons.dev.netverb import (
    DEFAULT_ATTEMPTS,
    Attempt,
    Diagnosis,
    Disposition,
    classify,
    is_retryable,
    run_network_verb,
)

#: FLOORS. The table is the thing this module's judgement lives in, so a scan of it that reached
#: nothing must not read as agreement. MEASURED 2026-09-17: 5 rows, 38 patterns.
ROW_FLOOR = 4
PATTERN_FLOOR = 20

#: A message that is in no row, so it exercises the UNCLASSIFIED default rather than a pattern.
UNMEASURED = 'fatal: the weather over the datacentre was unfavourable'


class _Clock:
    """A backoff recorder. Substituted for ``time.sleep`` only -- the command is always real."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def _child(
    tmp_path: Path, *, fails: int, message: str, stream: str = 'stderr', code: int = 1
) -> tuple[list[str], Path]:
    """A real command that fails *fails* times and then succeeds, counting its own invocations.

    Returns the argv and the counter path, so a test asserts how many times the CHILD ran rather
    than how many attempts the loop says it made.
    """
    counter = tmp_path / f'count-{fails}-{stream}-{code}.txt'
    script = tmp_path / f'child-{fails}-{stream}-{code}.py'
    script.write_text(
        'import pathlib, sys\n'
        'counter = pathlib.Path(sys.argv[1])\n'
        'seen = int(counter.read_text()) if counter.exists() else 0\n'
        'counter.write_text(str(seen + 1))\n'
        f'if seen < {fails}:\n'
        f'    sys.{stream}.write({message!r})\n'
        f'    sys.exit({code})\n'
        'sys.exit(0)\n',
        encoding='utf-8',
    )
    return [sys.executable, str(script), str(counter)], counter


def _ran(counter: Path) -> int:
    return int(counter.read_text(encoding='utf-8')) if counter.exists() else 0


def test_a_transient_that_clears_is_retried_and_reported_as_RECOVERED(tmp_path: Path) -> None:
    """FAILS TWICE, THEN SUCCEEDS -- the 2026-08-21 incident, reproduced as a process."""
    clock = _Clock()
    argv, counter = _child(tmp_path, fails=2, message='fatal: Authentication failed for the forge\n')
    report = run_network_verb(argv, backoff_s=0.0, sleep=clock)
    assert _ran(counter) == 3, 'the child itself must record three real invocations'
    assert report.ok
    assert report.attempt_count == 3
    assert report.disposition is Disposition.RECOVERED
    assert [a.diagnosis for a in report.attempts] == [
        Diagnosis.TRANSIENT,
        Diagnosis.TRANSIENT,
        Diagnosis.SUCCEEDED,
    ]
    assert len(clock.waits) == 2, 'one backoff per retry, and none after the success'
    assert 'RECOVERED' in report.remedy
    assert 'no action is needed' in report.remedy


def test_a_transient_that_never_clears_STOPS_at_the_bound(tmp_path: Path) -> None:
    """The other half: bounded means bounded, and the report says it gave up rather than "blocked"."""
    clock = _Clock()
    argv, counter = _child(tmp_path, fails=99, message='fatal: unable to access the forge: Connection reset\n')
    report = run_network_verb(argv, attempts=DEFAULT_ATTEMPTS, backoff_s=0.0, sleep=clock)
    assert _ran(counter) == DEFAULT_ATTEMPTS, 'it must stop at the bound, not loop'
    assert report.attempt_count == DEFAULT_ATTEMPTS
    assert report.disposition is Disposition.EXHAUSTED
    assert report.diagnosis is Diagnosis.TRANSIENT
    assert not report.ok
    assert report.returncode == 1
    assert 'gave up after 3 of 3' in report.remedy
    assert 'report it' in report.remedy
    assert len(clock.waits) == DEFAULT_ATTEMPTS - 1, 'no backoff after the last attempt'


@pytest.mark.parametrize(
    ('message', 'stream', 'expected'),
    [
        (' ! [rejected]        main -> main (non-fast-forward)\n', 'stderr', Diagnosis.REF_REJECTED),
        ('remote: error: 403 Forbidden: protected branch\n', 'stderr', Diagnosis.FORGE_REFUSED),
        ('[gate] the pre-push hook refused this push\n', 'stdout', Diagnosis.HOOK_REFUSED),
        ('fatal: Repository not found\n', 'stderr', Diagnosis.REMOTE_ABSENT),
    ],
)
def test_a_non_retryable_failure_is_reported_on_the_FIRST_attempt(
    tmp_path: Path, message: str, stream: str, expected: Diagnosis
) -> None:
    """ZERO RETRIES, asserted as a COUNT.

    A refusal repeats identically -- measured 2026-09-17, a pre-push hook printed the same refusal
    three times -- so an implementation that retried it would produce the same final report. Only
    the child's own counter separates the two, which is why it is the assertion that matters here.
    The hook row is driven on STDOUT on purpose: a hook writes its verdict there while git writes
    its failure to stderr, and a classifier reading one stream is blind to the other.
    """
    clock = _Clock()
    argv, counter = _child(tmp_path, fails=99, message=message, stream=stream)
    report = run_network_verb(argv, backoff_s=0.0, sleep=clock)
    assert _ran(counter) == 1, f'{expected.value} was retried; the whole point is that it is not'
    assert report.attempt_count == 1
    assert report.diagnosis is expected
    assert report.disposition is Disposition.REFUSED
    assert clock.waits == [], 'a refusal must not even pay the backoff'
    assert 'retrying cannot change this answer' in report.remedy


def test_a_command_that_succeeds_is_not_retried_at_all(tmp_path: Path) -> None:
    """The cheapest direction, and the one a broken loop breaks first."""
    clock = _Clock()
    argv, counter = _child(tmp_path, fails=0, message='')
    report = run_network_verb(argv, backoff_s=0.0, sleep=clock)
    assert _ran(counter) == 1
    assert report.ok
    assert report.disposition is Disposition.SUCCEEDED
    assert report.diagnosis is Diagnosis.SUCCEEDED
    assert clock.waits == []


def test_an_unmeasured_failure_is_retried_and_named_UNCLASSIFIED(tmp_path: Path) -> None:
    """The default is RETRYABLE and SAYS SO -- a shape nobody measured is not a shape we refuse."""
    clock = _Clock()
    argv, counter = _child(tmp_path, fails=99, message=UNMEASURED + '\n')
    report = run_network_verb(argv, attempts=2, backoff_s=0.0, sleep=clock)
    assert _ran(counter) == 2
    assert report.diagnosis is Diagnosis.UNCLASSIFIED
    assert report.disposition is Disposition.EXHAUSTED


def test_the_wall_terminates_an_attempt_and_the_next_one_still_runs(tmp_path: Path) -> None:
    """COMPOSITION WITH ``bounded``: a hung attempt is a TIMED_OUT attempt, and it is retryable."""
    clock = _Clock()
    script = tmp_path / 'hang.py'
    script.write_text(
        'import pathlib, sys, time\n'
        'counter = pathlib.Path(sys.argv[1])\n'
        'seen = int(counter.read_text()) if counter.exists() else 0\n'
        'counter.write_text(str(seen + 1))\n'
        'time.sleep(60)\n',
        encoding='utf-8',
    )
    counter = tmp_path / 'hang-count.txt'
    report = run_network_verb(
        [sys.executable, str(script), str(counter)], attempts=2, backoff_s=0.0, timeout=2.0, sleep=clock
    )
    assert _ran(counter) == 2, 'the wall must end the attempt, not the loop'
    assert [a.diagnosis for a in report.attempts] == [Diagnosis.TIMED_OUT, Diagnosis.TIMED_OUT]
    assert report.disposition is Disposition.EXHAUSTED


def test_a_callers_veto_stops_the_loop_and_is_named_in_the_report(tmp_path: Path) -> None:
    """THE LOCAL HALF'S SEAM. motronics' "my own gate holds the box" fits here without a fork."""
    seen: list[Attempt] = []

    def veto(attempt: Attempt) -> bool:
        seen.append(attempt)
        return False

    argv, counter = _child(tmp_path, fails=99, message='fatal: Connection reset\n')
    report = run_network_verb(argv, backoff_s=0.0, sleep=_Clock(), before_retry=veto)
    assert _ran(counter) == 1
    assert len(seen) == 1
    assert report.diagnosis is Diagnosis.STOPPED_BY_CALLER
    assert report.disposition is Disposition.REFUSED


def test_the_child_runs_with_the_interactive_prompt_closed(tmp_path: Path) -> None:
    """A credential PROMPT is a hang, and a hang would be diagnosed as a wall three times over."""
    script = tmp_path / 'env.py'
    script.write_text("import os, sys\nsys.stdout.write(os.environ.get('GIT_TERMINAL_PROMPT', 'unset'))\n", 'utf-8')
    report = run_network_verb([sys.executable, str(script)], attempts=1, backoff_s=0.0, sleep=_Clock())
    assert report.attempts[0].output.strip() == '0'
    opted_out = run_network_verb([sys.executable, str(script)], attempts=1, no_prompt=False, sleep=_Clock())
    assert opted_out.attempts[0].output.strip() in {'unset', '0'}


def test_the_classification_table_is_read_in_both_directions() -> None:
    """EVERY ROW, with a floor: a table that emptied cannot pass by agreeing with nothing."""
    assert len(ROWS) >= ROW_FLOOR, f'{len(ROWS)} classification rows, below the {ROW_FLOOR} floor'
    patterns = [p for _, _, ps in ROWS for p in ps]
    assert len(patterns) >= PATTERN_FLOOR, f'{len(patterns)} patterns, below the {PATTERN_FLOOR} floor'
    retryable_rows = {name for name, retryable, _ in ROWS if retryable}
    permanent_rows = {name for name, retryable, _ in ROWS if not retryable}
    assert retryable_rows, 'a table with only one side classifies nothing'
    assert permanent_rows, 'a table with only one side classifies nothing'
    for name, retryable, row_patterns in ROWS:
        for pattern in row_patterns:
            found = classify(f'remote: {pattern.upper()} while talking to the forge')
            assert found is Diagnosis(name), f'{pattern!r} classified as {found.value}, not {name}'
            assert is_retryable(found) is retryable, f'{pattern!r} disagrees with its own row'


def test_a_planted_unmeasured_output_falls_through_to_the_retryable_default() -> None:
    """THE PLANTED CONTROL for the table: the matcher can still miss, and a miss is not a refusal."""
    assert classify(UNMEASURED) is Diagnosis.UNCLASSIFIED
    assert is_retryable(Diagnosis.UNCLASSIFIED)
    assert not is_retryable(Diagnosis.HOOK_REFUSED)
    assert classify('') is Diagnosis.UNCLASSIFIED


def test_a_permanent_row_wins_over_a_transient_one_in_the_same_output() -> None:
    """ORDER IS EVIDENCE. A rejected push also prints a transient-looking line; the refusal wins."""
    combined = 'error: failed to push some refs\n ! [rejected] main -> main\nfatal: Authentication failed\n'
    assert classify(combined) is Diagnosis.REF_REJECTED


def test_attempts_below_one_is_refused() -> None:
    """A bound of zero is not a bound, it is a command that never runs wearing a report's clothes."""
    with pytest.raises(ValueError, match='at least 1'):
        run_network_verb([sys.executable, '-c', 'pass'], attempts=0)


def test_the_module_entry_point_reports_JSON_a_shell_caller_can_branch_on(tmp_path: Path) -> None:
    """THE SHELL CONSUMER'S DOOR, driven as the real process a shell would start.

    ``wdg-lab-update.sh`` is a shell caller, so the reachability being claimed is exactly this: an
    interpreter, a module name, and a JSON report on stdout while the command's own output stays on
    stderr. Nothing is imported here -- the test runs the module the way the consumer will.
    """
    argv, counter = _child(tmp_path, fails=99, message=' ! [rejected] main -> main\n')
    done = subprocess.run(
        [sys.executable, '-m', 'lab_commons.dev.netverb', '--attempts', '3', '--backoff', '0', '--json', '--', *argv],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 1, done.stderr
    assert _ran(counter) == 1, 'the entry point must carry the same refusal decision as the API'
    report = json.loads(done.stdout)
    assert report['disposition'] == 'refused'
    assert report['diagnosis'] == 'ref-rejected'
    assert report['attempt_count'] == 1
    assert 'rejected' in report['attempts'][0]['output']
    assert '[netverb]' in done.stderr
    assert 'rejected' in done.stderr
