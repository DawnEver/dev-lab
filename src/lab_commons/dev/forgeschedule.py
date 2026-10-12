"""WHAT GETS PRODUCED, AND IN WHAT ORDER -- one work queue, derived from git and the forge, never stored.

Every candidate is a part a ref's newest commit lacks -- ``(repo, ref, sha, platform, scope)`` -- or an
issue REQUEST. Each has a numeric VALUE and an expected COST; a claimer takes the feasible candidate
with the highest SCORE, value per cost (weighted shortest job first)::

    value = base[class] + boost + aging_rate * wait_hours
    score = weight[repo] * value / expected_cost

``base`` is an OPEN table of classes (``integration``, ``pr``, ``branch``, ``request`` by family default),
``boost`` is what the user attached on the forge (a declared label such as ``priority:user``, or an
explicit ``priority:<n>``), and the aging term grows without bound, so no candidate starves forever.
``expected_cost`` is core-hours on a cluster and wall-hours on a box, predicted from what the
repository's last run measured (:mod:`lab_commons.hpc.learned`); unmeasured work is priced at a declared
prior. ``weight`` belongs to the HOST (its machine file's ``[schedule] weights``), so a host serving
several repositories decides how to share itself while each repository ranks its own work.

THE NUMBERS ARE DATA, declared once in ``[tool.lab_commons.schedule]``; :class:`Schedule` holds the
family default and a repository overrides key by key (a table key by table key)::

    [tool.lab_commons.schedule]
    classes = {integration = 100, pr = 60, branch = 30, request = 20}
    aging_rate = 10                  # value per hour waited
    starve_after_hours = {integration = 6, pr = 12, branch = 24, request = 48}
    daily_budget_core_h = {branch = 200}   # per ref of the class, per 24 h; absent = unbounded
    boosts = {"priority:user" = 1000}
    branches = ["exp/*"]             # opted-in child branches (fnmatch), class ``branch``
    prior_cost_h = 4.0

WHY A CANDIDATE IS NOT CLAIMED is always named (:class:`Ranked`.``blocked``): no host serves its
platform, over its ref's budget, no headroom here, or outranked. A candidate waiting longer than its
class's ``starve_after_hours`` is STARVED and raises a ``forgealarm`` naming that reason.

:func:`rank` is pure and is the only ordering rule: an optimiser replaces it without touching I/O.
"""

from __future__ import annotations

import dataclasses
import fnmatch
import os
import re
import subprocess
import tomllib
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from lab_commons.dev.cpuseat import CpuSeat
from lab_commons.dev.forge import _GIT, _GIT_TIMEOUT_S, AUTH_REFUSED
from lab_commons.dev.forgealarm import STARVED, Alarm
from lab_commons.dev.forgepulls import pr_list
from lab_commons.dev.forgework import Client, ForgeCallFailed
from lab_commons.dev.lanepolicy import Policy
from lab_commons.hpc.shell import FULL

__all__ = [
    'NO_HEADROOM',
    'NO_HOST',
    'OUTRANKED',
    'OVER_BUDGET',
    'Candidate',
    'Headroom',
    'Ranked',
    'Schedule',
    'boost_of',
    'box_headroom',
    'candidates',
    'declared_platforms',
    'expected_cost',
    'host_weights',
    'labelled_issues',
    'load_schedule',
    'parse_usage',
    'rank',
    'ref_usage',
    'repo_name',
    'starved',
    'starved_alarms',
    'tip_of',
    'value',
]

_TABLE: Final = 'schedule'

#: The class of each candidate source the family knows; a repository may add classes of its own.
INTEGRATION: Final = 'integration'
PR: Final = 'pr'
BRANCH: Final = 'branch'
REQUEST: Final = 'request'

#: Why a candidate is not claimed -- the prefix of :attr:`Ranked.blocked`.
NO_HOST: Final = 'no host'
OVER_BUDGET: Final = 'over budget'
NO_HEADROOM: Final = 'no headroom'
OUTRANKED: Final = 'outranked'

_PRIORITY: Final = re.compile(r'^priority:(?P<n>-?\d+(?:\.\d+)?)$')
_TRACKING: Final = 'refs/remotes/origin/'


