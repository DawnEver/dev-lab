"""PR-REVIEW-IS-ADVISORY: the repo's declared review command on every open PR into integration, once per head.

Step 4 of the branch flow (user ruling 2026-10-19). Gitea only: GitHub is ONLY a push mirror, and no GitHub
pull request is read or reviewed.

THE FORGE ONLY ORCHESTRATES. The review itself -- profiles, prompts, providers, models, keys, merging -- is
the method's, run by the command the repo declares (``[tool.lab_commons.review] command``); this module runs
it on ``<merge base>..<head>`` and reads its stdout as the findings JSON
(:mod:`dev_lab.dev.forgereview_findings`). It holds no model client, no prompt and no key.

WHERE IT RUNS. Inside the integration step of ``forge serve`` (:func:`step`, called by
:func:`dev_lab.dev.forgeservesteps.prompt`): the review host follows the integrator, on whichever host
derives the integration queue.

WHAT IT POSTS, per open, non-draft PR into ``[tool.lab_commons.integrator] integration`` whose head carries no
:data:`REVIEW_CONTEXT` status yet:

* the findings as ONE comment keyed by the head sha (``Marker.REVIEW``);
* a :data:`REVIEW_CONTEXT` status on the head: ``success`` once posted, ``pending`` saying
  :data:`TAKEOVER_PENDING` when every reviewer was ``exhausted`` or ``auth`` (nothing is commented; the integrator
  session reviews that head through the same method -- anthropic API, then a ccc, then a ccds session), ``error``
  when the command failed or printed no known findings version. ADVISORY:
  :func:`dev_lab.dev.platformparts.parts_of` skips that context, so promotion and push admission never wait on it;
* ``pending`` saying :data:`OVER_CAP`, with a ``pending`` :data:`~dev_lab.dev.platformparts.HOLD_CONTEXT` beside
  it, when the head cannot be read in slices (its
  reviewable change is over ``max_total_bytes``, one file alone is over ``max_diff_bytes``, or it needs several
  slices and the command takes no ``{paths}``): the hold is the ONE review context the auto-merge
  (:mod:`dev_lab.dev.forgemerge`) waits on, until a session reviews the head and releases it
  (``forge status post <sha> --context tests/review-hold --state success``) -- an unreviewable head is never
  advisory-skipped into an unreviewed merge.

WHAT IS READ is :mod:`dev_lab.dev.forgereview_scope`'s: the branch's own change since its last reviewed head,
minus generated files, in slices of at most ``max_diff_bytes`` under one lens each. Each slice runs the command
once; their outputs merge into one document, and a declared ``synthesis`` command then reads that document
(``{findings}``) over the whole range for what crosses slices.

THE COST IS BOUNDED: one review per head sha (the status is the record; a second tick on the same head runs
nothing and posts nothing), drafts skipped, generated files never read, ``max_total_bytes`` per head. Declared::

    [tool.lab_commons.review]
    # {range}: <base>..<head>; {paths}: the slice's paths (one argument each); {lens}: strict|standard|light
    # {capabilities.<name>.<key>}: THIS host's machine-file value (the repo says WHAT, the host says WHERE)
    # the installed `ai-lab` console script; the method path stays a capability while its data lives in cc-market
    command = ["ai-lab", "review", "--method", "{capabilities.sharp_review.path}",
               "--range", "{range}", "--lens", "{lens}", "--model", "<id>", "--paths", "{paths}"]
    synthesis = []             # optional: run once over {findings} (the merged slices) and {range}
    max_diff_bytes = 200000    # one slice: what one reviewer reads
    max_total_bytes = 4000000  # one head: past it, held for a session
    derived = []               # globs of generated files beyond the family's (famfiles.GENERATED)
    strict = [...]             # globs read under the strict lens; light = [...] under the light one
    claim_stale = "1 h"        # the default: a claim older than this may be taken over

ANY FAILURE IS ``error`` WITH ITS REASON (P4). A HOST that cannot run the review -- a host value the command names
but this host's ``[capabilities]`` does not declare, a command it cannot start (:func:`can_start`: a missing
executable or module, checked BEFORE the claim), or one that turns out unable to run (:class:`ReviewUnsupported`)
-- posts :data:`HOST_UNABLE` naming the host and why, once: a fact about the host, so the head stays claimable by a
capable host, or by this one once fixed. A command that ran and refused or printed no known findings is the head's
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
import shutil
import subprocess
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

import lab_commons.launch as _door
from lab_commons.box.machine import provided
from lab_commons.config import section
from lab_commons.units import Q_

from dev_lab.dev.forgecarry import RUNNING, docs_only
from dev_lab.dev.forgepulls import ListingIncomplete, Marker, comment_list, comment_upsert, pr_list
from dev_lab.dev.forgereview_findings import (
    Findings,
    FindingsInvalid,
    UnknownSchemaVersion,
    counted,
    parse_findings,
    render,
)
from dev_lab.dev.forgereview_scope import ONLY_GENERATED, OVER_CAP, Budget, Scope, gather, plan, reviewed_heads
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.forgework import ForgeCallFailed
from dev_lab.dev.platformparts import HOLD_CONTEXT, REVIEW_CONTEXT

if TYPE_CHECKING:
    from dev_lab.dev.forgestatus import CommitStatus
    from dev_lab.dev.forgework import Client, PullRequest
    from dev_lab.dev.lanepolicy import Policy

__all__ = [
    'HOST_FIELD',
    'OVER_CAP',
    'RANGE_FIELD',
    'REFUSED_EXIT',
    'RETIRED_KEYS',
    'REVIEW_CONTEXT',
    'TAKEOVER_KINDS',
    'TAKEOVER_PENDING',
    'Review',
    'ReviewRefused', 'ReviewUnsupported',
    'command_for',
    'load_review',
    'render',
    'review_from',
    'review_tick',
    'run_command',
    'step',
]  # fmt: skip

#: The placeholder the declared command carries; the reviewed ``<base>..<head>`` range replaces it.
RANGE_FIELD: Final = '{range}'

#: An argument exactly this expands into the slice's paths, one argument each.
PATHS_FIELD: Final = '{paths}'

#: Replaced by the slice's lens (:data:`dev_lab.dev.forgereview_scope.LENSES`).
LENS_FIELD: Final = '{lens}'

#: The family's default lens globs: what refuses or declares is read strictly, prose lightly.
STRICT: Final = ('**/hooks/**', '**/rules/**', 'tests/architecture/**', '**/contracts/**')
LIGHT: Final = ('docs-src/**', '**/.claude/memory/**', '**/*.md')

#: A placeholder for a value THIS host declares: ``{capabilities.<name>.<key>}`` (``~`` expanded).
HOST_FIELD: Final = re.compile(r'\{capabilities\.(?P<name>[a-z][a-z0-9_]*)\.(?P<key>[a-z][a-z0-9_]*)\}')

#: The exit a review command REFUSES with (a bad method, version or range): empty stdout, the reason on stderr.
REFUSED_EXIT: Final = 2

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

_CLAIM: Final = re.compile(rf'^{CLAIMED} (?P<host>\S+) at (?P<at>\S+), reviewing')
_PROBE: Final = 'import importlib.util, sys; sys.exit(importlib.util.find_spec(sys.argv[1]) is None)'

#: The keys of the retired in-process reviewer, each refused naming where its concern lives now.
RETIRED_KEYS: Final = {
    'model': 'the review command chooses its model (declare it in `command`: `--model <id>`)',
    'max_tokens': 'the review command bounds its own output',
    'rules': 'the review method reads its own rules and profiles (`--method <dir>` in `command`)',
}

_TABLE: Final = 'review'
_MISSING_MODULE: Final = 'No module named'  # what `python -m <absent>` says
_COMMAND_TIMEOUT_S: Final = 1800
_DESCRIPTION: Final = 240  # a commit-status description is short


@dataclass(frozen=True)
class Review:
    """``[tool.lab_commons.review]``: the command that reviews, and what bounds and cuts what it reads."""

    command: tuple[str, ...] = ()  # undeclared: nothing is reviewed (the command names its own model)
    synthesis: tuple[str, ...] = ()  # undeclared: the slice outputs are merged, nothing reads across them
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
    declared = tomllib.loads(text).get('tool', {}).get('lab_commons', {}).get(_TABLE, {})
    if retired := [f'{key} is retired: {RETIRED_KEYS[key]}' for key in declared if key in RETIRED_KEYS]:
        msg = f'[tool.lab_commons.{_TABLE}] in {origin}: ' + '; '.join(retired)
        raise ValueError(msg)
    known = {field.name for field in dataclasses.fields(Review)}
    if unknown := sorted(set(declared) - known):
        msg = f'[tool.lab_commons.{_TABLE}] in {origin} has unknown key(s) {unknown}; the keys are {sorted(known)}'
        raise ValueError(msg)
    return Review(**{key: tuple(value) if isinstance(value, list) else value for key, value in declared.items()})


def load_review(root: Path) -> Review:
    """*root*'s working-tree ``[tool.lab_commons.review]``; defaults when it has no manifest."""
    manifest = root / 'pyproject.toml'
    return review_from(manifest.read_text(encoding='utf-8'), str(manifest)) if manifest.is_file() else Review()


