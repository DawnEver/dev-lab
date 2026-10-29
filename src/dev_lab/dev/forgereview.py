"""PR-REVIEW-BLOCKS-ON-HIGH-OR-SECURITY: the declared review command on every open PR into the PR base, per head.

Step 4 of the branch flow (user ruling 2026-10-19). ONE review on both forges (user ruling 2026-10-29); only who
TRIGGERS it differs. On Gitea the ``forge serve`` tick runs :func:`step` over every open PR; on GitHub a workflow
job runs ``forge review run --pr <N>`` (:func:`review_run`) for the one PR its event names. Both run the same round
(:func:`review_pull`). A job whose review secret is absent -- a fork PR, which GitHub never hands a secret -- holds
the head (:data:`NEEDS_MAINTAINER`) on the same hold the over-cap takeover uses, so a maintainer reviews it through
``forge review takeover <sha>``; nothing new is stored.

THE FORGE ONLY ORCHESTRATES. The review itself -- profiles, prompts, providers, models, keys, merging -- is
the method's, run by the command the repo declares (``[tool.dev_lab.review] command``); this module runs
it on ``<merge base>..<head>`` and reads its stdout as the findings JSON
(:mod:`dev_lab.dev.forgereview_findings`). It holds no model client, no prompt and no key.

WHERE IT RUNS follows what it needs -- the declared command -- never the poller lease. Every ``forge serve`` tick
runs :func:`step` (via :func:`dev_lab.dev.forgeservesteps.review`), poller or not; a host whose ``[runtimes]``
cannot fill or start the command (:func:`command_for`, :func:`can_start`) says so once and reads no PR. Among the
capable hosts the claim below makes each head reviewed once.

WHAT IT POSTS, per open, non-draft PR into ``[tool.dev_lab.integrator] integration`` whose head carries no
:data:`REVIEW_CONTEXT` status yet:

* the head's review ROUND as ONE comment keyed by the head sha (``Marker.REVIEW``): its tagged findings carried
  from the earlier rounds, re-checked, and recorded as a ledger (:mod:`dev_lab.dev.forgereview_rounds`; round 1
  opens with the change's context summary). Past ``max_rounds`` no command runs: only the blocking findings are
  re-checked, and the non-blocking ones move to ONE follow-up issue;
* a :data:`REVIEW_CONTEXT` status on the head: ``failure`` while an open ``HIGH`` or security finding is neither
  fixed nor disposed (``forge review dispose``, :mod:`dev_lab.dev.forgereview_dispose`), else ``success`` -- the
  auto-merge waits on a ``failure`` and on a head not yet reviewed (:func:`dev_lab.dev.forgemerge.review_blocks`);
  ``pending`` saying
  :data:`TAKEOVER_PENDING` when every reviewer was ``exhausted`` or ``auth`` (nothing is commented; the integrator
  session reviews that head through the same method -- anthropic API, then a ccc, then a ccds session), ``error``
  when the command failed or printed no known findings version (those two stay advisory: no finding exists).
  It is not a PART (:func:`dev_lab.dev.platformparts.parts_of` skips it): promotion and push admission never wait
  on it, the merge does;
* ``pending`` saying :data:`OVER_CAP_TAKEOVER`, with a ``pending`` :data:`~dev_lab.dev.platformparts.HOLD_CONTEXT`
  beside it, when a metered program review cannot read the head (its reviewable change is over
  ``max_total_bytes``, one file alone is over ``max_diff_bytes``, or it needs several slices and the command takes
  no ``{paths}``). That is a TAKEOVER, as :data:`TAKEOVER_PENDING` is: the INTEGRATOR AGENT owns it (user ruling
  2026-10-26). The forge lists the held head in its integration prompts with the door to run, and the integrator
  session runs ``python -m dev_lab.dev.forge review takeover <sha>`` (:mod:`dev_lab.dev.forgetakeover`): the SAME
  method over every slice, unmetered, then the findings comment, :data:`REVIEW_CONTEXT` and the release. The hold
  is the ONE review context the auto-merge (:mod:`dev_lab.dev.forgemerge`) waits on, and only that door releases
  it, refusing without a findings comment for the sha. A human is asked only for a decision the review surfaces.

WHAT IS READ is :mod:`dev_lab.dev.forgereview_scope`'s: the branch's own change since its last reviewed head,
minus generated files, in slices of at most ``max_diff_bytes`` under one lens each. Each slice runs the command
once; their outputs merge into one document, and a declared ``synthesis`` command then reads that document
(``{findings}``) over the whole range for what crosses slices.

THE COST IS BOUNDED: one review per head sha (the status is the record; a second tick on the same head runs
nothing and posts nothing), drafts skipped, generated files never read, ``max_total_bytes`` per head.

THE COMMAND IS THE FAMILY'S (:data:`FAMILY_COMMAND`): a repo declares only where it differs, every key optional::

    [tool.dev_lab.review]
    # command: only a genuinely different method; the family's, redeclared, is refused. Placeholders:
    # {range}: <base>..<head>; {paths}: the slice's paths (one argument each); {lens}: strict|standard|light;
    # {model}: `model`; {rules}: the registry's rule ids, comma-separated (ai-lab imports no registry);
    # {principles}: a JSON file of dev_lab.dev.principles (written per run; ai-lab holds no copy);
    # {runtimes.<name>.<key>}: THIS host's machine-file [runtimes.<name>] value (repo says WHAT, host WHERE)
    model = "<id>"             # the default is FAMILY_MODEL
    synthesis = []             # optional: run once over {findings} (the merged slices) and {range}
    max_rounds = 3             # full review rounds per PR (FAMILY_MAX_ROUNDS); past it, blocking re-checks only
    max_diff_bytes = 200000    # one slice: what one reviewer reads
    max_total_bytes = 4000000  # one head: past it, held for a session
    derived = []               # globs of generated files beyond the family's (famfiles.GENERATED)
    strict = [...]             # globs read under the strict lens; light = [...] under the light one
    claim_stale = "1 h"        # the default: a claim older than this may be taken over

ANY FAILURE IS ``error`` WITH ITS REASON (P4). A HOST that cannot run the review -- a host value the command names
but this host's ``[runtimes]`` does not declare, or a command it cannot start (:func:`can_start`: a missing
executable or module) -- is checked BEFORE the claim and posts NOTHING: a fact about the host is not the head's
status. One that started and turned out unable (:class:`ReviewUnsupported`) replaces its own claim with
:data:`HOST_UNABLE` naming the host and why, and that head stays claimable by a capable host, or by this one
once fixed. A command that ran and refused or printed no known findings is the head's
own ``error``, and that head is not retried. Otherwise the host CLAIMS the head:
a ``pending`` status ``claimed by <host> at <time>, reviewing``. Every other host skips a head whose review status is
anything but a released (``released by``) or stale claim (:func:`claimable`), so N serving hosts review a head once.

Undeclared, nothing is reviewed and the step says so. Exit :data:`REFUSED_EXIT` is the command's named refusal
(:class:`ReviewRefused`): its stderr reason is the ``error`` status.

The keys of the retired in-process reviewer (``model``, ``max_tokens``, ``rules``) are refused by name.
"""

