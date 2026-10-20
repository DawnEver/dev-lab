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
* a :data:`REVIEW_CONTEXT` status on the head: ``success`` once posted, ``error`` when the command failed,
  printed no known findings version, or the diff is over the cap. ADVISORY:
  :func:`lab_commons.dev.platformparts.parts_of` skips that context, so the auto-merge
  (:mod:`lab_commons.dev.forgemerge`), promotion and push admission never wait on it.

THE COST IS BOUNDED: one command run per head sha (the status is the record; a second tick on the same head
runs nothing and posts nothing), drafts skipped, and a diff over ``max_diff_bytes`` never reviewed. Declared::

    [tool.lab_commons.review]
    command = ["python", "-m", "ai_lab.review", "--range", "{range}"]   # {range}: <merge base>..<head>
    max_diff_bytes = 200000                                            # a larger diff is not reviewed

The keys of the retired in-process reviewer (``model``, ``max_tokens``, ``rules``) are refused by name.
"""

from __future__ import annotations

import dataclasses
import subprocess
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
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

if TYPE_CHECKING:
    from lab_commons.dev.forgework import Client
    from lab_commons.dev.lanepolicy import Policy

__all__ = [
    'DEFAULT_COMMAND', 'RANGE_FIELD', 'RETIRED_KEYS', 'REVIEW_CONTEXT', 'Review', 'command_for', 'load_review',
    'render', 'review_from', 'review_tick', 'run_command', 'step',
]  # fmt: skip

#: The placeholder the declared command carries; the reviewed ``<merge base>..<head>`` range replaces it.
RANGE_FIELD: Final = '{range}'

#: The family default: sharp-review's method, run headless through ai-lab, printing the findings JSON.
DEFAULT_COMMAND: Final = ('python', '-m', 'ai_lab.review', '--range', RANGE_FIELD)

#: The keys of the retired in-process reviewer, each refused naming where its concern lives now.
RETIRED_KEYS: Final = {
    'model': 'the review command chooses its model (declare it in `command`, e.g. `--model <id>`)',
    'max_tokens': 'the review command bounds its own output',
    'rules': 'the review method reads its own rules and profiles (`--method <dir>` in `command`)',
}

_TABLE: Final = 'review'
_COMMAND_TIMEOUT_S: Final = 1800
_DESCRIPTION: Final = 240  # a commit-status description is short
_GIT_TIMEOUT_S: Final = 120


@dataclass(frozen=True)
class Review:
    """``[tool.lab_commons.review]``: the command that reviews, and the diff-size bound."""

    command: tuple[str, ...] = DEFAULT_COMMAND
    max_diff_bytes: int = 200_000


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


def run_command(argv: Sequence[str], root: Path) -> str:
    """The stdout of the declared review command run in *root*; :class:`OSError` naming a non-zero exit."""
    done = _door.run(
        list(argv), cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=_COMMAND_TIMEOUT_S, check=False,
    )  # fmt: skip
    if done.returncode != 0:
        msg = f'the review command exited {done.returncode}: {done.stderr.strip()[-300:]}'
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


def review_tick(
    root: Path,
    client: Client,
    review: Review,
    *,
    base: str,
    run: Callable[[Sequence[str], Path], str] = run_command,
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
        if any(status.context == REVIEW_CONTEXT for status in status_list(client, head)):
            continue
        size = len(_git(root, 'diff', f'{target}...{head}').encode())
        if size > review.max_diff_bytes:
            why = f'not reviewed: the diff is {size} bytes, over the cap max_diff_bytes={review.max_diff_bytes}'
            status_post(client, head, context=REVIEW_CONTEXT, state='error', description=why)
            lines.append(f'#{pull.number} {head[:12]}: {why}')
            continue
        reviewed = f'{_git(root, "merge-base", target, head).strip()}..{head}'
        try:
            found = parse_findings(run(command_for(review, reviewed), root))
        except UnknownSchemaVersion as unknown:
            why = f'not reviewed: {unknown}'[:_DESCRIPTION]
            status_post(client, head, context=REVIEW_CONTEXT, state='error', description=why)
            lines.append(f'#{pull.number} {head[:12]}: {why}')
            continue
        except (OSError, FindingsInvalid, subprocess.SubprocessError) as failed:
            why = f'the review command failed ({type(failed).__name__}); advisory, not retried on this head'
            status_post(client, head, context=REVIEW_CONTEXT, state='error', description=why)
            lines.append(f'#{pull.number} {head[:12]}: {why}: {failed}')
            continue
        _, comment = comment_upsert(client, pull.number, kind=Marker.REVIEW, key=head, text=render(head, found))
        url = comment.url if comment else ''
        status_post(
            client, head, context=REVIEW_CONTEXT, state='success', target_url=url,
            description=f'advisory review posted: {_counted(found)}; it does not gate the merge',
        )  # fmt: skip
        lines.append(f'#{pull.number} {head[:12]}: reviewed, {_counted(found)}')
    return tuple(lines)


def step(
    root: Path,
    built: Client,
    *,
    policy: Policy,
    say: Callable[[str], None],
    run: Callable[[Sequence[str], Path], str] = run_command,
) -> None:
    """The review inside the integration step, on whichever host runs it; a failure is said, never raised."""
    try:
        review = load_review(root)
        for line in review_tick(root, built, review, base=policy.integration, run=run):
            say(f'[serve] review: {line}')
    except (ForgeCallFailed, ListingIncomplete, OSError, ValueError, subprocess.SubprocessError) as failed:
        say(f'[serve] the PR review did not run: {failed}')
