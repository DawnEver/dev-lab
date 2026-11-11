"""ACTIONS ALONE: a GitHub repo is tested and gated by GitHub Actions only (user ruling 2026-11-11); Gitea keeps all.

Every test pairs the GitHub refusal with its PLANTED CONTROL on Gitea, so neither side reads a constant.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from _protect_fakes import GITEA_TEXT, GITHUB_TEXT

from dev_lab.dev import forgereview_gate, integrate
from dev_lab.dev._forgebackends import (
    ACTIONS,
    ADVISORY,
    BACKENDS,
    FORGE_SERVE,
    GITEA,
    GITHUB,
    JUDGE_HOST,
    NotWired,
    require_producer,
)
from dev_lab.dev.ciworkflows import placed
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgecontexts import JUDGE_CHECK, MERGE_READY_CONTEXT, REVIEW_CONTEXT
from dev_lab.dev.forgeprotect import INTEGRATION, TRUNK, required_contexts
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.reviewgate import PREPARE_WORKFLOW

JUDGE_LOGIN = '[tool.dev_lab.review]\nwhere = "judge"\njudge_login = "judge"\n'
JUDGE_APP = '[tool.dev_lab.review]\nwhere = "judge"\njudge_app = 5619495\n'
HUB = Forge('github.com', 'owner', 'alpha')
TEA = Forge('gitea.example', 'owner', 'alpha')


def test_github_wires_its_actions_alone_and_gitea_every_producer() -> None:
    assert GITHUB.producers == {ACTIONS}
    assert GITEA.producers == {ACTIONS, FORGE_SERVE, JUDGE_HOST}
    assert BACKENDS == {'github': GITHUB, 'gitea': GITEA}
    with pytest.raises(NotWired, match='github does not wire'):
        require_producer(GITHUB, FORGE_SERVE, 'forge serve of x')
    require_producer(GITEA, FORGE_SERVE, 'forge serve of x')  # PLANTED CONTROL


@pytest.mark.parametrize('review', [JUDGE_LOGIN, JUDGE_APP])
def test_a_github_repo_declaring_a_judge_is_refused_at_render_and_a_gitea_one_renders_its_prepare(review: str) -> None:
    with pytest.raises(NotWired, match='judge-host'):
        placed(review, 'p', 'github')
    if review == JUDGE_LOGIN:
        assert PREPARE_WORKFLOW in placed(review, 'p', 'gitea'), 'PLANTED CONTROL: Gitea keeps its judge'


def test_a_github_repo_s_merge_gate_names_only_actions_produced_contexts() -> None:
    """Its merge-ready is a job of ci.yml after the Actions part, security and head-gate jobs; review runs there too."""
    ci = placed(GITHUB_TEXT, 'p', 'github')['ci.yml'][1]
    jobs = ci['jobs']
    assert set(jobs['merge-ready']['needs']) <= set(jobs)
    assert 'forge review run' in str(jobs['review']), 'the review is an Actions job, not a judge host'
    assert PREPARE_WORKFLOW not in placed(GITHUB_TEXT, 'p', 'github')
    contexts = required_contexts(GITHUB_TEXT, 'p', HUB)
    assert contexts[INTEGRATION] == (MERGE_READY_CONTEXT,)
    assert all(JUDGE_CHECK not in one and REVIEW_CONTEXT not in one for one in contexts.values())
    assert contexts[TRUNK] == ('tests/base', 'tests/base@macos', 'tests/base@windows')


def test_a_gitea_repo_s_gate_still_reads_its_serve_host_s_contexts() -> None:
    """PLANTED CONTROL: Gitea's serve host merges, so its integration requires the part and security it posts."""
    assert required_contexts(GITEA_TEXT, 'p', TEA)[INTEGRATION] == ('tests/base', 'tests/security')


@pytest.mark.parametrize('judge_app', [0, 5619495])
def test_no_merge_gate_waits_on_the_judge_on_either_forge(monkeypatch: pytest.MonkeyPatch, judge_app: int) -> None:
    """User ruling 2026-11-11: GitHub wires no judge host; on Gitea the judge's verdict is advisory, never waited on.

    PLANTED CONTROL: a Gitea serve repo with no tests/review posted still waits on its review.
    """
    assert JUDGE_HOST in ADVISORY
    judge = SimpleNamespace(where='judge', judge_app=judge_app, judge_login='judge')
    monkeypatch.setattr(forgereview_gate, 'forge_review', lambda _client, _base: judge)
    with pytest.raises(NotWired):
        forgereview_gate.review_gate(SimpleNamespace(backend=GITHUB), base='integrate/main')
    unapproved = [CommitStatus('tests/base', 'success', 'scope=full ran=1 hands=-', '')]
    assert forgereview_gate.review_gate(SimpleNamespace(backend=GITEA), base='integrate/main')(unapproved) is None
    serve = SimpleNamespace(where='serve', judge_app=0, judge_login='')
    monkeypatch.setattr(forgereview_gate, 'forge_review', lambda _client, _base: serve)
    monkeypatch.setattr(forgereview_gate, 'forge_posted', lambda _client: lambda _status: True)
    assert forgereview_gate.review_gate(SimpleNamespace(backend=GITEA), base='integrate/main')(unapproved) is not None


@pytest.mark.parametrize(('backend', 'waived'), [(GITHUB, {'femm'}), (GITEA, set())])
def test_promotion_on_github_waives_a_heavy_part_no_actions_job_produces(
    monkeypatch: pytest.MonkeyPatch, backend, waived: set[str]
) -> None:
    """A heavy test is KEPT and off GitHub's gate; Gitea's promotion still waits on it (PLANTED CONTROL)."""
    monkeypatch.setattr(
        integrate, 'pyproject_at', lambda _root, _sha: '[tool.lab_commons.tests]\nresources = ["femm"]\n'
    )
    statuses = [CommitStatus('tests/base', 'success', 'scope=full ran=3 hands=femm:2', '')]
    client = SimpleNamespace(backend=backend)
    assert integrate._off_gate(None, client, 'a' * 40, statuses) == waived
