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
from dev_lab.dev.forgeprotect import INTEGRATION, TRUNK, required_contexts, targets
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.reviewgate import PREPARE_WORKFLOW

JUDGE_LOGIN = '[tool.dev_lab.review]\nwhere = "judge"\njudge_login = "judge"\n'
JUDGE_APP = '[tool.dev_lab.review]\nwhere = "judge"\njudge_app = 5619495\n'
HUB = Forge('github.com', 'owner', 'alpha')
TEA = Forge('gitea.example', 'owner', 'alpha')


def test_github_wires_no_serve_host_and_gitea_every_producer() -> None:
    assert GITHUB.producers == {ACTIONS, JUDGE_HOST}
    assert GITEA.producers == {ACTIONS, FORGE_SERVE, JUDGE_HOST}
    assert BACKENDS == {'github': GITHUB, 'gitea': GITEA}
    with pytest.raises(NotWired, match='github does not wire'):
        require_producer(GITHUB, FORGE_SERVE, 'forge serve of x')
    require_producer(GITEA, FORGE_SERVE, 'forge serve of x')  # PLANTED CONTROL


@pytest.mark.parametrize('review', [JUDGE_APP, ''])
def test_a_github_repo_s_gate_names_only_actions_produced_contexts_judge_or_not(review: str) -> None:
    """The judge host still reviews (review-prepare.yml renders), but no required context or approval waits on it.

    PLANTED CONTROL: the judge repo renders its prepare workflow; the serve repo does not.
    """
    text = GITHUB_TEXT + review
    assert (PREPARE_WORKFLOW in placed(text, 'p', 'github')) is bool(review)
    contexts = required_contexts(text, 'p', HUB)
    assert contexts[INTEGRATION] == (MERGE_READY_CONTEXT,)
    assert all(JUDGE_CHECK not in one and REVIEW_CONTEXT not in one for one in contexts.values())
    assert contexts[TRUNK] == ('tests/base', 'tests/base@macos', 'tests/base@windows')
    integration, _ = targets(text, 'p', HUB)
    assert (integration.judge_app, integration.approvals, integration.approver) == (0, 0, '')


def test_a_gitea_repo_s_gate_still_reads_its_serve_host_s_contexts() -> None:
    """PLANTED CONTROL: Gitea's serve host merges, so its integration requires the part and security it posts."""
    assert required_contexts(GITEA_TEXT, 'p', TEA)[INTEGRATION] == ('tests/base', 'tests/security')


@pytest.mark.parametrize('backend', [GITHUB, GITEA])
@pytest.mark.parametrize('judge_app', [0, 5619495])
def test_no_merge_gate_waits_on_the_judge_on_either_forge(monkeypatch: pytest.MonkeyPatch, backend, judge_app) -> None:
    """User ruling 2026-11-11: the judge's verdict is advisory on both forges, never waited on.

    PLANTED CONTROL: a serve repo with no tests/review posted still waits on its review.
    """
    assert JUDGE_HOST in ADVISORY
    judge = SimpleNamespace(where='judge', judge_app=judge_app, judge_login='judge')
    monkeypatch.setattr(forgereview_gate, 'forge_review', lambda _client, _base: judge)
    unapproved = [CommitStatus('tests/base', 'success', 'scope=full ran=1 hands=-', '')]
    assert forgereview_gate.review_gate(SimpleNamespace(backend=backend), base='integrate/main')(unapproved) is None
    serve = SimpleNamespace(where='serve', judge_app=0, judge_login='')
    monkeypatch.setattr(forgereview_gate, 'forge_review', lambda _client, _base: serve)
    monkeypatch.setattr(forgereview_gate, 'forge_posted', lambda _client: lambda _status: True)
    assert forgereview_gate.review_gate(SimpleNamespace(backend=backend), base='integrate/main')(unapproved) is not None


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
