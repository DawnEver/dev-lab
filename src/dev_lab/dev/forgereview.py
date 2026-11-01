"""PR-REVIEW-BLOCKS-ON-HIGH-OR-SECURITY: the declared review command on every open PR into the PR base, per head.

Step 4 of the branch flow (user ruling 2026-10-19). ONE review on both forges (user ruling 2026-10-29); only who
TRIGGERS it differs. On Gitea the ``forge serve`` tick runs :func:`step` over every open PR; on GitHub a workflow
job runs ``forge review run --pr <N>`` (:func:`dev_lab.dev.forgetakeover.review_run`) for the one PR its event
names. Both run the same round (:func:`review_pull`). A job whose review secret is absent -- a fork PR, which
GitHub never hands a secret -- holds
the head (:data:`NEEDS_MAINTAINER`) until a maintainer re-runs the forge's review with the secret; nothing new is
stored.

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
  opens with the change's context summary). Past ``max_rounds`` or the PR's dollar cap nothing runs: the head
  waits, named (:mod:`dev_lab.dev.reviewbudget`);
* a :data:`REVIEW_CONTEXT` status on the head: ``failure`` while an open ``HIGH`` or security finding is neither
  fixed nor disposed (``forge review dispose``, :mod:`dev_lab.dev.forgereview_dispose`), else ``success`` -- the
  auto-merge waits on every state but ``success`` (:func:`dev_lab.dev.reviewgate.review_missing`);
  ``pending`` saying
  :data:`TAKEOVER_PENDING` when every reviewer was ``exhausted`` or ``auth`` (nothing is commented; the integrator
  session reviews that head through the same method -- anthropic API, then a ccc, then a ccds session), ``error``
  when the command failed or printed no known findings version. NONE of these is advisory: each waits the merge
  until the FORGE posts ``success`` (D11: :mod:`dev_lab.dev.reviewgate` reads the status's recorded creator).
  It is not a PART (:func:`dev_lab.dev.platformparts.parts_of` skips it): promotion and push admission never wait
  on it, the merge does;
* a ``pending`` :data:`~dev_lab.dev.platformparts.HOLD_CONTEXT` beside a ``pending`` :data:`REVIEW_CONTEXT` ONLY
  when the review could not run for this PR: its job has no review secret (:data:`NEEDS_MAINTAINER`) or its host
  cannot run the command (:class:`HostCannot`, on a workflow job). The forge's review is re-run, and its round
  releases the hold; a session's ``forge review takeover <sha>`` is advisory only (D11). A head is never held for
  its SIZE (D123, user ruling 2026-10-31, superseding 2026-10-26): an oversize head is one structure-level review.

WHAT IS READ is :mod:`dev_lab.dev.forgereview_scope`'s: the branch's own change since its last reviewed head,
minus generated files, in slices of at most ``max_diff_bytes`` under one lens each -- or, past the bounds, ONE
whole-range slice the reviewer explores from the directory level. Each slice runs the command
once; their outputs merge into one document, and a declared ``synthesis`` command then reads that document
(``{findings}``) over the whole range for what crosses slices.

THE COST IS BOUNDED: one review per head sha (the status is the record; a second tick on the same head runs
nothing and posts nothing), drafts skipped, generated files never read, ``max_total_bytes`` per head.

A ROUND IS SPENT ONLY ON NEW WORK (D52, user ruling 2026-11-01): every push was a round and every forge sync of
integration into a PR restarted its review at the merge base (motronics #5397, twice in a day), against a cap of
:data:`~dev_lab.dev.forgereview_rounds.FAMILY_MAX_ROUNDS`.

* A PURE SYNC carries: a head whose tree is git's clean automatic merge of its last reviewed head with integration
  posts that head's counted success (:func:`~dev_lab.dev.forgereview_claim.synced`), and runs nothing. Any other
  head since a reviewed one is read from that merge (:func:`~dev_lab.dev.forgereview_scope.own_base`): its own new
  work only. An increment with no code to read stands on its reviewed head only when that head's success is
  counted; otherwise the PR is read whole again -- an empty push never turns a ``failure`` into a ``success``.
* DEBOUNCE, on the serve tick: a head committed inside ``quiet`` (:data:`DEFAULT_QUIET`) is not reviewed yet --
  nothing is posted, no round is spent -- and the next tick past it reviews it, so a burst of pushes costs one
  round. The tick re-reads every PR anyway, so waiting holds no runner.
* DRAFTS are never reviewed (skipped here and by the review job); marking one ready is a trigger
  (``ready_for_review`` in the workflows' types; the serve's next tick). A push after ready does NOT turn the PR
  back into a draft (D53): a fix push gets its round, and the debounce coalesces a burst of them.

THE COMMAND IS THE FAMILY'S (:data:`FAMILY_COMMAND`): a repo declares only where it differs, every key optional::

    [tool.dev_lab.review]
    # command: only a genuinely different method; the family's, redeclared, is refused. Placeholders:
    # {range}: <base>..<head>; {paths}: the slice's paths (one argument each); {lens}: strict|standard|light;
    # {model}: `model`; {rules}: the registry's rule ids, comma-separated (ai-lab imports no registry);
    # {principles}: a JSON file of dev_lab.dev.principles (written per run; ai-lab holds no copy);
    # {summary}: --pr-body <file> on the one summarizing call, --no-summary on the rest;
    # {disposed}: a JSON file of the findings disposed earlier (the forge's own dispositions only);
    # {runtimes.<name>.<key>}: THIS host's machine-file [runtimes.<name>] value (repo says WHAT, host WHERE)
    model = "<id>"             # the default is FAMILY_MODEL
    synthesis = []             # optional: run once over {findings} (the merged slices) and {range}
    max_rounds = 5             # full review rounds per PR (FAMILY_MAX_ROUNDS); past it, the head waits
    max_diff_bytes = 200000    # one slice: what one reviewer reads
    max_total_bytes = 4000000  # one head: past it, held for a session
    derived = []               # globs of generated files beyond the family's (famfiles.GENERATED)
    strict = [...]             # globs read under the strict lens; light = [...] under the light one
    code = [...]               # globs of what executes (forgereview_scope.CODE): nothing else is read or capped
    not_code = [...]           # globs never code whatever their extension (forgereview_scope.NOT_CODE)
    claim_stale = "1 h"        # the default: a claim older than this may be taken over
    quiet = "10 min"           # the default (DEFAULT_QUIET): the serve reviews a head only once it is this old

ANY FAILURE IS ``error`` WITH ITS REASON (P4). A HOST that cannot run the review -- a host value the command names
but this host's ``[runtimes]`` does not declare, or a command it cannot start (:func:`can_start`: a missing
executable or module) -- is checked BEFORE the claim and posts NOTHING: a fact about the host is not the head's
status. One that started and turned out unable (:class:`ReviewUnsupported`) replaces its own claim with
:data:`~dev_lab.dev.forgereview_claim.HOST_UNABLE` naming the host and why, and that head stays
claimable by a capable host, or by this one once fixed. A command that ran and refused or printed no known
findings is the head's own ``error``, and that head is not retried. Otherwise the host CLAIMS the head:
a ``pending`` status ``claimed by <host> at <time>, reviewing``. Every other host skips a head whose review status is
anything but a released (``released by``) or stale claim (:func:`~dev_lab.dev.forgereview_claim.claimable`), so
N serving hosts review a head once.

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
from dev_lab.dev.forgepulls import ListingIncomplete, pr_list
from dev_lab.dev.forgereview_claim import CAPPED, CLAIMED, DESCRIPTION, counted_success, passed, synced, unable
from dev_lab.dev.forgereview_command import ReviewRefused, ReviewUnsupported, Runner, can_start, run_command
from dev_lab.dev.forgereview_findings import Finding, Findings, FindingsInvalid, UnknownSchemaVersion, parse_findings
from dev_lab.dev.forgereview_judge import (
    AdjudicationRefused,
    Judge,
    Verdict,
    identity,
    judge,
    ruling,
    self_review,
    upheld,
)
from dev_lab.dev.forgereview_rounds import FAMILY_MAX_ROUNDS, ledger_of, post_round, trailed, trusted_bodies
from dev_lab.dev.forgereview_runtimes import (
    HOST_FIELD,
    RUNTIMES_TABLE,
    host_runtimes,
    retired_field,
    retired_table,
    runtime_names,
)
from dev_lab.dev.forgereview_scope import (
    ONLY_GENERATED,
    Budget,
    Scope,
    gather,
    plan,
    reviewed_ancestor,
    reviewed_heads,
    synced_from,
)
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.forgework import ForgeCallFailed
from dev_lab.dev.labsession import sessions
from dev_lab.dev.lanepolicy import policy_at
from dev_lab.dev.platformparts import HOLD_CONTEXT, REVIEW_CONTEXT
from dev_lab.dev.reviewbudget import Spend, charged_to, gate, raised_of, read_spend, tag_of
from dev_lab.dev.reviewgate import DeclarationUnread, forge_posted, post_review
from dev_lab.dev.rules import RULES

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client, PullRequest
    from dev_lab.dev.lanepolicy import Policy

__all__ = [
    'EMPTY_COMMAND_FIX',
    'FAMILY_COMMAND',
    'FAMILY_JUDGE',
    'FAMILY_MODEL',
    'FAMILY_RUNTIMES',
    'MODEL_FIELD',
    'NEEDS_MAINTAINER',
    'RANGE_FIELD',
    'RETIRED_KEYS',
    'REVIEW_CONTEXT',
    'RULES_FIELD',
    'TAKEOVER_KINDS',
    'TAKEOVER_PENDING',
    'HostCannot',
    'Review',
    'command_for',
    'hold',
    'judge_for',
    'load_review',
    'review_at',
    'review_from',
    'review_pull',
    'review_tick',
    'step',
    'trusted_integration',
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
    '--principles', forgereview_scope.PRINCIPLES_FIELD, forgereview_scope.SUMMARY_FIELD,
    '--disposed', forgereview_scope.DISPOSED_FIELD,
)  # fmt: skip

#: The family's JUDGE (:mod:`dev_lab.dev.forgereview_judge`): ai-lab re-judges open findings and adjudicates
#: claims over ``{findings}`` (each with its claim) at the head of ``{range}``. Declared only to differ.
FAMILY_JUDGE: Final = (
    '{runtimes.ai_lab.python}', '-m', 'ai_lab.review.judge', '--range', RANGE_FIELD, '--model', MODEL_FIELD,
    '--rules', RULES_FIELD, '--principles', forgereview_scope.PRINCIPLES_FIELD,
    '--findings', forgereview_scope.FINDINGS_FIELD,
)  # fmt: skip

#: The runtimes the family's commands read from a host's ``[runtimes]``: the ONE set a deploy migrates.
FAMILY_RUNTIMES: Final = runtime_names((*FAMILY_COMMAND, *FAMILY_JUDGE))

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

#: DEBOUNCE (D52): how long a head must have been committed before the serve reviews it. A burst of pushes inside
#: it is ONE round, of its last head; a head older than it is reviewed on the first tick that sees it.
DEFAULT_QUIET: Final = '10 min'

#: What :data:`REVIEW_CONTEXT` and the hold say (``pending``) when the job running the review has no review secret:
#: a fork PR. The head is held until a maintainer re-runs the forge's review with the secret present.
NEEDS_MAINTAINER: Final = 'review needs a maintainer: the review secret is absent (a fork PR)'

#: The keys of the retired in-process reviewer, each refused naming where its concern lives now.
RETIRED_KEYS: Final = {
    'max_tokens': 'the review command bounds its own output',
    'rules': 'the review command reads the rules and profiles of the method it packages',
}

_TABLE: Final = 'review'

#: What an empty ``command`` is refused with (user ruling 2026-10-31, every PR is reviewed): no repo opts out, and
#: an omitted ``command`` is the family's, so the one fix is to delete the empty declaration.
EMPTY_COMMAND_FIX: Final = (
    'command = [] opts out of the review, and every PR is reviewed: delete it (the family command applies)'
)


class HostCannot(OSError):
    """The host cannot fill or start the review command: a fact about the HOST, checked before any claim.

    The serve tick says it and leaves the head to a capable host; a workflow job -- the ONLY reviewer of its PR
    -- holds the head for the takeover door and fails (:func:`dev_lab.dev.forgetakeover.review_run`).
    """


@dataclass(frozen=True)
class Review:
    """``[tool.dev_lab.review]``: the command that reviews, and what bounds and cuts what it reads."""

    command: tuple[str, ...] = FAMILY_COMMAND  # declare only a genuinely different method
    model: str = FAMILY_MODEL  # fills ``{model}``
    synthesis: tuple[str, ...] = ()  # undeclared: the slice outputs are merged, nothing reads across them
    judge: tuple[str, ...] = FAMILY_JUDGE  # re-judges open findings and adjudicates claims, every round
    max_rounds: int = FAMILY_MAX_ROUNDS  # full rounds per PR; past it, the head waits (reviewbudget)
    max_diff_bytes: int = 200_000  # one slice
    max_total_bytes: int = 4_000_000  # one head
    derived: tuple[str, ...] = ()
    strict: tuple[str, ...] = STRICT
    light: tuple[str, ...] = LIGHT
    code: tuple[str, ...] = forgereview_scope.CODE
    not_code: tuple[str, ...] = forgereview_scope.NOT_CODE
    claim_stale: str = DEFAULT_CLAIM_STALE  # a duration: a claim older than this may be taken over
    quiet: str = DEFAULT_QUIET  # a duration: the serve reviews a head only once it is this old (D52)

    def __post_init__(self) -> None:
        """Refuse a ``claim_stale`` or ``quiet`` that is not a duration, naming it."""
        stale_after(self)
        _duration('quiet', self.quiet)

    @property
    def quiet_for(self) -> timedelta:
        """``quiet`` as a :class:`~datetime.timedelta`."""
        return _duration('quiet', self.quiet)

    @property
    def stale(self) -> timedelta:
        """``claim_stale`` as a :class:`~datetime.timedelta`."""
        return stale_after(self)

    @property
    def budget(self) -> Budget:
        """The bounds and globs :func:`~dev_lab.dev.forgereview_scope.plan` cuts a head by."""
        return Budget(
            self.max_diff_bytes, self.max_total_bytes, self.derived, self.strict, self.light, self.code, self.not_code
        )


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
    if 'command' in declared and not review.command:
        msg = f'[tool.dev_lab.{_TABLE}] in {origin}: {EMPTY_COMMAND_FIX}'
        raise ValueError(msg)
    if 'command' in declared and review.command == FAMILY_COMMAND:
        msg = f'[tool.dev_lab.{_TABLE}] in {origin} redeclares the family command: delete it (override `model`)'
        raise ValueError(msg)
    if why := retired_field((*review.command, *review.synthesis)):
        msg = f'[tool.dev_lab.{_TABLE}] in {origin}: {why}'
        raise ValueError(msg)
    return review


def load_review(root: Path) -> Review:
    """*root*'s working-tree ``[tool.dev_lab.review]``; defaults when it has no manifest.

    A LOCAL check of a checkout's own declaration (the family test, the policy page, merge-ready's config line);
    never what a PR's review acts on -- that is the base's, :func:`review_at`.
    """
    manifest = root / 'pyproject.toml'
    return review_from(manifest.read_text(encoding='utf-8'), str(manifest)) if manifest.is_file() else Review()


def trusted_integration(root: Path, client: Client) -> str:
    """The integration branch a PR review trusts: the one the repository's DEFAULT branch declares.

    THE TRUST CHAIN (dev-lab #38 rounds 2-4): the forge's ``default_branch`` (main, which moves only by
    ``integrate promote``) -> its ``[tool.dev_lab.integrator] integration`` (``git show origin/<default>``) -> that
    branch's review declaration (:func:`review_at`) -> the command that runs beside the review key. The PR head
    enters only as the DIFF, read as data. F-169e99e6c68c: a name read from the working tree -- the head's --
    let a PR opened against a branch it controls name that branch the integration, and its declaration ran.
    A default branch the forge does not name, or whose manifest cannot be read, refuses
    (:class:`~dev_lab.dev.reviewgate.DeclarationUnread`), never falls back to the head.
    """
    repo: Any = client.call('GET', client.repo)
    default = repo.get('default_branch') if isinstance(repo, dict) else None
    if not default:
        msg = 'the forge names no default branch: which integration branch a review trusts is undecided'
        raise DeclarationUnread(msg)
    try:
        return policy_at(root, f'origin/{default}').integration
    except (ValueError, OSError) as failed:
        msg = f'origin/{default}:pyproject.toml declares no readable integration branch: {failed}'
        raise DeclarationUnread(msg) from failed


def review_at(root: Path, base: str) -> Review:
    """The ``[tool.dev_lab.review]`` ``origin/<base>`` declares in *root* -- what a PR's review acts on.

    F-46e412ee799d, F-ef3a6c8b86b2 (dev-lab #38 round 2): the review job checks out the PR head, and the declared
    ``command`` runs beside the review key, so a head's own declaration would choose the code that runs -- under
    ``pull_request_target`` too, whose WORKFLOW alone is the base's. *base* is the integration branch
    :func:`trusted_integration` names (the job, a takeover, an adjudication) or the serve's own policy, read from
    the operator's checkout, never a PR head. A PR changing its review declaration is reviewed under the base's
    until it lands, like the Actions adoption (:mod:`dev_lab.dev.reviewgate`). Read from git (``git show``, never
    the working tree), so the serve's tick reads no forge before it knows its host can run the command. An
    unreadable base declaration refuses (:class:`~dev_lab.dev.reviewgate.DeclarationUnread`), never falls back.
    """
    where = f'origin/{base}:pyproject.toml'
    try:
        text = forgereview_scope.git(root, 'show', where)[1]
    except OSError as failed:
        msg = f'{where} cannot be read: {failed}'
        raise DeclarationUnread(msg) from failed
    if not text.strip():
        msg = f'{where} is empty'
        raise DeclarationUnread(msg)
    return review_from(text, where)


def stale_after(review: Review) -> timedelta:
    """*review*'s ``claim_stale``; a bare number or a non-duration is refused naming it."""
    return _duration('claim_stale', review.claim_stale)


def _duration(key: str, value: str) -> timedelta:
    """The declared *key*'s *value* as a :class:`~datetime.timedelta`; a bare number or a non-duration is refused."""
    try:
        quantity = Q_(value)
    except Exception as bad:
        msg = f'{key} {value!r} is not a duration; write one such as "1 h"'
        raise ValueError(msg) from bad
    if not isinstance(quantity, Q_) or not quantity.check('[time]'):
        msg = f'{key} {value!r} is not a duration (it needs a unit); write one such as "1 h"'
        raise ValueError(msg)
    return timedelta(seconds=float(quantity.m_as('s')))


def command_for(
    review: Review, reviewed: str, runtimes: Mapping[str, Mapping[str, Any]], *,
    paths: Sequence[str] = (), lens: str = 'standard', synthesis: bool = False, judge: bool = False,
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

    declared = review.judge if judge else review.synthesis if synthesis else review.command
    return [one for arg in declared for one in filled(arg)]


def judge_for(
    root: Path, review: Review, reviewed: str, run: Callable[[Sequence[str], Path], str],
    runtimes: Mapping[str, Mapping[str, Any]],
) -> Judge:  # fmt: skip
    """The :data:`~dev_lab.dev.forgereview_judge.Judge` of *review*'s declared judge over *reviewed*, on this host.

    The command is filled only when there is something to judge: a first round has no open finding.
    """

    def judged(items: Sequence[tuple[Finding, str]]) -> Mapping[str, Verdict]:
        if not items:
            return {}
        argv = command_for(review, reviewed, runtimes, judge=True)
        return judge(argv, items, run, root, findings_field=forgereview_scope.FINDINGS_FIELD,
                     principles_field=forgereview_scope.PRINCIPLES_FIELD)  # fmt: skip

    return judged


def _scope(
    root: Path, client: Client, review: Review, pull: PullRequest, target: str, *, done: Sequence[str]
) -> Scope:  # fmt: skip
    """What *pull*'s head review reads: its new work since the reviewed heads *done*, cut by *review*'s budget.

    An increment with no code to read stands on its reviewed head only when that head's success is counted; else
    the whole PR is read (D52, module docstring): an empty push after a ``failure`` is never "nothing to review".
    """
    sliceable = PATHS_FIELD in review.command
    scope = plan(root, target, pull.head_sha, review.budget, done, sliceable=sliceable)
    earlier = reviewed_ancestor(root, pull.head_sha, done)
    if scope.slices or not earlier or counted_success(client, earlier, base=pull.base) is not None:
        return scope
    return plan(root, target, pull.head_sha, review.budget, (), sliceable=sliceable)


def _young(root: Path, head: str, runner: Runner) -> str | None:
    """Why *head* is not reviewed YET (D52 debounce): committed inside the runner's ``quiet``; ``None`` when old."""
    if not runner.quiet:
        return None
    committed = datetime.fromisoformat(forgereview_scope.git(root, 'show', '-s', '--format=%cI', head)[1].strip())
    if (age := runner.clock() - committed) >= runner.quiet:
        return None
    return f'not reviewed yet: committed {int(age.total_seconds())} s ago, inside quiet {runner.quiet}'


def _settle(root: Path, client: Client, pull: PullRequest, review: Review, scope: Scope, *, found: Findings,
            authored: Mapping[str, str], runner: Runner) -> str:  # fmt: skip
    """Replace the claim on *pull*'s head with the final status *found* earns (and its round); the line said."""
    head = pull.head_sha
    if found.reviewers and all(one.status in TAKEOVER_KINDS for one in found.reviewers):
        kinds = ', '.join(f'{one.name} {one.status}' for one in found.reviewers)
        why = f'{TAKEOVER_PENDING}: no reviewer could run ({kinds}); waits for the forge review to be re-run'[
            :DESCRIPTION
        ]
        post_review(client, head, state='pending', description=why)
        return f'#{pull.number} {head[:12]}: {why}'
    if not any(one.status in {'ok', 'skipped'} for one in found.reviewers):
        kinds = ', '.join(f'{one.name} {one.status}' for one in found.reviewers) or 'none planned'
        why = f'not reviewed: no reviewer returned findings ({kinds}); waits for a takeover'[:DESCRIPTION]
        post_review(client, head, state='error', description=why)
        return f'#{pull.number} {head[:12]}: {why}'
    return post_round(root, client, pull, scope.range, found=found, max_rounds=review.max_rounds,
                      outside=scope.outside, authored=authored, **_judging(root, client, review, pull,
                                                                            runner=runner))  # fmt: skip


def _judging(root: Path, client: Client, review: Review, pull: PullRequest, *, runner: Runner) -> dict:
    """The judge, the reviewer and the head's author sessions every round is posted with.

    The JUDGE reads the PR's whole change at its head (merge base..head), never the round's increment: a finding
    about a file the increment did not touch is judged on that file as the head holds it (#7 round 3).
    """
    since = forgereview_scope.git(root, 'merge-base', f'origin/{pull.base}', pull.head_sha)[1].strip()
    return {
        'judged': judge_for(root, review, f'{since}..{pull.head_sha}', runner.run, runner.runtimes),
        'reviewer': identity(client, runner.host, serving=runner.serving),
        'authors': sessions(root, f'origin/{pull.base}', pull.head_sha),
    }


def _without_command(client: Client, pull: PullRequest, scope: Scope) -> str | None:
    """The line said when *pull*'s head is settled with no command run (nothing but generated files to read)."""
    if scope.slices:
        return None
    post_review(client, pull.head_sha, state='success', description=ONLY_GENERATED[:DESCRIPTION])
    return f'#{pull.number} {pull.head_sha[:12]}: {ONLY_GENERATED}'


def capped(
    root: Path, client: Client, review: Review, pull: PullRequest, runner: Runner
) -> tuple[Review | None, str | None]:
    """*review* as *pull*'s next round may run it (:mod:`dev_lab.dev.reviewbudget`), and a note or the WAIT line.

    A waiting head gets a ``pending`` :data:`~dev_lab.dev.forgereview_claim.CAPPED` status naming the cap and the
    remedy, and the review is ``None`` -- posted and said once (``None, None`` after), and read again every tick,
    so a raise or a new month releases it.
    """
    head, bodies = pull.head_sha, trusted_bodies(client, pull.number)
    prior = ledger_of(bodies)
    rounds_done = 0 if prior is None else prior.round - (prior.head == head)
    spend = runner.spend(runner.runtimes, root)
    tag = tag_of(pull.url, pull.number)
    allowed = gate(number=pull.number, spent_usd=0.0 if spend is None else spend.of(tag), rounds_done=rounds_done,
                   max_rounds=review.max_rounds, spend=spend, raised=raised_of(bodies))  # fmt: skip
    if allowed.state == 'run':
        model = review.model if allowed.model is None else allowed.model
        unknown = '' if spend is not None else ' (no spend report on this host: the round cap alone holds)'
        return dataclasses.replace(review, max_rounds=allowed.max_rounds, model=model), unknown
    said = f'{CAPPED} {allowed.why}'[:DESCRIPTION]
    latest = next((one for one in status_list(client, head) if one.context == REVIEW_CONTEXT), None)
    if latest is not None and (latest.state, latest.description) == ('pending', said):
        return None, None
    post_review(client, head, state='pending', description=said)
    return None, f'#{pull.number} {head[:12]}: {said}'


def hold(client: Client, pull: PullRequest, why: str) -> str:
    """Hold *pull*'s head for the takeover door: :data:`REVIEW_CONTEXT` and the hold both ``pending`` *why*."""
    post_review(client, pull.head_sha, state='pending', description=why[:DESCRIPTION])
    status_post(client, pull.head_sha, context=HOLD_CONTEXT, state='pending', description=why[:DESCRIPTION])
    return f'#{pull.number} {pull.head_sha[:12]}: {why}'


def review_pull(root: Path, client: Client, review: Review, pull: PullRequest, runner: Runner) -> str | None:
    """Review *pull*'s head once (the round in the module docstring); the line said, ``None`` when nothing was.

    The declared command reviews ``<merge base>..<head>`` and prints the findings JSON; one comment and one
    :data:`REVIEW_CONTEXT` status per head are posted from it. A host that cannot start it posts nothing;
    a command that fails or prints anything but a known findings version posts ``error`` naming why, and is not
    retried on that head.
    """
    head, target = pull.head_sha, f'origin/{pull.base}'
    counted = forge_posted(client, head, base=pull.base) if runner.verifies else None
    if (stands := passed(root, client, head, runner.clock(), review.stale, counted=counted)) is not None:
        return f'#{pull.number} {head[:12]}: {stands}' if stands else None
    # the forge's own rounds only: a pasted marker naming an unreviewed sha would shrink the range or seed a carry
    done = reviewed_heads(trusted_bodies(client, pull.number))
    if (source := synced_from(root, target, head, done)) and (why := synced(client, head, source, base=pull.base)):
        return f'#{pull.number} {head[:12]}: {why}'
    if (wait := _young(root, head, runner)) is not None:
        return f'#{pull.number} {head[:12]}: {wait}'
    allowed, note = capped(root, client, review, pull, runner)
    if allowed is None:
        return note
    review = allowed
    scope = _scope(root, client, review, pull, target, done=done)
    said = _without_command(client, pull, scope)
    if said is None and not runner.secret:
        said = hold(client, pull, NEEDS_MAINTAINER)
    if said is not None:
        return said
    with charged_to(tag_of(pull.url, pull.number)):
        said = _command_round(root, client, review, pull, scope=scope, runner=runner)
    return said + (note or '')


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
        raise HostCannot(cannot)
    # the reviewer and the judge read these ranges with no forge token: a partial clone holds their blobs first
    forgereview_scope.prefetch(root, scope.range, f'origin/{pull.base}...{head}')
    # checked before the claim too: a session that authored the head posts nothing on it
    me = identity(client, runner.host, serving=runner.serving)
    ruling(me, f'reviewing #{pull.number}')
    self_review(me, sessions(root, f'origin/{pull.base}', head), f'reviewing #{pull.number}')
    claim = f'{CLAIMED} {runner.host} at {clock().isoformat(timespec="seconds")}, reviewing'
    post_review(client, head, state='pending', description=claim)
    try:
        synth = command_for(review, scope.range, runner.runtimes, synthesis=True)
        found = parse_findings(gather(scope.range, argvs, synth, runner.run, root, pr_body=pull.body,
                                      disposed=upheld(trusted_bodies(client, pull.number))))  # fmt: skip
    except ReviewUnsupported as unsupported:  # started, then the host could not: replaces the claim
        return unable(client, pull, runner.host, str(unsupported))
    except (UnknownSchemaVersion, ReviewRefused) as named:
        why = f'not reviewed: {named}'[:DESCRIPTION]
        post_review(client, head, state='error', description=why)
        return f'#{pull.number} {head[:12]}: {why}'
    except (OSError, FindingsInvalid, subprocess.SubprocessError) as failed:
        why = f'the review command failed ({type(failed).__name__}); not retried here, waits for a takeover'
        post_review(client, head, state='error', description=why)
        return f'#{pull.number} {head[:12]}: {why}: {failed}'
    authored = trailed(root, f'origin/{pull.base}', head)
    return _settle(root, client, pull, review, scope, found=found, authored=authored, runner=runner)


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
    spend: Callable[[Mapping[str, Mapping[str, Any]], Path], Spend | None] = read_spend,
    quiet: timedelta = timedelta(0),
) -> tuple[str, ...]:
    """:func:`review_pull` on every open, non-draft PR into *base* -- the serve tick's trigger; the lines said.

    *quiet* is the debounce (D52): :func:`step` passes the declared ``quiet``; zero reviews every head now.
    """
    runner = Runner(
        host=host, runtimes=runtimes, run=run, ready=ready, clock=clock, serving=True, spend=spend, quiet=quiet
    )

    def said(pull: PullRequest) -> str | None:
        try:
            return review_pull(root, client, review, pull, runner)
        except HostCannot as cannot:  # another serving host may run it: nothing is posted
            return f'#{pull.number} {pull.head_sha[:12]}: not reviewed on this host -- {cannot}'
        except AdjudicationRefused as author:  # the head's own author session: another reviewer runs it
            return f'#{pull.number} {pull.head_sha[:12]}: not reviewed here -- {author}'

    pulls = (pull for pull in pr_list(client) if pull.base == base and not pull.draft and pull.head_sha)
    return tuple(line for pull in pulls if (line := said(pull)) is not None)


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
        review = review_at(root, policy.integration)
        here = host_runtimes()
        try:  # any range, any slice: can this host run the command at all
            cannot = ready(command_for(review, '', here), root)
        except ReviewUnsupported as unsupported:
            cannot = retired_table(review.command, here) or str(unsupported)
        if cannot is not None:
            say(f'[serve] review: not run on this host -- {cannot}')
            return
        lines = review_tick(
            root, built, review, base=policy.integration, run=run, ready=ready, host=host, runtimes=here,
            quiet=review.quiet_for,
        )  # fmt: skip
        for line in lines:
            say(f'[serve] review: {line}')
    except (ForgeCallFailed, ListingIncomplete, OSError, ValueError, subprocess.SubprocessError) as failed:
        say(f'[serve] the PR review did not run: {failed}')