from __future__ import annotations

import dataclasses
import re
import subprocess
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from lab_commons.units import Q_

from dev_lab.dev import forgereview_scope
from dev_lab.dev.family import declared_table
from dev_lab.dev.forgecarry import RUNNING, docs_only
from dev_lab.dev.forgepulls import ListingIncomplete, comment_list, pr_list
from dev_lab.dev.forgereview_command import ReviewRefused, ReviewUnsupported, can_start, run_command
from dev_lab.dev.forgereview_findings import Findings, FindingsInvalid, UnknownSchemaVersion, parse_findings
from dev_lab.dev.forgereview_rounds import FAMILY_MAX_ROUNDS, capped, post_round
from dev_lab.dev.forgereview_runtimes import HOST_FIELD, RUNTIMES_TABLE, host_runtimes, retired_field
from dev_lab.dev.forgereview_scope import ONLY_GENERATED, OVER_CAP_TAKEOVER, Budget, Scope, gather, plan, reviewed_heads
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.forgework import ForgeCallFailed
from dev_lab.dev.platformparts import HOLD_CONTEXT, REVIEW_CONTEXT
from dev_lab.dev.rules import RULES

if TYPE_CHECKING:
    from dev_lab.dev.forgestatus import CommitStatus
    from dev_lab.dev.forgework import Client, PullRequest
    from dev_lab.dev.lanepolicy import Policy

