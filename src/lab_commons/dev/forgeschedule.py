"""WHAT GETS PRODUCED, AND IN WHAT ORDER -- one work queue, derived from git and the forge, never stored.

Every candidate is a part a ref's newest commit lacks -- ``(repo, ref, sha, part, scope)`` -- or an
issue REQUEST. Which parts a commit needs is DERIVED (:func:`lab_commons.dev.platformparts.derived`):
``base``, and every part its posted parts hand ids to. Each has a numeric VALUE and an expected COST; a
claimer takes the feasible candidate with the highest SCORE, value per cost (weighted shortest job first)::

    value = base[class] + boost + aging_rate * wait_hours
    score = weight[repo] * value / expected_cost

EVERY HOST SERVES EVERY CLASS, from this one queue: ORDER is the rank, FIT is the admission
(:func:`lab_commons.compute.admission.admit`); a host's ``[priority]`` orders, and claims nothing
(:mod:`lab_commons.compute.priority`). A candidate's class comes from where it is: the declared
integration branch is ``integration``, the head of an open PR into it ``pr``, an issue carrying the
request label ``request``, and any other origin branch the class ONE ORDERED RULE names
(``classes_by_ref``, first match); a branch no pattern matches is not served.

``base`` is an OPEN table of classes (``integration``, ``pr``, ``feature``, ``branch``, ``request`` by family default),
``boost`` is what the user attached on the forge (a declared label such as ``priority:user``, or an
explicit ``priority:<n>``), and the aging term grows without bound, so no candidate starves forever.
``expected_cost`` is core-hours on a cluster and wall-hours on a box, predicted from what the
repository's last run measured (:mod:`lab_commons.compute.learned`); unmeasured work is priced at a declared
prior. ``weight`` belongs to the HOST (its machine file's ``[schedule] weights``), so a host serving
several repositories decides how to share itself while each repository ranks its own work. A host's
own user is served by its own reserve (:mod:`lab_commons.box.machine`), never by a lift in the order.

THE NUMBERS ARE DATA, declared once in ``[tool.lab_commons.schedule]``; :class:`Schedule` holds the
family default and a repository overrides key by key (a table key by table key)::

    [tool.lab_commons.schedule]
    classes = {integration = 100, pr = 60, feature = 45, branch = 30, request = 20}
    aging_rate = 10                  # value per hour waited
    starve_after_hours = {integration = 6, pr = 12, feature = 18, branch = 24, request = 48}
    daily_budget_core_h = {branch = 200}   # per ref of the class, per 24 h; absent = unbounded
    boosts = {"priority:user" = 1000}
    classes_by_ref = {"feat/*" = "feature", "fix/*" = "feature", "lane/*" = "branch"}  # ordered; replaces whole
    prior_cost_h = 4.0

ONE RUN PER REF AND PART (D6, user ruling 2026-10-17). A ref of a ``coalesce`` class has at most one run
of a part in flight across the fleet; its current tip waits behind that run
(:mod:`lab_commons.dev.forgecoalesce`), which is never cancelled, and is tested next as one batch. An
earlier tip never claimed is never a candidate. A lane is tested at every pushed sha.

WHY A CANDIDATE IS NOT CLAIMED is always named (:class:`Ranked`.``blocked``): waiting behind its ref's
run in flight, no host serves its part, over its ref's budget, or not admitted here -- naming the resources it lacks
(:func:`lab_commons.compute.admission.admit`). A candidate waiting longer than its class's
``starve_after_hours`` is STARVED and raises a ``forgealarm`` naming that reason.

The pure scoring -- :class:`~lab_commons.compute.model.Schedule`, :func:`~lab_commons.compute.model.rank` -- lives
in :mod:`lab_commons.compute.model`; this module gathers candidates and loads the numbers (I/O).
"""

from __future__ import annotations

