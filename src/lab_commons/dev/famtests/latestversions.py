"""LATEST-DEPENDENCIES -- the resolved state against a LIVE latest, and a failed fetch is INCONCLUSIVE.

WHAT THE CONSUMER'S FILE ASSERTS. Every repo in this family declares its dependencies as FLOATING git
URLs and ``>=`` floors, which is textually compliant with the never-pin rule, and the RESOLVED
installs have frozen anyway. A declaration cannot see that: three floating requirements and a
resolution nailed months ago are the same four lines of ``pyproject.toml``. MEASURED 2026-09-21 by
reading three consumer checkouts' untracked ``uv.lock`` files: this library resolved at
``0.1.1 @ 5127b6d8`` with its remote **174 commits** ahead of that very revision, and the two other
libraries the family vendors **85** and **688** behind theirs. The cost was already being paid,
MEASURED the same day: one consumer's virtualenv held this library at ``0.1.1``, which predates
``lab_commons.dev`` entirely, so the pre-push hook that runs ``bump-version`` died with
``ModuleNotFoundError`` and that checkout could not be pushed at all.

WHY THIS IS A FAMILY MODULE AND NOT A PER-REPO GUARD. The three drifts above are three repos holding
three frozen shas of the same two libraries, and the reading is identical in all three. What is a
repo's own answer -- its tracked set, its exemption list and its ceilings -- arrives as keyword
arguments with no defaults, the shape every body in this package uses.

THE FETCH IS INSIDE THE VERDICT, AND THE PRECEDENT THAT REFUSES ONE DOES NOT APPLY -- which is the
claim this module has to make in those terms rather than by asserting an exception.
:mod:`lab_commons.dev.famtests.upperbounds` refuses a network call inside a blocking verdict because
"a network call inside a blocking verdict makes every gate depend on somebody else's uptime, which is
the opposite of what a gate is for". That refusal is CORRECT for what it guards and is preserved:
this is not a network call that DECIDES a verdict. The call is bounded -- every verb goes through
:mod:`lab_commons.dev.netverb`, which retries a bounded number of times behind a wall and reports a
diagnosis per attempt -- and its failure is :exc:`FetchUnavailable`, a non-``AssertionError`` that
carries INCONCLUSIVE, so a fetch that does not answer cannot be read as either a pass or a failure.
What ``upperbounds`` forbids is an unanswered call slipping INTO the verdict as one of its two
answers; here the third answer is where it lands, and it is named. The family has that tier already:
:mod:`lab_commons.dev.verify` returns 0/1/2 for PASS/FAIL/INCONCLUSIVE and its own docstring states
that collapsing the last two rebuilds the defect the algebra exists to end.

THE COMMITTED OBSERVATION IS A SHARED BASELINE AND NEVER A SILENT FALL-BACK. It is what two agents on
two boxes are comparing against when they say "the latest we knew", it is what a reader consults when
a fetch fails, and it is the declaration that fixes the SET of packages this repo tracks -- the live
fetch asks about exactly its rows, so a dependency nobody declared is a dependency nobody observes.
It is NOT the thing the resolved state is compared against: that comparison is against the LIVE
answer, which is the strongest arm available. The 7-day ceiling in
:func:`lab_commons.dev.depversions.staleness` still applies to it, and it is now the OFFLINE remedy --
a baseline too old to be a remedy is itself a finding -- rather than the arm that decides the
verdict. What is refused in every direction is the third possibility: PASSING on a failed fetch.
"PyPI was down, so we passed" hands the verdict to somebody else's uptime exactly as surely as the
defect ``upperbounds`` names, and it does so silently, which is worse.

THE TWO ARMS ANSWER DIFFERENT QUESTIONS AND NEITHER SUBSTITUTES FOR THE OTHER. Arm one is the
resolved lock against the live latest, by EXACT STRING EQUALITY -- never an ordering, because the
requirement is "not the latest, fail" and because a PEP 440 version and a forty-character git
revision do not share an ordering. Arm two is the RUNNING environment against that lock, read through
``importlib.metadata``: a lock is a declaration and the venv is what a verdict actually ran in, and a
drift between them invalidates a verdict rather than ageing it. Arm two makes NO CLAIM about a package
this environment does not have installed -- a lock resolves for markers and platforms a given box does
not satisfy, so an absent install is a fact about the box, not about the dependency.

THE READINGS LIVE IN :mod:`lab_commons.dev.depversions`, AND THAT IS THE SEAM THIS BODY RUNS ON. A
``famtests`` body usually splits its own pure readers out beside it -- ``_upperbounds_readings``,
``_citedtests_readings``, ``_storedreadings_readings`` -- and this one has none to split, which is
stated rather than left for a reader to wonder about. Reading a lock, an observation file and an
installed environment is the RUNTIME a repo CALLS, and its home is ``dev`` by this package's own
placement rule; what stays here is the verdict -- floors, declarations, refusals and remedies. The
boundary is :mod:`lab_commons.dev.famtests.depdoor`'s against :mod:`lab_commons.dev.dep`, which has
the same shape and no readings file either, and the import runs one way as it does there.

WHAT THIS DOES NOT PROVE, and the first half of this is what a reader most needs. ``uv.lock`` is a
**per-checkout, UNTRACKED cache** rather than a shared declaration -- gitignored family-wide by user
ruling, with :func:`lab_commons.dev.doorcensus.assert_no_tracked_lock` refusing any repo that commits
one -- so the whole of arm one and arm two is a guard on LOCAL resolved state. It cannot speak for
another checkout: two clones of one repo can hold two different locks, and in a fresh checkout with
no lock at all there is no resolved state to judge, which is why both populations are floored and an
absent lock REFUSES rather than reporting clean. The only shared file here is the baseline, and that
is what makes two boxes' answers comparable at all. Nor does a green run say the fetched answer is
CORRECT -- ``info.version`` is whatever PyPI calls latest and ``ls-remote`` reports a revision with no
opinion about it. Nor does the baseline's COMPLETENESS follow from anything in this module: a
dependency that nobody has written a row for is invisible here, and reading the consumer's manifest
for what it declares is :mod:`lab_commons.dev.famtests.upperbounds`' subject, on the same file, under
a rule this one does not restate.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from lab_commons.dev import depversions, floors
from lab_commons.dev.depversions import STALE_AFTER_DAYS, Exemption, Observation, Observed, Resolved, gap

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

__all__ = [
    'DependencyDrift',
    'Exemption',
    'Fetch',
    'FetchUnavailable',
    'LatestScan',
    'Observed',
    'Resolved',
    'assert_dependencies_are_latest',
    'assert_the_reader_still_convicts',
    'take_scan',
]

#: The seam a consumer hands its fetcher in through: the committed baseline goes in, and an
#: :class:`~lab_commons.dev.depversions.Observation` comes back. A CALLABLE rather than an import,
#: because that is what keeps every network verb outside this module's import graph -- the consumer
#: names :func:`lab_commons.dev.dep_observe.refresh`, or a planted stand-in a control drives.
Fetch = Callable[[Mapping[str, Observed]], Observation]


class DependencyDrift(AssertionError):
    """A resolved dependency is not the latest, a venv disagrees with its lock, or the baseline rotted."""


class FetchUnavailable(RuntimeError):
    """The live fetch did not answer for every tracked dependency, so nothing may be concluded.

    NOT an ``AssertionError``, and that is the whole point rather than a typing detail: this family
    reads an assertion failure as a named FAIL, and this is the third answer -- the run cannot say.
    A caller that turned it into a pass would be handing its verdict to somebody else's uptime; one
    that turned it into a failure would be reporting drift it never measured.
    """


@dataclass(frozen=True, slots=True)
class LatestScan:
    """One walk of a checkout: the declaration, the resolution, and what is actually installed.

    ``observation`` is carried so a refusal can name the file a reader should open when a fetch
    fails, and so a caller does not have to remember which path it passed.
    """

    observation: Path
    baseline: Mapping[str, Observed]
    resolved: Mapping[str, Resolved]
    installed: Mapping[str, str]


def take_scan(root: Path, *, observation: Path, installed: Mapping[str, str] | None = None) -> LatestScan:
    """Read a checkout once: its baseline, its lock, and the environment's side of arm two.

    Args:
        root: the consumer's checkout. The lock is ``root`` / :data:`lab_commons.dev.depversions.
            LOCK_NAME`, which is not a parameter because the tool that writes it fixes the name.
        observation: the COMMITTED baseline. A path rather than a name under *root*, because a repo
            may keep it wherever its own conventions put it and a guess would read the wrong file
            cleanly.
        installed: overrides what this environment reports, keyed by distribution name. The seam a
            control drives, so an arm about a venv disagreeing with a lock never needs one.

    Returns:
        A :class:`LatestScan`. A missing lock and a missing baseline are both EMPTY here rather than
        refused: they are facts about the checkout, and it is the verdict's floors that refuse them.

    """
    resolved = depversions.resolved_lock(root / depversions.LOCK_NAME)
    return LatestScan(
        observation=observation,
        baseline=depversions.read_observed(observation),
        resolved=resolved,
        installed=dict(installed) if installed is not None else depversions.installed_versions(resolved),
    )


def assert_dependencies_are_latest(
    scan: LatestScan,
    *,
    fetch: Fetch,
    exemptions: Mapping[str, Exemption],
    exemption_ceiling: int,
    floor: int,
    headroom: int,
    resolved_floor: int,
    resolved_headroom: int,
    what: str,
    today: date | None = None,
    ceiling_days: int = STALE_AFTER_DAYS,
) -> None:
    """THE CHECK. The offline arms first, then the live fetch, then the arm it decides.

    Args:
        scan: what :func:`take_scan` returned.
        fetch: the live refresh, called with the baseline and answering an
            :class:`~lab_commons.dev.depversions.Observation`. It is called ONLY when every offline
            arm holds, so a red that needs no network never spends one.
        exemptions: packages deliberately not tracked to the latest. NO DEFAULT, and it is judged
            before it is used -- a reason, a review date, a ceiling and a set of names that exist.
        exemption_ceiling: the largest exempt set this repo accepts, which is the escape hatch's
            ceiling rather than a reason.
        floor: the consumer's MEASURED count of rows in the committed baseline. NO DEFAULT.
        headroom: how far past it that population may grow before the floor is re-measured.
        resolved_floor: the MEASURED count of packages the lock resolves. NO DEFAULT, and it is what
            refuses a checkout whose lock is absent -- finding nothing is vacuous rather than green.
        resolved_headroom: the same band for that population.
        what: names the guard in the floor refusals. NO DEFAULT.
        today: the day the baseline's age and the exemptions' review dates are judged against, or
            ``None`` for the clock.
        ceiling_days: how old the committed baseline may be before it must be refreshed.

    Raises:
        lab_commons.dev.floors.FloorUnmet: a population is below its floor -- including the
            no-lock case, which is where a fresh checkout is refused rather than passed.
        lab_commons.dev.floors.SlackFloor: a floor has stopped binding.
        DependencyDrift: an offline arm or the live arm found a problem, all of them named.
        FetchUnavailable: the live fetch did not answer for every tracked package. INCONCLUSIVE.

    """
    day = today or depversions.today()
    observed_what = f'{what} (observed)'
    resolved_what = f'{what} (resolved)'
    floors.assert_floor(len(scan.baseline), floor=floor, what=observed_what)
    floors.assert_floor_still_binds(len(scan.baseline), floor=floor, headroom=headroom, what=observed_what)
    floors.assert_floor(len(scan.resolved), floor=resolved_floor, what=resolved_what)
    floors.assert_floor_still_binds(
        len(scan.resolved), floor=resolved_floor, headroom=resolved_headroom, what=resolved_what
    )
    tracked = {name for name in scan.baseline if name not in exemptions}
    offline = _offline(
        scan,
        exemptions=exemptions,
        day=day,
        ceiling_days=ceiling_days,
        exemption_ceiling=exemption_ceiling,
    )
    if offline:
        raise DependencyDrift(_drift(what, offline))
    live = fetch(scan.baseline)
    missing = sorted(tracked - set(live.answered))
    if missing:
        raise FetchUnavailable(_unavailable(scan, live, missing=missing, day=day, ceiling_days=ceiling_days))
    # `tracked` is a subset of the LOCK's names by construction: `_offline` above refuses a baseline
    # row this checkout does not resolve, so reaching here means every tracked name has a resolution.
    moving = [gap(name, scan.resolved[name].identity, live.answered[name]) for name in sorted(tracked)]
    drifted = [problem for problem in moving if problem]
    if drifted:
        raise DependencyDrift(_drift(what, drifted))


def _offline(
    scan: LatestScan,
    *,
    exemptions: Mapping[str, Exemption],
    day: date,
    ceiling_days: int,
    exemption_ceiling: int,
) -> list[str]:
    """Every problem an offline arm can find: the baseline's age, the lock, the venv and the waivers.

    THE AGE IS REPORTED ONCE, for the OLDEST row, rather than once per row: the ceiling is about the
    FILE -- a refresh rewrites every row from one fetch -- and a sentence per row would report one
    finding as many times as the baseline happens to be long.
    """
    out: list[str] = []
    oldest = min(scan.baseline.values(), key=lambda row: row.observed_on)
    stale = depversions.staleness(oldest.observed_on, day, ceiling_days=ceiling_days)
    if stale:
        out.append(f'{oldest.name}: {stale}')
    orphaned = sorted(set(scan.baseline) - set(scan.resolved))
    if orphaned:
        out.append(
            f'the shared baseline tracks {orphaned} and this checkout resolves none of them. A baseline '
            f'row outliving the dependency it names is a waiver nothing uses -- drop the row, or fix '
            f'the name it tracks.'
        )
    for name in sorted(scan.resolved):
        problem = depversions.environment_gap(name, scan.installed.get(name), scan.resolved[name])
        if problem:
            out.append(problem)
    out.extend(depversions.exemption_problems(exemptions, scan.baseline, today=day, ceiling=exemption_ceiling))
    return out


def _drift(what: str, problems: Sequence[str]) -> str:
    """The refusal, every problem named -- an offender list a reader triages rather than one at a time."""
    return (
        f'{what}: {len(problems)} problem(s) between what this checkout resolved, what this environment '
        f'has installed, and what the sources say today:\n  '
        + '\n  '.join(problems)
        + '\nA floating requirement over a frozen resolution is the drift no reading of the declaration '
        'can see. Move it to the latest, re-sync the environment from the lock, refresh the baseline, '
        'or exempt the package WITH a reason and a review date.'
    )


def _unavailable(
    scan: LatestScan,
    live: Observation,
    *,
    missing: Sequence[str],
    day: date,
    ceiling_days: int,
) -> str:
    """THE INCONCLUSIVE REFUSAL, naming the packages, the fetch's own diagnosis, and the baseline's age."""
    oldest = min(scan.baseline.values(), key=lambda row: row.observed_on)
    age = (day - oldest.observed_on).days
    said = '\n    '.join(f'{name}: {live.failed.get(name, "the fetch said nothing about it")}' for name in missing)
    return (
        f'the live fetch did not answer for {list(missing)} of the {len(scan.baseline)} packages this '
        f'repo tracks, so this run CANNOT say whether they are at the latest. That is INCONCLUSIVE and '
        f"not a pass: passing on an unanswered fetch hands this repo's answer to somebody else's "
        f'uptime, which is the same defect as asking the network to decide, arriving from the other '
        f'end. The fetch said:\n    {said}\n'
        f'Remedy: re-run it -- the verbs are bounded and retried, so a transient blip clears itself. If '
        f'it stays down, read the committed baseline {scan.observation}: its oldest row, '
        f'{oldest.name}, was observed {age} days ago against a {ceiling_days}-day ceiling, so a '
        f'baseline that has gone stale is a reason to refresh rather than one to lean on.'
    )


def _arm(scan: LatestScan, fetch: Fetch, *, day: date, what: str) -> None:
    """The verdict as the control drives it: no exemptions, floors measured against a planted tree."""
    assert_dependencies_are_latest(
        scan,
        fetch=fetch,
        exemptions={},
        exemption_ceiling=1,
        floor=2,
        headroom=100,
        resolved_floor=2,
        resolved_headroom=100,
        what=what,
        today=day,
    )


def _answered(day: date, **latest: str) -> Observation:
    """A planted fetch that answered for exactly the names given, each as an ``'index'`` row."""
    return Observation(
        answered={
            name: Observed(name=name, latest=value, observed_on=day, kind='index', source=name)
            for name, value in sorted(latest.items())
        },
        failed={},
    )


#: The planted lock: a REGISTRY source and a GIT source, because the two carry different identities
#: -- a version and a revision -- and an arm that only ever saw one of them would not prove the other
#: is read at all. The consumer's own project is in the file too, as an ``editable`` source that must
#: be SKIPPED: it is the one row whose presence proves the skip is real rather than untested.
_PLANTED_LOCK = """\
version = 1
[[package]]
name = "an-index-dep"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "a-remote-dep"
version = "0.1.1"
source = { git = "https://example.invalid/a-remote-dep.git#aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }

[[package]]
name = "this-checkout"
version = "0.0.0"
source = { editable = "." }
"""

_PLANTED_BASELINE = """\
[observed.an-index-dep]
latest = "1.0.0"
observed_on = "{day}"
kind = "index"
source = "an-index-dep"

[observed.a-remote-dep]
latest = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
observed_on = "{day}"
kind = "remote"
source = "https://example.invalid/a-remote-dep.git"
"""

#: The revision the planted remote resolves to, spelled once so the lock and the baseline cannot
#: disagree by a typo in a way that would make the MATCHING arm pass for the wrong reason.
_REVISION = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'


def assert_the_reader_still_convicts(plant_root: Path, *, observation_name: str, what: str) -> None:
    """THE PLANTED CONTROL, through the REAL scanner and the REAL verdict, in every direction at once.

    A guard that has never been shown to fire proves nothing when it is green, and the opposite error
    is as fatal: one that convicts everything gets deleted rather than obeyed. So all four answers are
    planted on one tree -- a package whose live answer MOVED must convict, a package whose live answer
    matches must NOT, a fetch that answers for ONE OF TWO must be INCONCLUSIVE rather than either of
    the other two, and a checkout with no lock at all must be REFUSED by the floor rather than
    reported clean.

    Args:
        plant_root: an empty directory to plant into -- a consumer's ``tmp_path``.
        observation_name: what this repo calls its committed baseline, so the control writes the file
            the consumer's own walk reads rather than a name of this module's choosing.
        what: names the guard in the floor refusals.

    Raises:
        AssertionError: an arm that should have convicted did not, or one that should not have did.

    """
    if any(plant_root.iterdir()):
        msg = f'{plant_root} is not empty, so this control would be reading another tree'
        raise AssertionError(msg)
    day = date(2026, 9, 21)
    observation = plant_root / observation_name
    (plant_root / depversions.LOCK_NAME).write_text(_PLANTED_LOCK, encoding='utf-8')
    observation.write_text(_PLANTED_BASELINE.format(day=day.isoformat()), encoding='utf-8')
    # TWO MAPPINGS, BECAUSE ARM ONE AND ARM TWO COMPARE DIFFERENT IDENTITIES. ``held`` is what the
    # venv reports, a VERSION for both packages; ``live`` is what the sources answer, a version for
    # the index row and a REVISION for the git one. A control that used one mapping for both would
    # have made arm two convict on the git row and proved nothing about arm one -- which is exactly
    # how this control failed the first time it was run.
    held = {'an-index-dep': '1.0.0', 'a-remote-dep': '0.1.1'}
    live = {'an-index-dep': '1.0.0', 'a-remote-dep': _REVISION}
    scan = take_scan(plant_root, observation=observation, installed=held)
    if sorted(scan.resolved) != ['a-remote-dep', 'an-index-dep']:
        msg = (
            f'the planted lock resolved {sorted(scan.resolved)}; the registry and git rows are the two '
            f'identities this arm is about, and the editable row -- a source that is this checkout '
            f'itself -- must be SKIPPED rather than judged against the latest of anything.'
        )
        raise AssertionError(msg)

    _must_refuse(
        scan,
        lambda _baseline: _answered(day, **dict(live, **{'an-index-dep': '2.0.0'})),
        day=day,
        what=what,
        tokens=('an-index-dep', '2.0.0'),
        why=(
            'a package resolved at 1.0.0 with the live index answering 2.0.0 was NOT convicted. That is '
            'the subject of this module: a declaration cannot see a frozen resolution, and a guard that '
            'cannot either is decoration.'
        ),
    )
    _must_not_convict(scan, lambda _baseline: _answered(day, **live), day=day, what=what)

    _must_be_inconclusive(
        scan,
        lambda _baseline: _answered(day, **{'an-index-dep': '1.0.0'}),
        day=day,
        what=what,
        tokens=('a-remote-dep', observation_name),
    )

    (plant_root / depversions.LOCK_NAME).unlink()
    without_lock = take_scan(plant_root, observation=observation, installed=held)
    _must_refuse_a_checkout_with_no_lock(without_lock, day=day, what=what)


def _must_refuse(
    scan: LatestScan,
    fetch: Fetch,
    *,
    day: date,
    what: str,
    tokens: Sequence[str],
    why: str,
) -> None:
    """Drive the REAL verdict and insist it refuses, with every planted token named in the refusal."""
    try:
        _arm(scan, fetch, day=day, what=what)
    except DependencyDrift as caught:
        absent = sorted(token for token in tokens if token not in str(caught))
        if absent:
            msg = f'the arm refused without naming {absent}, so a reader cannot tell what moved:\n{caught}'
            raise AssertionError(msg) from None
        return
    raise AssertionError(why)


def _must_not_convict(scan: LatestScan, fetch: Fetch, *, day: date, what: str) -> None:
    """THE OTHER SIDE OF THE RATCHET. A guard that refuses every correct tree is deleted, not obeyed."""
    try:
        _arm(scan, fetch, day=day, what=what)
    except DependencyDrift as caught:
        msg = (
            f'a package resolved at exactly what the live source answers was convicted:\n{caught}\n'
            f'A guard that convicts a correct tree is a guard that gets deleted rather than obeyed.'
        )
        raise AssertionError(msg) from None


def _must_be_inconclusive(
    scan: LatestScan,
    fetch: Fetch,
    *,
    day: date,
    what: str,
    tokens: Sequence[str],
) -> None:
    """A fetch that answered for SOME tracked packages must be INCONCLUSIVE, never either answer."""
    try:
        _arm(scan, fetch, day=day, what=what)
    except FetchUnavailable as caught:
        absent = sorted(token for token in tokens if token not in str(caught))
        if absent:
            msg = (
                f'the inconclusive refusal did not name {absent} -- the package that went unanswered or '
                f'the committed baseline to fall back on:\n{caught}'
            )
            raise AssertionError(msg) from None
        return
    msg = (
        'a fetch that answered for one of two tracked packages was read as an ANSWER. It must be '
        'INCONCLUSIVE: passing on an unanswered fetch is "the index was down so we passed", which hands '
        "the verdict to somebody else's uptime exactly as letting the network decide does."
    )
    raise AssertionError(msg)


def _must_refuse_a_checkout_with_no_lock(scan: LatestScan, *, day: date, what: str) -> None:
    """A fresh clone has no resolved state at all, so the only honest answer is to refuse it."""
    try:
        _arm(scan, lambda _baseline: _answered(day, **{'an-index-dep': '1.0.0'}), day=day, what=what)
    except floors.FloorUnmet:
        return
    msg = (
        'a checkout with no lock was judged. Reading nothing and reporting clean is the vacuous green '
        'every floor in this family exists to stop, and a fresh clone is exactly where it happens.'
    )
    raise AssertionError(msg)