class ReviewRefused(OSError):
    """The review command refused the request (exit :data:`REFUSED_EXIT`), naming why on stderr."""


class ReviewUnsupported(OSError):
    """The host cannot run the declared command at all (absent, a module missing, a capability undeclared).

    Like every failure it posts ``error`` naming why.
    """


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


def can_start(argv: Sequence[str], root: Path) -> str | None:
    """Why this host cannot start *argv* (its executable absent, or its ``-m`` module unimportable); ``None`` if it can.

    Checked BEFORE a claim is posted; the reason becomes the ``error`` status.
    """
    found = shutil.which(argv[0]) or (argv[0] if Path(argv[0]).is_file() else None)
    if found is None:
        return f'unsupported: the review command {argv[0]!r} is not installed on this host'
    match argv:
        case [_, '-m', module, *_]:
            probe = _door.run([found, '-c', _PROBE, module], cwd=root, capture_output=True, timeout=120, check=False)
            if probe.returncode != 0:
                return f'unsupported: the review command cannot import {module!r} on this host'
    return None


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


def run_command(argv: Sequence[str], root: Path) -> str:
    """The stdout of the declared command run in *root*; :class:`ReviewRefused` or :class:`OSError` on a failure."""
    try:
        done = _door.run(
            list(argv), cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=_COMMAND_TIMEOUT_S, check=False,
        )  # fmt: skip
    except FileNotFoundError:
        msg = f'unsupported: the review command {argv[0]!r} is not installed on this host'
        raise ReviewUnsupported(msg) from None
    why = done.stderr.strip()[-300:]
    if done.returncode != 0 and _MISSING_MODULE in done.stderr:
        msg = f'unsupported: the review command cannot import its module on this host ({why})'
        raise ReviewUnsupported(msg)
    if done.returncode == REFUSED_EXIT:
        msg = f'the review command refused: {why}'
        raise ReviewRefused(msg)
    if done.returncode != 0:
        msg = f'the review command exited {done.returncode}: {why}'
        raise OSError(msg)
    return done.stdout


