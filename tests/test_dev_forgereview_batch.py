"""BATCHED REVIEW CALLS (user ruling 2026-11-04): a pending batch is no verdict, and the next run resumes it.

A round whose batch is still running keeps the batch state on the PR. The real round (:func:`review_tick`)
over real git and the stateful fake forge; the review command is a fake that behaves as ai-lab's batched command
does: it reads and writes ``--batch-state`` and exits pending while its batch runs. Every refusal has its planted
control.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from _branch_repos import advance
from _forge_fake import run_git
from _forge_state import StateForge
from test_dev_forgereview import _MANIFEST, JUDGE, FakeCommand, _can, _forge, _output, _work

from dev_lab.dev.ciworkflows import workflows
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgepulls import Marker, marker
from dev_lab.dev.forgereview import REVIEW_CONTEXT, TAKEOVER_PENDING, review_tick
from dev_lab.dev.forgereview_batch import (
    BATCH_FIELD,
    BATCH_PENDING,
    FAMILY_BATCH,
    NO_BATCH,
    WAIT_LEFT,
    batch_args,
    held_state,
    wait_of,
    within,
)
from dev_lab.dev.forgereview_claim import claimable
from dev_lab.dev.forgereview_command import PENDING_EXIT, ReviewPending, run_command
from dev_lab.dev.forgereview_declared import (
    FAMILY_BUNDLE,
    FAMILY_COMMAND,
    FAMILY_JUDGE,
    RANGE_FIELD,
    Review,
    command_for,
    review_from,
)
from dev_lab.dev.forgereview_scope import gather
from dev_lab.dev.forgestatus import CommitStatus, status_list, status_post
from dev_lab.dev.forgetakeover import main as review_main
from dev_lab.dev.forgework import ACTIONS_BOT

_BATCHED = Review(command=('reviewer', '--range', RANGE_FIELD, BATCH_FIELD), judge=JUDGE)


class BatchedCommand(FakeCommand):
    """A review command that batches: pending (exit 75) until its batch has been polled *polls* times.

    Its state file is the evidence: it submits ``msgbatch_1`` once, and a run handed a state naming it resumes
    polling it -- a run handed no state would submit again, and ``submitted`` counts that.
    """

    def __init__(self, polls: int = 2) -> None:
        """Nothing submitted yet; the batch ends on the *polls*-th poll."""
        super().__init__()
        self.polls, self.submitted, self.waits = polls, 0, []

    def __call__(self, argv: Sequence[str], root: Path) -> str:
        if argv and argv[0] == 'judge':
            return self._judge(argv, root)
        if '--no-batch' in argv:
            return super().__call__(argv, root)
        self.waits.append(argv[argv.index('--wait') + 1])
        state = Path(argv[argv.index('--batch-state') + 1])
        held = json.loads(state.read_text(encoding='utf-8')) if state.is_file() else None
        if held is None:
            self.submitted += 1
            held = {'version': 1, 'seed': 's', 'batches': [{'id': 'msgbatch_1', 'polls': 0}]}
        held['batches'][0]['polls'] += 1
        state.write_text(json.dumps(held), encoding='utf-8')
        if held['batches'][0]['polls'] < self.polls:
            msg = 'model batch msgbatch_1 submitted 2026-11-04T09:00:00+00:00, results pending'
            raise ReviewPending(msg)
        return super().__call__(argv, root)


def _review_status(forge, head: str) -> CommitStatus:
    return next(s for s in status_list(forge, head) if s.context == REVIEW_CONTEXT)


def test_a_pending_batch_posts_no_verdict_and_the_next_tick_resumes_it_without_resubmitting(tmp_path: Path) -> None:
    """Round 1 pends: ``pending`` BATCH_PENDING, the state on the PR, no round. Tick 2 resumes and posts the round.

    PLANTED control: the resumed run was handed the state the first wrote (``submitted`` stays 1).
    """
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    command = BatchedCommand(polls=2)
    review_tick(work, forge, _BATCHED, base='integrate/main', run=command, ready=_can, host='box')
    status = _review_status(forge, head)
    assert status.state == 'pending'
    assert status.description.startswith(BATCH_PENDING)
    assert 'msgbatch_1' in status.description
    (stored,) = forge.comments[number]
    assert marker(Marker.REVIEW_BATCH, head) in stored['body']
    assert '"msgbatch_1"' in stored['body']
    assert not any(marker(Marker.REVIEW, head) in c['body'] for c in forge.comments[number]), 'no round, no verdict'
    review_tick(work, forge, _BATCHED, base='integrate/main', run=command, ready=_can, host='box')
    assert command.submitted == 1, 'resumed from the state on the PR, never resubmitted'
    assert _review_status(forge, head).state == 'success'
    assert any(marker(Marker.REVIEW, head) in c['body'] for c in forge.comments[number])


def test_every_command_of_a_round_shares_one_wait(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge, _ = _forge(head)
    command = BatchedCommand(polls=1)
    review = Review(command=_BATCHED.command, judge=JUDGE, batch_wait='5 min')
    review_tick(work, forge, review, base='integrate/main', run=command, ready=_can, host='box')
    assert command.waits
    assert all(0 <= int(left) <= 300 for left in command.waits)


def test_a_state_comment_by_an_untrusted_author_is_never_handed_to_a_command(tmp_path: Path) -> None:
    """An author pasting a state naming some batch is not read: the command starts fresh.

    PLANTED control: the forge's own state comment is read.
    """
    _work_tree, head = _work(tmp_path)
    forge, number = _forge(head)
    planted = {'version': 1, 'seed': 'x', 'batches': [{'id': 'msgbatch_planted', 'polls': 99}]}
    body = f'{marker(Marker.REVIEW_BATCH, head)}\n```json\n{json.dumps(planted)}\n```'
    forge.comments[number].append({'id': 900, 'body': body, 'html_url': 'c/900', 'user': {'login': 'mallory'}})
    with held_state(forge, number, head, {forge.whoami()}) as state:
        assert not state.exists()
    forge.comments[number][-1]['user']['login'] = forge.whoami()
    with held_state(forge, number, head, {forge.whoami()}) as state:
        assert json.loads(state.read_text(encoding='utf-8')) == planted


def test_the_batch_flags_follow_the_declaration(tmp_path: Path) -> None:
    state = tmp_path / 's.json'
    assert FAMILY_BATCH is True
    assert batch_args(Review(), state) == (
        '--batch', '--batch-state', str(state), '--wait', WAIT_LEFT, '--on-expiry', 'sync',
    )  # fmt: skip
    assert batch_args(Review(batch=False), state) == NO_BATCH == ('--no-batch',)
    assert batch_args(Review(on_expiry='fail'), state)[-1] == 'fail'


def test_the_family_commands_batch_and_a_caller_without_state_calls_at_once() -> None:
    """``{batch}`` is in every family command; filled without a state it is ``--no-batch`` (it could not resume)."""
    for command in (FAMILY_COMMAND, FAMILY_JUDGE, FAMILY_BUNDLE):
        assert BATCH_FIELD in command
    runtimes = {'ai_lab': {'python': sys.executable}}
    plain = command_for(Review(), 'a..b', runtimes, paths=['x.py'])
    assert plain[-1] == '--no-batch'
    batched = command_for(Review(), 'a..b', runtimes, paths=['x.py'], batching=('--batch', '--wait', '9'))
    assert batched[-3:] == ['--batch', '--wait', '9']


def test_the_declaration_is_validated() -> None:
    assert review_from('[tool.dev_lab.review]\nbatch = false\n', 'p').batch is False
    assert wait_of(review_from('[tool.dev_lab.review]\n', 'p')) == timedelta(minutes=20)
    with pytest.raises(ValueError, match='on_expiry'):
        review_from('[tool.dev_lab.review]\non_expiry = "later"\n', 'p')
    with pytest.raises(ValueError, match='batch_wait'):
        review_from('[tool.dev_lab.review]\nbatch_wait = "20"\n', 'p')


def test_within_fills_the_seconds_left_when_each_command_starts() -> None:
    now = [datetime(2026, 11, 4, 9, 0, tzinfo=UTC)]
    seen = []
    timed = within(lambda argv, *_: seen.append(list(argv)) or '', now[0] + timedelta(seconds=90), lambda: now[0])
    timed(['x', '--wait', WAIT_LEFT], Path())
    now[0] += timedelta(seconds=120)
    timed(['x', '--wait', WAIT_LEFT], Path())
    assert [argv[-1] for argv in seen] == ['90', '0']


def test_a_pending_head_is_claimable_at_once() -> None:
    now = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
    pending = CommitStatus(REVIEW_CONTEXT, 'pending', f'{BATCH_PENDING} model batch msgbatch_1 ...', '', None)
    other = CommitStatus(REVIEW_CONTEXT, 'pending', 'takeover pending: ...', '')
    assert claimable(pending, now, timedelta(hours=1))
    assert not claimable(other, now, timedelta(hours=1)), 'PLANTED control: another pending is not ours to take'


def test_exit_75_is_pending_never_a_failure(tmp_path: Path) -> None:
    said = 'pending: model batch msgbatch_1 submitted 2026-11-04T09:00:00+00:00, results pending'
    pend = [sys.executable, '-c', f'import sys; sys.stderr.write({said!r}); sys.exit({PENDING_EXIT})']
    with pytest.raises(ReviewPending, match=re.escape(said.removeprefix('pending: '))):
        run_command(pend, tmp_path)
    assert PENDING_EXIT == 75


def test_a_slice_pending_still_lets_the_slices_after_it_submit(tmp_path: Path) -> None:
    ran = []

    def run(argv: Sequence[str], _root: Path) -> str:
        ran.append(argv[0])
        if argv[0] == 'one':
            msg = 'model batch msgbatch_1 pending'
            raise ReviewPending(msg)
        return _output()

    with pytest.raises(ReviewPending, match='msgbatch_1'):
        gather('a..b', [['one'], ['two']], ['synth'], run, tmp_path, pr_body='', disposed={})
    assert ran == ['one', 'two'], 'slice two submitted; the synthesis waits for both'


# --- the GitHub job: a pending batch is not a failure, and a schedule resumes it with no human -------------------

_BATCHED_MANIFEST = _MANIFEST.replace(
    "command = ['reviewer', '--range', '{range}', '--model', 'm']",
    "command = ['reviewer', '--range', '{range}', '--model', 'm', '{batch}']",
)


def _batched_work(tmp_path: Path) -> tuple[Path, str]:
    work, head = _work(tmp_path)
    advance(work, 'integrate/main', 'pyproject.toml', _BATCHED_MANIFEST)  # the base's declaration batches
    run_git(work, 'checkout', '-q', head)
    return work, head


@pytest.mark.parametrize(('host', 'code'), [('github.com', 0), ('forge.example.org', 1)])
def test_a_pending_batch_is_not_a_failed_job_where_the_gate_reads_the_status_creator(
    tmp_path: Path, host: str, code: int
) -> None:
    """Pending is not failure, and where the gate reads the status creator the job is not red for it.

    On GitHub the gate trusts the status CREATOR, so the job exits 0 and the head's ``pending`` status alone holds
    the merge. On Gitea the gate trusts the review RUN's success, so a pending run
    must not conclude success (a planted status would then count): it exits 1 there.
    """
    work, head = _batched_work(tmp_path)
    forge = StateForge(Forge(host, 'o', 'r'))
    number = forge.add_pull('pr/x', 'integrate/main', title='add x', sha=head)
    forge.login = ACTIONS_BOT
    command = BatchedCommand(polls=99)
    assert review_main(['run', '--pr', str(number)], cwd=work, client=forge, run=command, ready=_can) == code
    status = _review_status(forge, head)
    assert (status.state, status.description.startswith(BATCH_PENDING)) == ('pending', True)


def test_the_github_job_still_fails_when_its_pending_is_not_a_batch(tmp_path: Path) -> None:
    """PLANTED CONTROL: a pending that is no batch (no reviewer could run: a takeover waits) still fails the job."""
    work, head = _batched_work(tmp_path)
    forge = StateForge(Forge('github.com', 'o', 'r'))
    number = forge.add_pull('pr/x', 'integrate/main', title='add x', sha=head)
    forge.login = ACTIONS_BOT
    exhausted = FakeCommand(_output(reviewers=(('correctness', 'exhausted'),)))
    assert review_main(['run', '--pr', str(number)], cwd=work, client=forge, run=exhausted, ready=_can) == 1


def test_the_scheduled_resume_settles_only_the_batch_pending_heads(tmp_path: Path) -> None:
    """``forge review run --batch-pending`` resumes every head whose batch pends, from the state on its PR.

    PLANTED CONTROL: a head held for a takeover (another pending) is not touched.
    """
    work, head = _batched_work(tmp_path)
    other = advance(work, 'pr/y', 'y.py', 'y\n')
    run_git(work, 'checkout', '-q', head)
    forge = StateForge(Forge('github.com', 'o', 'r'))
    number = forge.add_pull('pr/x', 'integrate/main', title='add x', sha=head)
    forge.add_pull('pr/y', 'integrate/main', title='add y', sha=other)
    forge.login = ACTIONS_BOT
    status_post(forge, other, context=REVIEW_CONTEXT, state='pending', description=f'{TAKEOVER_PENDING}: held')
    command = BatchedCommand(polls=2)
    review_main(['run', '--pr', str(number)], cwd=work, client=forge, run=command, ready=_can)
    assert _review_status(forge, head).state == 'pending'
    resumed = review_main(['run', '--batch-pending'], cwd=work, client=forge, run=command, ready=_can,
                          fetch=lambda _where, _number: None)  # fmt: skip
    assert resumed == 0
    assert _review_status(forge, head).state == 'success'
    assert command.submitted == 1, 'resumed from the PR, never resubmitted'
    assert _review_status(forge, other).description.startswith(TAKEOVER_PENDING)


def test_the_merge_tick_resumes_pending_batches_on_its_schedule(tmp_path: Path) -> None:
    """One cadence (merge-tick's schedule) also resumes batches; a ``status`` event never starts a review."""
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.ci."merge-tick.yml"]\n', encoding='utf-8')
    tick = workflows(tmp_path)['merge-tick.yml']
    job = tick['jobs']['review-resume']
    assert job['if'] == "${{ github.event_name != 'status' }}"
    runs = ' '.join(step.get('run', '') for step in job['steps'])
    assert 'forge review run --batch-pending' in runs
    assert '--secret-env ANTHROPIC_API_KEY' in runs
    assert job['permissions'] == {'contents': 'read', 'statuses': 'write', 'pull-requests': 'write', 'issues': 'write'}