@dataclass(frozen=True)
class Schedule:
    """``[tool.lab_commons.schedule]``: the family default; a repository overrides key by key."""

    classes: Mapping[str, float] = field(
        default_factory=lambda: {INTEGRATION: 100.0, PR: 60.0, BRANCH: 30.0, REQUEST: 20.0}
    )
    #: Value gained per hour a candidate waits -- the term that guarantees no class starves forever.
    aging_rate: float = 10.0
    starve_after_hours: Mapping[str, float] = field(
        default_factory=lambda: {INTEGRATION: 6.0, PR: 12.0, BRANCH: 24.0, REQUEST: 48.0}
    )
    #: Core-hours one ref of the class may use per 24 h; a class absent here is unbounded.
    daily_budget_core_h: Mapping[str, float] = field(default_factory=dict)
    #: Label -> value added; ``priority:<n>`` adds ``n`` without being declared.
    boosts: Mapping[str, float] = field(default_factory=lambda: {'priority:user': 1000.0})
    #: Opted-in child branches (fnmatch patterns), served as class ``branch`` beside the integration branch.
    branches: tuple[str, ...] = ()
    #: The label that makes an open issue a request.
    request_label: str = 'forge:request'
    #: The expected cost, in hours, of work nothing has measured yet.
    prior_cost_h: float = 4.0

    def base(self, kind: str) -> float:
        """The base value of class *kind*; an undeclared class is refused by name."""
        if kind not in self.classes:
            msg = f'class {kind!r} is not in [tool.lab_commons.{_TABLE}] classes {sorted(self.classes)}'
            raise ValueError(msg)
        return float(self.classes[kind])


def load_schedule(root: Path) -> Schedule:
    """*root*'s ``[tool.lab_commons.schedule]`` over the family default; an unknown key is refused."""
    manifest = root / 'pyproject.toml'
    declared: dict[str, Any] = {}
    if manifest.is_file():
        with manifest.open('rb') as handle:
            declared = tomllib.load(handle).get('tool', {}).get('lab_commons', {}).get(_TABLE, {})
    default = Schedule()
    known = {one.name for one in dataclasses.fields(Schedule)}
    unknown = sorted(set(declared) - known)
    if unknown:
        msg = f'[tool.lab_commons.{_TABLE}] in {manifest} has unknown key(s) {unknown}; the keys are {sorted(known)}'
        raise ValueError(msg)
    merged: dict[str, Any] = {}
    defaults = dataclasses.asdict(default)
    for key, given in declared.items():
        current = defaults[key]
        merged[key] = {**current, **given} if isinstance(current, Mapping) else given
    if 'branches' in merged:
        merged['branches'] = tuple(merged['branches'])
    return dataclasses.replace(default, **merged)


def host_weights(table: Mapping[str, Any]) -> dict[str, float]:
    """The machine file's ``[schedule] weights`` (repo ``owner/name`` -> multiplier); absent = 1 for all."""
    return {str(repo): float(weight) for repo, weight in dict(table.get('weights', {})).items()}


@dataclass(frozen=True)
class Candidate:
    """One unit of work waiting: a part a ref's newest commit lacks, or an issue request (``number``)."""

    repo: str
    ref: str
    sha: str
    platform: str
    kind: str
    since: datetime
    scope: str = FULL
    labels: tuple[str, ...] = ()
    number: int = 0

    @property
    def key(self) -> str:
        """How a host card and an alarm name it: ``<ref>@<sha12>:<platform>``."""
        return f'{self.ref}@{self.sha[:12]}:{self.platform}'


@dataclass(frozen=True)
class Ranked:
    """A candidate with its numbers, and why it is not claimed (``''`` = nothing blocks it)."""

    candidate: Candidate
    value: float
    cost_h: float
    score: float
    wait_h: float
    blocked: str = ''


def boost_of(labels: Sequence[str], schedule: Schedule) -> float:
    """The value the user attached: every declared label's boost plus every ``priority:<n>``."""
    total = 0.0
    for label in labels:
        if label in schedule.boosts:
            total += float(schedule.boosts[label])
        elif (found := _PRIORITY.match(label)) is not None:
            total += float(found['n'])
    return total


def value(candidate: Candidate, schedule: Schedule, now: datetime) -> float:
    """``base[class] + boost + aging_rate * wait_hours`` (module docstring)."""
    wait_h = max(0.0, (now - candidate.since).total_seconds() / 3600)
    return schedule.base(candidate.kind) + boost_of(candidate.labels, schedule) + schedule.aging_rate * wait_h


def expected_cost(measured: Mapping[str, Any], prior_h: float, *, cores: int = 1) -> float:
    """Hours one full run costs: the last run's measured core-seconds (durations + overheads) over *cores*.

    On a cluster *cores* is 1 (core-hours); on a box it is the box's cores (wall-hours). Nothing measured
    is *prior_h*.
    """
    seconds = sum(dict(measured.get('durations', {})).values()) + sum(dict(measured.get('overheads', {})).values())
    return seconds / 3600 / max(1, cores) if seconds > 0 else prior_h


