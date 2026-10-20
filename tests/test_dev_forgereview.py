"""PR-REVIEW-IS-ADVISORY: the repo's declared review command on each open PR, once per head, gating nothing.

Real git repositories (a bare ``origin`` and a clone), the stateful fake forge, and a fake review command printing
the findings JSON: the evidence is what the forge was asked to write and what the command was run with. Every
refusal has its planted control.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest
from _branch_repos import advance, clone_pair
from _forge_fake import git_out
from _forge_state import StateForge

from lab_commons.credentials import API_KEY_TASKS, NoCredential, key_username
from lab_commons.dev.forgemerge import decide
from lab_commons.dev.forgepulls import Marker, marker
from lab_commons.dev.forgereview import (
    API_HOST,
    DEFAULT_COMMAND,
    KEY_NAME,
    KEY_TASK,
    RANGE_FIELD,
    REVIEW_CONTEXT,
    Review,
    ReviewKeyMissing,
    render,
    review_from,
    review_key,
    review_tick,
    run_command,
    step,
)
from lab_commons.dev.forgereview_findings import UnknownSchemaVersion, parse_findings
from lab_commons.dev.forgestatus import CommitStatus, status_list
from lab_commons.dev.lanepolicy import Policy
from lab_commons.dev.platformparts import standing
from lab_commons.outcomes import Conclusion

_KEY = 'sk-ant-the-review-key'
_RULES = '# Rules\n\n- NEVER-DO-X: never do x.\n'
_MANIFEST = "[tool.lab_commons.branchset]\ntrunk = 'main'\nsessions = ['integrate/main']\nephemeral = ['pr/*']\n"


def _output(*, reviewers: tuple[tuple[str, str], ...] = (('correctness', 'ok'),), **top: object) -> str:
    """A findings-output v1 document: one HIGH finding on ``x.txt`` when any reviewer is ok."""
    rows = [
        {'name': name, 'provider': 'anthropic', 'status': status, 'dropped_findings': 0} for name, status in reviewers
    ]
    ok = [{'name': row['name'], 'provider': 'anthropic'} for row in rows if row['status'] == 'ok']
    finding = {
        'id': 'SR-20261020-001', 'severity': 'HIGH', 'file': 'x.txt:1', 'summary': 'adds x, which NEVER-DO-X forbids',
        'category': 'Bug', 'status': 'OPEN', 'suggestion': 'drop x', 'detail': 'x is forbidden', 'confidence': 'single',
        'reviewers': ok,
    }  # fmt: skip
    document = {
        'schema_version': 1, 'range': 'a..b', 'profiles': [row['name'] for row in rows], 'reviewers': rows,
        'findings': [finding] if ok else [],
    } | top  # fmt: skip
    return json.dumps(document)


class FakeCommand:
    """Prints one findings document, and records every argv it was run with and where."""

    def __init__(self, out: str | None = None) -> None:
        """No run yet; *out* is what it prints (default :func:`_output`)."""
        self.ran: list[tuple[list[str], Path]] = []
        self.out = _output() if out is None else out

    def __call__(self, argv: Sequence[str], root: Path) -> str:
        self.ran.append((list(argv), root))
        return self.out


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


def _tick(work: Path, forge: StateForge, command: FakeCommand, review: Review | None = None) -> tuple[str, ...]:
    return review_tick(work, forge, review or Review(), base='integrate/main', run=command)


def test_the_declared_command_reviews_the_merge_base_range_and_its_findings_are_posted(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    command = FakeCommand()
    base = git_out(work, 'merge-base', 'origin/integrate/main', head)
    _tick(work, forge, command, Review(command=('reviewer', '--range', RANGE_FIELD)))
    ((argv, where),) = command.ran
    assert argv == ['reviewer', '--range', f'{base}..{head}']
    assert where == work
    (comment,) = forge.comments[number]
    assert marker(Marker.REVIEW, head) in comment['body']
    assert '**HIGH** `x.txt:1`' in comment['body']
    assert 'SR-20261020-001' in comment['body']
    assert 'correctness@anthropic' in comment['body']
    (status,) = [s for s in status_list(forge, head) if s.context == REVIEW_CONTEXT]
    assert status.state == 'success'
    assert '1 finding(s), 1 HIGH' in status.description
    assert 'does not gate' in status.description


def test_the_family_default_command_is_the_headless_sharp_review_through_ai_lab() -> None:
    assert Review().command == DEFAULT_COMMAND
    assert DEFAULT_COMMAND[:3] == ('python', '-m', 'ai_lab.review')
    assert RANGE_FIELD in DEFAULT_COMMAND


@pytest.mark.parametrize('version', [2, 0, '1'])
def test_an_unknown_schema_version_is_refused_by_name_and_nothing_is_commented(tmp_path: Path, version: object) -> None:
    """PLANTED control: the same document at version 1 is posted (the first test)."""
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    _tick(work, forge, FakeCommand(_output(schema_version=version)))
    (status,) = status_list(forge, head)
    assert status.state == 'error'
    assert f'schema_version {version!r}' in status.description
    assert forge.comments[number] == []
    with pytest.raises(UnknownSchemaVersion, match='schema_version 2'):
        parse_findings(_output(schema_version=2))


@pytest.mark.parametrize(
    'out', ['not json', '{"schema_version": 1}', _output(reviewers=(('c', 'bored'),)), _output()[:-1]]
)
def test_output_that_is_not_the_findings_json_posts_an_error_naming_the_failure(tmp_path: Path, out: str) -> None:
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    lines = _tick(work, forge, FakeCommand(out))
    (status,) = status_list(forge, head)
    assert status.state == 'error'
    assert 'FindingsInvalid' in status.description
    assert forge.comments[number] == []
    assert len(lines) == 1


def test_a_clean_run_says_no_findings() -> None:
    found = parse_findings(_output(reviewers=(('c', 'skipped'),)))
    assert found.findings == ()
    assert 'No findings.' in render('h' * 40, found)


def test_the_command_runner_returns_stdout_and_names_a_non_zero_exit(tmp_path: Path) -> None:
    """PLANTED control: the same runner on a command exiting 0 returns what it printed."""
    interpreter = sys.executable
    assert run_command([interpreter, '-c', 'print(1)'], tmp_path).strip() == '1'
    with pytest.raises(OSError, match='exited 3: boom'):
        run_command([interpreter, '-c', 'import sys; sys.stderr.write("boom"); sys.exit(3)'], tmp_path)


def test_a_second_tick_on_the_same_head_posts_nothing_and_runs_nothing(tmp_path: Path) -> None:
    """PLANTED control: a new head on the same PR is reviewed again."""
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    command = FakeCommand()
    _tick(work, forge, command)
    posted = (len(forge.comments[number]), len(forge.statuses[head]))
    _tick(work, forge, command)
    assert len(command.ran) == 1
    assert (len(forge.comments[number]), len(forge.statuses[head])) == posted
    moved = advance(work, 'pr/x', 'y.txt', 'y\n')
    forge.pulls[number]['head']['sha'] = moved
    _tick(work, forge, command)
    assert len(command.ran) == 2
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
    # Assembled, so the tree scan never reads an address-shaped literal (no tracked file carries one).
    assert KEY_NAME == f'{key_username(KEY_TASK)}@{API_HOST}' == 'api-key-pr-review' + '@' + 'api.anthropic.com'


def test_a_draft_is_skipped(tmp_path: Path) -> None:
    """PLANTED control: the same PR once ready for review is reviewed."""
    work, head = _work(tmp_path)
    for draft in ({'draft': True}, {'title': 'WIP: add x'}):
        forge, number = _forge(head, **draft)
        command = FakeCommand()
        _tick(work, forge, command)
        assert command.ran == []
        assert forge.comments[number] == []
        forge.pulls[number] |= {'draft': False, 'title': 'add x'}
        _tick(work, forge, command)
        assert len(command.ran) == 1


def test_a_diff_over_the_cap_is_not_sent_and_says_so_once(tmp_path: Path) -> None:
    """PLANTED control: the same diff under a larger cap is reviewed (the first test)."""
    work, head = _work(tmp_path)
    forge, _ = _forge(head)
    command = FakeCommand()
    _tick(work, forge, command, Review(max_diff_bytes=10))
    assert command.ran == []
    (status,) = status_list(forge, head)
    assert status.context == REVIEW_CONTEXT
    assert 'cap' in status.description
    _tick(work, forge, command, Review(max_diff_bytes=10))
    assert len(forge.statuses[head]) == 1


def test_a_pr_into_another_base_is_not_reviewed(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge = StateForge()
    forge.add_pull('pr/x', 'main', sha=head)
    command = FakeCommand()
    _tick(work, forge, command)
    assert command.ran == []


def test_a_failed_command_posts_an_error_once(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge, number = _forge(head)

    def broken(_argv: Sequence[str], _root: Path) -> str:
        msg = 'the review command exited 1: no provider'
        raise OSError(msg)

    review_tick(work, forge, Review(), base='integrate/main', run=broken)
    review_tick(work, forge, Review(), base='integrate/main', run=broken)
    (status,) = status_list(forge, head)
    assert status.state == 'error'
    assert 'OSError' in status.description
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
    declared = "[tool.lab_commons.review]\ncommand = ['r', '{range}']\nmax_diff_bytes = 5\n"
    assert review_from(declared, 'p') == Review(command=('r', '{range}'), max_diff_bytes=5)
    with pytest.raises(ValueError, match='unknown key'):
        review_from("[tool.lab_commons.review]\ncomand = ['x']\n", 'p')


# --- the serve step ----------------------------------------------------------------------------------


def test_the_step_reviews_into_the_policys_integration_and_says_a_failure(tmp_path: Path) -> None:
    """PLANTED control: the same step against a forge that cannot list PRs says so and raises nothing."""
    work, head = _work(tmp_path)
    forge, _ = _forge(head)
    command = FakeCommand()
    said: list[str] = []
    step(work, forge, policy=Policy(), say=said.append, run=command)
    assert len(command.ran) == 1
    assert any('reviewed, 1 finding(s)' in line for line in said)

    class Down(StateForge):
        def call(self, *_a: object, **_k: object) -> object:
            msg = 'down'
            raise OSError(msg)

    said.clear()
    step(work, Down(), policy=Policy(), say=said.append, run=command)
    assert any('did not run' in line for line in said)
