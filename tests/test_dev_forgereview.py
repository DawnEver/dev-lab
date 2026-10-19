"""PR-REVIEW-IS-ADVISORY: a Claude review of each open PR, once per head, with its own key, gating nothing.

Real git repositories (a bare ``origin`` and a clone), the stateful fake forge, and a fake model: the evidence is
what the forge was asked to write and what the model was asked. Every refusal has its planted control.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _branch_repos import advance, clone_pair
from _forge_state import StateForge

from lab_commons.credentials import API_KEY_TASKS, NoCredential, key_username
from lab_commons.dev.forgealarm import AUTH, Alarm
from lab_commons.dev.forgemerge import decide
from lab_commons.dev.forgepulls import Marker, marker
from lab_commons.dev.forgereview import (
    API_HOST,
    CAPABILITY,
    DEFAULT_MODEL,
    KEY_NAME,
    KEY_TASK,
    REVIEW_CONTEXT,
    Ask,
    Review,
    ReviewKeyMissing,
    review_from,
    review_key,
    review_tick,
    step,
)
from lab_commons.dev.forgestatus import CommitStatus, status_list
from lab_commons.dev.lanepolicy import Policy
from lab_commons.dev.platformparts import standing
from lab_commons.outcomes import Conclusion

_KEY = 'sk-ant-the-review-key'
_RULES = '# Rules\n\n- NEVER-DO-X: never do x.\n'
_MANIFEST = "[tool.lab_commons.branchset]\ntrunk = 'main'\nsessions = ['integrate/main']\nephemeral = ['pr/*']\n"


class FakeModel:
    """Answers every ask with one finding, and records what it was asked."""

    def __init__(self) -> None:
        """No call yet."""
        self.asked: list[tuple[Ask, str]] = []

    def __call__(self, ask: Ask, key: str) -> str:
        self.asked.append((ask, key))
        return '- `x.txt:1` -- adds x, which NEVER-DO-X forbids.'


def _work(tmp_path: Path) -> tuple[Path, str]:
    """A clone whose ``integrate/main`` carries the rule files and whose ``pr/x`` adds one file; the PR head."""
    _, work = clone_pair(tmp_path)
    (work / '.claude' / 'rules').mkdir(parents=True)
    (work / 'tests').mkdir()
    advance(work, 'integrate/main', 'tests/test_a.py', 'def test_a():\n    assert True\n')  # the audit's subject
    advance(work, 'integrate/main', 'AGENTS.md', '# Agents\n')
    advance(work, 'integrate/main', '.claude/rules/taste.md', _RULES)
    (work / 'pyproject.toml').write_text(_MANIFEST, encoding='utf-8')
    head = advance(work, 'pr/x', 'x.txt', 'x\n')
    return work, head


def _forge(head: str, **pull: object) -> tuple[StateForge, int]:
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', title='add x', sha=head)
    forge.pulls[number] |= pull
    return forge, number


def _tick(work: Path, forge: StateForge, model: FakeModel, review: Review | None = None) -> tuple[str, ...]:
    return review_tick(work, forge, review or Review(), base='integrate/main', key=lambda: _KEY, ask=model)


def test_a_pr_is_reviewed_with_its_diff_and_the_repos_own_rules_and_the_result_is_posted(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    model = FakeModel()
    _tick(work, forge, model)
    ((ask, key),) = model.asked
    assert key == _KEY
    assert ask.model == DEFAULT_MODEL == 'claude-opus-5-5'
    assert 'NEVER-DO-X' in ask.system  # .claude/rules/**
    assert '# Agents' in ask.system  # AGENTS.md
    assert '+x' in ask.prompt
    assert 'x.txt' in ask.prompt
    (comment,) = forge.comments[number]
    assert marker(Marker.REVIEW, head) in comment['body']
    assert 'x.txt:1' in comment['body']
    (status,) = [s for s in status_list(forge, head) if s.context == REVIEW_CONTEXT]
    assert status.state == 'success'
    assert 'advisory' in status.description


def test_a_second_tick_on_the_same_head_posts_nothing_and_asks_nothing(tmp_path: Path) -> None:
    """PLANTED control: a new head on the same PR is reviewed again."""
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    model = FakeModel()
    _tick(work, forge, model)
    posted = (len(forge.comments[number]), len(forge.statuses[head]))
    _tick(work, forge, model)
    assert len(model.asked) == 1
    assert (len(forge.comments[number]), len(forge.statuses[head])) == posted
    moved = advance(work, 'pr/x', 'y.txt', 'y\n')
    forge.pulls[number]['head']['sha'] = moved
    _tick(work, forge, model)
    assert len(model.asked) == 2
    assert [s.context for s in status_list(forge, moved)] == [REVIEW_CONTEXT]


def test_a_missing_key_is_refused_by_its_own_name_and_no_other_key_is_read() -> None:
    """PLANTED control: the same reader with the key stored returns it."""
    asked: list[tuple[str, object]] = []

    def empty(host: str, **options: object) -> str:
        asked.append((host, options.get('task')))
        raise NoCredential(host)

    with pytest.raises(ReviewKeyMissing, match=KEY_NAME.replace('.', r'\.')):
        review_key(fill=empty)
    assert asked == [(API_HOST, KEY_TASK)]
    assert review_key(fill=lambda _host, **_: _KEY) == _KEY


def test_the_review_key_is_the_anthropic_hosts_pr_review_task_key() -> None:
    """The existing scheme, not a second one: the model's own host, the task's own username."""
    assert API_HOST == 'api.anthropic.com'
    assert KEY_TASK in API_KEY_TASKS
    assert KEY_NAME == f'{key_username(KEY_TASK)}@{API_HOST}' == 'api-key-pr-review@api.anthropic.com'


def test_a_tick_without_the_key_posts_nothing_and_raises_naming_it(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    model = FakeModel()

    def missing() -> str:
        raise ReviewKeyMissing(KEY_NAME)

    with pytest.raises(ReviewKeyMissing):
        review_tick(work, forge, Review(), base='integrate/main', key=missing, ask=model)
    assert model.asked == []
    assert forge.comments[number] == []
    assert forge.statuses.get(head, []) == []


def test_a_draft_is_skipped(tmp_path: Path) -> None:
    """PLANTED control: the same PR once ready for review is reviewed."""
    work, head = _work(tmp_path)
    for draft in ({'draft': True}, {'title': 'WIP: add x'}):
        forge, number = _forge(head, **draft)
        model = FakeModel()
        _tick(work, forge, model)
        assert model.asked == []
        assert forge.comments[number] == []
        forge.pulls[number] |= {'draft': False, 'title': 'add x'}
        _tick(work, forge, model)
        assert len(model.asked) == 1


def test_a_diff_over_the_cap_is_not_sent_and_says_so_once(tmp_path: Path) -> None:
    """PLANTED control: the same diff under a larger cap is reviewed (the first test)."""
    work, head = _work(tmp_path)
    forge, _ = _forge(head)
    model = FakeModel()
    _tick(work, forge, model, Review(max_diff_bytes=10))
    assert model.asked == []
    (status,) = status_list(forge, head)
    assert status.context == REVIEW_CONTEXT
    assert 'cap' in status.description
    _tick(work, forge, model, Review(max_diff_bytes=10))
    assert len(forge.statuses[head]) == 1


def test_a_pr_into_another_base_is_not_reviewed(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge = StateForge()
    forge.add_pull('pr/x', 'main', sha=head)
    model = FakeModel()
    _tick(work, forge, model)
    assert model.asked == []


def test_a_failed_model_call_posts_an_error_and_never_the_key(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge, number = _forge(head)

    def broken(_ask: Ask, key: str) -> str:
        msg = f'refused {key}'
        raise OSError(msg)

    lines = review_tick(work, forge, Review(), base='integrate/main', key=lambda: _KEY, ask=broken)
    (status,) = status_list(forge, head)
    assert status.state == 'error'
    assert _KEY not in status.description
    assert not any(_KEY in line for line in lines)
    assert forge.comments[number] == []


# --- advisory: the review gates nothing ----------------------------------------------------------------


def _status(context: str, state: str, description: str) -> CommitStatus:
    return CommitStatus(context, state, description, '', 1)


def test_the_review_status_is_not_a_part_so_it_never_gates_auto_merge(tmp_path: Path) -> None:
    """PLANTED control: a FAIL in a real part context on the same head does gate it."""
    passed = _status('tests/base', 'success', 'scope=full ran=3 hands=-')
    for review in ('failure', 'error', 'pending'):
        statuses = (passed, _status(REVIEW_CONTEXT, review, 'advisory review: 3 findings'))
        assert standing(statuses, head='h').result is Conclusion.PASS
    failed = (passed, _status('tests/jmag', 'failure', 'scope=full ran=3 hands=-'))
    assert standing(failed, head='h').result is Conclusion.FAIL
    work, head = _work(tmp_path)
    statuses = (passed, _status(REVIEW_CONTEXT, 'failure', 'advisory review'))
    found = decide(work, Policy(pr_merges_since='0' * 40), branch='pr/x', number=1, head=head, statuses=statuses)
    assert found.ready, found.missing


# --- the declaration ---------------------------------------------------------------------------------


def test_the_declaration_defaults_and_overrides_and_refuses_an_unknown_key() -> None:
    assert review_from('', 'p') == Review()
    declared = "[tool.lab_commons.review]\nmodel = 'claude-x'\nmax_diff_bytes = 5\n"
    assert review_from(declared, 'p') == Review(model='claude-x', max_diff_bytes=5)
    with pytest.raises(ValueError, match='unknown key'):
        review_from("[tool.lab_commons.review]\nmodle = 'x'\n", 'p')


# --- the serve step ----------------------------------------------------------------------------------


def test_the_step_runs_only_on_a_host_declaring_the_capability(tmp_path: Path) -> None:
    """PLANTED control: the same host with ``[capabilities.pr_review]`` reviews the PR."""
    work, head = _work(tmp_path)
    forge, _ = _forge(head)
    model = FakeModel()
    said: list[str] = []
    step(work, forge, 'r', capabilities={}, say=said.append, alarm=print, key=lambda: _KEY, ask=model)
    assert model.asked == []
    step(work, forge, 'r', capabilities={CAPABILITY: {}}, say=said.append, alarm=print, key=lambda: _KEY, ask=model)
    assert len(model.asked) == 1
    assert any('reviewed by' in line for line in said)


def test_the_step_alarms_a_missing_key_by_its_name_and_posts_nothing(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge, _ = _forge(head)
    raised: list[Alarm] = []

    def empty(host: str, **_: object) -> str:
        raise NoCredential(host)

    step(
        work, forge, 'r', capabilities={CAPABILITY: {}}, say=print, alarm=raised.append,
        key=lambda: review_key(fill=empty), ask=FakeModel(),
    )  # fmt: skip
    (alarm,) = raised
    assert alarm.kind == AUTH
    assert KEY_NAME in alarm.subject
    assert forge.statuses.get(head, []) == []
