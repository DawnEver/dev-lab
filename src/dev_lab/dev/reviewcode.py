"""REVIEW-CODE: what a review reads as code, and the review job's first step, which settles a PR with none.

THE ONE CLASSIFICATION (user ruling 2026-10-29): a review reads what executes -- :data:`CODE` minus
:data:`NOT_CODE`, either overridden by a repo's ``[tool.dev_lab.review]`` ``code`` / ``not_code``.
:mod:`dev_lab.dev.forgereview_scope` cuts every review by :func:`is_code`; this module is its one home.

THE FIRST STEP OF GITEA'S REVIEW JOB (:func:`main`, 2026-11-03): a PR whose every changed file is not code -- a
consumer's memory-only PR (#5514) -- paid a mirror clone and two venv installs per push (100-150 s each) only for
the review to post :data:`ONLY_GENERATED`. The step reads the PR's changed files from the forge API with the job
token, judges them by the SAME :func:`is_code` under the trusted integration branch's declared globs, and when
none is code posts that very ``success`` (the job's run URL as its target, so the gate counts it exactly as the
review's own) and tells the later steps to stop. It is CONSERVATIVE: the whole PR's files, never an increment
(so D52's "an empty push after a failure is never nothing to review" holds); only an open, non-draft PR into the
integration branch the DEFAULT branch declares (the trust chain of ``forgereview_declared.trusted_integration``);
and anything it cannot read decides "review it", never "skip".

STDLIB ONLY, and no ``dev_lab`` import: the job fetches this one file at the door's locked dev-lab commit and runs
it before any install.
"""

from __future__ import annotations

import json
import os
import sys
import tomllib
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Final

__all__ = [
    'CODE',
    'NOT_CODE',
    'ONLY_GENERATED',
    'REVIEW_CONTEXT',
    'SETTLED_OUTPUT',
    'Call',
    'forge_call',
    'is_code',
    'main',
    'matches',
    'nothing_to_review',
    'settle',
]

#: What a head whose change is only generated files is posted as (``success``): nothing a reviewer reads.
ONLY_GENERATED: Final = 'nothing to review: every changed file is generated or not code'

#: What executes, by glob: a changed file is reviewed only if it matches one and no :data:`NOT_CODE` glob.
CODE: Final = (
    '**/*.py', '**/*.pyi', '**/*.rs', '**/*.js', '**/*.mjs', '**/*.cjs', '**/*.ts', '**/*.tsx', '**/*.sh',
    '**/*.ps1', '**/*.bat', '**/*.cmd', '**/*.c', '**/*.h', '**/*.cpp', '**/*.hpp', '**/*.toml', '**/*.yml',
    '**/*.yaml', '**/*.cfg', '**/*.ini', '**/Makefile', '**/Dockerfile', '**/justfile',
)  # fmt: skip

#: Never code though its extension says so: agent memory, archived code, and golden reference data (a consumer repo
#: golden is a TOML of measured values, 15 MB each). Each glob is narrow -- a hook under ``.claude/``, a ``logs``
#: package or a ``golden_*.py`` module executes and is read.
NOT_CODE: Final = ('**/.claude/memory/**', 'attic/**', '**/golden*.toml')

#: The commit-status context the review posts (``forgecontexts.REVIEW_CONTEXT``; a test pins the two equal).
REVIEW_CONTEXT: Final = 'tests/review'

#: The step output the later steps of the job read: ``true`` when this step settled the head.
SETTLED_OUTPUT: Final = 'settled'

_PAGE: Final = 50
_TIMEOUT_S: Final = 60


def _whole(parts: Sequence[str], pattern: Sequence[str]) -> bool:
    """Whether *parts* match *pattern* segment by segment: ``**`` spans any number of segments."""
    if not pattern:
        return not parts
    if pattern[0] == '**':
        return any(_whole(parts[i:], pattern[1:]) for i in range(len(parts) + 1))
    return bool(parts) and fnmatchcase(parts[0], pattern[0]) and _whole(parts[1:], pattern[1:])


def matches(path: str, globs: Iterable[str]) -> bool:
    """Whole-path glob match (``PurePath.full_match`` semantics, which needs 3.13; the family declares 3.12)."""
    parts = path.split('/')
    return any(_whole(parts, glob.split('/')) for glob in globs)


