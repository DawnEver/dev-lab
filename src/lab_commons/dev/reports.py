"""What each verify step REPORTED, read out of the text it printed. Pure functions, no processes.

SPLIT OUT OF :mod:`lab_commons.dev.verify` at a real seam rather than at a line count. Everything
here is a pure function of a string and an integer; everything there launches a process, writes a
log or stamps a verdict. The consequence is the one that matters: the measured pytest output that
motivates this whole layer can be tested as a STRING CONSTANT, and the case that produced it --
``consumer_c``, 2026-09-15, 307 collected, 3 collection errors, ZERO run, and a ``307 passed``-shaped
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
* in a complete suite census, a skip DECLARED and not observed truncates it too. An allowance
  nothing uses is a hole that reads as a decision, and without this half the list only ever grows.

The default is an EMPTY list, so a project that declares nothing behaves exactly as it did before
the allowance existed. That is the property that makes this strictly stronger than the strict
reading rather than a loosening of it.

WHAT THE ALLOWANCE MATCHES, and there is exactly ONE spelling. Entries are PREFIXES of the pytest
NODE ID, matched with ``str.startswith``; ``tests/test_vendor.py`` covers every skip in that module
and ``tests/test_vendor.py::test_a`` pins one test.

**IT USED TO MATCH A ``path:line`` LOCATION, AND THE LINES MOVE.** MEASURED 2026-10-07 in a consumer:
a five-line comment inserted into a test file moved a skip from ``:101`` to ``:106`` and silently
invalidated a pin that had just been measured by hand; the repo's own list read 18 rows in one
checkout, 20 in a second and 21 in a third, and a stale pin makes every verdict from that checkout
INCONCLUSIVE. A location is not a name -- it is a fact about a file's layout, and it is reported
differently depending on HOW a skip is raised (a marker reports at the decorator, a module
``pytestmark`` at the ``def``, a helper at the helper, a fixture at the test). A node id is the name
of the test, and the edit that moves a line cannot reach it.

READING IT NEEDS ONE FLAG, and that is a MEASUREMENT rather than a preference. pytest FOLDS the skip
summary by default -- ``SKIPPED [2] tests/test_vendor.py:31: reason``, grouped by (file, line,
reason) with no node id anywhere in the line. ``--no-fold-skipped`` selects
``_pytest.terminal.show_skipped_unfolded`` instead, which prints ``SKIPPED <node id> - <reason>``,
one line per skip. :func:`~lab_commons.dev.verify.run_verify` passes it, and
``tests/test_dev_logdistil.py`` pins the line a LIVE pytest prints rather than a hand-written one.

WHAT A CONSUMER MUST DECLARE, AND HOW THE ROWS MIGRATE: nothing in the test code, and mechanically.
An old row truncates at the colon -- ``tests/x.py:31`` becomes ``tests/x.py``, which is a prefix of
every node id in that module -- and the refusal for an undeclared skip PRINTS the node ids, so
tightening a row to one test is a copy and paste. Tightening is worth it: a module-wide row cannot
say WHICH test went quiet, which is the whole argument for a named set over a count.

AND THE ALLOWANCE HAS A CEILING, because an escape hatch with only a reason is one somebody widens.
:data:`SKIP_CEILING` caps the SHARE of the accounted run that may be skipped at all, however much
was declared -- a project past it fixes tests rather than declaring more. It is also what stops the
vacuous satisfaction of this rule: ``_summary_shortfall``'s collected-versus-accounted check does
NOT catch a suite that skips everything, because a skipped test IS accounted for in the summary, so
a project could otherwise declare its whole suite and settle a PASS having executed nothing.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lab_commons.dev.pytestout import collected_count, markers_in, summary_counts
from lab_commons.file_io import read_toml

__all__ = [
    'SKIP_CEILING',
    'MalformedAllowance',
    'StepReport',
    'declared_skips',
    'read_pytest',
    'read_ruff',
    'stale_declarations',
]

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

#: The words that mean a selected test PRODUCED an outcome. ``skipped`` and ``deselected`` are
#: deliberately absent: neither ran, and the floor below is the one thing standing between a suite
#: that skipped everything and a green verdict over zero executed tests.
_OUTCOME_WORDS: Final[tuple[str, ...]] = ('passed', 'failed', 'error', 'xfailed', 'xpassed')

#: A node id named as a failure or an error in pytest's short summary.
_FAILED_NODE = re.compile(r'^(?:FAILED|ERROR)\s+(\S+)')

#: One short-summary skip line, in the shape ``--no-fold-skipped`` prints it: the NODE ID, then the
#: reason. THE NODE ID SHAPE IS PART OF THE PATTERN AND NOT DECORATION, because a consumer's
#: ``addopts`` may carry ``-s``: a test's own stdout then lands in the same log, and a line somebody
#: PRINTED that happens to begin with the word would otherwise be read as a skip nobody declared.
#: Every node id pytest builds names a ``.py`` path, optionally followed by ``::`` parts, so that is
#: what is required here; the reason is not captured at all, because nothing an allowance declares
#: is about it.
_SKIPPED = re.compile(r'^SKIPPED +(\S+\.py(?:::\S+)?)', re.MULTILINE)

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
    """The skip allowance *root*'s own ``pyproject.toml`` declares, as pytest NODE ID prefixes.

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
            f'list of non-empty strings. It is read as PREFIXES of the pytest NODE ID a skip is '
            f'reported at -- e.g. ["tests/test_vendor.py", "tests/test_vendor.py::test_a"]. Refused '
            f'rather than defaulted to empty: a declaration nobody could parse would exempt nothing '
            f'while its author believed it exempted everything.'
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


