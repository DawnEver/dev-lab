"""PR-REVIEW-IS-ONE-SHOT-ADVICE: the declared review command, once per PR; its findings advice.

Real git repositories (a bare ``origin`` and a clone), the stateful fake forge, and a fake review command printing
the findings JSON: the evidence is what the forge was asked to write and what the command was run with. Every
refusal has its planted control.
"""

from __future__ import annotations

import dataclasses
import json
import re
import socket
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from _branch_repos import advance, clone_pair
from _forge_fake import git_out, run_git
from _forge_state import StateForge
from _review_doubles import _state
from lab_commons.outcomes import Conclusion

from dev_lab.dev import forgereview_command
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgemerge import decide
from dev_lab.dev.forgepulls import Marker, marker
from dev_lab.dev.forgereview import (
    NEEDS_MAINTAINER,
    REVIEW_AGAIN_GROWTH,
    ask_again,
    review_pull,
    review_tick,
    step,
)
from dev_lab.dev.forgereview_advice import ONE_SHOT, trusted_bodies
from dev_lab.dev.forgereview_claim import CLAIMED, HOST_UNABLE, RETRYING, UNREVIEWED_STATUS
from dev_lab.dev.forgereview_command import (
    REFUSED_EXIT,
    ReviewRefused,
    ReviewUnsupported,
    Runner,
    can_start,
    run_command,
)
from dev_lab.dev.forgereview_declared import (
    DEFAULT_CLAIM_STALE,
    EMPTY_COMMAND_FIX,
    FAMILY_COMMAND,
    PATHS_FIELD,
    RANGE_FIELD,
    RETIRED_KEYS,
    Review,
    command_for,
    review_from,
)
from dev_lab.dev.forgereview_findings import UnknownSchemaVersion, parse_findings
from dev_lab.dev.forgereview_runtimes import HOST_FIELD, retired_table
from dev_lab.dev.forgestatus import CommitStatus, status_list
from dev_lab.dev.forgework import ACTIONS_BOT
from dev_lab.dev.lanepolicy import Policy
from dev_lab.dev.platformparts import HOLD_CONTEXT, REVIEW_CONTEXT, standing
from dev_lab.dev.reviewbudget import Spend
from dev_lab.dev.reviewcap import UNREVIEWED, unreviewed_line, waiver_of
from dev_lab.dev.reviewgate import github_posted, status_gate

_LANE_POLICY = Policy(integration='integrate/main')  # every repo declares its integration branch (D83)

_DECLARED = Review(command=('reviewer', '--range', RANGE_FIELD, '--model', 'm'))
_RULES = '# Rules\n\n- NEVER-DO-X: never do x.\n'
_MANIFEST = (
    "[tool.dev_lab.branchset]\ntrunk = 'main'\nsessions = ['integrate/main']\nephemeral = ['pr/*']\n"
    "[tool.dev_lab.review]\ncommand = ['reviewer', '--range', '{range}', '--model', 'm']\n"
    "quiet = '0 s'\n"  # the step reviews at once; the debounce has its own test
    "[tool.dev_lab.integrator]\nintegration = 'integrate/main'\n"  # every repo declares it (D83)
)


