"""A ROSTER MAY NOT STORE A NUMBER IT COULD DERIVE -- the stale-reading guard for placement prose.

WHAT EARNED IT, MEASURED 2026-09-19 ACROSS THE FAMILY'S FOUR PLACEMENT ROSTERS. Every row of a
placement roster is ``path -> Placement(side, why)``, and the ``why`` is where the author records the
density reading that decided the side: ``MEASURED 2026-09-19: own=29 hits=0 -> 0.00%``. Those numbers
are DERIVABLE -- :func:`lab_commons.dev.famtests.density.measure_density` re-computes every one of
them from the file the row names -- and they are STORED, so they go stale the moment the file changes
and nothing anywhere notices. A sweep of the two labs read 66 rows quoting ``own=`` and found **38 of
them disagreeing with the live reading**, in a tree where every repo was GREEN. The worst were not
close: a row read ``own=142`` against a live 26, another ``own=77`` against 12, another ``own=88``
against 27.

THE DIRECTION IS THE FINDING AND IT IS NOT RANDOM. Most deltas are large and NEGATIVE -- the file
SHRANK when its kit adoption landed and the sentence describing it was never re-read -- so a roster
SYSTEMATICALLY OVER-STATES the work it has left. A progress meter that over-reports remaining work is
the one failure a green suite cannot show you, because nothing compares a stored number against its
derivation. That is this family's own named dominant defect, a declaration asserting a property the
code does not enforce, sitting inside the instrument that measures the migration.

A BLANKET "NO NUMBERS IN PROSE" RULE IS WRONG AND IS NOT WHAT THIS IS. Some readings in these rows
are quoted as EVIDENCE of how a bar was derived, or as the BEFORE half of a delta that is the whole
point of the sentence -- ``own=25 hits=0, down from own=36``. Erasing those would delete the
derivation the row exists to carry. So the deliverable is not a ban on numbers; it is a rule that can
TELL A LIVE CLAIM FROM A DATED HISTORICAL ONE, and re-derives only the first kind.

THE RULE, and it is honest because it defaults to CONVICTING rather than excusing:

* Claims are read in GROUPS -- a maximal run of readings separated by nothing but whitespace and
  punctuation. ``own=29 hits=0 -> 0.00%`` is one group, because that is how every author in the
  corpus writes a reading, and a percentage belongs to the pair it was computed from.
* A group is HISTORICAL if a marker from :data:`HISTORICAL_MARKERS` sits within
  :data:`MARKER_WINDOW` characters in front of it (``down from``, ``up from``, ``THE OLD ROW READ``),
  or if the date attached to it is SUPERSEDED by a later date on a group quoting the same spelling in
  the same row.
* ``own=86 -> 39`` is a DELTA and is read as both: the left number is that row's history and the
  right one is its live claim. Five rows in the corpus write a change this way rather than with a
  marker word, and reading only the left number would have convicted the author of storing a figure
  the sentence itself says is former. The arrow is distinguished from a percentage by what follows
  it, which is why :data:`PERCENT` is matched first.
* Every other group is a claim about NOW, and must equal the live derivation. **Silence is a live
  claim.** An author who writes a number and marks nothing has asserted it of the file as it stands,
  which is exactly what the 38 stale rows did.
* A marker-historical group must be DATABLE -- some date must precede it in the row. History nobody
  can place is not evidence, and without this arm ``down from`` is a two-word amnesty on any number.

THE RATCHET'S OTHER SIDE IS :func:`assert_history_is_dated`'s second half, and it is the arm that
makes the first one unavoidable: a row that quotes a spelling ONLY historically has no live reading
left, which is what marking everything ``down from`` would buy. A row that records history must
record the present too.

EQUALITY, NEVER ``<=``. A stored ``own=25`` against a live 29 and a stored ``own=402`` against a live
453 are the same defect in opposite directions, and this family has just paid for the asymmetric form
twice -- six wrong constants hidden by a ``declared <= live`` guard in one week, and a
``parameters.keys() >= {...}`` in two repos that could not see a parameter added.

THE FLOOR IS NOT DECORATION HERE AND THE INCIDENT IS THIS MODULE'S OWN. The first sweep of this
question wrapped its measurement in ``except Exception: continue``, swallowed a ``TypeError`` on
every single row, and printed ``DISAGREE=0``. A bare except made a broken scan report a clean tree.
:func:`assert_stored_readings_are_live` binds a floor on LIVE CLAIMS READ before it judges one, and
:func:`claims_in` raises rather than returning empty when handed a spelling set that cannot fire --
finding nothing is what a broken extractor returns, and it is indistinguishable from a fixed roster.

NOT :mod:`lab_commons.dev.famtests.placement`, which is the roster's OTHER four arms: that one reads
the manifest's KEYS against a walk and bounds two bars against readings passed to it; it never opens a
row's ``why`` and has no opinion about prose. NOT :mod:`~lab_commons.dev.famtests.density` either,
which is the METER -- it computes a reading and judges nothing. This is the only body in the package
that asserts a SENTENCE agrees with a MEASUREMENT, and it needs both of those modules to do it.

SCOPE, STATED SO A READER DOES NOT SUPPLY "EVERYTHING". This reads ``Placement.why`` prose and the
labelled spellings a density reading is written in. It does NOT read the module-level CALIBRATION
comments (``ADMIT scripts/dep.py own= 22 repo=1``) that bound a roster's ceiling: those are dated
readings of a bar's derivation, they are not attached to a row, and
:func:`lab_commons.dev.famtests.placement.assert_ceiling_is_bounded` already makes the pair an
argument. It also does not read population counts -- ``23 rows``, ``49 modules``, ``79 tracked
paths`` -- because none of them is derivable from the file the row names, and a guard that guessed at
them would convict prose it cannot re-measure.

ONE SPELLING IN THE CORPUS IS READ IMPRECISELY AND IT IS NAMED HERE RATHER THAN QUIETLY WIDENED FOR.
``own=95 project=2 -> 2.11%, then own=72 project=2 -> 2.78%`` retires its first reading with the word
``then``, under a single date, so neither :data:`HISTORICAL_MARKERS` nor supersession sees it and both
halves read as live. The row is still convicted -- two contradictory readings of NOW cannot both agree
-- and the refusal names both, so the author is told the truth even though the reason is one step off.
It is ONE site in four rosters, and a marker keyed on ``then`` would mark the wrong half: the word
sits in front of the CURRENT reading, not the former one. The remedy belongs in the prose, which is
what ``down from`` already spells, and inventing a rule for a single sentence is how a reader stops
being explainable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from lab_commons.dev import floors

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

__all__ = [
    'HISTORICAL_MARKERS',
    'MARKER_WINDOW',
    'PERCENT',
    'Claim',
    'NoSpellings',
    'StaleReading',
    'UndatedHistory',
    'assert_history_is_dated',
    'assert_stored_readings_are_live',
    'assert_the_reader_still_convicts',
    'claims_in',
    'disagreements',
]

#: The spelling a DERIVED PERCENTAGE takes in every roster in the family -- ``-> 7.46%`` -- written as
#: an arrow rather than as ``key=value`` because it is not a labelled reading but the quotient of the
#: two beside it. A member of the ``spellings`` set like any other, so a repo that does not write
#: percentages simply omits it and no arm silently looks for one.
PERCENT: Final = '%'

#: The words the corpus actually uses to mark a number as a FORMER reading, measured 2026-09-19 by
#: reading the 70 characters in front of all 168 labelled claims in the two labs' rosters: 25 of them
#: are ``down from``/``up from`` and one is ``THE OLD ROW READ``. Matched case-insensitively. A NAMED
#: SET rather than a heuristic, because the alternative -- "any sentence that sounds retrospective" --
#: is an amnesty whose width nobody can state.
HISTORICAL_MARKERS: Final[tuple[str, ...]] = (
    'down from',
    'up from',
    'old row read',
    'was own=',
    'previously',
)

#: How far in front of a group a marker may sit and still govern it. Every marker in the corpus is
#: ADJACENT to its number; the window exists so a ``down from`` forty sentences earlier cannot excuse
#: a live claim. Narrow on purpose: the failure this width can cause is a FALSE CONVICTION, which the
#: author reads and fixes, where a wide one causes a silent pass.
MARKER_WINDOW: Final = 60

_DATE = re.compile(r'\b(\d{4}-\d{2}-\d{2})\b')


class NoSpellings(AssertionError):
    """A reader was handed no spelling to look for, so every row it reads has nothing in it."""


class StaleReading(AssertionError):
    """A row quotes a reading as CURRENT that disagrees with re-deriving it from the file it names."""


class UndatedHistory(AssertionError):
    """A row marks a reading as former without a date to place it at, or keeps only history."""


@dataclass(frozen=True)
class Claim:
    """One number a row's prose quotes, with everything needed to judge it. A READING, not a verdict.

    Attributes:
        spelling: which reading it is -- a key such as ``own``, or :data:`PERCENT`.
        value: the number as written.
        text: the exact substring, so a refusal can quote the row back to its author rather than
            describe it.
        at: the date this group is attached to -- the last one appearing before it in the row -- or
            ``None`` when the row carries no date at all before this point.
        historical: whether this claim describes a FORMER state.
        why: how it was classified -- ``'live'``, ``'marker'``, ``'superseded'`` or ``'arrow'``.

    """

    spelling: str
    value: float
    text: str
    at: str | None
    historical: bool
    why: str


def _marker_in(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in HISTORICAL_MARKERS)


def _pattern(spellings: frozenset[str]) -> re.Pattern[str]:
    keys = sorted(spelling for spelling in spellings if spelling != PERCENT)
    alternation = '|'.join(re.escape(key) for key in keys)
    alternatives = []
    if keys:
        # THE DELTA FIRST, because `own=86 -> 39` also matches the bare-key form and the left number
        # alone is the wrong reading of it.
        alternatives.append(
            rf'(?P<dkey>{alternation})\s*=\s*(?P<dold>\d+(?:\.\d+)?)\s*->\s*(?P<dnew>\d+)(?![\d.]*\s*%)'
        )
        alternatives.append(rf'(?P<key>{alternation})\s*=\s*(?P<kv>\d+(?:\.\d+)?)')
    if PERCENT in spellings:
        alternatives.append(r'->\s*(?P<pv>\d+(?:\.\d+)?)\s*%')
    return re.compile('|'.join(alternatives), re.IGNORECASE)


#: ``(spelling, value, text, start, end, forced_historical)`` -- one raw reading, before a group is
#: dated or a marker read. The last field is the ARROW DELTA's left half, which is history by the
#: sentence's own grammar rather than by anything around it.
_Reading = tuple[str, float, str, int, int, bool]


def _readings_in(why: str, *, pattern: re.Pattern[str]) -> list[_Reading]:
    found: list[_Reading] = []
    for match in pattern.finditer(why):
        groups = match.groupdict()
        text, start, end = match.group(0), match.start(), match.end()
        if groups.get('dnew') is not None:
            spelling = match.group('dkey').lower()
            found.append((spelling, float(groups['dold']), text, start, end, True))
            found.append((spelling, float(groups['dnew']), text, start, end, False))
        elif groups.get('kv') is not None:
            found.append((match.group('key').lower(), float(groups['kv']), text, start, end, False))
        elif groups.get('pv') is not None:
            found.append((PERCENT, float(groups['pv']), text, start, end, False))
    return found


def _grouped(why: str, *, found: list[_Reading]) -> list[list[int]]:
    """A new group starts where the gap since the previous reading cannot be the space inside one.

    A sentence end, a date, a marker word, or simply more prose than :data:`MARKER_WINDOW` all break
    the run. Splitting too eagerly costs a FALSE CONVICTION, which an author reads and fixes; joining
    too eagerly hands one group's marker to a reading it does not govern, which is silent.
    """
    grouped: list[list[int]] = []
    for index, entry in enumerate(found):
        previous_end = found[index - 1][4] if index else 0
        gap = why[previous_end : entry[3]]
        starts = not index or '.' in gap or bool(_DATE.search(gap)) or len(gap) > MARKER_WINDOW or _marker_in(gap)
        if starts:
            grouped.append([index])
        else:
            grouped[-1].append(index)
    return grouped


def claims_in(why: str, *, spellings: frozenset[str]) -> tuple[Claim, ...]:
    """Every numeric reading *why* quotes, each already classified live or historical.

    Args:
        why: one row's prose.
        spellings: the labelled readings this repo writes, plus :data:`PERCENT` if it writes
            percentages. NO DEFAULT: which keys a roster uses is a fact about that roster -- the two
            labs write ``own``, ``repo``, ``project`` and ``hits`` and do not agree on which -- and a
            guessed set does not raise, it finds nothing and reports the roster clean.

    Returns:
        The claims, in the order they appear.

    Raises:
        NoSpellings: *spellings* is empty or holds a blank string. Either makes every row read as
            carrying no claim, which is exactly what a fixed roster reads as.

    """
    spellings = frozenset(spellings)
    if not spellings or any(not spelling.strip() for spelling in spellings):
        msg = (
            'a stored-reading scan with no spelling to look for finds nothing in every row and '
            'reports the roster clean, which is indistinguishable from a roster with no stale number '
            "in it. Declare the keys this repo's rows are written in."
        )
        raise NoSpellings(msg)

    found = _readings_in(why, pattern=_pattern(spellings))
    grouped = _grouped(why, found=found)

    classified: list[tuple[str, float, str, str | None, bool, bool]] = [('', 0.0, '', None, False, False)] * len(found)
    for group in grouped:
        start = found[group[0]][3]
        dates = _DATE.findall(why[:start])
        at = dates[-1] if dates else None
        previous_end = found[group[0] - 1][4] if group[0] else 0
        marked = _marker_in(why[max(previous_end, start - MARKER_WINDOW) : start])
        for index in group:
            spelling, value, text, _, _, forced = found[index]
            classified[index] = (spelling, value, text, at, marked, forced)

    # SUPERSESSION, per spelling, over the groups that are not already former. A dated reading with a
    # later dated reading of the SAME spelling behind it in the same row is that row's own history.
    latest: dict[str, str] = {}
    for spelling, _, _, at, marked, forced in classified:
        if not (marked or forced) and at is not None:
            latest[spelling] = max(latest.get(spelling, ''), at)

    claims = []
    for spelling, value, text, at, marked, forced in classified:
        superseded = not (marked or forced) and at is not None and at < latest.get(spelling, '')
        kind = 'arrow' if forced else 'marker' if marked else 'superseded' if superseded else 'live'
        claims.append(
            Claim(
                spelling=spelling,
                value=value,
                text=text,
                at=at,
                historical=forced or marked or superseded,
                why=kind,
            )
        )
    return tuple(claims)


def _agrees(claim: Claim, live: float) -> bool:
    """A key is compared as written; a percentage at the precision the AUTHOR chose.

    Rounding to the author's own decimals is not a tolerance -- it is reading ``7.46%`` as the two
    decimals it is. A fixed epsilon here would be an absolute tolerance on a quantity whose scale the
    consumer chooses, which is the one constant class this family has a written rule about.
    """
    if claim.spelling != PERCENT:
        return claim.value == live
    _, _, decimals = claim.text.partition('.')
    places = len(re.sub(r'[^0-9]', '', decimals))
    return round(live, places) == round(claim.value, places)


def disagreements(
    rows: Mapping[str, str],
    *,
    spellings: frozenset[str],
    derive: Callable[[str], Mapping[str, float]],
) -> tuple[dict[str, tuple[tuple[Claim, float], ...]], int]:
    """Every LIVE claim that disagrees with re-deriving it, and how many live claims were READ.

    Args:
        rows: ``path -> why``. The paths are the roster's own keys, so *derive* is handed exactly what
            the row names and never a guess at it.
        spellings: see :func:`claims_in`.
        derive: the repo's own re-derivation, ``path -> {spelling: value}``. NO DEFAULT and no
            fallback to :func:`lab_commons.dev.famtests.density.measure_density`: which signals and
            which delegation homes a reading was taken under are the repo's answer, and a kit
            re-deriving under its own would report every row stale on the first run and be believed
            once.

    Returns:
        ``(path -> ((claim, live), ...), live_claims_read)``. The count is RETURNED rather than
        inferred, because a caller cannot tell "no disagreement" from "nothing read" without it -- and
        that is the exact shape of the vacuous zero this module was written after.

    Raises:
        KeyError: *derive* returned no value for a spelling a row quotes. NOT swallowed: a missing
            derivation is the scan failing, and a scan treating its own failure as agreement is the
            ``except Exception: continue`` that printed ``DISAGREE=0``.
        NoSpellings: see :func:`claims_in`.

    """
    stale: dict[str, tuple[tuple[Claim, float], ...]] = {}
    read = 0
    for path, why in rows.items():
        claims = [claim for claim in claims_in(why, spellings=spellings) if not claim.historical]
        if not claims:
            continue
        live = derive(path)
        bad = []
        for claim in claims:
            if claim.spelling not in live:
                msg = (
                    f'{path}: the row quotes {claim.text!r} and the re-derivation returned no '
                    f'{claim.spelling!r}. The scan could not answer, which is not the same as agreeing.'
                )
                raise KeyError(msg)
            read += 1
            if not _agrees(claim, live[claim.spelling]):
                bad.append((claim, live[claim.spelling]))
        if bad:
            stale[path] = tuple(bad)
    return stale, read


def assert_stored_readings_are_live(
    rows: Mapping[str, str],
    *,
    spellings: frozenset[str],
    derive: Callable[[str], Mapping[str, float]],
    floor: int,
    headroom: int,
    what: str,
) -> None:
    """EVERY UNMARKED NUMBER IN A ROW IS A CLAIM ABOUT NOW, and must survive re-derivation.

    Args:
        rows: ``path -> why``.
        spellings: see :func:`claims_in`.
        derive: see :func:`disagreements`.
        floor: the fewest LIVE claims this roster's prose may carry before the scan stops being a
            reading of it. NO DEFAULT.
        headroom: how far past *floor* the corpus may grow before the floor must be re-measured. NO
            DEFAULT, and it is the side no roster in this family ever wrote.
        what: names the roster, so a refusal says which one drifted. NO DEFAULT -- a default label
            does not raise, it MISDIRECTS.

    Raises:
        StaleReading: a live claim disagrees with its derivation.
        lab_commons.dev.floors.FloorUnmet: fewer live claims than the floor -- the extractor broke, or
            the roster stopped quoting its measurements, and both read identically to a clean sweep.
        lab_commons.dev.floors.SlackFloor: the floor has been outgrown past its headroom.
        lab_commons.dev.floors.FloorMisdeclared: the floor or the headroom refuses nothing.
        KeyError: see :func:`disagreements`.

    """
    stale, read = disagreements(rows, spellings=spellings, derive=derive)
    floors.assert_floor(read, floor=floor, what=f'{what} live stored readings')
    floors.assert_floor_still_binds(read, floor=floor, headroom=headroom, what=f'{what} live stored readings')
    if stale:
        lines = [
            f'  {path}: {claim.text!r} (taken {claim.at or "undated"}) but re-derives to {live:g}'
            for path, bad in sorted(stale.items())
            for claim, live in bad
        ]
        body = '\n'.join(lines)
        msg = (
            f'the {what} roster stores {len(lines)} reading(s) its own files no longer give:\n{body}\n'
            f'A derivable number written without a marker is a claim about the file AS IT STANDS. '
            f'RE-MEASURE and rewrite the sentence, or mark the old number as former with '
            f'{HISTORICAL_MARKERS[0]!r} and quote the new one beside it -- never edit the digit to '
            f'whatever makes this pass, and never delete the row. Expect most of these to read HIGH: '
            f'a file shrinks when its migration lands, so a stale roster over-states the work left.'
        )
        raise StaleReading(msg)


def assert_history_is_dated(
    rows: Mapping[str, str],
    *,
    spellings: frozenset[str],
    floor: int,
    what: str,
) -> None:
    """A FORMER READING MUST BE PLACEABLE, AND MAY NOT BE ALL A ROW HAS -- the ratchet's two sides.

    The first half keeps the marker honest: without a date, ``down from`` is two words excusing any
    number from re-derivation for ever, and an escape hatch needs a CEILING rather than just a reason.
    The second half is that ceiling. A row quoting a spelling ONLY in the past has no live reading left
    to be judged on, which is precisely what marking everything former would buy -- so a row that
    records history must record the present too.

    Args:
        rows: ``path -> why``.
        spellings: see :func:`claims_in`.
        floor: the fewest HISTORICAL claims the corpus must carry. NO DEFAULT, and it refuses the
            OTHER direction of vacuity: a roster whose prose has stopped recording deltas at all passes
            every arm above trivially, and the capability this module protects -- the derivation a row
            was written to carry -- has then disappeared without a red.
        what: names the roster. NO DEFAULT.

    Raises:
        UndatedHistory: a marked reading has no date before it, or a spelling appears only
            historically in a row.
        lab_commons.dev.floors.FloorUnmet: fewer historical claims than the floor.
        lab_commons.dev.floors.FloorMisdeclared: the floor refuses nothing.

    """
    undatable: list[str] = []
    orphaned: list[str] = []
    seen = 0
    for path, why in sorted(rows.items()):
        claims = claims_in(why, spellings=spellings)
        live_spellings = {claim.spelling for claim in claims if not claim.historical}
        for claim in claims:
            if not claim.historical:
                continue
            seen += 1
            if claim.at is None:
                undatable.append(f'  {path}: {claim.text!r} is marked former with no date in front of it')
            if claim.spelling not in live_spellings:
                orphaned.append(f'  {path}: {claim.spelling!r} appears only as history, with no current reading')
    floors.assert_floor(seen, floor=floor, what=f'{what} historical readings')
    if undatable or orphaned:
        body = '\n'.join(sorted(set(undatable)) + sorted(set(orphaned)))
        msg = (
            f'the {what} roster records history that cannot be placed, or that stands alone:\n{body}\n'
            f'A former reading is evidence only if a reader can say WHEN it was taken, and a row '
            f'keeping only history has marked its way out of being re-derived. Date the reading, and '
            f'quote the current one beside it.'
        )
        raise UndatedHistory(msg)


def assert_the_reader_still_convicts(*, spelling: str) -> None:
    """PLANT each shape this module exists to refuse, and prove the SHIPPED arms convict it.

    Every plant is a row this function writes, judged by the real :func:`claims_in`,
    :func:`assert_stored_readings_are_live` and :func:`assert_history_is_dated` -- nothing is stubbed.
    The one injected thing is *derive*, which MUST be injected because a planted row names no file:
    that is the boundary :mod:`lab_commons.dev.famtests.boxseat` and
    :mod:`lab_commons.dev.famtests.depdoor` already set, and it is stated rather than hidden.

    Args:
        spelling: one labelled reading this repo's rows are written in, e.g. ``'own'``. NO DEFAULT:
            the kit cannot plant a shape in a vocabulary it was not told, and a guessed key plants a
            row the reader cannot see and then reports the control passed.

    Raises:
        AssertionError: an arm failed to convict a planted violation, or convicted the clean row.

    """
    keys = frozenset({spelling, PERCENT})
    readings = {'agrees': {spelling: 12.0, PERCENT: 0.0}, 'stale': {spelling: 12.0, PERCENT: 0.0}}

    def derive(path: str) -> Mapping[str, float]:
        return readings[path]

    clean = {'agrees': f'MEASURED 2026-09-19: {spelling}=12 -> 0.00%, down from {spelling}=40 -> 5.00%.'}
    assert_stored_readings_are_live(clean, spellings=keys, derive=derive, floor=1, headroom=8, what='planted clean')
    assert_history_is_dated(clean, spellings=keys, floor=1, what='planted clean')

    stale = dict(clean, stale=f'MEASURED 2026-09-19: {spelling}=40 -> 5.00%.')
    _convicts(
        lambda: assert_stored_readings_are_live(
            stale, spellings=keys, derive=derive, floor=1, headroom=8, what='planted stale'
        ),
        refusal=StaleReading,
        saying='stale',
        missed=f'a row storing {spelling}=40 against a live 12 was admitted: the derivation is not being read.',
    )
    _convicts(
        lambda: assert_history_is_dated(
            {'agrees': f'{spelling}=12 -> 0.00%, down from {spelling}=40.'},
            spellings=keys,
            floor=1,
            what='planted undated',
        ),
        refusal=UndatedHistory,
        saying='no date',
        missed='a former reading with no date anywhere in its row was admitted: the marker is a free amnesty.',
    )
    _convicts(
        lambda: assert_history_is_dated(
            {'agrees': f'MEASURED 2026-09-19: down from {spelling}=40.'},
            spellings=keys,
            floor=1,
            what='planted history-only',
        ),
        refusal=UndatedHistory,
        saying='only as history',
        missed=f'a row quoting {spelling} only as history was admitted, so marking every number former buys a pass.',
    )
    _convicts(
        lambda: claims_in(clean['agrees'], spellings=frozenset()),
        refusal=NoSpellings,
        saying='no spelling',
        missed='an empty spelling set was accepted, so a mis-wired reader reports every roster clean.',
    )


def _convicts(
    arm: Callable[[], object],
    *,
    refusal: type[AssertionError],
    saying: str,
    missed: str,
) -> None:
    """Run *arm*, require it to raise *refusal*, and require the refusal to SAY what it convicted.

    The message check is the half that matters: an arm raising the right class about the wrong row is
    a control that passes on a coincidence, and this package has an arm whose whole subject is
    assertions searching for a token their own producer was handed.
    """
    caught: AssertionError | None = None
    try:
        arm()
    except refusal as raised:
        caught = raised
    if caught is None:  # pragma: no cover - reaching this means the guard stopped guarding
        raise AssertionError(missed)
    if saying not in str(caught):  # pragma: no cover
        msg = f'the refusal fired but says {str(caught)[:120]!r}, which does not name {saying!r}.'
        raise AssertionError(msg)