def rank(
    candidates: Sequence[Candidate],
    schedules: Mapping[str, Schedule],
    now: datetime,
    *,
    cost_h: Mapping[str, float],
    weights: Mapping[str, float] | None = None,
) -> tuple[Ranked, ...]:
    """Every candidate scored and ordered, highest score first. PURE: the one ordering rule.

    *schedules* and *cost_h* are keyed by repo; *weights* by repo, 1 for a repo it omits.
    """
    weights = weights or {}
    ranked = []
    for one in candidates:
        schedule = schedules[one.repo]
        worth = value(one, schedule, now)
        cost = max(cost_h.get(one.repo, schedule.prior_cost_h), 1e-6)
        wait_h = max(0.0, (now - one.since).total_seconds() / 3600)
        ranked.append(Ranked(one, worth, cost, weights.get(one.repo, 1.0) * worth / cost, wait_h))
    return tuple(sorted(ranked, key=lambda item: (-item.score, item.candidate.since, item.candidate.key)))


def starved(ranked: Sequence[Ranked], schedules: Mapping[str, Schedule]) -> tuple[Ranked, ...]:
    """The blocked candidates that waited past their class's ``starve_after_hours``."""
    found = []
    for item in ranked:
        bound = schedules[item.candidate.repo].starve_after_hours.get(item.candidate.kind)
        if item.blocked and bound is not None and item.wait_h > bound:
            found.append(item)
    return tuple(found)


@dataclass(frozen=True)
class Headroom:
    """What this host can take on now: free cores, and job submissions its QOS still accepts (``None`` = no cap)."""

    cores: int
    submits: int | None = None

    def why_not(self) -> str:
        """``''`` when a run fits, else the reason (one core and one submission are the floor of any run)."""
        if self.cores < 1:
            return f'{NO_HEADROOM}: no free core here'
        if self.submits is not None and self.submits < 1:
            return f'{NO_HEADROOM}: the QOS accepts no more submissions'
        return ''


def box_headroom() -> Headroom:
    """A box's headroom: its cores, none while a run holds its CPU seat."""
    return Headroom(cores=0 if CpuSeat.holders() else os.cpu_count() or 1)


def starved_alarms(queue: Sequence[Ranked], schedule: Schedule, repo: str) -> list[Alarm]:
    """A ``starved`` alarm for every candidate of *queue* past its class's bound, naming why it waits."""
    return [
        Alarm(
            STARVED,
            repo,
            f'{item.candidate.key} is starved',
            f'class {item.candidate.kind} waited {item.wait_h:.1f} h, past its '
            f'{schedule.starve_after_hours[item.candidate.kind]:g} h bound; not claimed: {item.blocked}',
            about=item.candidate.key,
        )
        for item in starved(queue, {one.candidate.repo: schedule for one in queue})
    ]


def tip_of(root: Path, ref: str) -> str:
    """*ref*'s tip on ``origin`` as last fetched, ``''`` when it has none."""
    return _git(root, 'rev-parse', '--verify', '-q', f'{_TRACKING}{ref}')


def parse_usage(sacct: str) -> dict[str, float]:
    """``sacct -n -P -o JobName,CPUTimeRAW`` lines into core-hours per run job name's sha12 (``run-<sha12>``)."""
    used: dict[str, float] = {}
    for line in sacct.splitlines():
        name, _, seconds = line.partition('|')
        if name.startswith('run-') and seconds.strip().isdigit():
            used[name[4:]] = used.get(name[4:], 0.0) + int(seconds) / 3600
    return used


#: The sacct read of this account's last day, parsed by :func:`parse_usage`.
USAGE_COMMAND: Final = 'sacct -X -n -P -S now-24hours -o JobName,CPUTimeRAW'


def ref_usage(root: Path, ref: str, used: Mapping[str, float]) -> float:
    """Core-hours *ref*'s recent commits used in the last day (*used* keyed by sha12)."""
    if not used:
        return 0.0
    shas = _git(root, 'rev-list', '-n', '100', f'{_TRACKING}{ref}').split()
    return sum(used.get(sha[:12], 0.0) for sha in shas)


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        [_GIT, '-C', str(root), *args],
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=_GIT_TIMEOUT_S,
        check=False,
    )
    return done.stdout.strip() if done.returncode == 0 else ''


def _when(root: Path, sha: str, fallback: datetime) -> datetime:
    stamp = _git(root, 'show', '-s', '--format=%cI', sha)
    return datetime.fromisoformat(stamp).astimezone(UTC) if stamp else fallback


def _tips(root: Path) -> dict[str, str]:
    listed = _git(root, 'for-each-ref', '--format=%(refname) %(objectname)', _TRACKING)
    return {ref.removeprefix(_TRACKING): sha for ref, sha in (line.split(' ') for line in listed.splitlines() if line)}


def _labels(raw: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(label['name']) for label in raw.get('labels') or ())