def _skip_shortfall(
    counts: dict[str, int], text: str, allowed: tuple[str, ...], *, complete_skip_census: bool
) -> tuple[str, ...]:
    r"""The skip ratchet, BOTH directions, plus the ceiling and the naming floor.

    Pure over its arguments so the planted controls drive THIS function rather than a re-implemented
    agreement with it. Every reason names the specific NODE IDS on its side of the ratchet: a count
    cannot say WHICH test went quiet, and an allowance that is only a number is one a reader repairs
    by editing the digit.

    BOTH SIDES ARE NORMALISED TO FORWARD SLASHES BEFORE THEY ARE COMPARED, and that is measured
    rather than defensive: pytest builds a node id with ``/`` but re-spells it against the invocation
    directory, so a declaration committed once -- in a repo four boxes share -- would match on one of
    them and silently truncate on the other. A verdict that depends on which machine ran it is not a
    verdict.

    THE RUNTIME HALF OF THE TWO-SIDED RATCHET, and it is the weaker half: the STALE side needs a
    complete suite census, so a selected invocation never checks it. :func:`stale_declarations` is
    the arm that binds without a run at all.
    """
    found = _SKIPPED.findall(text)
    observed = {node.replace('\\', '/') for node in found}
    allowed = tuple(prefix.replace('\\', '/') for prefix in allowed)
    named = len(found)
    total_skipped = counts.get('skipped', 0)
    reasons: list[str] = []
    if named != total_skipped:
        reasons.append(
            f'the summary counts {total_skipped} skip(s) and the short summary names {named}: run '
            f'pytest with -rfEs --no-fold-skipped, because a skip nobody named is one the allowance '
            f'cannot be checked against'
        )
    undeclared = sorted(site for site in observed if not any(site.startswith(prefix) for prefix in allowed))
    if undeclared:
        reasons.append(
            f'skipped and not declared in [tool.lab_commons.verify] allowed_skips: {", ".join(undeclared)}. '
            f'A skip is a selected test that reported nothing; a known failure is an xfail with its residual.'
        )
    stale = (
        sorted(prefix for prefix in allowed if not any(site.startswith(prefix) for site in observed))
        if complete_skip_census
        else []
    )
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


