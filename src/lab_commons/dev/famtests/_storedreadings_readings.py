"""THE READER a stored-reading guard judges a row with -- the claims, never the verdict.

WHAT IT READS. Given one placement-roster row's ``why`` prose it answers WHICH numbers that sentence
quotes, what each one is a reading OF, what date it is attached to, and -- the whole difficulty --
whether it is a claim about NOW or a former reading the author deliberately kept. The verdicts over
it are :mod:`lab_commons.dev.famtests.storedreadings`, which states why the question exists at all
and re-exports every name here.

THE SEAM IS THE ONE ``configrender``, ``datedmemory``, ``citedtests`` and ``upperbounds`` already
run on, and it earns its keep the same way: a control can drive the JUDGING half over claims a test
SUPPLIES, so an arm is not confined to shapes the shipped reader happens to produce. It also keeps
the reader honest about being a READING -- nothing here raises over a stale number, and the only
refusal it makes at all is the vacuous one, an empty vocabulary that would report every roster in
the family clean.

THE SPELLINGS ARE DERIVED FROM THE CORPUS, NOT GUESSED. Measured 2026-09-19 over the two labs' and
motronics' four rosters: a labelled reading is written ``key=value`` in exactly four keys
(``own``, ``repo``, ``project``, ``hits``), a derived percentage as ``-> 7.46%``, and a change as
either ``down from``/``up from`` or as the arrow delta ``own=86 -> 39``. A regex invented in the
abstract finds none of that, and a scan that finds nothing reports a clean tree.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

__all__ = [
    'HISTORICAL_MARKERS',
    'MARKER_WINDOW',
    'PERCENT',
    'Claim',
    'NoSpellings',
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