__all__ = [
    'FAMILY_COMMAND',
    'FAMILY_MODEL',
    'MODEL_FIELD',
    'NEEDS_MAINTAINER',
    'OVER_CAP_TAKEOVER',
    'RANGE_FIELD',
    'RETIRED_KEYS',
    'REVIEW_CONTEXT',
    'RULES_FIELD',
    'TAKEOVER_KINDS',
    'TAKEOVER_PENDING',
    'Review',
    'Runner',
    'command_for',
    'load_review',
    'review_from',
    'review_pull',
    'review_run',
    'review_tick',
    'step',
]  # fmt: skip

#: The placeholder the declared command carries; the reviewed ``<base>..<head>`` range replaces it.
RANGE_FIELD: Final = '{range}'

#: An argument exactly this expands into the slice's paths, one argument each.
PATHS_FIELD: Final = '{paths}'

#: Replaced by the slice's lens (:data:`dev_lab.dev.forgereview_scope.LENSES`).
LENS_FIELD: Final = '{lens}'

#: Replaced by the family registry's rule ids, comma-separated: ai-lab (the method) is GIVEN them and imports no
#: registry of its runner's.
RULES_FIELD: Final = '{rules}'

#: Replaced by the review's ``model`` (:data:`FAMILY_MODEL` unless the repo overrides it).
MODEL_FIELD: Final = '{model}'

#: The model the family reviews with: ONE declared value; a repo overrides it with ``model = "<id>"``.
FAMILY_MODEL: Final = 'claude-sonnet-5-5'

#: The family's review command (REVIEW-COMMAND-IS-THE-FAMILY'S): ai-lab's review module on THIS host's ai-lab
#: interpreter, which packages the method, sliced (``{paths}``) under a lens. A repo declares ``command`` only
#: when its method genuinely differs; redeclaring this one is refused, so no stale copy can drift from it.
FAMILY_COMMAND: Final = (
    '{runtimes.ai_lab.python}', '-m', 'ai_lab.review', '--range', RANGE_FIELD, '--lens', LENS_FIELD,
    '--model', MODEL_FIELD, '--rules', RULES_FIELD, '--paths', PATHS_FIELD,
    '--principles', forgereview_scope.PRINCIPLES_FIELD,
)  # fmt: skip

#: The family's default lens globs: what refuses or declares is read strictly, prose lightly.
STRICT: Final = ('**/hooks/**', '**/rules/**', 'tests/architecture/**', '**/contracts/**')
LIGHT: Final = ('docs-src/**', '**/.claude/memory/**', '**/*.md')

#: A reviewer status meaning its provider cannot serve this run at all: the review needs a takeover.
TAKEOVER_KINDS: Final = frozenset({'exhausted', 'auth'})

#: What :data:`REVIEW_CONTEXT` says when every reviewer is one of :data:`TAKEOVER_KINDS` (a ``pending`` status).
TAKEOVER_PENDING: Final = 'takeover pending'

#: How old a claim may grow before another host may take the head over (its claimant presumed dead): above the
#: command's own timeout, so a live review is never taken over.
DEFAULT_CLAIM_STALE: Final = '1 h'

#: The claim a host posts (``pending``) before it runs the command: every other host skips the head.
CLAIMED: Final = 'claimed by'

#: A claim given back by hand (``pending``): the head is free again at once.
RELEASED: Final = 'released by'

#: What an ``error`` says when THIS HOST cannot run the review (:class:`ReviewUnsupported`): a fact about the host,
#: not the head, so the head stays claimable -- by a capable host, or by this one once it is fixed.
HOST_UNABLE: Final = 'not reviewed: cannot run on host'

#: What :data:`REVIEW_CONTEXT` and the hold say (``pending``) when the job running the review has no review secret:
#: a fork PR. The head is held; a maintainer's ``forge review takeover <sha>`` reviews it and releases the hold.
NEEDS_MAINTAINER: Final = 'review needs a maintainer: the review secret is absent (a fork PR)'

_CLAIM: Final = re.compile(rf'^{CLAIMED} (?P<host>\S+) at (?P<at>\S+), reviewing')

#: The keys of the retired in-process reviewer, each refused naming where its concern lives now.
RETIRED_KEYS: Final = {
    'max_tokens': 'the review command bounds its own output',
    'rules': 'the review command reads the rules and profiles of the method it packages',
}

