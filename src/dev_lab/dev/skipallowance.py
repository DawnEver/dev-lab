"""WHICH SKIPS A PROJECT MAY LIVE WITH: ``[tool.dev_lab.verify] allowed_skips``, both sides, and its ceiling.

Split from :mod:`dev_lab.dev.reports` (2026-11-15, module-size band) along the seam its docstring
already drew: the reports read what a step printed; this is the declaration a skip is judged against.

THE SKIP ALLOWANCE IS A TWO-SIDED RATCHET, and it is the part of this module with the most rope.
A skip is not an outcome (:class:`~dev_lab.dev.verdict.Proof` says so in its own words): it is a
selected test that told nobody anything. The strict reading -- any skip truncates the run -- is
correct and unusable across four repos, because a tool that answers INCONCLUSIVE on every invocation
forever stops being read, and a refusal nobody reads gets routed around instead of fixed. So a
project may DECLARE the skips it is living with, in its own ``pyproject.toml``::

    [tool.dev_lab.verify]
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
one line per skip. :func:`~dev_lab.dev.verifysteps.run_verify` passes it, and
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
from typing import TYPE_CHECKING, Final

from lab_commons.file_io import read_toml

from dev_lab.dev.family import declared_table

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    'SKIPPED',
    'SKIP_CEILING',
    'MalformedAllowance',
    'declared_skips',
    'skip_ceiling',
    'skip_shortfall',
    'stale_declarations',
    'stale_skips',
    'vanished_shortfall',
]

#: The most of a run that may be skipped before nothing can settle, whatever was declared. A RATIO
#: rather than a count, so it means the same thing to a 40-test repo and a 3000-test one -- and a
#: ratio between two operating points is the shape ``taste.md`` requires of an escape hatch. A tenth
#: is this family's number: past it the declaration has stopped being a list of known holes and has
#: become the way the suite is run.
SKIP_CEILING: Final = 0.10

#: One short-summary skip line, in the shape ``--no-fold-skipped`` prints it: the NODE ID, then the
#: reason. THE NODE ID SHAPE IS PART OF THE PATTERN AND NOT DECORATION, because a consumer's
#: ``addopts`` may carry ``-s``: a test's own stdout then lands in the same log, and a line somebody
#: PRINTED that happens to begin with the word would otherwise be read as a skip nobody declared.
#: Every node id pytest builds names a ``.py`` path, optionally followed by ``::`` parts, so that is
#: what is required here; the reason is not captured at all, because nothing an allowance declares
#: is about it.
SKIPPED = re.compile(r'^SKIPPED +(\S+\.py(?:::\S+)?)', re.MULTILINE)


class MalformedAllowance(ValueError):
    """``[tool.dev_lab.verify] allowed_skips`` is present but is not a list of strings.

    ITS OWN CLASS, and a REFUSAL rather than a fallback to the empty list. A declaration the reader
    could not parse is the dominant defect in this family: the project believes it declared its
    skips, the tool believes none were declared, and every skip in the suite then truncates a run
    the author thinks they exempted -- or, if the direction of the mistake ran the other way, an
    undeclared skip passes. Neither is a state a silent default may put a repo in.
    """


def declared_skips(root: Path) -> tuple[str, ...]:
    """The skip allowance *root*'s own ``pyproject.toml`` declares, as pytest NODE ID prefixes.

    Read through :func:`lab_commons.file_io.read_toml`, which is this package's one TOML reader --
    a second reader is a second set of edge cases, and the family already decided which one it has.

    An ABSENT file, an absent ``[tool.dev_lab.verify]`` table and an absent ``allowed_skips``
    key all mean the same thing and all answer ``()``: nothing is declared, so every skip truncates,
    which is the behaviour every repo in the family has today. A PRESENT key of the wrong shape does
    NOT answer ``()`` -- see :class:`MalformedAllowance`.

    Raises:
        MalformedAllowance: the key is present and is not a list of strings.

    """
    manifest = root / 'pyproject.toml'
    if not manifest.is_file():
        return ()
    table = declared_table(read_toml(manifest), 'verify', {})
    if 'allowed_skips' not in table:
        return ()
    declared = table['allowed_skips']
    if not isinstance(declared, list) or not all(isinstance(entry, str) and entry.strip() for entry in declared):
        msg = (
            f'[tool.dev_lab.verify] allowed_skips in {manifest} is {declared!r}, which is not a '
            f'list of non-empty strings. It is read as PREFIXES of the pytest NODE ID a skip is '
            f'reported at -- e.g. ["tests/test_vendor.py", "tests/test_vendor.py::test_a"]. Refused '
            f'rather than defaulted to empty: a declaration nobody could parse would exempt nothing '
            f'while its author believed it exempted everything.'
        )
        raise MalformedAllowance(msg)
    return tuple(sorted(set(declared)))


def skip_shortfall(
    counts: dict[str, int],
    text: str,
    allowed: tuple[str, ...],
    *,
    complete_skip_census: bool,
    recorded: frozenset[str] | None = None,
) -> tuple[str, ...]:
    r"""The skip ratchet, BOTH directions, and the per-stage naming floor.

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
    found = SKIPPED.findall(text) if recorded is None else list(recorded)
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
            f'skipped and not declared in [tool.dev_lab.verify] allowed_skips: {", ".join(undeclared)}. '
            f'A skip is a selected test that reported nothing; a known failure is an xfail with its residual.'
        )
    if complete_skip_census:
        reasons.extend(stale_skips(observed, allowed))
    return tuple(reasons)