def _output(
    *,
    reviewers: tuple[tuple[str, str], ...] = (('correctness', 'ok'),),
    severity: str = 'MEDIUM',
    security: bool = False,
    **top: object,
) -> str:
    """A findings-output v3 document: one tagged finding anchored on ``x.py``'s line, when any reviewer is ok."""
    rows = [
        {'name': name, 'provider': 'anthropic', 'status': status, 'dropped_findings': 0} for name, status in reviewers
    ]
    ok = [{'name': row['name'], 'provider': 'anthropic'} for row in rows if row['status'] == 'ok']
    finding = {
        'id': 'F-0123456789ab', 'severity': severity, 'security': security, 'rule': 'NEVER-DO-X', 'file': 'x.py',
        'anchor': 'x', 'summary': 'adds x, which NEVER-DO-X forbids', 'category': 'Bug', 'status': 'OPEN',
        'suggestion': 'drop x', 'detail': 'x is forbidden', 'confidence': 'single', 'reviewers': ok,
    }  # fmt: skip
    document = {
        'schema_version': 3, 'range': 'a..b', 'profiles': [row['name'] for row in rows], 'reviewers': rows,
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
    advance(work, 'main', 'pyproject.toml', _MANIFEST)  # the review a PR is reviewed under (review_at): the base's
    run_git(work, 'push', '-q', 'origin', 'origin/main:refs/heads/integrate/main')  # one commit, the head's too
    run_git(work, 'fetch', '-q', 'origin')
    advance(work, 'integrate/main', 'tests/test_a.py', 'def test_a():\n    assert True\n')  # the audit's subject
    advance(work, 'integrate/main', 'AGENTS.md', '# Agents\n')
    advance(work, 'integrate/main', '.claude/rules/taste.md', _RULES)
    head = advance(work, 'pr/x', 'x.py', 'x\n')
    return work, head


def _forge(head: str, **pull: object) -> tuple[StateForge, int]:
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', title='add x', sha=head)
    forge.pulls[number] |= pull
    return forge, number


def _tick(work: Path, forge: StateForge, command: FakeCommand, review: Review | None = None) -> tuple[str, ...]:
    return review_tick(work, forge, review or _DECLARED, base='integrate/main', run=command, ready=_can, host='box')


def test_the_declared_command_reviews_the_merge_base_range_and_its_advice_is_posted(tmp_path: Path) -> None:
    """A HIGH finding is advice: ``success`` naming it. PLANTED control: the same finding as security is ``failure``."""
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    command = FakeCommand(_output(severity='HIGH'))
    base = git_out(work, 'merge-base', 'origin/integrate/main', head)
    _tick(work, forge, command, Review(command=('reviewer', '--range', RANGE_FIELD)))
    ((argv, where),) = command.ran
    assert argv == ['reviewer', '--range', f'{base}..{head}']
    assert where == work
    (comment,) = forge.comments[number]
    assert marker(Marker.REVIEW, head) in comment['body']
    assert '**HIGH** `x.py`' in comment['body']
    assert 'F-0123456789ab' in comment['body']
    assert 'correctness@anthropic' in comment['body']
    assert 'rule `NEVER-DO-X`' in comment['body']
    assert '**What changed**: 1 file(s)' in comment['body'], 'the review opens with the context summary'
    assert _state(forge, head)[0] == 'success'
    assert '1 HIGH' in _state(forge, head)[1]
    secure, _ = _forge(head)
    _tick(work, secure, FakeCommand(_output(severity='LOW', security=True)), Review(command=_DECLARED.command))
    state, said = _state(secure, head)
    assert state == 'failure'
    assert 'F-0123456789ab' in said


def test_an_empty_command_is_a_loud_config_error_naming_the_one_fix() -> None:
    """Every PR is reviewed (user ruling 2026-10-31): `command = []` is refused, never an opt-out.

    PLANTED control: with `command` omitted, a repo gets the family's.
    """
    with pytest.raises(ValueError, match=re.escape(EMPTY_COMMAND_FIX)):
        review_from('[tool.dev_lab.review]\ncommand = []\n', 'pyproject.toml')
    assert review_from('[tool.dev_lab.review]\n', 'pyproject.toml').command == FAMILY_COMMAND


def test_an_empty_command_names_the_fix_at_the_merge_and_at_the_takeover(tmp_path: Path) -> None:
    """A green head in such a repo is not mergeable, and every door names the SAME fix -- never an unsatisfiable one."""
    work, head = _work(tmp_path)
    forge, _ = _forge(head)
    opted_out = _MANIFEST.split('[tool.dev_lab.review]', maxsplit=1)[0] + '[tool.dev_lab.review]\ncommand = []\n'
    advance(work, 'integrate/main', 'pyproject.toml', opted_out)  # the serve reads the base's (review_at)
    policy = dataclasses.replace(_LANE_POLICY, pr_merges_since='0' * 40)
    green = (_status('tests/base', 'success', 'scope=full'), _status('tests/security', 'success', 'nothing found'),
             _status(REVIEW_CONTEXT, 'success', 'reviewed'))  # fmt: skip
    found = decide(
        work, policy, branch='pr/x', number=1, head=head, statuses=green, reviewed=status_gate(github_posted)
    )
    assert not found.ready
    assert any(EMPTY_COMMAND_FIX in line for line in found.missing), found.missing
    said: list[str] = []
    step(work, forge, policy=_LANE_POLICY, say=said.append, host='box', run=FakeCommand(), ready=_can)
    assert any(EMPTY_COMMAND_FIX in line for line in said)


def test_a_usage_error_is_the_hosts_command_not_speaking_this_interface(tmp_path: Path) -> None:
    """A usage error is the host's older command, never the head's refusal.

    argparse also exits 2: a command that does not know a flag is an older tool on THIS host, so the head stays
    claimable (:class:`ReviewUnsupported`). PLANTED control: a named refusal is still the head's.
    """
    usage = 'usage: review [-h] --base BASE' + chr(10) + 'review: error: unrecognized arguments: --rules A,B'
    older = [sys.executable, '-c', f'import sys; sys.stderr.write({usage!r}); sys.exit({REFUSED_EXIT})']
    with pytest.raises(ReviewUnsupported, match='unrecognized arguments: --rules') as mismatch:
        run_command(older, tmp_path)
    assert not isinstance(mismatch.value, ReviewRefused)
    named = [
        sys.executable,
        '-c',
        f'import sys; sys.stderr.write("unknown method version 9"); sys.exit({REFUSED_EXIT})',
    ]
    with pytest.raises(ReviewRefused):
        run_command(named, tmp_path)


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

    review_tick(work, forge, _DECLARED, base='integrate/main', run=refusing, ready=_can, host='box')
    state, said = _state(forge, head)
    assert state == 'error'
    assert said.startswith(RETRYING)
    assert 'refused: unknown method version 9' in said
    assert forge.comments[number] == []


@pytest.mark.parametrize(
    'kinds', [('exhausted',), ('auth',), ('unsupported',), ('exhausted', 'auth', 'unsupported')],
    ids=['exhausted', 'auth', 'unsupported', 'all'],
)  # fmt: skip
def test_a_review_no_reviewer_could_run_is_retried_once_then_merges_unreviewed(tmp_path: Path, kinds) -> None:
    """A reviewer that cannot review NEVER blocks (user ruling 2026-11-06): one retry, then ``Unreviewed``.

    PLANTED CONTROL: one ok reviewer among them posts the review, and no Unreviewed record.
    """
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    reviewers = tuple((f'r{at}', kind) for at, kind in enumerate(kinds))
    _tick(work, forge, FakeCommand(_output(reviewers=reviewers)))
    state, said = _state(forge, head)
    assert (state, said.startswith(RETRYING)) == ('error', True)
    assert waiver_of(trusted_bodies(forge, number)) is None, 'one failure is retried, not waived'
    _tick(work, forge, FakeCommand(_output(reviewers=reviewers)))
    state, said = _state(forge, head)
    assert (state, said.startswith(UNREVIEWED_STATUS)) == ('pending', True)
    waived = waiver_of(trusted_bodies(forge, number))
    assert waived is not None
    assert waived.startswith(f'{UNREVIEWED}: no reviewer returned findings')
    later = FakeCommand()
    _tick(work, forge, later)
    assert later.ran == [], 'not retried again: the head merges unreviewed'
    ok, control = _forge(head)
    _tick(work, ok, FakeCommand(_output(reviewers=(*reviewers, ('c', 'ok')))))
    assert _state(ok, head)[0] == 'success'
    assert waiver_of(trusted_bodies(ok, control)) is None


def _can(_argv: Sequence[str], _root: Path) -> str | None:
    return None  # every fake command can start


def test_a_host_without_the_commands_interpreter_or_module_says_why_and_posts_nothing(tmp_path: Path) -> None:
    """Checked BEFORE the claim: the line names why, nothing is posted on the head, and the command never ran."""
    interpreter = sys.executable
    assert 'not installed' in (can_start([str(tmp_path / 'no-such-python'), '-m', 'ai_lab.review'], tmp_path) or '')
    assert 'cannot import' in (can_start([interpreter, '-m', 'no_such_module_for_review'], tmp_path) or '')
    assert can_start([interpreter, '-m', 'json.tool'], tmp_path) is None
    with pytest.raises(ReviewUnsupported, match='cannot import'):
        run_command([interpreter, '-m', 'no_such_module_for_review'], tmp_path)
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    command = FakeCommand()
    lines = review_tick(work, forge, _DECLARED, base='integrate/main', run=command, ready=can_start, host='box')
    assert 'not installed' in lines[0]
    assert command.ran == []
    assert "'reviewer' is not installed" in lines[0]
    assert status_list(forge, head) == ()
    assert forge.comments[number] == []


def test_the_declared_command_is_the_ai_lab_review_module_on_the_hosts_python() -> None:
    """The forge runs ``python -m ai_lab.review`` on the host's declared ai-lab interpreter (no console script).

    The method is ai-lab's own, so ``ai_lab`` is the only host value and no ``--method`` is passed.
    """
    declared = review_from((Path(__file__).parents[1] / 'pyproject.toml').read_text(encoding='utf-8'), 'pyproject')
    assert declared.command[:3] == ('{runtimes.ai_lab.python}', '-m', 'ai_lab.review')
    assert {m['name'] for arg in declared.command for m in HOST_FIELD.finditer(arg)} == {'ai_lab'}
    assert '--method' not in declared.command


def test_a_host_value_field_is_replaced_by_the_hosts_declared_runtime() -> None:
    """The repo declares WHAT, the host WHERE: ``{runtimes.<name>.<key>}`` reads this host's machine file."""
    declared = Review(command=('{runtimes.ai_lab.python}', '--data', '{runtimes.corpus.path}', RANGE_FIELD))
    host = {'ai_lab': {'python': 'C:/rt/python.exe'}, 'corpus': {'path': '~/corpus'}}
    argv = command_for(declared, 'a..b', host)
    assert argv == ['C:/rt/python.exe', '--data', str(Path('~/corpus').expanduser()), 'a..b']


@pytest.mark.parametrize('host', [{}, {'ai_lab': {}}], ids=['no capability', 'no key'])
def test_a_host_value_this_host_does_not_declare_is_skipped_unposted(tmp_path: Path, host) -> None:
    """Checked BEFORE the claim: the line names the capability, nothing is posted. PLANTED: a declaring host runs it."""
    declared = Review(command=('{runtimes.ai_lab.python}', '--range', RANGE_FIELD))
    with pytest.raises(ReviewUnsupported, match=r'\[runtimes\.ai_lab\] python'):
        command_for(declared, 'a..b', host)
    work, head = _work(tmp_path)
    forge, _ = _forge(head)
    command = FakeCommand()
    kw = {'base': 'integrate/main', 'run': command, 'ready': _can, 'host': 'box'}
    lines = review_tick(work, forge, declared, runtimes=host, **kw)
    assert '[runtimes.ai_lab] python' in lines[0]
    assert command.ran == []
    assert status_list(forge, head) == ()
    forge, _ = _forge(head)
    review_tick(work, forge, declared, runtimes={'ai_lab': {'python': 'py'}}, **kw)
    ((argv, _),) = command.ran
    assert argv[0] == 'py'


def test_a_command_that_turns_out_unsupported_replaces_its_claim_with_error(tmp_path: Path) -> None:
    """It started and then could not: the claim becomes ``error`` naming why, never a silent release."""
    work, head = _work(tmp_path)
    forge, _ = _forge(head)

    def absent(_argv: Sequence[str], _root: Path) -> str:
        msg = 'unsupported: the review command cannot import its module on this host'
        raise ReviewUnsupported(msg)

    review_tick(work, forge, _DECLARED, base='integrate/main', run=absent, ready=_can, host='A')
    (failed,) = status_list(forge, head)
    assert failed.state == 'error'
    assert 'cannot import its module' in failed.description


def test_a_host_that_cannot_run_the_review_leaves_the_head_to_a_capable_host(tmp_path: Path) -> None:
    """A fact about the HOST, not the head: nothing is posted, and a capable host still reviews.

    PLANTED control: a command refused on the head is retried once, then merges unreviewed, never re-run.
    """
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    declared = Review(command=('{runtimes.ai_lab.python}', '--range', RANGE_FIELD))
    command = FakeCommand()
    kw = {'base': 'integrate/main', 'run': command}
    review_tick(work, forge, declared, ready=_can, host='A', **kw)
    assert forge.statuses.get(head, []) == []
    review_tick(work, forge, declared, ready=_can, host='B', runtimes={'ai_lab': {'python': 'py'}}, **kw)
    assert len(command.ran) == 1
    assert status_list(forge, head)[0].state == 'success'
    assert len(forge.comments[number]) == 1

    def absent(_argv: Sequence[str], _root: Path) -> str:
        msg = 'unsupported: the review command cannot import its module on this host'
        raise ReviewUnsupported(msg)

    forge, _ = _forge(head)
    review_tick(work, forge, _DECLARED, base='integrate/main', run=absent, ready=_can, host='A')
    assert status_list(forge, head)[0].description.startswith(f'{HOST_UNABLE} A: ')
    retried = FakeCommand()
    review_tick(work, forge, _DECLARED, base='integrate/main', run=retried, ready=_can, host='A')
    assert retried.ran  # the same host, fixed, reviews on a later tick

    def refusing(_argv: Sequence[str], _root: Path) -> str:
        msg = 'bad range'
        raise ReviewRefused(msg)

    forge, number = _forge(head)
    review_tick(work, forge, _DECLARED, base='integrate/main', run=refusing, ready=_can, host='A')
    review_tick(work, forge, _DECLARED, base='integrate/main', run=refusing, ready=_can, host='B')
    later = FakeCommand()
    review_tick(work, forge, _DECLARED, base='integrate/main', run=later, ready=_can, host='C')
    assert later.ran == [], 'a refusal tried twice merges unreviewed; nobody re-runs it'
    assert _state(forge, head)[1].startswith(UNREVIEWED_STATUS)
    waived = f'{UNREVIEWED}: the review command failed (ReviewRefused: bad range)'
    assert waiver_of(trusted_bodies(forge, number)) == waived


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


@pytest.mark.parametrize('version', [2, 0, '3'])
def test_an_unknown_schema_version_is_refused_by_name_and_nothing_is_commented(tmp_path: Path, version: object) -> None:
    """PLANTED control: the same document at version 3 is posted (the first test); v2 is retired, refused."""
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    _tick(work, forge, FakeCommand(_output(schema_version=version)))
    state, said = _state(forge, head)
    assert state == 'error'
    assert f'schema_version {version!r}' in said
    assert forge.comments[number] == []
    with pytest.raises(UnknownSchemaVersion, match='schema_version 2'):
        parse_findings(_output(schema_version=2))


@pytest.mark.parametrize(
    'out', ['not json', '{"schema_version": 3}', _output(reviewers=(('c', 'bored'),)), _output()[:-1]]
)
def test_output_that_is_not_the_findings_json_posts_an_error_naming_the_failure(tmp_path: Path, out: str) -> None:
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    lines = _tick(work, forge, FakeCommand(out))
    state, said = _state(forge, head)
    assert state == 'error'
    assert 'FindingsInvalid' in said
    assert forge.comments[number] == []
    assert len(lines) == 1


def test_a_clean_run_says_no_findings(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    _tick(work, forge, FakeCommand(_output(reviewers=(('c', 'skipped'),))))
    assert 'No findings.' in forge.comments[number][0]['body']
    assert [s.state for s in status_list(forge, head) if s.context == REVIEW_CONTEXT] == ['success']


def test_the_command_runner_returns_stdout_and_names_a_non_zero_exit(tmp_path: Path) -> None:
    """PLANTED control: the same runner on a command exiting 0 returns what it printed."""
    interpreter = sys.executable
    assert run_command([interpreter, '-c', 'print(1)'], tmp_path).strip() == '1'
    with pytest.raises(OSError, match='exited 3: boom'):
        run_command([interpreter, '-c', 'import sys; sys.stderr.write("boom"); sys.exit(3)'], tmp_path)


def test_one_review_per_pr_a_fix_push_posts_the_standing_verdict_and_runs_nothing(tmp_path: Path) -> None:
    """User ruling 2026-11-06: the review is one-shot. A second tick, and a later head, run no command.

    PLANTED CONTROL: the first head of the PR is reviewed.
    """
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    command = FakeCommand()
    _tick(work, forge, command)
    assert len(command.ran) == 1
    posted = (len(forge.comments[number]), len(forge.statuses[head]))
    _tick(work, forge, command)
    assert (len(forge.comments[number]), len(forge.statuses[head])) == posted
    fix = advance(work, 'pr/x', 'x.py', 'x fixed\n')
    forge.pulls[number]['head']['sha'] = fix
    lines = _tick(work, forge, command)
    assert len(command.ran) == 1, 'a fix push is not reviewed again'
    state, said = _state(forge, fix)
    assert state == 'success'
    assert said.startswith(f'review of {head[:12]} stands')
    assert lines == (f'#{number} {fix[:12]}: {said}',)
    assert len(forge.comments[number]) == 1


def test_a_standing_security_finding_holds_every_later_head_until_the_review_is_asked_again(tmp_path: Path) -> None:
    """A security failure carries to a fix push; ``ask_again`` re-reviews that head once.

    PLANTED CONTROL: without the request, the fix push stays ``failure`` and nothing runs.
    """
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    _tick(work, forge, FakeCommand(_output(security=True)))
    fix = advance(work, 'pr/x', 'x.py', 'x fixed\n')
    forge.pulls[number]['head']['sha'] = fix
    command = FakeCommand(_output(reviewers=(('c', 'skipped'),)))
    _tick(work, forge, command)
    assert command.ran == []
    assert _state(forge, fix)[0] == 'failure'
    ask_again(forge, number, fix, 'dev@box')
    _tick(work, forge, command)
    assert len(command.ran) == 1
    assert _state(forge, fix)[0] == 'success'
    _tick(work, forge, command)
    assert len(command.ran) == 1, 'a request is honoured once'


def test_a_pr_grown_to_the_declared_multiple_is_reviewed_once_more(tmp_path: Path) -> None:
    """REVIEW_AGAIN_GROWTH: a PR whose own code doubled is mostly unread work.

    PLANTED CONTROL: a push that grows it less is not reviewed again.
    """
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    command = FakeCommand()
    _tick(work, forge, command)
    small = advance(work, 'pr/x', 'x.py', 'x\ny\n')
    forge.pulls[number]['head']['sha'] = small
    _tick(work, forge, command)
    assert len(command.ran) == 1
    assert REVIEW_AGAIN_GROWTH == 2
    big = advance(work, 'pr/x', 'big.py', ''.join(f'line_{n} = {n}\n' for n in range(400)))
    forge.pulls[number]['head']['sha'] = big
    _tick(work, forge, command)
    assert len(command.ran) == 2
    assert marker(Marker.REVIEW, big) in forge.comments[number][-1]['body']


@pytest.mark.parametrize('key', sorted(RETIRED_KEYS))
def test_a_key_of_the_retired_in_process_reviewer_is_refused_by_name(key: str) -> None:
    """PLANTED control: the same table without the retired key loads (the declaration test)."""
    with pytest.raises(ValueError, match=f'{key} is retired: '):
        review_from(f"[tool.dev_lab.review]\n{key} = 'x'\nmax_diff_bytes = 5\n", 'p')
    assert review_from('[tool.dev_lab.review]\nmax_diff_bytes = 5\n', 'p').max_diff_bytes == 5


def test_the_forge_holds_no_model_client_prompt_or_key() -> None:
    """The forge only orchestrates: the review table holds the command, a model NAME and bounds, never a client or key.

    That the retired reviewer's names are gone is the retired-spelling scan's (``lab_commons.hpc.retired``).
    """
    assert {field.name for field in dataclasses.fields(Review)} == {
        'command', 'model', 'synthesis', 'max_diff_bytes', 'max_total_bytes', 'derived', 'strict', 'light',
        'code', 'not_code', 'reviewers', 'backlog',
        'claim_stale', 'quiet', 'where', 'bundle', 'judge_login', 'judge_app', 'preparers',
        'batch', 'on_expiry', 'batch_wait',
    }  # fmt: skip


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


def test_a_diff_past_the_total_is_sliced_and_the_code_left_out_is_listed_never_held(tmp_path: Path) -> None:
    """D123, 2026-11-06: every slice names its paths (no path-less ``agent`` call the headless mode refuses).

    PLANTED CONTROL: within the total, every path is read and nothing is listed.
    """
    work, _ = _work(tmp_path)
    head = advance(work, 'pr/x', 'y.py', 'y\n')
    forge, number = _forge(head)
    command = FakeCommand()
    sliced = ('reviewer', '--range', RANGE_FIELD, PATHS_FIELD)
    _tick(work, forge, command, Review(command=sliced, max_diff_bytes=10, max_total_bytes=1))
    ((argv, _),) = command.ran
    assert argv[3:] in (['x.py'], ['y.py']), 'one slice, with its paths'
    left = 'y.py' if argv[3:] == ['x.py'] else 'x.py'
    assert f'not read (1): `{left}`' in forge.comments[number][0]['body']
    assert _state(forge, head)[0] == 'success'
    whole, again = _forge(head)
    every = FakeCommand()
    _tick(work, whole, every, Review(command=sliced))
    assert [argv[3:] for argv, _ in every.ran] == [['x.py', 'y.py']]
    assert 'not read' not in whole.comments[again][0]['body']


def test_a_pr_into_another_base_is_not_reviewed(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge = StateForge()
    forge.add_pull('pr/x', 'main', sha=head)
    command = FakeCommand()
    _tick(work, forge, command)
    assert command.ran == []


def test_a_failed_command_is_retried_once_on_the_serve_tick_then_merges_unreviewed(tmp_path: Path) -> None:
    """PLANTED CONTROL: a successful review posts no Unreviewed record (the first test's forge)."""
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    runs: list[int] = []

    def broken(_argv: Sequence[str], _root: Path) -> str:
        runs.append(1)
        msg = 'the review command exited 1: no provider'
        raise OSError(msg)

    for _ in range(3):
        review_tick(work, forge, _DECLARED, base='integrate/main', run=broken, ready=_can, host='box')
    assert len(runs) == 2, 'tried, retried once, then left'
    state, said = _state(forge, head)
    assert (state, said.startswith(UNREVIEWED_STATUS)) == ('pending', True)
    assert 'OSError' in said
    (comment,) = forge.comments[number]
    assert (
        unreviewed_line('the review command failed (OSError: the review command exited 1: no provider)')
        in (comment['body'])
    )
    clean, control = _forge(head)
    _tick(work, clean, FakeCommand())
    assert waiver_of(trusted_bodies(clean, control)) is None


def test_no_review_key_and_a_reached_budget_merge_unreviewed_and_run_nothing(tmp_path: Path) -> None:
    """A fork PR's job holds no key; a PR past its dollar cap gets no review: neither holds the merge."""
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    command = FakeCommand()
    keyless = Runner(host='job', run=command, ready=_can, secret=False)
    review_pull(work, forge, _DECLARED, forge.pr_view(number), keyless)
    assert command.ran == []
    assert _state(forge, head)[1] == f'{UNREVIEWED_STATUS} {NEEDS_MAINTAINER}'
    assert waiver_of(trusted_bodies(forge, number)) == f'{UNREVIEWED}: {NEEDS_MAINTAINER}'
    spent = Spend(budget_usd=10.0, spent_usd=10.0)
    capped, again = _forge(head)
    broke = Runner(host='box', run=command, ready=_can, spend=lambda *_: spent)
    review_pull(work, capped, _DECLARED, capped.pr_view(again), broke)
    assert command.ran == []
    assert 'monthly review budget spent' in _state(capped, head)[1]
    assert (waiver_of(trusted_bodies(capped, again)) or '').startswith(f'{UNREVIEWED}: review monthly')


def test_no_review_status_or_comment_asks_to_divide_the_pr(tmp_path: Path) -> None:
    """One session, one task, one PR (user ruling 2026-11-06): no text the review posts suggests otherwise.

    The forbidden word is spelled in parts so the retired-spellings scan does not read it here. PLANTED CONTROL:
    the scan does see the word in a text that carries it.
    """
    forbidden = 'sp' + 'lit'
    texts: list[str] = []
    cases = ((_output(severity='HIGH'), 1), (_output(security=True), 1), (_output(reviewers=(('c', 'auth'),)), 2))
    for out, runs in cases:
        work, head = _work(tmp_path / str(len(texts)))
        forge, number = _forge(head)
        for _ in range(runs):
            _tick(work, forge, FakeCommand(out))
        texts += [one['description'] for one in forge.statuses[head]]
        texts += [one['body'] for one in forge.comments[number]]
    spent = Spend(budget_usd=10.0, spent_usd=10.0)
    work, head = _work(tmp_path / 'cap')
    forge, number = _forge(head)
    review_pull(work, forge, _DECLARED, forge.pr_view(number), Runner(host='b', ready=_can, spend=lambda *_: spent))
    texts += [one['description'] for one in forge.statuses[head]] + [one['body'] for one in forge.comments[number]]
    assert texts
    offending = [text for text in texts if forbidden in text.lower().replace(ONE_SHOT.lower(), '')]
    assert offending == []
    assert [t for t in (f'please {forbidden} the PR',) if forbidden in t.lower()], 'PLANTED: the scan sees it'


# --- blocking: the merge waits on a failed or unposted review, never a part ----------------------------


def _status(context: str, state: str, description: str) -> CommitStatus:
    return CommitStatus(context, state, description, '', 1, ACTIONS_BOT)  # the forge posted it (D11)


def test_the_review_status_is_never_a_part_but_its_failure_waits_the_merge(tmp_path: Path) -> None:
    """``failure`` (a security finding), an unposted review and a live claim wait; the rest merge.

    PLANTED controls: a FAIL in a real part context does fail the standing; every review state but ``success``
    waits the merge, even in a repo that declares no review command (user ruling 2026-10-31).
    """
    passed = _status('tests/base', 'success', 'scope=full ran=3 hands=-')
    secured = _status('tests/security', 'success', 'nothing found')  # the security merge condition, met
    for review in ('failure', 'error', 'pending'):
        statuses = (passed, _status(REVIEW_CONTEXT, review, 'reviewed: advice 3 MEDIUM'))
        assert standing(statuses, head='h').result is Conclusion.PASS
    failed = (passed, _status('tests/jmag', 'failure', 'scope=full ran=3 hands=-'))
    assert standing(failed, head='h').result is Conclusion.FAIL
    work, head = _work(tmp_path)
    policy = dataclasses.replace(_LANE_POLICY, pr_merges_since='0' * 40)

    def ready(*review: tuple[str, str]) -> bool:
        statuses = (passed, secured, *(_status(REVIEW_CONTEXT, state, said) for state, said in review))
        return decide(
            work, policy, branch='pr/x', number=1, head=head, statuses=statuses, reviewed=status_gate(github_posted)
        ).ready

    assert not ready(('failure', 'security finding(s) F-1: fix them'))
    assert not ready()
    assert not ready(('pending', f'{CLAIMED} A at 2026-10-26T09:00:00+00:00, reviewing'))
    assert ready(('success', 'reviewed: advice 1 HIGH, 0 MEDIUM, 0 LOW; none blocks'))
    assert not ready(('error', 'the review command failed (OSError)')), 'a status never waives the review'


def test_a_review_hold_waits_the_merge_until_it_is_released(tmp_path: Path) -> None:
    """The hold is its OWN context, never a description prefix.

    PLANTED controls: released, it merges; the review context saying the hold's words holds nothing.
    """
    passed = _status('tests/base', 'success', 'scope=full ran=3 hands=-')
    work, head = _work(tmp_path)
    policy = dataclasses.replace(_LANE_POLICY, pr_merges_since='0' * 40)
    over = NEEDS_MAINTAINER
    held = (_status(HOLD_CONTEXT, 'pending', over), _status(REVIEW_CONTEXT, 'success', 'reviewed'), passed)
    found = decide(work, policy, branch='pr/x', number=1, head=head, statuses=held, reviewed=status_gate(github_posted))
    assert not found.ready
    assert any(HOLD_CONTEXT in line for line in found.missing), found.missing
    assert standing(held, head='h').result is Conclusion.PASS, 'the hold is a merge wait, never a part'
    secured = _status('tests/security', 'success', 'nothing found')  # the security merge condition, met
    released = (
        _status(HOLD_CONTEXT, 'success', 'released by box after the integrator review'),
        _status(REVIEW_CONTEXT, 'success', 'review: reviewed: advice 0 HIGH; none blocks'),
        passed,
        secured,
    )
    assert decide(
        work, policy, branch='pr/x', number=1, head=head, statuses=released, reviewed=status_gate(github_posted)
    ).ready
    worded = (_status(REVIEW_CONTEXT, 'success', NEEDS_MAINTAINER), passed, secured)
    assert decide(
        work, policy, branch='pr/x', number=1, head=head, statuses=worded, reviewed=status_gate(github_posted)
    ).ready


# --- the declaration ---------------------------------------------------------------------------------


def test_the_declaration_defaults_and_overrides_and_refuses_an_unknown_key() -> None:
    assert review_from('', 'p') == Review()
    declared = "[tool.dev_lab.review]\ncommand = ['r', '{range}']\nmax_diff_bytes = 5\n"
    assert review_from(declared, 'p') == Review(command=('r', '{range}'), max_diff_bytes=5)
    with pytest.raises(ValueError, match='unknown key'):
        review_from("[tool.dev_lab.review]\ncomand = ['x']\n", 'p')


# --- the serve step ----------------------------------------------------------------------------------


def test_a_host_that_cannot_run_the_command_skips_the_step_without_reading_the_forge(tmp_path: Path) -> None:
    """WHERE IT RUNS follows what it needs: an incapable host says why once and lists no PR.

    PLANTED CONTROL: the same step on a host that can start the command reviews the head.
    """
    work, head = _work(tmp_path)

    class Unread(StateForge):
        def call(self, *_a: object, **_k: object) -> object:
            msg = 'an incapable host read the forge'
            raise AssertionError(msg)

    said: list[str] = []
    command = FakeCommand()

    def cannot(_argv: Sequence[str], _root: Path) -> str:
        return 'unsupported: no ai_lab here'

    step(work, Unread(), policy=_LANE_POLICY, say=said.append, host='ada/x', run=command, ready=cannot)
    assert said == ['[serve] review: not run on this host -- unsupported: no ai_lab here']
    assert command.ran == []
    forge, _ = _forge(head)
    step(work, forge, policy=_LANE_POLICY, say=said.append, host='G', run=command, ready=_can)
    assert len(command.ran) == 1


def test_the_step_reviews_into_the_policys_integration_and_says_a_failure(tmp_path: Path) -> None:
    """PLANTED control: the same step against a forge that cannot list PRs says so and raises nothing."""
    work, head = _work(tmp_path)
    forge, _ = _forge(head)
    command = FakeCommand()
    said: list[str] = []
    step(work, forge, policy=_LANE_POLICY, say=said.append, host='box', run=command, ready=_can)
    assert len(command.ran) == 1
    assert any('review, success' in line for line in said)

    class Down(StateForge):
        def call(self, *_a: object, **_k: object) -> object:
            msg = 'down'
            raise OSError(msg)

    said.clear()
    step(work, Down(), policy=_LANE_POLICY, say=said.append, host='box', run=command, ready=_can)
    assert any('did not run' in line for line in said)


def test_the_steps_claim_names_the_serve_host_not_the_box(tmp_path: Path) -> None:
    """The claim names the host serve declares (its card name). PLANTED control: never this box's hostname."""
    work, head = _work(tmp_path)
    forge, _ = _forge(head)
    said: list[str] = []
    step(work, forge, policy=_LANE_POLICY, say=said.append, host='cluster/acct', run=FakeCommand(), ready=_can)
    posted = [one['description'] for one in forge.statuses[head]]
    assert posted[0].startswith(f'{CLAIMED} cluster/acct at ')
    assert socket.gethostname() not in posted[0]


def test_a_runtime_still_spelled_as_a_capability_names_the_deploy_remedy() -> None:
    """The forge host's serve tick said only "declares no [runtimes.ai_lab]"; the retired spelling names its remedy."""
    command = ('{runtimes.ai_lab.python}', RANGE_FIELD)
    why = retired_table(command, {}, {'ai_lab': {'python': 'x'}, 'jmag': {}})
    assert why == (
        'the machine file still spells [capabilities.ai_lab]; run workstation deploy to move it to [runtimes]'
    )
    assert retired_table(command, {'ai_lab': {'python': 'x'}}, {'ai_lab': {}}) is None, 'PLANTED: a declared runtime'
    assert retired_table(command, {}, {'jmag': {}}) is None


# --- a sync with integration never re-reviews -----------------------------------------------------------


def _reviewed_then_synced(tmp_path: Path, host: str = 'forge.example.org') -> tuple[Path, StateForge, int, str, str]:
    """A PR on *host* whose head was reviewed (success), then integration was merged in clean; ``R`` and the sync."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    work, head = _work(tmp_path)
    forge = StateForge(Forge(host, 'o', 'r'))
    number = forge.add_pull('pr/x', 'integrate/main', title='add x', sha=head)
    _tick(work, forge, FakeCommand())
    advance(work, 'integrate/main', 'theirs.py', ''.join(f'theirs_{n} = {n}\n' for n in range(400)))
    run_git(work, 'checkout', '-q', '-B', 'sync', 'origin/pr/x')
    run_git(work, '-c', 'user.name=t', '-c', 'user.email=t@t', 'merge', '-q', '--no-edit', 'origin/integrate/main')
    synced = git_out(work, 'rev-parse', 'HEAD')
    run_git(work, 'push', '-q', '--no-verify', 'origin', 'HEAD:refs/heads/pr/x')
    run_git(work, 'fetch', '-q', 'origin')
    forge.pulls[number]['head']['sha'] = synced
    return work, forge, number, head, synced


@pytest.mark.parametrize('host', ['forge.example.org', 'github.com'])
def test_a_sync_with_integration_never_re_reviews_however_large_upstream_is(tmp_path: Path, host: str) -> None:
    """Growth is the PR's OWN code, measured from the merge base: integration's work never counts.

    PLANTED CONTROL: the PR's own growth does (the growth test).
    """
    work, forge, number, head, synced = _reviewed_then_synced(tmp_path, host)
    command = FakeCommand()
    _tick(work, forge, command)
    assert command.ran == []
    assert _state(forge, synced)[1].startswith(f'review of {head[:12]} stands')
    assert len(forge.comments[number]) == 1


def test_a_head_inside_the_quiet_period_waits_and_spends_nothing(tmp_path: Path) -> None:
    """D52 DEBOUNCE: the serve reviews a head only once it is ``quiet`` old; nothing is posted before.

    PLANTED CONTROL: the same head, a tick past the quiet period, is reviewed.
    """
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    committed = datetime.fromisoformat(git_out(work, 'show', '-s', '--format=%cI', head))
    command = FakeCommand()
    quiet = Review().quiet_for
    assert quiet == timedelta(minutes=10)
    lines = review_tick(work, forge, _DECLARED, base='integrate/main', run=command, ready=_can, host='box',
                        clock=lambda: committed + timedelta(minutes=3), quiet=quiet)  # fmt: skip
    assert command.ran == []
    assert forge.statuses.get(head, []) == []
    assert forge.comments[number] == []
    assert lines[0].startswith(f'#{number} {head[:12]}: not reviewed yet')
    review_tick(work, forge, _DECLARED, base='integrate/main', run=command, ready=_can, host='box',
                clock=lambda: committed + timedelta(minutes=11), quiet=quiet)  # fmt: skip
    assert len(command.ran) == 1
    with pytest.raises(ValueError, match='quiet'):
        Review(quiet='10')


def test_a_command_whose_interpreter_ignores_safe_path_cannot_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """dev-lab #40: an interpreter blind to ``PYTHONSAFEPATH`` (older than 3.11) cannot start the command.

    It would put the PR checkout first on ``sys.path`` beside the key.

    PLANTED control: the same interpreter, the env withheld, reports no safe path and is refused.
    """
    assert can_start([sys.executable, '-m', 'json.tool'], tmp_path) is None
    monkeypatch.setattr(forgereview_command, 'SAFE_PATH', {})
    assert 'safe_path' in (can_start([sys.executable, '-m', 'json.tool'], tmp_path) or '')