_TABLE: Final = 'review'
_DESCRIPTION: Final = 240  # a commit-status description is short


@dataclass(frozen=True)
class Review:
    """``[tool.dev_lab.review]``: the command that reviews, and what bounds and cuts what it reads."""

    command: tuple[str, ...] = FAMILY_COMMAND  # declare only a genuinely different method
    model: str = FAMILY_MODEL  # fills ``{model}``
    synthesis: tuple[str, ...] = ()  # undeclared: the slice outputs are merged, nothing reads across them
    max_rounds: int = FAMILY_MAX_ROUNDS  # full rounds per PR; past it, the open blocking findings are re-checked only
    max_diff_bytes: int = 200_000  # one slice
    max_total_bytes: int = 4_000_000  # one head
    derived: tuple[str, ...] = ()
    strict: tuple[str, ...] = STRICT
    light: tuple[str, ...] = LIGHT
    claim_stale: str = DEFAULT_CLAIM_STALE  # a duration: a claim older than this may be taken over

    def __post_init__(self) -> None:
        """Refuse a ``claim_stale`` that is not a duration, naming it."""
        stale_after(self)

    @property
    def stale(self) -> timedelta:
        """``claim_stale`` as a :class:`~datetime.timedelta`."""
        return stale_after(self)

    @property
    def budget(self) -> Budget:
        """The bounds and globs :func:`~dev_lab.dev.forgereview_scope.plan` cuts a head by."""
        return Budget(self.max_diff_bytes, self.max_total_bytes, self.derived, self.strict, self.light)


def review_from(text: str, origin: str) -> Review:
    """The :class:`Review` *text* declares, defaults for what it omits; a retired or unknown key is refused."""
    declared = declared_table(tomllib.loads(text), _TABLE, {})
    if retired := [f'{key} is retired: {RETIRED_KEYS[key]}' for key in declared if key in RETIRED_KEYS]:
        msg = f'[tool.dev_lab.{_TABLE}] in {origin}: ' + '; '.join(retired)
        raise ValueError(msg)
    known = {field.name for field in dataclasses.fields(Review)}
    if unknown := sorted(set(declared) - known):
        msg = f'[tool.dev_lab.{_TABLE}] in {origin} has unknown key(s) {unknown}; the keys are {sorted(known)}'
        raise ValueError(msg)
    review = Review(**{key: tuple(value) if isinstance(value, list) else value for key, value in declared.items()})
    if 'command' in declared and review.command == FAMILY_COMMAND:
        msg = f'[tool.dev_lab.{_TABLE}] in {origin} redeclares the family command: delete it (override `model`)'
        raise ValueError(msg)
    if why := retired_field((*review.command, *review.synthesis)):
        msg = f'[tool.dev_lab.{_TABLE}] in {origin}: {why}'
        raise ValueError(msg)
    return review


def load_review(root: Path) -> Review:
    """*root*'s working-tree ``[tool.dev_lab.review]``; defaults when it has no manifest."""
    manifest = root / 'pyproject.toml'
    return review_from(manifest.read_text(encoding='utf-8'), str(manifest)) if manifest.is_file() else Review()


def stale_after(review: Review) -> timedelta:
    """*review*'s ``claim_stale``; a bare number or a non-duration is refused naming it."""
    try:
        quantity = Q_(review.claim_stale)
    except Exception as bad:
        msg = f'claim_stale {review.claim_stale!r} is not a duration; write one such as "1 h"'
        raise ValueError(msg) from bad
    if not isinstance(quantity, Q_) or not quantity.check('[time]'):
        msg = f'claim_stale {review.claim_stale!r} is not a duration (it needs a unit); write one such as "1 h"'
        raise ValueError(msg)
    return timedelta(seconds=float(quantity.m_as('s')))


def claimable(status: CommitStatus | None, now: datetime, stale: timedelta) -> bool:
    """Whether a head whose review status is *status* may be claimed: none, a released or stale claim, or a host unable.

    A host that could not run the review (:data:`HOST_UNABLE`) is the host's fault, never the head's.
    """
    if status is None or (status.state, status.description.startswith(HOST_UNABLE)) == ('error', True):
        return True
    if status.state != 'pending':
        return False
    if status.description.startswith(RELEASED):
        return True
    if (claim := _CLAIM.match(status.description)) is None:
        return False  # takeover pending, or any other pending: not ours to take
    try:
        at = datetime.fromisoformat(claim['at'])
    except ValueError:
        return True  # an unreadable claim cannot hold a head forever
    return now - at >= stale


