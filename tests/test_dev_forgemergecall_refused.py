"""A MERGE THE FORGE REFUSES NAMES ITS CAUSE AND DOOR, on a REAL loopback forge, both backends (dev-lab #1066).

Gitea answers a PR conflicting with its base 405 "Please try again later" (``mergeable: false``); GitHub 405
"Pull Request is not mergeable" (``mergeable_state: dirty``). Either is said as the conflict's door; a red
``pr-current`` status is said as PR-HEAD-IS-CURRENT's; any other refusal keeps the forge's text. PLANTED: a clean
PR merges, and a refusal whose PR is clean is never said as a conflict.
"""

from __future__ import annotations

from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from typing import Any

import pytest
from _forge_fake import Loopback, Recorder, answer, client, serve

from dev_lab.dev.forge import Forge
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgemergecall import MergeRefused, merge
from dev_lab.dev.prcurrent import RULE, SYNC

_SHA = 'a' * 40
_GITEA = (Forge('forge.example.org', 'o', 'r'), '/api/v1/repos/o/r', 'POST')
_GITHUB = (Forge('github.com', 'o', 'r'), '/repos/o/r', 'PUT')
_BACKENDS = pytest.mark.parametrize(('forge', 'repo', 'verb'), [_GITEA, _GITHUB], ids=['gitea', 'github'])


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


def _pull(*, conflict: bool) -> dict[str, Any]:
    return {
        'number': 7, 'head': {'ref': 'pr/x', 'sha': _SHA}, 'base': {'ref': 'integrate/main'},
        'mergeable': not conflict, 'mergeable_state': 'dirty' if conflict else 'blocked',
    }  # fmt: skip


def _refused(server: ThreadingHTTPServer, forge: Forge) -> str:
    with pytest.raises(MergeRefused) as refused:
        merge(client(forge, Loopback(server)), 7, head=_SHA, message='s\n\nb', delete_branch=False)
    assert isinstance(refused.value, ForgeCallFailed), 'every door catching a failed merge says it'
    return str(refused.value)


@_BACKENDS
def test_a_merge_refused_for_a_conflict_names_the_base_and_the_sync_door(
    server: ThreadingHTTPServer, forge: Forge, repo: str, verb: str
) -> None:
    answer(verb, f'{repo}/pulls/7/merge', (405, {'message': 'Please try again later'}))
    answer('GET', f'{repo}/pulls/7', (200, _pull(conflict=True)))
    said = _refused(server, forge)
    assert said.startswith(f'o/r#7 conflicts with integrate/main: merge integrate/main into pr/x -- {SYNC}, resolve')
    assert 'Please try again later' in said, "the forge's own text stays on record"


@_BACKENDS
def test_a_merge_refused_on_a_red_pr_current_names_pr_head_is_current(
    server: ThreadingHTTPServer, forge: Forge, repo: str, verb: str
) -> None:
    answer(verb, f'{repo}/pulls/7/merge', (405, {'message': 'Not all required status checks successful'}))
    answer('GET', f'{repo}/pulls/7', (200, _pull(conflict=False)))
    status = {'id': 1, 'context': 'pr-current', 'state': 'failure', 'status': 'failure', 'description': 'lock stale'}
    statuses = f'{repo}/commits/{_SHA}/statuses' if forge.host == 'github.com' else f'{repo}/statuses/{_SHA}'
    answer('GET', statuses, (200, [status]))
    said = _refused(server, forge)
    assert f'its head is not current ({RULE}): lock stale -- {SYNC}, push' in said
    assert 'conflicts with' not in said, 'PLANTED: a clean PR is never said to conflict'


@_BACKENDS
def test_an_unknown_merge_refusal_keeps_the_forge_s_text(
    server: ThreadingHTTPServer, forge: Forge, repo: str, verb: str
) -> None:
    answer(verb, f'{repo}/pulls/7/merge', (405, {'message': 'merge disabled by a planted rule'}))
    answer('GET', f'{repo}/pulls/7', (200, _pull(conflict=False)))
    said = _refused(server, forge)
    assert said.startswith('o/r#7: the forge refused the merge:')
    assert 'merge disabled by a planted rule' in said
    assert 'conflicts with' not in said
    assert RULE not in said


@_BACKENDS
def test_a_clean_pr_merges_and_reads_no_cause(server: ThreadingHTTPServer, forge: Forge, repo: str, verb: str) -> None:
    """PLANTED CONTROL: the merge call answered, nothing is read off the PR."""
    answer(verb, f'{repo}/pulls/7/merge', (200, {'merged': True}))
    merge(client(forge, Loopback(server)), 7, head=_SHA, message='s\n\nb', delete_branch=False)
    assert [(one['method'], one['path']) for one in Recorder.received] == [(verb, f'{repo}/pulls/7/merge')]