def stale_declarations(root: Path, allowed: tuple[str, ...]) -> tuple[str, ...]:
    """Every declared entry whose SUBJECT has left the tree, read off the disk with no run at all.

    **THE ARM ``allowed_skips`` DID NOT HAVE**, and it is the sibling of the one a consumer's own
    docstring asks for beside ``_debt.COST_IS_CONDITIONAL``: *"a reason for a marker nobody carries
    is a hole ... A declaration whose subject left must leave with it."* That repo has the arm as a
    test of its own. This one had only the runtime ratchet in :func:`_skip_shortfall`, which fires on
    a COMPLETE suite census and says nothing at all between runs -- MEASURED in that repo: an entry
    pinned at ``:39`` while the marker sat at ``:48``, *"an allowance for a location that no longer
    exists"*, and every verdict from a checkout with no clone reading INCONCLUSIVE until somebody
    re-measured by hand.

    A LOCATION could never be checked this way -- nothing but a run knows which line a skip is
    reported at -- and a NODE ID can: it names a module and a test that either exist or do not. That
    is the second thing the key change bought.

    AND IT IS WHY AN ALLOWANCE WRITTEN IN THE OLD SPELLING IS REFUSED AT ONCE RATHER THAN AFTER A
    TWENTY-MINUTE RUN. MEASURED over all four repos 2026-10-07: one consumer's 21 ``path:line`` entries
    are every one of them refused here, before any step launches, by name -- where the runtime
    ratchet would have reported them only at the end, mixed in with the very skips they were meant
    to cover.

    Resolving happens against *root*, and an entry reaching outside it is refused rather than read:
    an allowance is written by the repo it governs and has no business naming a file beyond it.

    Args:
        root: the checkout the declarations are resolved against.
        allowed: the entries as declared, in declaration order.

    Returns:
        The entries whose subject is gone, in the order declared. Empty is the only clean answer.

    """
    at = root.resolve()
    gone: list[str] = []
    for entry in allowed:
        module, _, node = entry.partition('::')
        target = (at / module).resolve() if module else at
        if (
            not module
            or not target.is_relative_to(at)
            or not target.exists()
            or (node and target.is_file() and not _names(target, node))
        ):
            gone.append(entry)
    return tuple(gone)


def _names(path: Path, node: str) -> bool:
    """Whether *path* defines every ``::``-separated part of *node*, ignoring a ``[param]`` suffix.

    A NAME CHECK AND NOT A COLLECTION, deliberately: this arm's subject is "is the declaration still
    about something", and the runtime ratchet above is the one that says whether pytest actually
    reached it. Anything more would need pytest, which is the thing this arm exists to do without.
    """
    try:
        tree = ast.parse(path.read_text('utf-8', errors='replace'))
    except (OSError, SyntaxError, ValueError):
        return False
    defined = {
        inner.name
        for inner in ast.walk(tree)
        if isinstance(inner, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    }
    return all(part.split('[', 1)[0] in defined for part in node.split('::'))


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
    if (collected := collected_count(text)) is not None and (total := sum(counts.values())) < collected:
        reasons.append(
            f'pytest collected {collected} item(s) and accounted for {total}: the difference '
            f'never reported, and a run that did not reach its selection cannot be promoted'
        )
    return tuple(reasons)


def read_pytest(
    text: str, *, returncode: int, allowed_skips: tuple[str, ...] = (), complete_skip_census: bool = True
) -> StepReport:
    """The report for the pytest step, from what it PRINTED and what it exited with.

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
    * a skip on either side of *allowed_skips*, or a skip share above :data:`SKIP_CEILING`.
    """
    failures = tuple(dict.fromkeys(match.group(1) for line in text.splitlines() if (match := _FAILED_NODE.match(line))))
    counts = summary_counts(text)
    truncated: list[str] = []

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
        truncated.extend(_summary_shortfall(counts, text, failures))
        truncated.extend(_skip_shortfall(counts, text, allowed_skips, complete_skip_census=complete_skip_census))
    if returncode in _PYTEST_EXITS:
        truncated.append(_PYTEST_EXITS[returncode])
    elif returncode not in (0, 1):
        truncated.append(f'pytest exited {returncode}, which is not an exit code pytest defines')

    if truncated:
        return StepReport(name='pytest', truncated=tuple(dict.fromkeys(truncated)))
    return StepReport(name='pytest', reported=('pytest', *failures), failures=failures)