def _standing(client: Client, now: datetime, stale: timedelta) -> Callable[[str], CommitStatus | str]:
    """A sha's review as :func:`dev_lab.dev.forgecarry.docs_only` reads it: posted, live claim, else none."""

    def stood(sha: str) -> CommitStatus | str:
        latest = next((one for one in status_list(client, sha) if one.context == REVIEW_CONTEXT), None)
        if latest is not None and latest.state == 'success':
            return latest
        return RUNNING if latest is not None and latest.state == 'pending' and not claimable(latest, now, stale) else ''

    return stood


def _passed(root: Path, client: Client, head: str, now: datetime, stale: timedelta) -> str | None:
    """Why *head* is not reviewed now: ``''`` its own review is posted or held, else what carries; ``None``: review it.

    DOCS-ONLY-CARRIES: an earlier head's review stands (posted on *head*, no command run) or is still running.
    """
    latest = next((one for one in status_list(client, head) if one.context == REVIEW_CONTEXT), None)
    if not claimable(latest, now, stale):
        return ''
    carry = docs_only(root, head, _standing(client, now, stale), data_waits=False)
    if carry is not None and carry.verdict is not None:
        why = f'{carry.hold}: the review of {carry.source[:12]} stands'[:_DESCRIPTION]
        status_post(client, head, context=REVIEW_CONTEXT, state=carry.verdict.state, description=why,
                    target_url=carry.verdict.url)  # fmt: skip
    return None if carry is None else carry.hold


def command_for(
    review: Review, reviewed: str, runtimes: Mapping[str, Mapping[str, Any]], *,
    paths: Sequence[str] = (), lens: str = 'standard', synthesis: bool = False,
) -> list[str]:  # fmt: skip
    """The declared command (or *synthesis*), every placeholder replaced: the range, the slice, this host's values.

    A host value *runtimes* (this host's ``[runtimes]``) does not declare is :class:`ReviewUnsupported`.
    """

    def host_value(field: re.Match[str]) -> str:
        value = runtimes.get(field['name'], {}).get(field['key'])
        if not isinstance(value, str) or not value:
            where = f'[{RUNTIMES_TABLE}.{field["name"]}] {field["key"]}'
            msg = f'unsupported: this host declares no {where} for the review command'
            raise ReviewUnsupported(msg)
        return str(Path(value).expanduser()) if value.startswith('~') else value

    def filled(arg: str) -> list[str]:
        if arg == PATHS_FIELD:
            return list(paths)
        return [
            HOST_FIELD.sub(host_value, arg)
            .replace(RANGE_FIELD, reviewed)
            .replace(LENS_FIELD, lens)
            .replace(MODEL_FIELD, review.model)
            .replace(RULES_FIELD, ','.join(rule.id for rule in RULES))
        ]

    return [one for arg in (review.synthesis if synthesis else review.command) for one in filled(arg)]


def _scope(root: Path, client: Client, review: Review, pull: PullRequest, target: str) -> Scope:
    """What *pull*'s head review reads; held when it needs slices the command cannot take."""
    done = reviewed_heads(comment.body for comment in comment_list(client, pull.number))
    return plan(root, target, pull.head_sha, review.budget, done, sliceable=PATHS_FIELD in review.command)


def _unable(client: Client, pull: PullRequest, host: str, why: str) -> str:
    """Post :data:`HOST_UNABLE` naming *host* and *why* on *pull*'s head (not again if it already says so); the line.

    The head stays claimable: another host, or this one once fixed, reviews it on a later tick.
    """
    head = pull.head_sha
    said = f'{HOST_UNABLE} {host}: {why}'[:_DESCRIPTION]
    latest = next((one for one in status_list(client, head) if one.context == REVIEW_CONTEXT), None)
    if latest is None or (latest.state, latest.description) != ('error', said):
        status_post(client, head, context=REVIEW_CONTEXT, state='error', description=said)
    return f'#{pull.number} {head[:12]}: {said}'


