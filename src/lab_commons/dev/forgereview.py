"""PR-REVIEW-IS-ADVISORY: a Claude review of every open PR into integration, once per head, gating nothing.

Step 4 of the branch flow (user ruling 2026-10-19). Gitea only: GitHub is ONLY a push mirror, and no GitHub
pull request is read or reviewed.

WHERE IT RUNS. A ``forge serve`` step (:func:`step`), on a host whose machine file declares the capability
``[capabilities.pr_review]``; no other host reads the key or calls the model.

THE KEY IS ITS OWN. The reviewer reads ONE dedicated Anthropic API key, used for nothing else: the
``pr-review`` TASK key of the Anthropic host (:data:`KEY_NAME`), read through the one model-key scheme
(:func:`lab_commons.credentials.api_key`; stored by ``python -m ai_lab.auth login anthropic --task pr-review``)
-- never the host's default key, never another AI key, never an environment variable. Absent, it is
REFUSED BY THAT NAME (:class:`ReviewKeyMissing`), and nothing is posted. The key is never
logged, printed, posted or put in an exception text.

WHAT IT POSTS, per open, non-draft PR into ``[tool.lab_commons.integrator] integration`` whose head carries no
:data:`REVIEW_CONTEXT` status yet:

* the review as ONE comment keyed by the head sha (``Marker.REVIEW``), findings as ``path:line``;
* a :data:`REVIEW_CONTEXT` status on the head: ``success`` once posted, ``error`` when the model call failed
  or the diff is over the cap. ADVISORY: :func:`lab_commons.dev.platformparts.parts_of` skips that context, so
  the auto-merge (:mod:`lab_commons.dev.forgemerge`), promotion and push admission never wait on it.

THE COST IS BOUNDED: one model call per head sha (the status is the record; a second tick on the same head
asks nothing and posts nothing), drafts skipped, and a diff over ``max_diff_bytes`` never sent.

THE PROMPT is the repo's own rule files read at ``origin/<integration>`` -- never the PR's copy, which could
rewrite the rules it is judged by -- plus the PR's title, body and its diff against the merge base. Declared::

    [tool.lab_commons.review]
    model = "claude-opus-5-5"                        # default: the latest Claude
    max_diff_bytes = 200000                          # a larger diff is not sent
    max_tokens = 8192                                # the review's output bound
    rules = ["AGENTS.md", ".claude/rules/*.md"]      # fnmatch over tracked paths; ``*`` crosses ``/``
"""

from __future__ import annotations

import dataclasses
import fnmatch
import http.client
import json
import subprocess
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.credentials import NoCredential, api_key, key_username
from lab_commons.dev.forge import https_transport
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
    'API_HOST', 'DEFAULT_MODEL', 'KEY_NAME', 'KEY_TASK', 'REVIEW_CONTEXT', 'Ask', 'Review',
    'ReviewKeyMissing', 'anthropic', 'load_review', 'review_from', 'review_key', 'review_tick', 'step',
]  # fmt: skip

#: The Messages API host: where the review is asked, and the credential host its key is stored under.
API_HOST: Final = 'api.anthropic.com'

#: The API-key task the reviewer's OWN key is stored for (:data:`lab_commons.credentials.API_KEY_TASKS`).
KEY_TASK: Final = 'pr-review'

#: The reviewer's key as a refusal names it: ``<username>@<host>``.
KEY_NAME: Final = f'{key_username(KEY_TASK)}@{API_HOST}'

#: The latest Claude, the default reviewer.
DEFAULT_MODEL: Final = 'claude-opus-5-5'

#: The placeholder the declared command carries; the reviewed ``<merge base>..<head>`` range replaces it.
RANGE_FIELD: Final = '{range}'

#: The family default: sharp-review's method, run headless through ai-lab, printing the findings JSON.
DEFAULT_COMMAND: Final = ('python', '-m', 'ai_lab.review', '--range', RANGE_FIELD)

_TABLE: Final = 'review'
_COMMAND_TIMEOUT_S: Final = 1800
_DESCRIPTION: Final = 240  # a commit-status description is short
_API_VERSION: Final = '2023-06-01'
_TIMEOUT_S: Final = 600.0
_OK: Final = 200  # the one success the Messages API answers
_GIT_TIMEOUT_S: Final = 120