import dataclasses
import fnmatch
import re
import tomllib
import urllib.parse
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.compute.model import (
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
from lab_commons.dev.forgecoalesce import WAITING_BEHIND
from lab_commons.dev.forgehosts import host_id
from lab_commons.dev.forgepulls import pr_list
from lab_commons.dev.forgerequest import UndeclaredRequest, declared_request, parse_body, parse_paths
from lab_commons.dev.forgework import GITHUB, Client, ForgeCallFailed, is_pull
from lab_commons.dev.lanepolicy import Policy
from lab_commons.dev.platformparts import part_refs
from lab_commons.hpc.retired import RETIRED
from lab_commons.hpc.shell import FULL

__all__ = [
    'NOT_ADMITTED',
    'NO_HOST',
    'ORIGIN_HOST',
    'OVER_BUDGET',
    'candidates',
    'head_login',
    'held',
    'host_weights',
    'labelled_issues',
    'load_schedule',
    'over_budget',
    'parse_usage',
    'ref_usage',
    'repo_name',
    'starved_alarms',
    'tip_of',
    'vouched',
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
    retired = [
        f'{key} is retired: {RETIRED[f"{SCHEDULE_TABLE}] {key}"]}'
        for key in declared
        if f'{SCHEDULE_TABLE}] {key}' in RETIRED
    ]
    if retired:
        msg = f'[tool.lab_commons.{SCHEDULE_TABLE}] in {manifest}: ' + '; '.join(retired)
        raise ValueError(msg)
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
        replaces = key == 'classes_by_ref' or not isinstance(current, Mapping)
        merged[key] = given if replaces else {**current, **given}
    schedule = dataclasses.replace(default, **merged)
    undeclared = sorted(set(schedule.classes_by_ref.values()) - set(schedule.classes))
    if undeclared:
        msg = (
            f'[tool.lab_commons.{SCHEDULE_TABLE}] classes_by_ref in {manifest} names class(es) {undeclared} '
            f'that classes does not value: {sorted(schedule.classes)}'
        )
        raise ValueError(msg)
    return schedule


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


def held(blocked: str) -> bool:
    """Whether *blocked* is a fleet POLICY hold -- its ref's run in flight, or its ref's budget spent.

    A held candidate is no work any host could claim now, so it never makes a host idle with work pending;
    only a block THIS host could have admitted past -- nothing, or its own capacity -- does.
    """
    return blocked.startswith((WAITING_BEHIND, OVER_BUDGET))


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
    """``sacct -n -P -o JobName,CPUTimeRAW`` lines into core-hours per run job name's sha12 (``run-<sha12>-<part>``)."""
    used: dict[str, float] = {}
    for line in sacct.splitlines():
        name, _, seconds = line.partition('|')
        if name.startswith('run-') and seconds.strip().isdigit():
            sha12 = name[4:16]
            used[sha12] = used.get(sha12, 0.0) + int(seconds) / 3600
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
    done = _door.run(
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


#: The commit trailer naming the host card a commit was made on (written by the ``forge-host`` commit-msg hook).
ORIGIN_HOST: Final = 'Forge-Host'


def _trailer(root: Path, sha: str, key: str) -> str:
    """The last *key* trailer of commit *sha*; ``''`` when it carries none."""
    values = _git(root, 'show', '-s', f'--format=%(trailers:key={key},valueonly)', sha).split()
    return values[-1] if values else ''


def head_login(client: Client, sha: str) -> str:
    """The forge login commit *sha* resolves to (author, else committer); ``''`` when the forge resolves none.

    The forge maps the commit's email to an account; git's own author text is never read as a login, so an
    unresolved head carries no origin -- and no login priority -- rather than a guess. A credential refusal raises.
    """
    path = f'{client.repo}/commits/{sha}' if client.backend is GITHUB else f'{client.repo}/git/commits/{sha}'
    try:
        raw = client.call('GET', path)
    except ForgeCallFailed as failed:
        if failed.report.attempts and failed.report.attempts[-1].returncode in AUTH_REFUSED:
            raise
        return ''
    if not isinstance(raw, Mapping):
        return ''
    for role in ('author', 'committer'):
        who = raw.get(role)
        if isinstance(who, Mapping) and who.get('login'):
            return str(who['login'])
    return ''


def vouched(found: Sequence[Candidate], owners: Mapping[str, Collection[str]]) -> tuple[Candidate, ...]:
    """*found* with each ``origin_host`` kept only where its FORGE-RECORDED login publishes that host card.

    A trailer or a request body is text anyone can write; the forge records who authored the PR or the
    issue, and the hosts issue who authored each card
    (*owners*: host -> its login, :func:`~lab_commons.dev.forgehosts.card_owners`). A part's unvouched trailer
    is dropped; a public repo's card is keyed by the opaque :func:`~lab_commons.dev.forgehosts.host_id`
    of the raw name the trailer carries, and vouches it the same.
    A REQUEST's unvouched ``host`` pin is REFUSED by name (``refused``), never silently run unpinned.
    """
    return tuple(_vouched(one, owners) for one in found)


def _vouched(one: Candidate, owners: Mapping[str, Collection[str]]) -> Candidate:
    publishers = (*owners.get(one.origin_host, ()), *owners.get(host_id(one.origin_host), ()))
    if not one.origin_host or one.origin in publishers:
        return one
    if one.kind != REQUEST:
        return dataclasses.replace(one, origin_host='')
    publisher = ', '.join(sorted(publishers)) or 'nobody'
    why = (
        f'host = "{one.origin_host}" pins a host card {one.origin or "its author"} does not publish '
        f'(published by {publisher}): drop the pin, or ask its publisher'
    )
    return dataclasses.replace(one, origin_host='', refused=why)


def _tips(root: Path) -> dict[str, str]:
    listed = _git(root, 'for-each-ref', '--format=%(refname) %(objectname)', _TRACKING)
    return {ref.removeprefix(_TRACKING): sha for ref, sha in (line.split(' ') for line in listed.splitlines() if line)}


def _labels(raw: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(label['name']) for label in raw.get('labels') or ())


def labelled_issues(client: Client, label: str) -> tuple[dict[str, Any], ...]:
    """Open issues carrying *label*, raw (pull requests excluded) -- every page, one call shape on both forges.

    A page shorter than :data:`ISSUE_PAGE` is the last: request #51 is as visible as request #1.
    """
    query = client.backend.list_query.format(state='open', limit=ISSUE_PAGE) + '&labels=' + urllib.parse.quote(label)
    found: list[dict[str, Any]] = []
    page = 1
    while True:
        listed = client.call('GET', f'{client.repo}/issues?{query}&page={page}') or []
        found += [raw for raw in listed if not is_pull(raw) and label in _labels(raw)]
        if len(listed) < ISSUE_PAGE:
            return tuple(found)
        page += 1


#: Issues read per page of :func:`labelled_issues`.
ISSUE_PAGE: Final = 50


_REQUEST_HOST: Final = re.compile(r'^\s*host\s*=\s*["\'](?P<host>[\w./-]+)["\']', re.MULTILINE)


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
    root: Path, client: Client, schedule: Schedule, policy: Policy, *, say: Callable[[str], None]
) -> list[tuple[str, str, str, tuple[str, ...], int, str]]:
    """``(ref, newest sha, class, labels, PR number, PR author)`` of every served ref (module docstring)."""
    tips = _tips(root)
    refs = (
        [(policy.integration, tips[policy.integration], INTEGRATION, (), 0, '')] if policy.integration in tips else []
    )
    for pull in optional('open pull requests', lambda: pr_list(client), say):
        sha = tips.get(pull.head, pull.head_sha)
        if pull.base == policy.integration and pull.head != policy.integration and sha:
            refs.append((pull.head, sha, PR, pull.labels, pull.number, pull.author))
    served = {ref for ref, *_ in refs}
    for branch, sha in sorted(tips.items()):
        kind = schedule.class_of(branch)
        if kind is not None and branch not in served and branch not in {policy.integration, policy.trunk}:
            refs.append((branch, sha, kind, (), 0, ''))
    return refs


def _requests(root: Path, client: Client, repo: str, schedule: Schedule, now: datetime) -> list[Candidate]:
    """Every request issue as a job: its producer and sha from the body, its need-set as that sha declares it.

    A request whose producer is undeclared is still listed (part ``''``): the claim pass refuses it by name.
    """
    found = []
    for raw in labelled_issues(client, schedule.request_label):
        producer, sha = parse_body(raw.get('body') or '')
        paths = parse_paths(raw.get('body') or '')
        created = raw.get('created_at') or ''
        since = datetime.fromisoformat(created).astimezone(UTC) if created else now
        try:
            platform = declared_request(root, sha, producer, paths).part
        except UndeclaredRequest:
            platform = ''
        number = int(raw['number'])
        origin = str((raw.get('user') or {}).get('login', ''))
        host = _REQUEST_HOST.search(raw.get('body') or '')
        found.append(
            Candidate(
                repo,
                f'issue/{number}',
                sha,
                platform,
                REQUEST,
                since,
                FULL,
                labels=_labels(raw),
                number=number,
                origin=origin,
                origin_host=host['host'] if host else '',
                producer=producer,
                paths=paths,
            )
        )
    return found


def candidates(
    root: Path,
    client: Client,
    *,
    repo: str,
    parts: Callable[[str], Sequence[str]],
    schedule: Schedule,
    policy: Policy,
    now: datetime,
    say: Callable[[str], None] = lambda _: None,
) -> tuple[Candidate, ...]:
    """Every candidate, ONE per ref and part: the ref's newest sha (coalesced). Fetches nothing.

    *parts* names the parts a sha needs (:func:`lab_commons.dev.platformparts.derived` over its statuses).

    The integration branch, every open PR into it (labels from the PR), every branch ``classes_by_ref``
    classes, and every request issue -- each kept only where its part's ref filter admits its ref
    (:func:`lab_commons.dev.platformparts.part_refs`, the exclusion said through *say*) -- PRs and requests
    :func:`optional`, a failure said through *say*. A PR's origin is its author; any other head's is the
    login the forge resolves for its commit (:func:`head_login`), ``''`` when it resolves none.
    """
    found = []
    for ref, sha, kind, labels, number, pr_author in _part_refs(root, client, schedule, policy, say=say):
        needed = parts(sha)
        by = (pr_author or head_login(client, sha)) if needed else ''
        found += [
            Candidate(
                repo,
                ref,
                sha,
                platform,
                kind,
                _when(root, sha, now),
                FULL,
                labels=labels,
                number=number,
                origin=by,
                origin_host=_trailer(root, sha, ORIGIN_HOST) if by else '',
                session=ref,
            )
            for platform in needed
        ]
    found += optional('request issues', lambda: _requests(root, client, repo, schedule, now), say)
    return tuple(one for one in found if _ref_served(root, one, say))


def _ref_served(root: Path, wanted: Candidate, say: Callable[[str], None]) -> bool:
    """Whether *wanted*'s part declares its ref (``[tool.lab_commons.parts.refs]``); an exclusion is SAID.

    A request is no part: it is asked for by name at its sha, so no part's ref filter applies to it.
    """
    if wanted.kind == REQUEST:
        return True
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
