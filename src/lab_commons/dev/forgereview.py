"""PR-REVIEW-IS-ADVISORY: a Claude review of every open PR into integration, once per head, gating nothing.

Step 4 of the branch flow (user ruling 2026-10-19). Gitea only: GitHub is a push mirror, and its PRs are
carried to the forge as ``pr/gh-<N>`` before they are reviewed here.

WHERE IT RUNS. A ``forge serve`` step (:func:`step`), on a host whose machine file declares the capability
``[capabilities.pr_review]``; no other host reads the key or calls the model.

THE KEY IS ITS OWN. The reviewer reads ONE dedicated Anthropic API key, used for nothing else, from the git
credential store (:mod:`lab_commons.credentials`) under :data:`CREDENTIAL_HOST` -- never another AI key,
never an environment variable. Absent, it is REFUSED BY THAT NAME (:class:`ReviewKeyMissing`), and nothing is
posted. The key is never logged, printed, posted or put in an exception text.

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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.credentials import NoCredential, credential_for
from lab_commons.dev.forge import https_transport
from lab_commons.dev.forgealarm import AUTH, Alarm
from lab_commons.dev.forgepulls import ListingIncomplete, Marker, comment_upsert, pr_list
from lab_commons.dev.forgestatus import status_list, status_post
from lab_commons.dev.forgework import ForgeCallFailed
from lab_commons.dev.lanepolicy import load_policy
from lab_commons.dev.platformparts import REVIEW_CONTEXT

if TYPE_CHECKING:
    from lab_commons.dev.forgework import Client, PullRequest

__all__ = [
    'CAPABILITY', 'CREDENTIAL_HOST', 'DEFAULT_MODEL', 'REVIEW_CONTEXT', 'Ask', 'Review', 'ReviewKeyMissing',
    'anthropic', 'load_review', 'review_from', 'review_key', 'review_tick', 'step',
]  # fmt: skip

#: The machine-file capability a host declares to run the reviewer: ``[capabilities.pr_review]``.
CAPABILITY: Final = 'pr_review'

#: The git-credential host the reviewer's OWN key is stored under -- a name no other key uses.
CREDENTIAL_HOST: Final = 'pr-review.anthropic.lab-commons'

#: The latest Claude, the default reviewer.
DEFAULT_MODEL: Final = 'claude-opus-5-5'

_TABLE: Final = 'review'
_API_HOST: Final = 'api.anthropic.com'
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
    return Review(**declared | ({'rules': tuple(declared['rules'])} if 'rules' in declared else {}))


def load_review(root: Path) -> Review:
    """*root*'s working-tree ``[tool.lab_commons.review]``; defaults when it has no manifest."""
    manifest = root / 'pyproject.toml'
    return review_from(manifest.read_text(encoding='utf-8'), str(manifest)) if manifest.is_file() else Review()


def review_key(*, cwd: Path | None = None, fill: Callable[..., tuple[str, str]] = credential_for) -> str:
    """The reviewer's own key, from :data:`CREDENTIAL_HOST` alone; :class:`ReviewKeyMissing` naming it when absent."""
    try:
        return fill(CREDENTIAL_HOST, cwd=cwd)[1]
    except NoCredential as missing:
        msg = (
            f'the PR reviewer has no key: store its dedicated Anthropic API key in the git credential store '
            f'under host {CREDENTIAL_HOST} (no other key is ever used): {missing}'
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
    connection = transport(_API_HOST, _TIMEOUT_S)
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


def _ask(root: Path, review: Review, pull: PullRequest, base: str, diff: str) -> Ask:
    system = f'{_INSTRUCTIONS}\n\n# The repository rules\n\n{_rules(root, base, review.rules)}'
    prompt = f'# PR #{pull.number}: {pull.title}\n\n{pull.body}\n\n# The diff\n\n```diff\n{diff}\n```\n'
    return Ask(review.model, system, prompt, review.max_tokens)


def review_tick(
    root: Path,
    client: Client,
    review: Review,
    *,
    base: str,
    key: Callable[[], str],
    ask: Callable[[Ask, str], str],
) -> tuple[str, ...]:
    """Review every open, non-draft PR into *base* whose head has no review status; the lines it says.

    *key* is read once, and only when a PR is due; a missing key raises before anything is posted.
    """
    lines: list[str] = []
    secret = ''
    target = f'origin/{base}'
    for pull in pr_list(client):
        head = pull.head_sha
        if pull.base != base or pull.draft or not head:
            continue
        if any(status.context == REVIEW_CONTEXT for status in status_list(client, head)):
            continue
        diff = _git(root, 'diff', f'{target}...{head}')
        size = len(diff.encode())
        if size > review.max_diff_bytes:
            why = f'not reviewed: the diff is {size} bytes, over the cap max_diff_bytes={review.max_diff_bytes}'
            status_post(client, head, context=REVIEW_CONTEXT, state='error', description=why)
            lines.append(f'#{pull.number} {head[:12]}: {why}')
            continue
        secret = secret or key()
        try:
            said = ask(_ask(root, review, pull, target, diff), secret)
        except (OSError, ValueError) as failed:
            why = f'the model call failed ({type(failed).__name__}); advisory, not retried on this head'
            status_post(client, head, context=REVIEW_CONTEXT, state='error', description=why)
            lines.append(f'#{pull.number} {head[:12]}: {why}')
            continue
        text = f'**Advisory review** of `{head[:12]}` by `{review.model}` -- it gates nothing.\n\n{said}'
        _, comment = comment_upsert(client, pull.number, kind=Marker.REVIEW, key=head, text=text)
        url = comment.url if comment else ''
        status_post(
            client, head, context=REVIEW_CONTEXT, state='success', target_url=url,
            description=f'advisory review by {review.model} posted; it does not gate the merge',
        )  # fmt: skip
        lines.append(f'#{pull.number} {head[:12]}: reviewed by {review.model}')
    return tuple(lines)


def step(
    root: Path,
    built: Client,
    repo: str,
    *,
    capabilities: Mapping[str, object],
    say: Callable[[str], None],
    alarm: Callable[[Alarm], object],
    key: Callable[[], str] | None = None,
    ask: Callable[[Ask, str], str] = anthropic,
) -> None:
    """The serve step: on a host declaring :data:`CAPABILITY` only; a missing key alarms, a forge failure is said."""
    if CAPABILITY not in capabilities:
        return
    try:
        policy, review = load_policy(root), load_review(root)
        reading = key or (lambda: review_key(cwd=root))
        for line in review_tick(root, built, review, base=policy.integration, key=reading, ask=ask):
            say(f'[serve] review: {line}')
    except ReviewKeyMissing as missing:
        alarm(Alarm(AUTH, repo, f'the PR reviewer has no key ({CREDENTIAL_HOST})', str(missing)))
    except (ForgeCallFailed, ListingIncomplete, OSError, ValueError, subprocess.SubprocessError) as failed:
        say(f'[serve] the PR review did not run: {failed}')