def is_code(path: str, code: Iterable[str], not_code: Iterable[str]) -> bool:
    """Whether *path* executes: it matches a *code* glob and no *not_code* one."""
    return matches(path, code) and not matches(path, not_code)


def nothing_to_review(paths: Sequence[str], manifest: str) -> bool:
    """Whether *paths* (a PR's whole change) hold no code under the ``[tool.dev_lab.review]`` *manifest* declares.

    An empty change is never "nothing": an unread file list must not settle a head.
    """
    declared = tomllib.loads(manifest).get('tool', {}).get('dev_lab', {}).get('review', {})
    code, not_code = tuple(declared.get('code', CODE)), tuple(declared.get('not_code', NOT_CODE))
    return bool(paths) and not any(is_code(path, code, not_code) for path in paths)


#: ``(method, url, body)`` -> the decoded JSON reply, or the raw text for a ``raw`` read.
Call = Callable[[str, str, 'dict[str, Any] | None'], Any]


def settle(call: Call, api: str, number: int, head: str, run_id: str) -> str | None:
    """Post :data:`ONLY_GENERATED` on PR *number*'s *head* when nothing in it is code; why, else ``None``.

    *api* is ``<forge>/api/v1/repos/<owner>/<repo>``; *run_id* names this job's run, whose web URL the status
    links (``reviewgate.job_run_url``: read from the forge, never assembled).
    """
    pull = call('GET', f'{api}/pulls/{number}', None)
    if pull.get('state') != 'open' or pull.get('draft') or pull['head']['sha'] != head:
        return None
    default = call('GET', api, None)['default_branch']
    policy = tomllib.loads(call('GET', f'{api}/raw/pyproject.toml?ref={default}', None))
    integration = policy.get('tool', {}).get('dev_lab', {}).get('integrator', {}).get('integration')
    if not integration or pull['base']['ref'] != integration:
        return None
    paths: list[str] = []
    for page in range(1, 10_000):
        files = call('GET', f'{api}/pulls/{number}/files?limit={_PAGE}&page={page}', None)
        paths += [one['filename'] for one in files]
        if len(files) < _PAGE:
            break
    if not nothing_to_review(paths, call('GET', f'{api}/raw/pyproject.toml?ref={integration}', None)):
        return None
    run = call('GET', f'{api}/actions/runs/{run_id}', None)
    status = {'context': REVIEW_CONTEXT, 'state': 'success', 'description': ONLY_GENERATED,
              'target_url': str(run.get('html_url') or '')}  # fmt: skip
    call('POST', f'{api}/statuses/{head}', status)
    return f'#{number} {head[:12]}: {ONLY_GENERATED} ({len(paths)} files)'


def forge_call(token: str) -> Call:
    """A :data:`Call` on the forge API with *token*: JSON replies decoded, ``/raw/`` reads as text."""

    def call(method: str, url: str, body: dict[str, Any] | None) -> Any:  # noqa: ANN401 -- JSON or text
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(url, data=data, method=method)  # noqa: S310 -- the forge's https/http API
        request.add_header('Authorization', f'token {token}')
        if data is not None:
            request.add_header('Content-Type', 'application/json')
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as reply:  # noqa: S310
            text = reply.read().decode('utf-8')
        return text if '/raw/' in url else json.loads(text or 'null')

    return call


def main(env: Mapping[str, str] | None = None, call: Call | None = None) -> int:
    """The step: settle the event's PR when it holds no code, and write :data:`SETTLED_OUTPUT` to the step output.

    Never fails the job: whatever it cannot read, the full review runs.
    """
    env = os.environ if env is None else env
    try:
        api = f'{env["FORGE_URL"]}/api/v1/repos/{env["GITHUB_REPOSITORY"]}'
        said = settle(call or forge_call(env['GITHUB_TOKEN']), api, int(env['PR_NUMBER']), env['HEAD_SHA'],
                      env['GITHUB_RUN_ID'])  # fmt: skip
    except Exception as failed:  # noqa: BLE001 -- any unread fact means the review runs
        said, why = None, f'not settled ({type(failed).__name__}: {failed}): the review runs'
    else:
        why = said or 'code to review: the review runs'
    sys.stdout.buffer.write(why.encode('utf-8') + b'\n')  # bare interpreter: the kit's emit is absent
    with Path(env['GITHUB_OUTPUT']).open('a', encoding='utf-8') as out:
        out.write(f'{SETTLED_OUTPUT}={"true" if said else "false"}\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
