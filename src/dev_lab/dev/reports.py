"""What each verify step reported: text witnesses and optional exact recorded cells. No processes.

SPLIT OUT OF :mod:`dev_lab.dev.verify` at a real seam rather than at a line count. Everything
here is a pure function of its supplied evidence; everything there launches a process, writes a
log or stamps a verdict. The consequence is the one that matters: the measured pytest output that
motivates this whole layer can be tested as a STRING CONSTANT, and the case that produced it --
``consumer_c``, 2026-09-15, 307 collected, 3 collection errors, ZERO run, and a ``307 passed``-shaped
line in the same output -- cannot be produced on demand by any live run, which is exactly why it
went unnoticed for as long as it did.

"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from lab_commons.hpc.testcells import conclude, merged
from lab_commons.outcomes import Conclusion

from dev_lab.dev.pytestout import collected_count, markers_in, summary_counts
from dev_lab.dev.skipallowance import SKIPPED, skip_ceiling, skip_shortfall, stale_skips
from dev_lab.dev.test_outcomes import skipped_nodes

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from lab_commons.hpc.testcells import TestCell

__all__ = ['StepReport', 'read_pytest', 'read_ruff', 'read_stages']

#: pytest's documented exit codes, and what each one means for a PROOF. 0 and 1 are the only two
#: that describe a run which reached its tests; every other one is a reason the run was cut short,
#: and it is named rather than folded into "non-zero".
#: pytest's exit when it collected nothing (everything deselected, or no test at all).
_NOTHING_COLLECTED: Final = 5

_PYTEST_EXITS: Final[dict[int, str]] = {
    2: 'pytest exit 2: the run was interrupted by the user or an internal condition',
    3: 'pytest exit 3: an internal error happened while running tests',
    4: 'pytest exit 4: pytest was misused, so the selection it ran is not the one asked for',
    _NOTHING_COLLECTED: 'pytest exit 5: NO TESTS WERE COLLECTED, which is not the same as none failing',
}

#: The words that mean a selected test PRODUCED an outcome. ``skipped`` and ``deselected`` are
#: deliberately absent: neither ran, and the floor below is the one thing standing between a suite
#: that skipped everything and a green verdict over zero executed tests.
_OUTCOME_WORDS: Final[tuple[str, ...]] = ('passed', 'failed', 'error', 'xfailed', 'xpassed')

#: A node id named as a failure or an error in pytest's short summary.
_FAILED_NODE = re.compile(r'^(?:FAILED|ERROR)\s+(\S+)')

#: The banner pytest prints when it stops early. The word alone is enough -- it appears in
#: ``!!!! Interrupted: 3 errors during collection !!!!`` and in the KeyboardInterrupt banner, and
#: both mean the same thing to a proof.
_INTERRUPTED = re.compile(r'^!+\s*(?:Interrupted|KeyboardInterrupt)\b.*', re.MULTILINE)

#: Collection that failed BEFORE any test ran, in pytest's own words.
_COLLECTION_ERRORS = re.compile(r'(\d+)\s+errors?\s+during\s+collection')


@dataclass(frozen=True, slots=True)
class StepReport:
    """What ONE step of the verify run contributed to the proof. Three named sets, no verdict.

    ``reported`` is what produced an OUTCOME -- the step's own name once it ran to a readable exit
    status, plus (for pytest) every node id the short summary attributed a failure to. ``failures``
    is a subset of it, because :class:`~dev_lab.dev.verdict.Result` refuses to name a failure
    that never reported: a test that failed something the run never reached is a hole, not a red.

    ``truncated`` is where INCONCLUSIVE comes from, and it is a NAMED SET rather than a flag for the
    reason ``integration.md`` records about count pins -- "it did not finish" and "three collection
    errors" have different remedies, and a reader who gets a boolean has to go and find out which.
    """

    name: str
    reported: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    truncated: tuple[str, ...] = ()


def read_ruff(name: str, returncode: int) -> StepReport:
    """The report for one ruff step, from its exit status alone.

    Ruff's exit codes are a total answer and its output is advice: ``0`` clean, ``1`` violations
    found (already printed, one per line), anything else an error IN ruff -- a config it could not
    read, a path it could not walk. The third case must not read as ``1``: "your code is dirty" and
    "the checker did not run" are the same non-zero to a shell, and collapsing them is how a broken
    config passes for a clean tree once somebody stops reading the output.
    """
    if returncode == 0:
        return StepReport(name=name, reported=(name,))
    if returncode == 1:
        return StepReport(name=name, reported=(name,), failures=(name,))
    return StepReport(
        name=name,
        truncated=(f'{name} exited {returncode}, which is ruff erroring rather than ruff reporting',),
    )


def _executed_count(counts: dict[str, int]) -> int:
    """Count accounted executions, never items excluded by the selector or stage split."""
    return sum(counts.get(word, 0) for word in (*_OUTCOME_WORDS, 'skipped'))


def _skip_ceiling(stages: Iterable[dict[str, int]]) -> tuple[str, ...]:
    """The allowance's share ceiling over the whole executed selection, deselections excluded."""
    counted = list(stages)
    return skip_ceiling(sum(c.get('skipped', 0) for c in counted), sum(_executed_count(c) for c in counted))


