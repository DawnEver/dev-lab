"""LATEST-DEPENDENCIES, the RESOLVED half -- what a checkout actually holds, read with no network.

WHAT THE CONSUMER'S FILE ASSERTS. Every repo in this family declares its dependencies as FLOATING
git URLs and ``>=`` floors, which is textually compliant with the never-pin rule -- and the RESOLVED
installs have frozen anyway. A declaration cannot see that: three floating requirements and a
resolution nailed three months ago are the same four lines of ``pyproject.toml``. MEASURED
2026-09-21 by reading three consumer checkouts' untracked ``uv.lock`` files: this library was
resolved at ``0.1.1 @ 5127b6d8`` with its remote **174 commits** ahead of that very revision, and
the two other libraries the family vendors sat **85** and **688** commits behind theirs. The cost
was already being paid, MEASURED the same day: one consumer's virtualenv held this library at
``0.1.1``, which predates ``lab_commons.dev`` entirely, so the pre-push hook that runs
``uv run --no-sync python -m lab_commons.dev.githooks bump-version`` died with
``ModuleNotFoundError`` and that checkout could not be pushed at all.

WHY THIS IS A FAMILY MODULE AND NOT A PER-REPO GUARD. The three drifts above are three different
repos holding three different frozen shas of the same two libraries, and the reading is identical in
all of them: a package name, what the lock says it resolved to, and what the source says today. What
differs per repo is its own lock path, its own tracked set and its own ceiling, and those arrive as
arguments.

THE NETWORK IS NOT IN THIS MODULE, AND THAT IS A STRUCTURAL CLAIM RATHER THAN A PROMISE.
:mod:`lab_commons.dev.famtests.upperbounds` refuses the network inside a verdict in its own words --
"a network call inside a blocking verdict makes every gate depend on somebody else's uptime, which is
the opposite of what a gate is for" -- and that refusal is CORRECT and is preserved here by
placement rather than by argument. This module imports no transport, no ``subprocess`` and no HTTP
client, and its guard asserts that over the import graph with a planted control. The refresher lives
in :mod:`lab_commons.dev.dep_observe`, which imports this module and never the reverse.

THE REFRESH IS BOUNDED, ITS FAILURE IS INCONCLUSIVE, AND IT MAY NEVER DEGRADE INTO A PASS. The
precedent above refuses the network because an unanswered call would decide the verdict; the shape
here inverts that, which is the whole reason the precedent does not apply. A LIVE answer is the
strongest arm this repo can have and the verdict takes it. A call that does NOT answer makes the
verdict INCONCLUSIVE -- :exc:`~lab_commons.dev.famtests.latestversions.FetchUnavailable`, a
non-``AssertionError`` -- and its remedy names the committed observation and its age. What is
refused is the third possibility, PASSING on a failed fetch: "PyPI was down, so we passed" hands the
verdict to somebody else's uptime just as surely as the defect ``upperbounds`` names, and it does so
silently, which is worse. Every call goes through :mod:`lab_commons.dev.netverb`, so it is bounded
by an attempt count and a wall and it reports a diagnosis rather than the word "blocked".

THE COMPARISON IS STRING EQUALITY AND THERE IS NO VERSION ORDERING ANYWHERE, deliberately.
``resolved != latest`` is the question, which the user's requirement states exactly -- not the
latest, fail -- and a comparator would be a second, unmeasured opinion about what "latest" means
across two ecosystems that spell it differently (a PEP 440 version, a forty-character git sha).
:mod:`packaging` is not imported, and this package's own gate refuses it: the dev layer is stdlib
plus tier 1.

WHAT THIS DOES NOT PROVE, and the first half of this is the statement a reader most needs.
``uv.lock`` is a **per-checkout, UNTRACKED cache**, not a shared declaration: it is gitignored
FAMILY-WIDE by user ruling and :func:`lab_commons.dev.doorcensus.assert_no_tracked_lock` refuses any
repo that commits one. So a reading taken here speaks for THIS checkout's resolution and cannot speak
for another box's -- two clones of one repo can hold two different locks, and a fresh clone with no
lock at all has no resolved state to judge, which is why every arm below is floored and a missing
lock REFUSES rather than reporting clean. What is shared is the OBSERVATION FILE, and that is what
makes two boxes' answers comparable. It does not prove the resolved package is the one that was
INSTALLED: that is the environment arm, which reads ``importlib.metadata`` and compares against the
lock, and a repo whose venv is stale in a way the lock does not record is blind to both arms. Nor
does it prove an exempted package is being tracked at all -- the exemption census is what keeps that
population visible, and it is a ceiling rather than a permission.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from importlib import metadata
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

__all__ = [
    'KINDS',
    'LOCK_NAME',
    'STALE_AFTER_DAYS',
    'Exemption',
    'Observation',
    'Observed',
    'Resolved',
    'UnreadableState',
    'environment_gap',
    'exemption_problems',
    'gap',
    'installed_versions',
    'read_observed',
    'resolved_lock',
    'staleness',
    'today',
]

#: The sources this family resolves a dependency from, and each one's IDENTITY -- what "the same
#: thing" means for it. A NAMED SET so a third source is a row rather than a branch, and so a
#: transport asked for a kind nobody declared refuses instead of guessing.
KINDS: Final[frozenset[str]] = frozenset({'index', 'remote'})

#: The lockfile ``uv`` writes. Untracked family-wide -- see this module's closing paragraph -- so a
#: reading of it is a reading of LOCAL state.
LOCK_NAME: Final = 'uv.lock'

#: How old a committed observation may be before it must be refreshed, in days. SEVEN, by user
#: ruling 2026-09-21: the ceiling exists to make a refresh happen on a schedule rather than at the
#: moment somebody notices, and a longer one is long enough for a dependency to move unnoticed.
STALE_AFTER_DAYS: Final = 7


class UnreadableState(RuntimeError):
    """A file this mechanism reads is PRESENT and cannot be read as the thing it claims to be.

    A refusal rather than an empty answer, because the two are not the same fact and only one of them
    is safe: an absent lock means "this checkout never resolved", which the floors report, whereas a
    corrupt one means "nobody read what is on disk", and returning an empty mapping would record it
    as the first.
    """


@dataclass(frozen=True, slots=True)
class Observed:
    """One package as a source answered it, and WHEN -- the row the shared baseline is made of.

    ``source`` is the LOCATOR a transport reads, not the endpoint it read: the PyPI project name for
    an ``'index'`` row and the git URL for a ``'remote'`` one. It is stored as the locator because the
    refresher has to be able to ask the same question again from the committed file alone, and an
    endpoint that has to be un-derived is a round trip nothing can check.
    """

    name: str
    latest: str
    observed_on: date
    kind: str
    source: str


@dataclass(frozen=True, slots=True)
class Resolved:
    """One package as a LOCK resolved it: what the source pins, and the version the lock records.

    ``identity`` and ``version`` are two different facts and both are needed. For a registry source
    they are the same string; for a git source the identity is the forty-character revision the URL
    carries and the version is whatever the build stamped, and it is the REVISION that answers "is
    this the latest", while the VERSION is what an installed distribution can be compared against.
    Collapsing them would silently compare a sha against a version, which is the one comparison this
    module refuses to make.
    """

    name: str
    version: str
    identity: str
    source: str


@dataclass(frozen=True, slots=True)
class Exemption:
    """A dependency deliberately not tracked to the latest, with the two facts that keep it visible.

    A REVIEW DATE rather than only a reason, because a reason is prose nobody has to revisit and the
    family's ESCAPE-HATCH-CEILING rule is exactly that an escape hatch needs a date or a ratio, never
    just a sentence. The ceiling on the SET is judged beside it, by :func:`exemption_problems`.
    """

    reason: str
    review_on: date


@dataclass(frozen=True, slots=True)
class Observation:
    """What a live refresh ANSWERED and what it could not, as one object with two named halves.

    The halves are separate because they are acted on differently and by different callers: the
    refresher refuses to write a file that is short, and the verdict is INCONCLUSIVE rather than
    green. A single mapping would collapse "PyPI said 0.25.2" with "PyPI said nothing", and the
    second of those is the answer that must never be read as a pass.
    """

    answered: Mapping[str, Observed]
    failed: Mapping[str, str]


def today() -> date:
    """The day a reading is taken on, read in UTC.

    Injected everywhere rather than called at each site, so a control can drive a date without a
    clock -- and re-exported here because ``date.today()`` resolves against the BOX's timezone, which
    makes a stamped observation a fact about where it was taken.
    """
    return datetime.now(tz=UTC).date()


def read_observed(path: Path) -> dict[str, Observed]:
    """The committed observation, keyed by distribution name. Missing is EMPTY, present is STRICT.

    Args:
        path: the observation file. It is a DECLARATION a repo commits, not a cache: a reader that
            found no file has found no declaration, and the caller's floor is what refuses that.

    Returns:
        ``{name: Observed}``, empty when the file does not exist.

    Raises:
        UnreadableState: the file exists and is not a readable observation -- bad TOML, no
            ``[observed]`` table, or a row missing a field. The alternative is returning an empty
            mapping, which is indistinguishable from "nothing was ever observed" and is exactly the
            vacuous green this family refuses.

    """
    if not path.is_file():
        return {}
    try:
        table = tomllib.loads(path.read_text(encoding='utf-8'))
    except (OSError, tomllib.TOMLDecodeError) as broken:
        msg = (
            f'{path} exists and is not readable TOML ({broken}). A file that cannot be read is not a '
            f'file with nothing in it: re-run the refresher to rewrite it, or delete it and let the '
            f'floor refuse the checkout for having no shared baseline.'
        )
        raise UnreadableState(msg) from broken
    rows = table.get('observed')
    if not isinstance(rows, dict):
        msg = (
            f'{path} carries no [observed] table, so it declares no package at all. Every row of this '
            f'file is a package somebody decided to track; write one with the refresher rather than '
            f'leaving a file that reads as a complete answer over an empty set.'
        )
        raise UnreadableState(msg)
    return {name: _row(name, path, row) for name, row in rows.items()}


def _row(name: str, path: Path, row: object) -> Observed:
    """One ``[observed.<name>]`` table, or a refusal naming what that row is missing."""
    fields = row if isinstance(row, dict) else {}
    latest = str(fields.get('latest', '')).strip()
    kind = str(fields.get('kind', '')).strip()
    source = str(fields.get('source', '')).strip()
    stamped = str(fields.get('observed_on', '')).strip()
    if not (latest and kind in KINDS and source and stamped):
        msg = (
            f'{path}: the row for {name!r} is incomplete. A row needs latest, kind (one of '
            f'{sorted(KINDS)}), source and observed_on; a row that names only some of them asserts a '
            f'comparison nobody can perform.'
        )
        raise UnreadableState(msg)
    try:
        observed_on = date.fromisoformat(stamped)
    except ValueError as broken:
        msg = (
            f'{path}: the row for {name!r} is dated {stamped!r}, which is not an ISO date. The date is '
            f'the one field that makes the ceiling fire, and a date no parser accepts makes it never fire.'
        )
        raise UnreadableState(msg) from broken
    return Observed(name=name, latest=latest, observed_on=observed_on, kind=kind, source=source)


def resolved_lock(path: Path) -> dict[str, Resolved]:
    """Every package a ``uv.lock`` RESOLVED, keyed by name. Missing is EMPTY, present is STRICT.

    Args:
        path: the lock file. Untracked family-wide, so this reads LOCAL state and says so.

    Returns:
        ``{name: Resolved}``. A ``[[package]]`` whose source is neither a registry nor a git URL --
        the consumer's own project, an editable path, a local directory -- is SKIPPED, because
        "is this the latest" is not a question about a thing nobody publishes.

    Raises:
        UnreadableState: the file exists and is not readable TOML. A lock that cannot be parsed is
            not a lock with no dependencies in it.

    """
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding='utf-8'))
    except (OSError, tomllib.TOMLDecodeError) as broken:
        msg = (
            f'{path} exists and is not readable TOML ({broken}). The resolved state of this checkout '
            f'is unknown, which is not the same as the checkout having resolved nothing: re-run '
            f'`uv lock` here, or delete the file rather than leaving one that answers wrongly.'
        )
        raise UnreadableState(msg) from broken
    out: dict[str, Resolved] = {}
    for entry in data.get('package', []):
        name = str(entry.get('name', '')) if isinstance(entry, dict) else ''
        source = entry.get('source') if isinstance(entry, dict) else None
        if not name or not isinstance(source, dict):
            continue
        version = str(entry.get('version', ''))
        if 'git' in source:
            url, _, revision = str(source['git']).partition('#')
            out[name] = Resolved(name, version, revision, f'git:{url}')
        elif 'registry' in source:
            out[name] = Resolved(name, version, version, f'registry:{source["registry"]}')
    return out


def installed_versions(names: Iterable[str]) -> dict[str, str]:
    """What THIS interpreter's environment has installed for each of *names*, by distribution name.

    A name that is not installed is ABSENT from the answer rather than mapped to an empty string, so
    a caller can tell "the environment does not have it" from "it has it and the version is blank",
    which are different repairs. Nothing here reads the lock: this is the other side of the arm.
    """
    out: dict[str, str] = {}
    for name in names:
        try:
            out[name] = metadata.distribution(name).version
        except metadata.PackageNotFoundError:
            continue
    return out


def gap(name: str, resolved: str, observed: Observed | None) -> str | None:
    """Why *name* is not at the latest *observed* knew about, or ``None`` when it is.

    EXACT STRING EQUALITY, both ways round, because that is the requirement the user stated -- "not
    the latest, fail" -- and because a comparator would be a second, unmeasured opinion about an
    ordering that a PEP 440 version and a git revision do not share. The two identities must
    therefore be of the SAME kind, and a mismatch between them (an observation taken from a registry
    against a lock that resolved from git) is reported as the difference it is rather than smoothed.
    """
    if observed is None:
        return (
            f'{name}: resolved to {resolved!r}, and no live observation covers it. The fetch answered '
            f'about a set that does not include this package, so nothing here compared it to anything.'
        )
    if resolved == observed.latest:
        return None
    return (
        f'{name}: resolved to {resolved!r} and {observed.kind} {observed.source!r} states '
        f'{observed.latest!r} as of {observed.observed_on.isoformat()}. Move it to the latest, or '
        f'exempt it with a reason and a review date -- a floating requirement over a frozen '
        f'resolution is the drift this arm exists to catch.'
    )


def environment_gap(name: str, installed: str | None, resolved: Resolved) -> str | None:
    """Why the RUNNING environment disagrees with the lock about *name*, or ``None``.

    The second arm, and it is about a different question from :func:`gap`: not "is this the latest"
    but "is what is installed the thing this lock resolved". A lock is a declaration; a venv is what
    a verdict actually ran in, and this family already holds that the two can disagree silently.

    NO CLAIM IS MADE WHEN THE LOCK RECORDS NO VERSION -- a git source without a ``version`` key gives
    this arm nothing to compare against, and inventing a comparison would be the declaration that
    lies. That case returns ``None``, and is a LOWER BOUND on the arm rather than a passing one.
    """
    if not resolved.version or installed is None:
        return None
    if installed == resolved.version:
        return None
    return (
        f'{name}: this environment has {installed or "nothing installed"} and {resolved.source} '
        f'resolved {resolved.version!r}. The lock is a declaration and the venv is what a verdict ran '
        f'in, so a drift between them invalidates the verdict rather than ageing it: re-sync the '
        f'environment from this lock, or re-lock if the lock is what is behind.'
    )


def staleness(observed_on: date, today: date, *, ceiling_days: int = STALE_AFTER_DAYS) -> str | None:
    """Why an observation taken on *observed_on* may no longer be relied on, or ``None``.

    Args:
        observed_on: the date the observation carries.
        today: the day it is being read on.
        ceiling_days: how old it may be. The family's answer is :data:`STALE_AFTER_DAYS`, published
            and defaulted rather than repeated at each call site; a repo with a different cadence
            names its own.

    Returns:
        A sentence, or ``None``. A date in the FUTURE is refused rather than passed: it is a date
        nobody can check, and it would hold the ceiling off for as long as it is wrong.

    """
    age = (today - observed_on).days
    if age < 0:
        return (
            f'the shared baseline is dated {observed_on.isoformat()}, which is {-age} days AFTER '
            f'{today.isoformat()}. An observation can only be stamped on the day it was taken, so this '
            f'one was written by hand or by a clock that is wrong, and either way the ceiling below '
            f'can never fire on it.'
        )
    if age > ceiling_days:
        return (
            f'the shared baseline was observed {age} days ago, past the {ceiling_days}-day ceiling. '
            f'It is what two boxes compare against and what a reader falls back to when a fetch '
            f'fails, so refresh it with `python -m lab_commons.dev.dep_observe` and commit the result '
            f'in the same edit -- raising the ceiling is how the arm is kept while the guarantee '
            f'is given up.'
        )
    return None


def exemption_problems(
    exemptions: Mapping[str, Exemption],
    names: Iterable[str],
    *,
    today: date,
    ceiling: int,
) -> tuple[str, ...]:
    """Every problem with the exemption declaration, as a tuple -- empty when it holds.

    Args:
        exemptions: distribution name to its :class:`Exemption`.
        names: the packages the declaration actually TRACKS. Two-sided, like every ratchet here: an
            exemption naming a package nobody tracks is a waiver nothing uses, which reads as a
            decision while covering nothing.
        today: the day the review dates are judged against.
        ceiling: the largest exempt set this repo accepts. NO DEFAULT: an escape hatch needs a
            CEILING rather than a reason, and the number is the adopting repo's own.

    Returns:
        One sentence per problem, sorted by the name they are about, with the ceiling's own sentence
        FIRST because it is about the set rather than about a row.

    """
    out: list[str] = []
    if len(exemptions) > ceiling:
        out.append(
            f'{len(exemptions)} dependencies are exempt from the latest arm and the ceiling is '
            f'{ceiling}. An exemption is a deferral, not a permission: a set that grows without a '
            f'number on it is how the arm reaches zero with nothing having been fixed.'
        )
    known = set(names)
    for name in sorted(exemptions):
        exemption = exemptions[name]
        if not exemption.reason.strip():
            out.append(
                f'{name}: exempt with no reason recorded. The reason is what the next reader '
                f're-argues the exemption with, and an empty one records only that it exists.'
            )
        if exemption.review_on < today:
            out.append(
                f'{name}: exempt until {exemption.review_on.isoformat()}, which has passed. Re-argue '
                f'it and move the date, or remove it -- an exemption past its review date is the '
                f'waiver nothing uses, wearing a date that says it was checked.'
            )
        if name not in known:
            out.append(
                f'{name}: exempt, and not a package this declaration tracks. An exemption covering '
                f'nothing is indistinguishable from one covering something, and it is the first '
                f'shape that lets the real one through unnoticed.'
            )
    return tuple(out)
