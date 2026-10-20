"""PR-REVIEW-IS-ADVISORY: the repo's declared review command on each open PR, once per head, gating nothing.

Real git repositories (a bare ``origin`` and a clone), the stateful fake forge, and a fake review command printing
the findings JSON: the evidence is what the forge was asked to write and what the command was run with. Every
refusal has its planted control.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from _branch_repos import advance, clone_pair
from _forge_fake import git_out
from _forge_state import StateForge

from lab_commons.dev import forgereview
from lab_commons.dev.forgemerge import decide
from lab_commons.dev.forgepulls import Marker, marker
from lab_commons.dev.forgereview import (
    CLAIMED,
    DEFAULT_CLAIM_STALE,
    RANGE_FIELD,
    REFUSED_EXIT,
    RELEASED,
    RETIRED_KEYS,
    REVIEW_CONTEXT,
    TAKEOVER_PENDING,
    Review,
    ReviewRefused,
    ReviewUnsupported,
    can_start,
    render,
    review_from,
    review_tick,
    run_command,
    step,
)
from lab_commons.dev.forgereview_findings import UnknownSchemaVersion, parse_findings
from lab_commons.dev.forgestatus import CommitStatus, status_list
from lab_commons.dev.lanepolicy import Policy
from lab_commons.dev.platformparts import standing
from lab_commons.outcomes import Conclusion

_DECLARED = Review(command=('reviewer', '--range', RANGE_FIELD, '--model', 'm'))
_RULES = '# Rules\n\n- NEVER-DO-X: never do x.\n'
_MANIFEST = (
    "[tool.lab_commons.branchset]\ntrunk = 'main'\nsessions = ['integrate/main']\nephemeral = ['pr/*']\n"
    "[tool.lab_commons.review]\ncommand = ['reviewer', '--range', '{range}', '--model', 'm']\n"
)


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
    return review_tick(work, forge, review or _DECLARED, base='integrate/main', run=command, ready=_can)


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


def test_an_undeclared_command_reviews_nothing_and_says_so(tmp_path: Path) -> None:
    """No default command: the model is the command's to name. PLANTED control: declared, it reviews."""
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    command = FakeCommand()
    said: list[str] = []
    assert Review().command == ()
    (work / 'pyproject.toml').write_text(_MANIFEST.split('[tool.lab_commons.review]', maxsplit=1)[0], encoding='utf-8')
    step(work, forge, policy=Policy(), say=said.append, run=command, ready=_can)
    assert command.ran == []
    assert forge.comments[number] == []
    assert any('command is not declared' in line for line in said)


def test_exit_2_is_the_commands_named_refusal_and_its_reason_is_the_status(tmp_path: Path) -> None:
    """PLANTED control: another non-zero exit is a plain failure, not a refusal."""
    interpreter = sys.executable
    refuse = [interpreter, '-c', f'import sys; sys.stderr.write("unknown method version 9"); sys.exit({REFUSED_EXIT})']
    with pytest.raises(ReviewRefused, match='refused: unknown method version 9'):
        run_command(refuse, tmp_path)
    with pytest.raises(OSError, match='exited 1') as other:
        run_command([interpreter, '-c', 'import sys; sys.exit(1)'], tmp_path)
    assert not isinstance(other.value, ReviewRefused)
    work, head = _work(tmp_path)
    forge, number = _forge(head)

    def refusing(_argv: Sequence[str], _root: Path) -> str:
        msg = 'the review command refused: unknown method version 9'
        raise ReviewRefused(msg)

    review_tick(work, forge, _DECLARED, base='integrate/main', run=refusing, ready=_can)
    (status,) = status_list(forge, head)
    assert status.state == 'error'
    assert 'refused: unknown method version 9' in status.description
    assert forge.comments[number] == []