def _settle(root: Path, client: Client, pull: PullRequest, review: Review, *, reviewed: str, found: Findings) -> str:
    """Replace the claim on *pull*'s head with the final status *found* earns (and its round); the line said."""
    head = pull.head_sha
    if found.reviewers and all(one.status in TAKEOVER_KINDS for one in found.reviewers):
        kinds = ', '.join(f'{one.name} {one.status}' for one in found.reviewers)
        why = f'{TAKEOVER_PENDING}: no reviewer could run ({kinds}); advisory, never blocks'[:_DESCRIPTION]
        status_post(client, head, context=REVIEW_CONTEXT, state='pending', description=why)
        return f'#{pull.number} {head[:12]}: {why}'
    if not any(one.status in {'ok', 'skipped'} for one in found.reviewers):
        kinds = ', '.join(f'{one.name} {one.status}' for one in found.reviewers) or 'none planned'
        why = f'not reviewed: no reviewer returned findings ({kinds}); advisory'[:_DESCRIPTION]
        status_post(client, head, context=REVIEW_CONTEXT, state='error', description=why)
        return f'#{pull.number} {head[:12]}: {why}'
    return post_round(root, client, pull, reviewed, found=found, max_rounds=review.max_rounds)


def _without_command(root: Path, client: Client, review: Review, pull: PullRequest, scope: Scope) -> str | None:
    """The line said when *pull*'s head is settled with no command run (past the cap, held, nothing to read)."""
    head = pull.head_sha
    if capped(client, pull, review.max_rounds):  # past max_rounds: the blocking findings re-checked only
        return post_round(root, client, pull, scope.range, found=None, max_rounds=review.max_rounds, by='re-check')
    if scope.held is None and scope.slices:
        return None
    state, why = ('pending', f'{OVER_CAP_TAKEOVER} ({scope.held})') if scope.held else ('success', ONLY_GENERATED)
    status_post(client, head, context=REVIEW_CONTEXT, state=state, description=why[:_DESCRIPTION])
    status_post(client, head, context=HOLD_CONTEXT, state=state, description=why[:_DESCRIPTION])
    return f'#{pull.number} {head[:12]}: {why}'


def _hold(client: Client, pull: PullRequest, why: str) -> str:
    """Hold *pull*'s head for the takeover door: :data:`REVIEW_CONTEXT` and the hold both ``pending`` *why*."""
    for context in (REVIEW_CONTEXT, HOLD_CONTEXT):
        status_post(client, pull.head_sha, context=context, state='pending', description=why[:_DESCRIPTION])
    return f'#{pull.number} {pull.head_sha[:12]}: {why}'


@dataclass(frozen=True)
class Runner:
    """How one host runs the review command: its name, its ``[runtimes]``, the run and start probes, its clock."""

    host: str
    runtimes: Mapping[str, Mapping[str, Any]] = MappingProxyType({})  # this host's: none by default
    run: Callable[[Sequence[str], Path], str] = run_command
    ready: Callable[[Sequence[str], Path], str | None] = can_start
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    #: Whether the review command's secret is present; absent (a fork PR's job) holds the head for a maintainer.
    secret: bool = True


def review_pull(root: Path, client: Client, review: Review, pull: PullRequest, runner: Runner) -> str | None:
    """Review *pull*'s head once (the round in the module docstring); the line said, ``None`` when nothing was.

    The declared command reviews ``<merge base>..<head>`` and prints the findings JSON; one comment and one
    :data:`REVIEW_CONTEXT` status per head are posted from it. A host that cannot start it posts nothing;
    a command that fails or prints anything but a known findings version posts ``error`` naming why, and is not
    retried on that head.
    """
    head = pull.head_sha
    if (passed := _passed(root, client, head, runner.clock(), review.stale)) is not None:
        return f'#{pull.number} {head[:12]}: {passed}' if passed else None
    scope = _scope(root, client, review, pull, f'origin/{pull.base}')
    said = _without_command(root, client, review, pull, scope)
    if said is None and not runner.secret:
        said = _hold(client, pull, NEEDS_MAINTAINER)
    return said if said is not None else _command_round(root, client, review, pull, scope=scope, runner=runner)