def command_for(
    review: Review, reviewed: str, capabilities: Mapping[str, Mapping[str, Any]], *,
    paths: Sequence[str] = (), lens: str = 'standard', synthesis: bool = False,
) -> list[str]:  # fmt: skip
    """The declared command (or *synthesis*), every placeholder replaced: the range, the slice, this host's values.

    A host value *capabilities* (this host's ``[capabilities]``) does not declare is :class:`ReviewUnsupported`.
    """

    def host_value(field: re.Match[str]) -> str:
        value = capabilities.get(field['name'], {}).get(field['key'])
        if not isinstance(value, str) or not value:
            where = f'[capabilities.{field["name"]}] {field["key"]}'
            msg = f'unsupported: this host declares no {where} for the review command'
            raise ReviewUnsupported(msg)
        return str(Path(value).expanduser()) if value.startswith('~') else value

    def filled(arg: str) -> list[str]:
        if arg == PATHS_FIELD:
            return list(paths)
        return [HOST_FIELD.sub(host_value, arg).replace(RANGE_FIELD, reviewed).replace(LENS_FIELD, lens)]

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


def _settle(client: Client, pull: PullRequest, found: Findings) -> str:
    """Replace the claim on *pull*'s head with the final status *found* earns (and its comment); the line said."""
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
    _, comment = comment_upsert(client, pull.number, kind=Marker.REVIEW, key=head, text=render(head, found))
    url = comment.url if comment else ''
    status_post(
        client, head, context=REVIEW_CONTEXT, state='success', target_url=url,
        description=f'advisory review posted: {counted(found)}; it does not gate the merge',
    )  # fmt: skip
    return f'#{pull.number} {head[:12]}: reviewed, {counted(found)}'


