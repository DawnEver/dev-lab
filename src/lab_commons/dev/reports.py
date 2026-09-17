"""What each verify step REPORTED, read out of the text it printed. Pure functions, no processes.

SPLIT OUT OF :mod:`lab_commons.dev.verify` at a real seam rather than at a line count. Everything
here is a pure function of a string and an integer; everything there launches a process, writes a
log or stamps a verdict. The consequence is the one that matters: the measured pytest output that
motivates this whole layer can be tested as a STRING CONSTANT, and the case that produced it --
``optimi_lab``, 2026-09-15, 307 collected, 3 collection errors, ZERO run, and a ``307 passed``-shaped
line in the same output -- cannot be produced on demand by any live run, which is exactly why it
went unnoticed for as long as it did.

THE SKIP ALLOWANCE IS A TWO-SIDED RATCHET, and it is the part of this module with the most rope.
A skip is not an outcome (:class:`~lab_commons.dev.verdict.Proof` says so in its own words): it is a
selected test that told nobody anything. The strict reading -- any skip truncates the run -- is
correct and unusable across four repos, because a tool that answers INCONCLUSIVE on every invocation
forever stops being read, and a refusal nobody reads gets routed around instead of fixed. So a
project may DECLARE the skips it is living with, in its own ``pyproject.toml``::

    [tool.lab_commons.verify]
    allowed_skips = ['tests/test_vendor.py']

and both directions refuse:

* a skip OBSERVED and not declared truncates the run, NAMED -- unchanged from the strict reading;
* a skip DECLARED and not observed truncates it too. An allowance nothing uses is a hole that reads
  as a decision, and without this half the list only ever grows.

The default is an EMPTY list, so a project that declares nothing behaves exactly as it did before
the allowance existed. That is the property that makes this strictly stronger than the strict
reading rather than a loosening of it.

WHAT THE ALLOWANCE MATCHES, and there is exactly ONE spelling. Entries are PREFIXES of the location
pytest prints, matched with ``str.startswith``; ``tests/test_vendor.py`` covers every skip in that
file and ``tests/test_vendor.py:31`` pins one site. They are NOT node ids, and that is a measured
constraint rather than a choice: pytest's ``-rs`` short summary reports a skip as
``SKIPPED [1] tests/test_vendor.py:31: needs the vendor``, grouping by (file, line, reason) --
there is no node id in it to match, because several parametrisations of one test share a line. The
count in the brackets is checked against the summary's own ``skipped`` total, so a report that named
fewer skips than the suite had truncates instead of letting the unnamed ones through.

AND THE ALLOWANCE HAS A CEILING, because an escape hatch with only a reason is one somebody widens.
:data:`SKIP_CEILING` caps the SHARE of the accounted run that may be skipped at all, however much
was declared -- a project past it fixes tests rather than declaring more. It is also what stops the
vacuous satisfaction of this rule: ``_summary_shortfall``'s collected-versus-accounted check does
NOT catch a suite that skips everything, because a skipped test IS accounted for in the summary, so
a project could otherwise declare its whole suite and settle a PASS having executed nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lab_commons.file_io import read_toml

__all__ = ['SKIP_CEILING', 'MalformedAllowance', 'StepReport', 'declared_skips', 'read_pytest', 'read_ruff']

#: The most of a run that may be skipped before nothing can settle, whatever was declared. A RATIO
#: rather than a count, so it means the same thing to a 40-test repo and a 3000-test one -- and a
#: ratio between two operating points is the shape ``taste.md`` requires of an escape hatch. A tenth
#: is this family's number: past it the declaration has stopped being a list of known holes and has
#: become the way the suite is run.
SKIP_CEILING: Final = 0.10

#: pytest's documented exit codes, and what each one means for a PROOF. 0 and 1 are the only two
#: that describe a run which reached its tests; every other one is a reason the run was cut short,
#: and it is named rather than folded into "non-zero".
_PYTEST_EXITS: Final[dict[int, str]] = {
    2: 'pytest exit 2: the run was interrupted by the user or an internal condition',
    3: 'pytest exit 3: an internal error happened while running tests',
    4: 'pytest exit 4: pytest was misused, so the selection it ran is not the one asked for',
    5: 'pytest exit 5: NO TESTS WERE COLLECTED, which is not the same as none failing',
}

#: The summary line's ``<count> <word>`` pairs. Searched for anywhere on the line so the ``=``
#: rule that usually decorates it is not part of the grammar a reader has to reproduce.
_COUNT = re.compile(r'(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b')

#: The words that mean a selected test PRODUCED an outcome. ``skipped`` and ``deselected`` are
#: deliberately absent: neither ran, and the floor below is the one thing standing between a suite
#: that skipped everything and a green verdict over zero executed tests.
_OUTCOME_WORDS: Final[tuple[str, ...]] = ('passed', 'failed', 'error', 'xfailed', 'xpassed')

#: A node id named as a failure or an error in pytest's short summary.
_FAILED_NODE = re.compile(r'^(?:FAILED|ERROR)\s+(\S+)')

#: One ``-rs`` short-summary line: the number of skips grouped there, and WHERE they are.
_SKIPPED = re.compile(r'^SKIPPED \[(\d+)\]\s+(.+?):\s', re.MULTILINE)

#: ``collected 307 items`` / ``collected 307 items / 3 errors``.
_COLLECTED = re.compile(r'collected\s+(\d+)\s+item')

#: The banner pytest prints when it stops early. The word alone is enough -- it appears in
#: ``!!!! Interrupted: 3 errors during collection !!!!`` and in the KeyboardInterrupt banner, and
#: both mean the same thing to a proof.
_INTERRUPTED = re.compile(r'^!+\s*(?:Interrupted|KeyboardInterrupt)\b.*', re.MULTILINE)

#: Collection that failed BEFORE any test ran, in pytest's own words.
_COLLECTION_ERRORS = re.compile(r'(\d+)\s+errors?\s+during\s+collection')


class MalformedAllowance(ValueError):
    """``[tool.lab_commons.verify] allowed_skips`` is present but is not a list of strings.

    ITS OWN CLASS, and a REFUSAL rather than a fallback to the empty list. A declaration the reader
    could not parse is the dominant defect in this family: the project believes it declared its
    skips, the tool believes none were declared, and every skip in the suite then truncates a run
    the author thinks they exempted -- or, if the direction of the mistake ran the other way, an
    undeclared skip passes. Neither is a state a silent default may put a repo in.
    """


@dataclass(frozen=True, slots=True)
class StepReport:
    """What ONE step of the verify run contributed to the proof. Three named sets, no verdict.

    ``reported`` is what produced an OUTCOME -- the step's own name once it ran to a readable exit
    status, plus (for pytest) every node id the short summary attributed a failure to. ``failures``
    is a subset of it, because :class:`~lab_commons.dev.verdict.Result` refuses to name a failure
    that never reported: a test that failed something the run never reached is a hole, not a red.

    ``truncated`` is where INCONCLUSIVE comes from, and it is a NAMED SET rather than a flag for the
    reason ``integration.md`` records about count pins -- "it did not finish" and "three collection
    errors" have different remedies, and a reader who gets a boolean has to go and find out which.
    """

    name: str
    reported: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    truncated: tuple[str, ...] = ()


def declared_skips(root: Path) -> tuple[str, ...]:
    """The skip allowance *root*'s own ``pyproject.toml`` declares, as location PREFIXES.

    Read through :func:`lab_commons.file_io.read_toml`, which is this package's one TOML reader --
    a second reader is a second set of edge cases, and the family already decided which one it has.

    An ABSENT file, an absent ``[tool.lab_commons.verify]`` table and an absent ``allowed_skips``
    key all mean the same thing and all answer ``()``: nothing is declared, so every skip truncates,
    which is the behaviour every repo in the family has today. A PRESENT key of the wrong shape does
    NOT answer ``()`` -- see :class:`MalformedAllowance`.

    Raises:
        MalformedAllowance: the key is present and is not a list of strings.

    """
    manifest = root / 'pyproject.toml'
    if not manifest.is_file():
        return ()
    table = read_toml(manifest).get('tool', {}).get('lab_commons', {}).get('verify', {})
    if 'allowed_skips' not in table:
        return ()
    declared = table['allowed_skips']
    if not isinstance(declared, list) or not all(isinstance(entry, str) and entry.strip() for entry in declared):
        msg = (
            f'[tool.lab_commons.verify] allowed_skips in {manifest} is {declared!r}, which is not a '
            f'list of non-empty strings. It is read as PREFIXES of the location pytest prints for a '
            f'skip -- e.g. ["tests/test_vendor.py", "tests/test_slow.py:31"]. Refused rather than '
            f'defaulted to empty: a declaration nobody could parse would exempt nothing while its '
            f'author believed it exempted everything.'
        )
        raise MalformedAllowance(msg)
    return tuple(sorted(set(declared)))


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


def _summary_counts(text: str) -> dict[str, int] | None:
    """The LAST line carrying ``<count> <word>`` pairs, as a mapping. ``None`` when there is none.

    The last rather than the first: pytest prints per-file progress and a short summary above its
    final line, and both can carry the same shape. ``None`` is not "zero of everything" -- a run
    that printed no summary said nothing, and the caller must be able to tell the two apart.
    """
    for line in reversed(text.splitlines()):
        pairs = _COUNT.findall(line)
        if pairs:
            counts: dict[str, int] = {}
            for count, word in pairs:
                counts['error' if word.startswith('error') else word] = int(count)
            return counts
    return None


def _skip_shortfall(counts: dict[str, int], text: str, allowed: tuple[str, ...]) -> tuple[str, ...]:
    r"""The skip ratchet, BOTH directions, plus the ceiling and the naming floor.

    Pure over its arguments so the planted controls drive THIS function rather than a re-implemented
    agreement with it. Every reason names the specific locations on its side of the ratchet: a count
    cannot say WHICH test went quiet, and an allowance that is only a number is one a reader repairs
    by editing the digit.

    BOTH SIDES ARE NORMALISED TO FORWARD SLASHES BEFORE THEY ARE COMPARED, and that is measured
    rather than defensive: pytest prints ``SKIPPED [1] tests\\test_vendor.py:4`` on Windows and
    ``tests/test_vendor.py:4`` on Linux, so a declaration committed once -- in a repo four boxes
    share -- would match on one of them and silently truncate on the other. A verdict that depends
    on which machine ran it is not a verdict.
    """
    observed = {location.replace('\\', '/') for _, location in _SKIPPED.findall(text)}
    allowed = tuple(prefix.replace('\\', '/') for prefix in allowed)
    named = sum(int(count) for count, _ in _SKIPPED.findall(text))
    total_skipped = counts.get('skipped', 0)
    reasons: list[str] = []
    if named != total_skipped:
        reasons.append(
            f'the summary counts {total_skipped} skip(s) and the short summary names {named}: run '
            f'pytest with -rs, because a skip nobody named is one the allowance cannot be checked against'
        )
    undeclared = sorted(site for site in observed if not any(site.startswith(prefix) for prefix in allowed))
    if undeclared:
        reasons.append(
            f'skipped and not declared in [tool.lab_commons.verify] allowed_skips: {", ".join(undeclared)}. '
            f'A skip is a selected test that reported nothing; a known failure is an xfail with its residual.'
        )
    stale = sorted(prefix for prefix in allowed if not any(site.startswith(prefix) for site in observed))
    if stale:
        reasons.append(
            f'declared in allowed_skips and NOT skipped by this run: {", ".join(stale)}. Delete the '
            f'entry in the same edit that un-skipped it -- a waiver nothing uses is a hole that reads '
            f'as a decision.'
        )
    accounted = sum(counts.values())
    if total_skipped and accounted and total_skipped / accounted > SKIP_CEILING:
        reasons.append(
            f'{total_skipped} of {accounted} accounted test(s) were skipped, above the '
            f'{SKIP_CEILING:.0%} ceiling: past it the allowance has stopped being a list of known '
            f'holes and has become the way the suite is run'
        )
    return tuple(reasons)


def _summary_shortfall(counts: dict[str, int], text: str, failures: tuple[str, ...]) -> tuple[str, ...]:
    """Every non-skip way a summary line describes a run that cannot settle. Pure over its arguments."""
    reasons: list[str] = []
    if counts.get('error'):
        reasons.append(f'{counts["error"]} test(s) errored, and an errored test produced no outcome to attribute')
    named = counts.get('failed', 0)
    if named != len(failures):
        reasons.append(
            f'the summary names {named} failure(s) and the output names {len(failures)} node id(s); '
            f'a FAIL that cannot say which test was red is the refusal a count pin is'
        )
    if not any(counts.get(word) for word in _OUTCOME_WORDS):
        reasons.append('no test produced a pass or fail outcome, so the run executed nothing it could be judged on')
    if (collected := _COLLECTED.search(text)) and (total := sum(counts.values())) < int(collected.group(1)):
        reasons.append(
            f'pytest collected {collected.group(1)} item(s) and accounted for {total}: the difference '
            f'never reported, and a run that did not reach its selection cannot be promoted'
        )
    return tuple(reasons)


def read_pytest(text: str, *, returncode: int, allowed_skips: tuple[str, ...] = ()) -> StepReport:
    """The report for the pytest step, from what it PRINTED and what it exited with.

    THE ORDER OF THE QUESTIONS IS THE DESIGN. It does not ask "did something pass"; it asks what
    could have cut the run short, and only a text with no such reason is allowed to settle. That
    is what catches the measured ``optimi_lab`` case, where a clean-looking ``307 passed`` line and
    ``!!!! Interrupted: 3 errors during collection !!!!`` were in the SAME output -- a parser
    looking for the good news finds it, and the good news was about a run that executed nothing.

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
    * a skip on either side of *allowed_skips*, or a skip share above :data:`SKIP_CEILING`.
    """
    failures = tuple(dict.fromkeys(match.group(1) for line in text.splitlines() if (match := _FAILED_NODE.match(line))))
    counts = _summary_counts(text)
    truncated: list[str] = []

    if banner := _INTERRUPTED.search(text):
        truncated.append(f'pytest was interrupted: {banner.group(0).strip("! ").strip()}')
    if errors := _COLLECTION_ERRORS.search(text):
        truncated.append(f'{errors.group(1)} error(s) during collection: those tests were never run')
    if 'INTERNALERROR' in text:
        truncated.append('pytest reported an INTERNALERROR, so the run describes pytest and not the suite')
    if counts is None:
        truncated.append('pytest printed no parsable summary line, so there is nothing to read a result out of')
    else:
        truncated.extend(_summary_shortfall(counts, text, failures))
        truncated.extend(_skip_shortfall(counts, text, allowed_skips))
    if returncode in _PYTEST_EXITS:
        truncated.append(_PYTEST_EXITS[returncode])
    elif returncode not in (0, 1):
        truncated.append(f'pytest exited {returncode}, which is not an exit code pytest defines')

    if truncated:
        return StepReport(name='pytest', truncated=tuple(dict.fromkeys(truncated)))
    return StepReport(name='pytest', reported=('pytest', *failures), failures=failures)
