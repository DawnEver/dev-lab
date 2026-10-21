"""PR-REVIEW-IS-ADVISORY: the repo's declared review command on every open PR into integration, once per head.

Step 4 of the branch flow (user ruling 2026-10-19). Gitea only: GitHub is ONLY a push mirror, and no GitHub
pull request is read or reviewed.

THE FORGE ONLY ORCHESTRATES. The review itself -- profiles, prompts, providers, models, keys, merging -- is
the method's, run by the command the repo declares (``[tool.lab_commons.review] command``); this module runs
it on ``<merge base>..<head>`` and reads its stdout as the findings JSON
(:mod:`lab_commons.dev.forgereview_findings`). It holds no model client, no prompt and no key.

WHERE IT RUNS. Inside the integration step of ``forge serve`` (:func:`step`, called by
:func:`lab_commons.dev.forgeservesteps.prompt`): the review host follows the integrator, on whichever host
derives the integration queue.

WHAT IT POSTS, per open, non-draft PR into ``[tool.lab_commons.integrator] integration`` whose head carries no
:data:`REVIEW_CONTEXT` status yet:

* the findings as ONE comment keyed by the head sha (``Marker.REVIEW``);
* a :data:`REVIEW_CONTEXT` status on the head: ``success`` once posted, ``pending`` saying
  :data:`TAKEOVER_PENDING` when every reviewer was ``exhausted`` or ``auth`` (nothing is commented; the integrator
  session reviews that head through the same method -- anthropic API, then a ccc, then a ccds session), ``error``
  when the command failed,
  printed no known findings version, or the diff is over the cap. ADVISORY:
  :func:`lab_commons.dev.platformparts.parts_of` skips that context, so the auto-merge
  (:mod:`lab_commons.dev.forgemerge`), promotion and push admission never wait on it.

THE COST IS BOUNDED: one command run per head sha (the status is the record; a second tick on the same head
runs nothing and posts nothing), drafts skipped, and a diff over ``max_diff_bytes`` never reviewed. Declared::

    [tool.lab_commons.review]
    # {range}: <merge base>..<head>; the command names its own method and model (no default model exists)
    command = ["python", "-m", "ai_lab.review", "--method", "<dir>", "--range", "{range}", "--model", "<id>"]
    max_diff_bytes = 200000   # a larger diff is not reviewed
    claim_stale = "1 h"       # the default: a claim older than this may be taken over

BEFORE it runs the command, the host checks it can start it (:func:`can_start`: a missing interpreter or
module is ``unsupported`` and posts nothing), then CLAIMS the head: a ``pending`` status
``claimed by <host> at <time>, reviewing``. Every other host skips a head whose review status is anything but a
released (``released by``) or stale claim (:func:`claimable`), so N serving hosts review a head once.

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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.dev.forgepulls import ListingIncomplete, Marker, comment_upsert, pr_list
from lab_commons.dev.forgereview_findings import (
    SEVERITIES,
    Findings,
    FindingsInvalid,
    UnknownSchemaVersion,
    parse_findings,
)
from lab_commons.dev.forgestatus import status_list, status_post
from lab_commons.dev.forgework import ForgeCallFailed
from lab_commons.dev.platformparts import REVIEW_CONTEXT
from lab_commons.units import Q_

if TYPE_CHECKING:
    from lab_commons.dev.forgestatus import CommitStatus
    from lab_commons.dev.forgework import Client, PullRequest
    from lab_commons.dev.lanepolicy import Policy

__all__ = [
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

#: The placeholder the declared command carries; the reviewed ``<merge base>..<head>`` range replaces it.
RANGE_FIELD: Final = '{range}'

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

#: A claim given back (``pending``): the head is free again at once.
RELEASED: Final = 'released by'

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
_GIT_TIMEOUT_S: Final = 120


@dataclass(frozen=True)
class Review:
    """``[tool.lab_commons.review]``: the command that reviews, and the diff-size bound."""

    command: tuple[str, ...] = ()  # undeclared: nothing is reviewed (the command names its own model)
    max_diff_bytes: int = 200_000
    claim_stale: str = DEFAULT_CLAIM_STALE  # a duration: a claim older than this may be taken over

    def __post_init__(self) -> None:
        """Refuse a ``claim_stale`` that is not a duration, naming it."""
        stale_after(self)

    @property
    def stale(self) -> timedelta:
        """``claim_stale`` as a :class:`~datetime.timedelta`."""
        return stale_after(self)


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
    return Review(**declared | ({'command': tuple(declared['command'])} if 'command' in declared else {}))


def load_review(root: Path) -> Review:
    """*root*'s working-tree ``[tool.lab_commons.review]``; defaults when it has no manifest."""
    manifest = root / 'pyproject.toml'
    return review_from(manifest.read_text(encoding='utf-8'), str(manifest)) if manifest.is_file() else Review()


def _git(root: Path, *args: str) -> str:
    done = _door.run(
        ['git', *args], cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=_GIT_TIMEOUT_S, check=False,
    )  # fmt: skip
    if done.returncode != 0:
        msg = f'git {" ".join(args)} failed: {done.stderr.strip()[:300]}'
        raise OSError(msg)
    return done.stdout