def _summary_shortfall(
    counts: dict[str, int], text: str, failures: tuple[str, ...], *, recorded_count: int | None = None
) -> tuple[str, ...]:
    """Every non-skip way a summary line describes a run that cannot settle. Pure over its arguments."""
    reasons: list[str] = []
    if counts.get('error'):
        reasons.append(f'{counts["error"]} test(s) errored, and an errored test produced no outcome to attribute')
    named = counts.get('failed', 0)
    if recorded_count is None and named != len(failures):
        reasons.append(
            f'the summary names {named} failure(s) and the output names {len(failures)} node id(s); '
            f'a FAIL that cannot say which test was red is the refusal a count pin is'
        )
    if recorded_count is not None:
        accounted = _executed_count(counts)
        if accounted != recorded_count:
            reasons.append(
                f'the summary accounts for {accounted} test(s) but the stage records contain {recorded_count}'
            )
        # Strict XPASS is counted as failed; non-strict XPASS as xpassed.
        # A skipped test may additionally be a decided unmarked-skip miss.
        # Their semantics remain TestCell.red's, not a second pytest classifier.
        at_least = named + counts.get('xpassed', 0)
        at_most = at_least + counts.get('skipped', 0)
        if not at_least <= len(failures) <= at_most:
            reasons.append(
                f'the summary reports {named} failed and {counts.get("xpassed", 0)} xpassed '
                f'but records contain {len(failures)} decided misses (at most {at_most}, including skips)'
            )
    if not any(counts.get(word) for word in _OUTCOME_WORDS):
        reasons.append('no test produced a pass or fail outcome, so the run executed nothing it could be judged on')
    if (collected := collected_count(text)) is not None and (total := sum(counts.values())) < collected:
        reasons.append(
            f'pytest collected {collected} item(s) and accounted for {total}: the difference '
            f'never reported, and a run that did not reach its selection cannot be promoted'
        )
    return tuple(reasons)