def skip_ceiling(skipped: int, accounted: int) -> tuple[str, ...]:
    """Judge the unchanged share ceiling once over the whole executed selection's *skipped* of *accounted*."""
    if skipped and accounted and skipped / accounted > SKIP_CEILING:
        return (
            (
                f'{skipped} of {accounted} accounted test(s) were skipped, above the '
                f'{SKIP_CEILING:.0%} ceiling: past it the allowance has stopped being a list of known '
                f'holes and has become the way the suite is run'
            ),
        )
    return ()


def stale_skips(observed: set[str], allowed: tuple[str, ...]) -> tuple[str, ...]:
    """The STALE side of the skip ratchet over the *observed* skip sites of a complete census."""
    stale = sorted(prefix for prefix in allowed if not any(site.startswith(prefix) for site in observed))
    if not stale:
        return ()
    reason = (
        f'declared in allowed_skips and NOT skipped by this run: {", ".join(stale)}. Delete the '
        f'entry in the same edit that un-skipped it -- a waiver nothing uses is a hole that reads '
        f'as a decision.'
    )
    return (reason,)


def stale_declarations(root: Path, allowed: tuple[str, ...]) -> tuple[str, ...]:
    """Every declared entry whose SUBJECT has left the tree, read off the disk with no run at all.

    **THE ARM ``allowed_skips`` DID NOT HAVE**, and it is the sibling of the one a consumer's own
    docstring asks for beside ``_debt.COST_IS_CONDITIONAL``: *"a reason for a marker nobody carries
    is a hole ... A declaration whose subject left must leave with it."* That repo has the arm as a
    test of its own. This one had only the runtime ratchet in :func:`skip_shortfall`, which fires on
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


def vanished_shortfall(stale: tuple[str, ...]) -> tuple[str, ...]:
    """The refusal for a declaration whose SUBJECT left the checkout, read off the tree.

    Its own function because it is the one shortfall no step produced: every other reason in
    :func:`dev_lab.dev.verifysteps.run_verify` is read out of what a process PRINTED, and this one is
    read out of the files a declaration names -- so it binds before anything launches, and on a selected invocation too,
    where the run cannot judge anybody else's allowance retired.
    """
    if not stale:
        return ()
    reason = (
        f'declared in [tool.dev_lab.verify] allowed_skips and naming nothing in this checkout: '
        f'{", ".join(stale)}. An entry is read as a pytest NODE ID -- a module path, optionally '
        f'followed by ::test_name -- so one that resolves to no file names no test at all. Delete it '
        f'in the same edit that removed its subject, or point it at the name that replaced it.'
    )
    return (reason,)


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