class ReviewRefused(OSError):
    """The review command refused the request (exit :data:`REFUSED_EXIT`), naming why on stderr."""


class ReviewUnsupported(OSError):
    """The host cannot run the declared command at all (its interpreter or module is missing): ``unsupported``.

    Nothing is posted, so the head's one attempt is left for a host that can run it.
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

    Checked BEFORE a claim is posted, so a host that cannot review posts nothing.
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
    """Whether a head whose review status is *status* may be claimed: none, a released claim, or a stale one."""
    if status is None:
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


def command_for(review: Review, reviewed: str) -> list[str]:
    """The declared command with every :data:`RANGE_FIELD` replaced by the *reviewed* ``a..b`` range."""
    return [arg.replace(RANGE_FIELD, reviewed) for arg in review.command]


def render(head: str, found: Findings) -> str:
    """The one PR comment: who reviewed with what status, then each finding, most severe first."""
    who = ', '.join(f'`{one.name}` ({one.provider or "-"}): {one.status}' for one in found.reviewers) or 'none'
    rows = sorted(found.findings, key=lambda one: SEVERITIES.index(one.severity))
    lines = [
        f'- **{one.severity}** `{one.file}` -- {one.summary} ({one.id}, {one.category}, {one.confidence}; '
        f'by {", ".join(one.reviewers)})' + (f'\n  - suggestion: {one.suggestion}' if one.suggestion else '')
        for one in rows
    ]
    body = '\n'.join(lines) or 'No findings.'
    return (
        f'**Advisory review** of `{head[:12]}` over `{found.range}` -- it gates nothing.\n\nReviewers: {who}\n\n{body}'
    )


def _counted(found: Findings) -> str:
    high = sum(one.severity == 'HIGH' for one in found.findings)
    return f'{len(found.findings)} finding(s), {high} HIGH'


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
        description=f'advisory review posted: {_counted(found)}; it does not gate the merge',
    )  # fmt: skip
    return f'#{pull.number} {head[:12]}: reviewed, {_counted(found)}'


def review_tick(
    root: Path,
    client: Client,
    review: Review,
    *,
    base: str,
    run: Callable[[Sequence[str], Path], str] = run_command,
    ready: Callable[[Sequence[str], Path], str | None] = can_start,
    host: str,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[str, ...]:
    """Review every open, non-draft PR into *base* whose head has no review status; the lines it says.

    The declared command reviews ``<merge base>..<head>`` and prints the findings JSON; one comment and one
    :data:`REVIEW_CONTEXT` status per head are posted from it. A command that fails, or prints anything but a
    known findings version, posts ``error`` naming why, and is not retried on that head.
    """
    lines: list[str] = []
    target = f'origin/{base}'
    for pull in pr_list(client):
        head = pull.head_sha
        if pull.base != base or pull.draft or not head:
            continue
        latest = next((one for one in status_list(client, head) if one.context == REVIEW_CONTEXT), None)
        if not claimable(latest, clock(), review.stale):
            continue
        size = len(_git(root, 'diff', f'{target}...{head}').encode())
        if size > review.max_diff_bytes:
            why = f'not reviewed: the diff is {size} bytes, over the cap max_diff_bytes={review.max_diff_bytes}'
            status_post(client, head, context=REVIEW_CONTEXT, state='error', description=why)
            lines.append(f'#{pull.number} {head[:12]}: {why}')
            continue
        reviewed = f'{_git(root, "merge-base", target, head).strip()}..{head}'
        argv = command_for(review, reviewed)
        if (cannot := ready(argv, root)) is not None:  # checked first: a host that cannot review posts nothing
            lines.append(f'#{pull.number} {head[:12]}: {cannot}; nothing posted')
            break
        claim = f'{CLAIMED} {host} at {clock().isoformat(timespec="seconds")}, reviewing'
        status_post(client, head, context=REVIEW_CONTEXT, state='pending', description=claim)
        try:
            found = parse_findings(run(argv, root))
        except ReviewUnsupported as unsupported:  # it started and then could not: give the claim back
            why = f'{RELEASED} {host}: {unsupported}'[:_DESCRIPTION]
            status_post(client, head, context=REVIEW_CONTEXT, state='pending', description=why)
            lines.append(f'#{pull.number} {head[:12]}: {unsupported}; the claim is released')
            break
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

    *host* is the serving host's card name (:func:`lab_commons.dev.forgehosts.card_host`): the name its claim posts.
    """
    try:
        review = load_review(root)
        if not review.command:
            say(f'[serve] review: not run -- [tool.lab_commons.{_TABLE}] command is not declared')
            return
        for line in review_tick(root, built, review, base=policy.integration, run=run, ready=ready, host=host):
            say(f'[serve] review: {line}')
    except (ForgeCallFailed, ListingIncomplete, OSError, ValueError, subprocess.SubprocessError) as failed:
        say(f'[serve] the PR review did not run: {failed}')