@pytest.mark.parametrize('kinds', [('exhausted',), ('auth',), ('exhausted', 'auth')], ids=['exhausted', 'auth', 'both'])
def test_every_reviewer_exhausted_or_auth_is_takeover_pending_and_never_a_failure(tmp_path: Path, kinds) -> None:
    """PLANTED controls: one ok reviewer among them posts the findings; a timeout among them is not a takeover."""
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    reviewers = tuple((f'r{at}', kind) for at, kind in enumerate(kinds))
    lines = _tick(work, forge, FakeCommand(_output(reviewers=reviewers)))
    (status,) = status_list(forge, head)
    assert status.state == 'pending'
    assert status.description.startswith(TAKEOVER_PENDING)
    assert forge.comments[number] == []
    assert TAKEOVER_PENDING in lines[0]
    assert standing((_status('tests/base', 'success', 'scope=full ran=3 hands=-'), status), head='h').result is (
        Conclusion.PASS
    )
    for mixed, state in (((*reviewers, ('c', 'ok')), 'success'), ((*reviewers, ('c', 'timeout')), 'error')):
        moved = advance(work, 'pr/x', f'{state}{len(mixed)}{kinds[0]}.txt', 'z\n')
        forge.pulls[number]['head']['sha'] = moved
        _tick(work, forge, FakeCommand(_output(reviewers=mixed)))
        (posted,) = status_list(forge, moved)
        assert posted.state == state
        assert TAKEOVER_PENDING not in posted.description


def _can(_argv: Sequence[str], _root: Path) -> str | None:
    return None  # every fake command can start


def test_a_host_without_the_commands_interpreter_or_module_is_unsupported_and_posts_nothing(tmp_path: Path) -> None:
    """Checked BEFORE the claim. PLANTED control: the same head on a host that can run it is reviewed."""
    interpreter = sys.executable
    assert 'not installed' in (can_start([str(tmp_path / 'no-such-python'), '-m', 'ai_lab.review'], tmp_path) or '')
    assert 'cannot import' in (can_start([interpreter, '-m', 'no_such_module_for_review'], tmp_path) or '')
    assert can_start([interpreter, '-m', 'json.tool'], tmp_path) is None
    with pytest.raises(ReviewUnsupported, match='cannot import'):
        run_command([interpreter, '-m', 'no_such_module_for_review'], tmp_path)
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    command = FakeCommand()
    lines = review_tick(work, forge, _DECLARED, base='integrate/main', run=command, ready=can_start)
    assert 'unsupported' in lines[0]
    assert 'nothing posted' in lines[0]
    assert command.ran == []
    assert forge.statuses.get(head, []) == []
    assert forge.comments[number] == []
    _tick(work, forge, command)
    (status,) = status_list(forge, head)
    assert status.state == 'success'


def test_a_command_that_turns_out_unsupported_releases_its_claim(tmp_path: Path) -> None:
    """PLANTED control: the released head is claimed and reviewed by the next host at once."""
    work, head = _work(tmp_path)
    forge, _ = _forge(head)

    def absent(_argv: Sequence[str], _root: Path) -> str:
        msg = 'unsupported: the review command cannot import its module on this host'
        raise ReviewUnsupported(msg)

    review_tick(work, forge, _DECLARED, base='integrate/main', run=absent, ready=_can, host='A')
    (released,) = status_list(forge, head)
    assert released.state == 'pending'
    assert released.description.startswith(f'{RELEASED} A')
    _tick(work, forge, FakeCommand())
    assert status_list(forge, head)[0].state == 'success'


def test_two_hosts_on_one_new_head_only_the_first_claims_and_reviews(tmp_path: Path) -> None:
    """The second host ticks WHILE the first is reviewing: it sees the claim and skips."""
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    second = FakeCommand()
    seen: list[tuple[str, ...]] = []

    class First(FakeCommand):
        def __call__(self, argv: Sequence[str], root: Path) -> str:
            seen.append(review_tick(work, forge, _DECLARED, base='integrate/main', run=second, ready=_can, host='B'))
            return super().__call__(argv, root)

    first = First()
    review_tick(work, forge, _DECLARED, base='integrate/main', run=first, ready=_can, host='A')
    assert len(first.ran) == 1
    assert second.ran == []
    assert seen == [()]
    posted = [one['description'] for one in forge.statuses[head]]
    assert posted[0].startswith(f'{CLAIMED} A at ')
    assert len(posted) == 2  # the claim, then the final status; B posted nothing
    assert status_list(forge, head)[0].state == 'success'
    assert len(forge.comments[number]) == 1