_INSTRUCTIONS: Final = (
    'You review one pull request against the rules of the repository it targets, quoted below. Report only '
    'real problems: a rule the change breaks, a bug, a missing test, a security risk. Each finding is one '
    'Markdown bullet beginning with the location as `path:line` (a line of the new file), then the rule ID '
    'when one applies, then the finding in one or two sentences. With no finding, say so in one line. Your '
    'review is advisory: it gates nothing.'
)


class ReviewKeyMissing(NoCredential):
    """The reviewer's own key is not stored: the reviewer refuses, naming where it must be stored."""


@dataclass(frozen=True)
class Review:
    """``[tool.lab_commons.review]``: the model, the cost bounds, and the rule files the prompt carries."""

    model: str = DEFAULT_MODEL
    max_diff_bytes: int = 200_000
    max_tokens: int = 8192
    rules: tuple[str, ...] = ('AGENTS.md', '.claude/rules/*.md')
    command: tuple[str, ...] = DEFAULT_COMMAND


@dataclass(frozen=True)
class Ask:
    """One model call: who answers, its system text (instructions and rules), the PR prompt, the output bound."""

    model: str
    system: str
    prompt: str
    max_tokens: int


def review_from(text: str, origin: str) -> Review:
    """The :class:`Review` *text* declares, defaults for what it omits; an unknown key is refused naming *origin*."""
    declared = tomllib.loads(text).get('tool', {}).get('lab_commons', {}).get(_TABLE, {})
    known = {field.name for field in dataclasses.fields(Review)}
    if unknown := sorted(set(declared) - known):
        msg = f'[tool.lab_commons.{_TABLE}] in {origin} has unknown key(s) {unknown}; the keys are {sorted(known)}'
        raise ValueError(msg)
    tuples = {key: tuple(declared[key]) for key in ('rules', 'command') if key in declared}
    return Review(**declared | tuples)


def load_review(root: Path) -> Review:
    """*root*'s working-tree ``[tool.lab_commons.review]``; defaults when it has no manifest."""
    manifest = root / 'pyproject.toml'
    return review_from(manifest.read_text(encoding='utf-8'), str(manifest)) if manifest.is_file() else Review()


def review_key(*, cwd: Path | None = None, fill: Callable[..., str] = api_key) -> str:
    """The reviewer's own key, :data:`KEY_NAME` alone; :class:`ReviewKeyMissing` naming it when absent."""
    try:
        return fill(API_HOST, task=KEY_TASK, cwd=cwd)
    except NoCredential as missing:
        msg = (
            f'the PR reviewer has no key {KEY_NAME} (no other key is ever used): store its dedicated Anthropic '
            f'API key with `python -m ai_lab.auth login anthropic --task {KEY_TASK}`: {missing}'
        )
        raise ReviewKeyMissing(msg) from None


def anthropic(
    ask: Ask, key: str, *, transport: Callable[[str, float], http.client.HTTPSConnection] = https_transport
) -> str:
    """The text of one Messages API answer to *ask*. The key travels in a header only, never in an error."""
    body = {
        'model': ask.model,
        'max_tokens': ask.max_tokens,
        'system': ask.system,
        'messages': [{'role': 'user', 'content': ask.prompt}],
    }
    headers = {'x-api-key': key, 'anthropic-version': _API_VERSION, 'content-type': 'application/json'}
    connection = transport(API_HOST, _TIMEOUT_S)
    try:
        connection.request('POST', '/v1/messages', json.dumps(body).encode(), headers)
        answer = connection.getresponse()
        raw = answer.read().decode('utf-8', errors='replace')
    finally:
        connection.close()
    if answer.status != _OK:
        msg = f'the model answered HTTP {answer.status}: {raw[:300]}'
        raise OSError(msg)
    return ''.join(block.get('text', '') for block in json.loads(raw).get('content', ()))


def _git(root: Path, *args: str) -> str:
    done = _door.run(
        ['git', *args], cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=_GIT_TIMEOUT_S, check=False,
    )  # fmt: skip
    if done.returncode != 0:
        msg = f'git {" ".join(args)} failed: {done.stderr.strip()[:300]}'
        raise OSError(msg)
    return done.stdout


def _rules(root: Path, base: str, patterns: tuple[str, ...]) -> str:
    """Every tracked file at *base* one of *patterns* matches, each under its path."""
    paths = _git(root, 'ls-tree', '-r', '--name-only', base).splitlines()
    chosen = [path for path in paths if any(fnmatch.fnmatchcase(path, one) for one in patterns)]
    return '\n\n'.join(f'=== {path} ===\n{_git(root, "show", f"{base}:{path}")}' for path in chosen)


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