def review_tick(
    root: Path,
    client: Client,
    review: Review,
    *,
    base: str,
    run: Callable[[Sequence[str], Path], str] = run_command,
    ready: Callable[[Sequence[str], Path], str | None] = can_start,
    host: str,
    capabilities: Mapping[str, Mapping[str, Any]] = MappingProxyType({}),  # this host's: none by default
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[str, ...]:
    """Review every open, non-draft PR into *base* whose head has no review status; the lines it says.

    The declared command reviews ``<merge base>..<head>`` and prints the findings JSON; one comment and one
    :data:`REVIEW_CONTEXT` status per head are posted from it. A host that cannot run it posts
    :data:`HOST_UNABLE` and leaves the head claimable; a command that fails or prints anything but a known findings
    version posts ``error`` naming why, and is not retried on that head.
    """
    lines: list[str] = []
    target = f'origin/{base}'
    for pull in pr_list(client):
        head = pull.head_sha
        if pull.base != base or pull.draft or not head:
            continue
        if (passed := _passed(root, client, head, clock(), review.stale)) is not None:
            lines.extend([f'#{pull.number} {head[:12]}: {passed}'] if passed else [])
            continue
        scope = _scope(root, client, review, pull, target)
        if scope.held is not None or not scope.slices:
            state, why = ('pending', f'{OVER_CAP} ({scope.held})') if scope.held else ('success', ONLY_GENERATED)
            status_post(client, head, context=REVIEW_CONTEXT, state=state, description=why[:_DESCRIPTION])
            status_post(client, head, context=HOLD_CONTEXT, state=state, description=why[:_DESCRIPTION])
            lines.append(f'#{pull.number} {head[:12]}: {why}')
            continue
        try:
            argvs = [command_for(review, scope.range, capabilities, paths=s.paths, lens=s.lens) for s in scope.slices]
            cannot = ready(argvs[0], root)
        except ReviewUnsupported as unsupported:
            cannot = str(unsupported)
        if cannot is not None:  # checked before the claim: the HOST cannot, the head stays claimable
            lines.append(_unable(client, pull, host, cannot))
            continue
        claim = f'{CLAIMED} {host} at {clock().isoformat(timespec="seconds")}, reviewing'
        status_post(client, head, context=REVIEW_CONTEXT, state='pending', description=claim)
        try:
            synth = command_for(review, scope.range, capabilities, synthesis=True)
            found = parse_findings(gather(scope.range, argvs, synth, run, root))
        except ReviewUnsupported as unsupported:  # started, then the host could not: replaces the claim
            lines.append(_unable(client, pull, host, str(unsupported)))
            continue
        except (UnknownSchemaVersion, ReviewRefused) as named:
            why = f'not reviewed: {named}'[:_DESCRIPTION]
            status_post(client, head, context=REVIEW_CONTEXT, state='error', description=why)
            lines.append(f'#{pull.number} {head[:12]}: {why}')
            continue
        except (OSError, FindingsInvalid, subprocess.SubprocessError) as failed:
            why = f'the review command failed ({type(failed).__name__}); advisory, not retried on this head'
            status_post(client, head, context=REVIEW_CONTEXT, state='error', description=why)
            lines.append(f'#{pull.number} {head[:12]}: {why}: {failed}')
            continue
        lines.append(_settle(client, pull, found))
    return tuple(lines)


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
    """The review inside the integration step, on whichever host runs it; a failure is said, never raised.

    *host* is the serving host's card name (:func:`dev_lab.dev.forgehosts.card_host`): the name its claim posts.
    """
    try:
        review = load_review(root)
        if not review.command:
            say(f'[serve] review: not run -- [tool.lab_commons.{_TABLE}] command is not declared')
            return
        here = provided(section('capabilities'))
        lines = review_tick(
            root, built, review, base=policy.integration, run=run, ready=ready, host=host, capabilities=here
        )
        for line in lines:
            say(f'[serve] review: {line}')
    except (ForgeCallFailed, ListingIncomplete, OSError, ValueError, subprocess.SubprocessError) as failed:
        say(f'[serve] the PR review did not run: {failed}')