def test_a_stale_claim_is_re_claimable_after_the_declared_age(tmp_path: Path) -> None:
    """PLANTED control: the same claim younger than ``claim_stale`` holds the head."""
    work, head = _work(tmp_path)
    forge, _ = _forge(head)
    t0 = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    command = FakeCommand()
    with pytest.raises(_Died):
        review_tick(
            work, forge, _DECLARED, base='integrate/main', run=lambda *_: _die(), ready=_can, host='A', clock=lambda: t0
        )
    assert status_list(forge, head)[0].description.startswith(f'{CLAIMED} A at 2026-10-20T09:00:00')
    declared = Review(command=_DECLARED.command, claim_stale='30 min')
    for minutes, runs in ((29, 0), (30, 1)):
        at = t0 + timedelta(minutes=minutes)
        review_tick(
            work, forge, declared, base='integrate/main', run=command, ready=_can, host='B', clock=lambda at=at: at
        )
        assert len(command.ran) == runs
    assert status_list(forge, head)[0].state == 'success'
    assert Review().claim_stale == DEFAULT_CLAIM_STALE == '1 h'
    assert Review().stale == timedelta(hours=1)
    with pytest.raises(ValueError, match='claim_stale'):
        Review(claim_stale='30')


class _Died(BaseException):
    """The claimant dies mid-review: nothing it could catch, so its claim stays behind."""


def _die() -> str:
    raise _Died


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


@pytest.mark.parametrize('key', sorted(RETIRED_KEYS))
def test_a_key_of_the_retired_in_process_reviewer_is_refused_by_name(key: str) -> None:
    """PLANTED control: the same table without the retired key loads (the declaration test)."""
    with pytest.raises(ValueError, match=f'{key} is retired: the review'):
        review_from(f"[tool.lab_commons.review]\n{key} = 'x'\nmax_diff_bytes = 5\n", 'p')
    assert review_from('[tool.lab_commons.review]\nmax_diff_bytes = 5\n', 'p').max_diff_bytes == 5


def test_the_forge_holds_no_model_client_prompt_or_key() -> None:
    """The forge only orchestrates: the in-process reviewer's surface is gone, not aliased."""
    for gone in ('anthropic', 'Ask', 'review_key', 'API_HOST', 'KEY_NAME', 'DEFAULT_MODEL', 'CAPABILITY'):
        assert not hasattr(forgereview, gone), gone
    assert {field.name for field in dataclasses.fields(Review)} == {'command', 'max_diff_bytes'}


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
    _tick(work, forge, command, Review(command=_DECLARED.command, max_diff_bytes=10))
    assert command.ran == []
    (status,) = status_list(forge, head)
    assert status.context == REVIEW_CONTEXT
    assert 'cap' in status.description
    _tick(work, forge, command, Review(command=_DECLARED.command, max_diff_bytes=10))
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

    review_tick(work, forge, _DECLARED, base='integrate/main', run=broken, ready=_can)
    review_tick(work, forge, _DECLARED, base='integrate/main', run=broken, ready=_can)
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
    step(work, forge, policy=Policy(), say=said.append, run=command, ready=_can)
    assert len(command.ran) == 1
    assert any('reviewed, 1 finding(s)' in line for line in said)

    class Down(StateForge):
        def call(self, *_a: object, **_k: object) -> object:
            msg = 'down'
            raise OSError(msg)

    said.clear()
    step(work, Down(), policy=Policy(), say=said.append, run=command, ready=_can)
    assert any('did not run' in line for line in said)