def _command_round(
    root: Path, client: Client, review: Review, pull: PullRequest, *, scope: Scope, runner: Runner
) -> str:
    """Claim *pull*'s head, run the command over *scope*'s slices and settle the head; the line said."""
    head, clock = pull.head_sha, runner.clock
    try:
        argvs = [command_for(review, scope.range, runner.runtimes, paths=s.paths, lens=s.lens) for s in scope.slices]
        cannot = runner.ready(argvs[0], root)
    except ReviewUnsupported as unsupported:
        cannot = str(unsupported)
    if cannot is not None:  # checked before the claim: the HOST cannot, so nothing is posted on the head
        return f'#{pull.number} {head[:12]}: not reviewed on this host -- {cannot}'
    claim = f'{CLAIMED} {runner.host} at {clock().isoformat(timespec="seconds")}, reviewing'
    status_post(client, head, context=REVIEW_CONTEXT, state='pending', description=claim)
    try:
        synth = command_for(review, scope.range, runner.runtimes, synthesis=True)
        found = parse_findings(gather(scope.range, argvs, synth, runner.run, root))
    except ReviewUnsupported as unsupported:  # started, then the host could not: replaces the claim
        return _unable(client, pull, runner.host, str(unsupported))
    except (UnknownSchemaVersion, ReviewRefused) as named:
        why = f'not reviewed: {named}'[:_DESCRIPTION]
        status_post(client, head, context=REVIEW_CONTEXT, state='error', description=why)
        return f'#{pull.number} {head[:12]}: {why}'
    except (OSError, FindingsInvalid, subprocess.SubprocessError) as failed:
        why = f'the review command failed ({type(failed).__name__}); advisory, not retried on this head'
        status_post(client, head, context=REVIEW_CONTEXT, state='error', description=why)
        return f'#{pull.number} {head[:12]}: {why}: {failed}'
    return _settle(root, client, pull, review, reviewed=scope.range, found=found)


def review_tick(
    root: Path,
    client: Client,
    review: Review,
    *,
    base: str,
    run: Callable[[Sequence[str], Path], str] = run_command,
    ready: Callable[[Sequence[str], Path], str | None] = can_start,
    host: str,
    runtimes: Mapping[str, Mapping[str, Any]] = MappingProxyType({}),  # this host's: none by default
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[str, ...]:
    """:func:`review_pull` on every open, non-draft PR into *base* -- the serve tick's trigger; the lines said."""
    runner = Runner(host=host, runtimes=runtimes, run=run, ready=ready, clock=clock)
    pulls = (pull for pull in pr_list(client) if pull.base == base and not pull.draft and pull.head_sha)
    return tuple(said for pull in pulls if (said := review_pull(root, client, review, pull, runner)) is not None)


def review_run(root: Path, client: Client, review: Review, number: int, *, base: str, runner: Runner) -> str:
    """:func:`review_pull` on PR *number* alone -- what a GitHub workflow job runs for its event's PR; the line."""
    pull = client.pr_view(number)
    if pull.base != base or pull.draft or not pull.head_sha:
        return f'#{number}: not reviewed -- only an open, non-draft PR into {base} is'
    return review_pull(root, client, review, pull, runner) or f'#{number} {pull.head_sha[:12]}: already reviewed'


def step(
    root: Path,
    built: Client,
    *,
    policy: Policy,
    say: Callable[[str], None],
    host: str,
    run: Callable[[Sequence[str], Path], str] = run_command,
    ready: Callable[[Sequence[str], Path], str | None] = can_start,
) -> None:
    """The review on this serving host, when it can run the command; a failure is said, never raised.

    *host* is the serving host's card name (:func:`dev_lab.dev.forgehosts.card_host`): the name its claim posts.
    A host that cannot fill or start the command says so once and reads no PR.
    """
    try:
        review = load_review(root)
        if not review.command:
            say(f'[serve] review: not run -- [tool.dev_lab.{_TABLE}] command is not declared')
            return
        here = host_runtimes()
        try:  # any range, any slice: can this host run the command at all
            cannot = ready(command_for(review, '', here), root)
        except ReviewUnsupported as unsupported:
            cannot = str(unsupported)
        if cannot is not None:
            say(f'[serve] review: not run on this host -- {cannot}')
            return
        lines = review_tick(root, built, review, base=policy.pr_base, run=run, ready=ready, host=host, runtimes=here)
        for line in lines:
            say(f'[serve] review: {line}')
    except (ForgeCallFailed, ListingIncomplete, OSError, ValueError, subprocess.SubprocessError) as failed:
        say(f'[serve] the PR review did not run: {failed}')