def read_pytest(
    text: str,
    *,
    returncode: int,
    allowed_skips: tuple[str, ...] = (),
    complete_skip_census: bool = True,
    cells: Mapping[str, TestCell] | None = None,
    flaky: frozenset[str] = frozenset(),
) -> StepReport:
    """Read pytest's text/exit witnesses and, when supplied, its exact canonical cells.

    ``cells=None`` is the independent text-log method. Live callers supply recorded
    cells explicitly, even when empty: identities and decisions then come only
    from TestCell.red/conclude, never from whitespace-delimited text. Summary
    totals must account for exactly those cells; text still independently guards
    truncation, collection, exit status and skip allowance/census.

    THE ORDER OF THE QUESTIONS IS THE DESIGN. It does not ask "did something pass"; it asks what
    could have cut the run short, and only a text with no such reason is allowed to settle. That
    is what catches the measured ``consumer_c`` case, where a clean-looking ``307 passed`` line and
    ``!!!! Interrupted: 3 errors during collection !!!!`` were in the SAME output -- a parser
    looking for the good news finds it, and the good news was about a run that executed nothing.

    ``complete_skip_census=False`` means the selector cannot judge another test's allowance
    retired. Observed skips still require declarations, named counts and the same skip ceiling.

    Every reason below is one this parser can see in the text or the exit status, and each is named
    in the words a remedy would be written in:

    * an ``Interrupted``/``KeyboardInterrupt`` banner, or ``N errors during collection``;
    * an ``INTERNALERROR``, which is pytest failing rather than the suite failing;
    * no parsable summary line at all -- the empty-output case, where a crashed or signalled
      process leaves a caller with nothing to read;
    * a summary naming errors, since an errored test never produced an outcome to attribute;
    * a summary whose ``failed`` count disagrees with the number of node ids the short summary
      names, so a FAIL could not name all of its failures;
    * a summary in which NOTHING passed or failed -- the floor against a suite that skipped itself
      into a green verdict, which the collected-versus-accounted check below cannot see;
    * ``collected N`` with fewer than N accounted for, or any exit code other than 0 or 1;
    * a skip on either side of *allowed_skips*, or a skip share above :data:`~dev_lab.dev.skipallowance.SKIP_CEILING`.
    """
    report = _read_stage(
        text,
        returncode=returncode,
        allowed_skips=allowed_skips,
        complete_skip_census=complete_skip_census,
        cells=cells,
        flaky=flaky,
    )
    ceiling = _skip_ceiling((summary_counts(text) or {},))
    if ceiling:
        return StepReport(name='pytest', truncated=(*report.truncated, *ceiling))
    return report


def _read_stage(
    text: str,
    *,
    returncode: int,
    allowed_skips: tuple[str, ...],
    complete_skip_census: bool,
    cells: Mapping[str, TestCell] | None,
    flaky: frozenset[str],
) -> StepReport:
    """Read stage witnesses; the public selection owner applies its whole-run skip ceiling."""
    failures = (
        tuple(dict.fromkeys(match.group(1) for line in text.splitlines() if (match := _FAILED_NODE.match(line))))
        if cells is None
        else tuple(node for node, one in cells.items() if one.red)
    )
    counts = summary_counts(text)
    truncated: list[str] = []
    if cells is None and flaky:
        truncated.append('flaky recorded identities were supplied without their cells')
    elif cells is not None and conclude(cells.values(), flaky) is Conclusion.INCONCLUSIVE:
        truncated.append(
            'recorded stage cells did not conclude: '
            f'undecided={tuple(node for node, one in cells.items() if one.met is None)}, flaky={tuple(sorted(flaky))}'
        )

    if banner := _INTERRUPTED.search(text):
        truncated.append(f'pytest was interrupted: {banner.group(0).strip("! ").strip()}')
    if errors := _COLLECTION_ERRORS.search(text):
        truncated.append(f'{errors.group(1)} error(s) during collection: those tests were never run')
    truncated.extend(
        f'the run reported {marker!r}, which is a run that died rather than one that finished'
        for marker in markers_in(text)
    )
    if counts is None:
        truncated.append('pytest printed no parsable summary line, so there is nothing to read a result out of')
    else:
        truncated.extend(
            _summary_shortfall(counts, text, failures, recorded_count=None if cells is None else len(cells))
        )
        truncated.extend(
            skip_shortfall(
                counts,
                text,
                allowed_skips,
                complete_skip_census=complete_skip_census,
                recorded=None if cells is None else skipped_nodes(cells),
            )
        )
    if returncode in _PYTEST_EXITS:
        truncated.append(_PYTEST_EXITS[returncode])
    elif returncode not in (0, 1):
        truncated.append(f'pytest exited {returncode}, which is not an exit code pytest defines')

    if truncated:
        return StepReport(name='pytest', truncated=tuple(dict.fromkeys(truncated)))
    return StepReport(name='pytest', reported=('pytest', *failures), failures=failures)