def labelled_issues(client: Client, label: str) -> tuple[dict[str, Any], ...]:
    """Open issues carrying *label*, raw (pull requests excluded) -- one call shape on gitea and GitHub."""
    query = client.backend.list_query.format(state='open', limit=50) + '&labels=' + urllib.parse.quote(label)
    listed = client.call('GET', f'{client.repo}/issues?{query}')
    return tuple(raw for raw in listed if 'pull_request' not in raw and label in _labels(raw))


_REQUEST_PLATFORM: Final = re.compile(r'^\s*platform\s*=\s*["\'](?P<platform>[\w-]+)["\']', re.MULTILINE)


def optional[T](what: str, listing: Callable[[], Sequence[T]], say: Callable[[str], None]) -> Sequence[T]:
    """An OPTIONAL listing: one that fails is said and served as empty; a credential refusal still raises.

    The integration head and the claims are ESSENTIAL -- without them nothing can be produced, so they
    raise. Open PRs and request issues only ADD candidates: losing them must not cost the head its part.
    """
    try:
        return listing()
    except ForgeCallFailed as failed:
        if failed.report.attempts and failed.report.attempts[-1].returncode in AUTH_REFUSED:
            raise
        say(f'[serve] skipped the {what}: {failed}')
        return ()


def _part_refs(
    root: Path, mode: str, client: Client, schedule: Schedule, policy: Policy, *, say: Callable[[str], None]
) -> list[tuple[str, str, str, tuple[str, ...], int]]:
    """``(ref, newest sha, class, labels, PR number)`` of every ref *mode* serves."""
    tips = _tips(root)
    if mode != 'integrate':
        return [(b, s, BRANCH, (), 0) for b, s in sorted(tips.items()) if b.startswith(policy.lane_prefixes)]
    refs = [(policy.integration, tips[policy.integration], INTEGRATION, (), 0)] if policy.integration in tips else []
    for pull in optional('open pull requests', lambda: pr_list(client), say):
        sha = tips.get(pull.head, pull.head_sha)
        if pull.base == policy.integration and pull.head != policy.integration and sha:
            refs.append((pull.head, sha, PR, pull.labels, pull.number))
    served = {ref for ref, *_ in refs}
    refs += [
        (branch, sha, BRANCH, (), 0)
        for branch, sha in sorted(tips.items())
        if branch not in served and any(fnmatch.fnmatchcase(branch, one) for one in schedule.branches)
    ]
    return refs


def _requests(client: Client, repo: str, schedule: Schedule, now: datetime) -> list[Candidate]:
    found = []
    for raw in labelled_issues(client, schedule.request_label):
        declared = _REQUEST_PLATFORM.search(raw.get('body') or '')
        created = raw.get('created_at') or ''
        since = datetime.fromisoformat(created).astimezone(UTC) if created else now
        platform = declared['platform'] if declared else 'linux'
        number = int(raw['number'])
        found.append(
            Candidate(repo, f'issue/{number}', '', platform, REQUEST, since, labels=_labels(raw), number=number)
        )
    return found


def candidates(
    root: Path,
    mode: str,
    client: Client,
    *,
    repo: str,
    platforms: Sequence[str],
    schedule: Schedule,
    policy: Policy,
    now: datetime,
    say: Callable[[str], None] = lambda _: None,
) -> tuple[Candidate, ...]:
    """Every candidate *mode* serves, ONE per ref and platform: the ref's newest sha (coalesced). Fetches nothing.

    ``integrate``: the integration branch, every open PR into it (labels from the PR), every opted-in
    branch, and every request issue -- PRs and requests
    :func:`optional`, a failure said through *say*. ``develop``: the lanes, as class ``branch``. ``quiet``: none.
    """
    if mode == 'quiet':
        return ()
    found = [
        Candidate(repo, ref, sha, platform, kind, _when(root, sha, now), labels=labels, number=number)
        for ref, sha, kind, labels, number in _part_refs(root, mode, client, schedule, policy, say=say)
        for platform in platforms
    ]
    if mode == 'integrate':
        found += optional('request issues', lambda: _requests(client, repo, schedule, now), say)
    return tuple(found)


def declared_platforms(root: Path) -> tuple[str, ...]:
    """The platforms *root* declares a producer for: ``[tool.lab_commons.parts.produce]``, plus linux with ``hpc``."""
    manifest = root / 'pyproject.toml'
    if not manifest.is_file():
        return ()
    declared = tomllib.loads(manifest.read_text(encoding='utf-8')).get('tool', {}).get('lab_commons', {})
    found = set(declared.get('parts', {}).get('produce', {}))
    if declared.get('hpc'):
        found.add('linux')
    return tuple(sorted(found))


def repo_name(client: Client) -> str:
    """``owner/name`` -- how a host's weights and an alarm name a repository."""
    return f'{client.forge.owner}/{client.forge.repo}'
