"""PUSHED-HEAD-IS-WATCHED, the Stop half: a pending head that can never settle never holds a turn forever.

Review finding F-05c3ae4cb27f: a head CI never posts a ``tests/*`` status on (a branch CI does not run on, a
docs-only head) read ``pending`` forever, and a pending refusal was never released -- so a turn could never end.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from _branch_repos import clone_pair
from _forge_fake import git_out
from _forge_state import StateForge

from dev_lab.dev import pushwatch
from dev_lab.dev.forgestatus import status_post
from dev_lab.dev.pushstop import GRACE_S, Stop, stop_refusal
from dev_lab.dev.pushwatch import watch_command

if TYPE_CHECKING:
    from pathlib import Path

PUSHED_AT = 1_000_000.0


def _pushed(tmp_path: Path) -> tuple[Path, str]:
    _, work = clone_pair(tmp_path)
    head = git_out(work, 'rev-parse', 'HEAD')
    pushwatch.record(work, 's1', 'refs/heads/pr/x', head, at=PUSHED_AT)
    return work, head


def _stop(work: Path, forge: StateForge, *, after_s: float, again: bool = False) -> Stop:
    return stop_refusal(work, 's1', client=forge, processes=lambda: (), again=again, now=PUSHED_AT + after_s)


def test_a_head_with_no_status_past_the_grace_has_nothing_to_watch(tmp_path: Path) -> None:
    work, _ = _pushed(tmp_path)
    said = _stop(work, StateForge(), after_s=GRACE_S + 1)
    assert said.block is None


def test_a_head_with_only_non_test_contexts_past_the_grace_has_nothing_to_watch(tmp_path: Path) -> None:
    work, head = _pushed(tmp_path)
    forge = StateForge()
    status_post(forge, head, context='ci/lint', state='pending', description='lint')
    assert _stop(work, forge, after_s=GRACE_S + 1).block is None


def test_a_head_with_no_status_within_the_grace_is_refused_with_the_watch_command(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same status-less head, before CI had time to post its first pending."""
    work, head = _pushed(tmp_path)
    said = _stop(work, StateForge(), after_s=GRACE_S - 1)
    assert said.block is not None
    assert watch_command(head) in said.block


def test_a_pending_head_whose_watch_reached_its_deadline_is_released_on_the_repeated_stop(tmp_path: Path) -> None:
    work, head = _pushed(tmp_path)
    forge = StateForge()
    status_post(forge, head, context='tests/base', state='pending', description='running')
    assert _stop(work, forge, after_s=GRACE_S * 10, again=True).block is not None, (
        'PLANTED CONTROL: no deadline recorded, a live pending head is refused even on a repeated stop'
    )
    pushwatch.record_deadline(work, head)
    first = _stop(work, forge, after_s=GRACE_S * 10)
    assert first.block is not None, 'the first stop still asks for a watch'
    released = _stop(work, forge, after_s=GRACE_S * 10, again=True)
    assert released.block is None
    assert released.note is not None
    assert head[:12] in released.note
    assert 'deadline' in released.note