def read_stages(
    stages: tuple[tuple[str, int], ...],
    *,
    allowed_skips: tuple[str, ...] = (),
    complete_skip_census: bool = True,
    stage_cells: tuple[tuple[Mapping[str, TestCell], frozenset[str]], ...] | None = None,
) -> StepReport:
    """ONE pytest report over the selection's stages (:mod:`dev_lab.dev.serialpass`): ``(text, returncode)`` each.

    A lone stage is :func:`read_pytest` exactly. Split, each stage is read on its own -- a stage that ran
    nothing (exit 5, no outcome) is dropped while another ran, since the split emptied it and not the
    selection -- and the reports are unioned. The STALE skip side needs the whole census, so it is judged
    once over every stage's skips rather than per stage, where each half would call the other's skips stale.
    The share ceiling likewise belongs to the whole executed selection, excluding deselections.
    """
    if stage_cells is not None and len(stage_cells) != len(stages):
        msg = f'pytest stage evidence has {len(stage_cells)} entries for {len(stages)} stages'
        raise ValueError(msg)
    if not stages:
        return StepReport(name='pytest', truncated=('no pytest stage ran',))
    if len(stages) == 1:
        text, code = stages[0]
        cells, flaky = (None, frozenset()) if stage_cells is None else stage_cells[0]
        return read_pytest(
            text,
            returncode=code,
            allowed_skips=allowed_skips,
            complete_skip_census=complete_skip_census,
            cells=cells,
            flaky=flaky,
        )
    ran = [
        index
        for index, (text, code) in enumerate(stages)
        if not (
            _ran_nothing(text, code)
            and (stage_cells is None or (not stage_cells[index][0] and not stage_cells[index][1]))
        )
    ] or [0]
    reports = [
        _read_stage(
            stages[index][0],
            returncode=stages[index][1],
            allowed_skips=allowed_skips,
            complete_skip_census=False,
            cells=None if stage_cells is None else stage_cells[index][0],
            flaky=frozenset() if stage_cells is None else stage_cells[index][1],
        )
        for index in ran
    ]
    observed = {
        node.replace('\\', '/')
        for index in ran
        for node in (SKIPPED.findall(stages[index][0]) if stage_cells is None else skipped_nodes(stage_cells[index][0]))
    }
    allowed = tuple(prefix.replace('\\', '/') for prefix in allowed_skips)
    stale = stale_skips(observed, allowed) if complete_skip_census else ()
    global_shortfall = ()
    if stage_cells is not None:
        cells, disagreed = merged(stage_cells[index][0] for index in ran)
        flaky = disagreed | frozenset(node for index in ran for node in stage_cells[index][1])
        if conclude(cells.values(), flaky) is Conclusion.INCONCLUSIVE:
            global_shortfall = (f'recorded run cells did not conclude; flaky identities: {tuple(sorted(flaky))}',)
    ceiling = _skip_ceiling(summary_counts(stages[index][0]) or {} for index in ran)
    truncated = tuple(
        dict.fromkeys([*(r for one in reports for r in one.truncated), *stale, *global_shortfall, *ceiling])
    )
    if truncated:
        return StepReport(name='pytest', truncated=truncated)
    failures = tuple(dict.fromkeys(f for one in reports for f in one.failures))
    return StepReport(name='pytest', reported=('pytest', *failures), failures=failures)


def _ran_nothing(text: str, returncode: int) -> bool:
    """A stage pytest exited 5 from with no outcome in its summary: everything it collected was deselected."""
    counts = summary_counts(text) or {}
    return returncode == _NOTHING_COLLECTED and not any(counts.get(word) for word in _OUTCOME_WORDS)
