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
repository's last run measured (:mod:`lab_commons.compute.learned`); unmeasured work is priced at a declared
prior. ``weight`` belongs to the HOST (its machine file's ``[schedule] weights``), so a host serving
several repositories decides how to share itself while each repository ranks its own work. A host's
own user is served by its own reserve (:mod:`lab_commons.compute.ledger`), never by a lift in the order.

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
platform, over its ref's budget, or not admitted here -- naming the resources it lacks
(:func:`lab_commons.compute.model.admit`). A candidate waiting longer than its class's
``starve_after_hours`` is STARVED and raises a ``forgealarm`` naming that reason.

The pure scoring -- :class:`~lab_commons.compute.model.Schedule`, :func:`~lab_commons.compute.model.rank` -- lives
in :mod:`lab_commons.compute.model`; this module gathers candidates and loads the numbers (I/O).
"""

from __future__ import annotations

import dataclasses
import fnmatch
import re
import subprocess
import tomllib
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from lab_commons.compute.model import (
    BRANCH,
    INTEGRATION,
    PR,
    REQUEST,
    SCHEDULE_TABLE,
    Candidate,
    Ranked,
    Schedule,
    starved,
)
from lab_commons.dev.forge import _GIT, _GIT_TIMEOUT_S, AUTH_REFUSED
from lab_commons.dev.forgealarm import STARVED, Alarm
from lab_commons.dev.forgepulls import pr_list
from lab_commons.dev.forgework import Client, ForgeCallFailed, is_pull
from lab_commons.dev.lanepolicy import Policy
from lab_commons.dev.platformparts import part_refs
from lab_commons.hpc.shell import FULL

__all__ = [
    'NOT_ADMITTED',
    'NO_HOST',
    'OVER_BUDGET',
    'candidates',
    'host_weights',
    'labelled_issues',
    'load_schedule',
    'over_budget',
    'parse_usage',
    'ref_usage',
    'repo_name',
    'starved_alarms',
    'tip_of',
]

#: Why a candidate is not claimed -- the prefix of :attr:`Ranked.blocked`.
NO_HOST: Final = 'no host'
OVER_BUDGET: Final = 'over budget'
NOT_ADMITTED: Final = 'not admitted'

_TRACKING: Final = 'refs/remotes/origin/'


def load_schedule(root: Path) -> Schedule:
    """*root*'s ``[tool.lab_commons.schedule]`` over the family default; an unknown key is refused."""
    manifest = root / 'pyproject.toml'
    declared: dict[str, Any] = {}
    if manifest.is_file():
        with manifest.open('rb') as handle:
            declared = tomllib.load(handle).get('tool', {}).get('lab_commons', {}).get(SCHEDULE_TABLE, {})
    default = Schedule()
    known = {one.name for one in dataclasses.fields(Schedule)}
    unknown = sorted(set(declared) - known)
    if unknown:
        msg = (
            f'[tool.lab_commons.{SCHEDULE_TABLE}] in {manifest} has unknown key(s) {unknown}; '
            f'the keys are {sorted(known)}'
        )
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


def over_budget(root: Path, wanted: Candidate, schedule: Schedule, usage: Mapping[str, float] | None) -> str:
    """Why *wanted* is over its class's daily budget on this host, ``''`` when it is not (or nothing meters)."""
    cap = schedule.daily_budget_core_h.get(wanted.kind)
    if cap is None or usage is None:
        return ''
    used = ref_usage(root, wanted.ref, usage)
    return f'{OVER_BUDGET}: {wanted.ref} used {used:.1f} of {cap:g} core-h in 24 h' if used >= cap else ''


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
    return tuple(raw for raw in listed if not is_pull(raw) and label in _labels(raw))


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
) -> list[tuple[str, str, str, tuple[str, ...], int, str]]:
    """``(ref, newest sha, class, labels, PR number, PR author)`` of every ref *mode* serves."""
    tips = _tips(root)
    if mode != 'integrate':
        return [(b, s, BRANCH, (), 0, '') for b, s in sorted(tips.items()) if b.startswith(policy.lane_prefixes)]
    refs = (
        [(policy.integration, tips[policy.integration], INTEGRATION, (), 0, '')] if policy.integration in tips else []
    )
    for pull in optional('open pull requests', lambda: pr_list(client), say):
        sha = tips.get(pull.head, pull.head_sha)
        if pull.base == policy.integration and pull.head != policy.integration and sha:
            refs.append((pull.head, sha, PR, pull.labels, pull.number, pull.author))
    served = {ref for ref, *_ in refs}
    refs += [
        (branch, sha, BRANCH, (), 0, '')
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
        origin = str((raw.get('user') or {}).get('login', ''))
        found.append(
            Candidate(
                repo,
                f'issue/{number}',
                '',
                platform,
                REQUEST,
                since,
                FULL,
                labels=_labels(raw),
                number=number,
                origin=origin,
            )
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
    branch, and every request issue -- each kept only where its part's ref filter admits its ref
    (:func:`lab_commons.dev.platformparts.part_refs`, the exclusion said through *say*) -- PRs and requests
    :func:`optional`, a failure said through *say*. ``develop``: the lanes, as class ``branch``. ``quiet``: none.
    """
    if mode == 'quiet':
        return ()
    found = [
        Candidate(repo, ref, sha, platform, kind, _when(root, sha, now), FULL, labels=labels, number=number, origin=by)
        for ref, sha, kind, labels, number, by in _part_refs(root, mode, client, schedule, policy, say=say)
        for platform in platforms
    ]
    if mode == 'integrate':
        found += optional('request issues', lambda: _requests(client, repo, schedule, now), say)
    return tuple(one for one in found if _ref_served(root, one, say))


def _ref_served(root: Path, wanted: Candidate, say: Callable[[str], None]) -> bool:
    """Whether *wanted*'s part declares its ref (``[tool.lab_commons.parts.refs]``); an exclusion is SAID."""
    admits = part_refs(root, wanted.platform, wanted.scope)
    if admits is None or any(fnmatch.fnmatchcase(wanted.ref, one) for one in admits):
        return True
    say(
        f'[serve] {wanted.ref} is not served tests/{wanted.platform} at {wanted.scope}: '
        f'[tool.lab_commons.parts.refs.{wanted.platform}] {wanted.scope} admits {list(admits)}'
    )
    return False


def repo_name(client: Client) -> str:
    """``owner/name`` -- how a host's weights and an alarm name a repository."""
    return f'{client.forge.owner}/{client.forge.repo}'
