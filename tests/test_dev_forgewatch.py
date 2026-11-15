"""``forge watch``: read-only, prints each change, ends settled or at the deadline."""

from __future__ import annotations

from _forge_state import StateForge

from dev_lab.dev import forgewatch
from dev_lab.dev.forgewatch import watch

SHA = 'c' * 40


def _post(forge: StateForge, context: str, state: str) -> None:
    forge.call('POST', f'{forge.repo}/statuses/{SHA}', {'context': context, 'state': state, 'description': state})


def test_watch_ends_when_every_part_is_final() -> None:
    forge, said, ticks = StateForge(), [], iter(range(100))
    _post(forge, 'tests/base', 'pending')

    def sleep(_s: float) -> None:
        _post(forge, 'tests/base', 'success')

    code = watch(forge, (SHA,), deadline_s=50, every_s=1, say=said.append, clock=lambda: next(ticks), sleep=sleep)
    assert code == 0
    assert said == ['tests/base: pending pending', 'tests/base: success success']
    assert {s['state'] for s in forge.statuses[SHA]} == {'pending', 'success'}, 'watch posted nothing'


def test_a_red_settles_with_one_and_a_pending_meets_the_deadline() -> None:
    forge = StateForge()
    _post(forge, 'tests/base', 'failure')
    assert watch(forge, (SHA,), deadline_s=0, every_s=1, say=lambda _l: None) == 1
    other = StateForge()
    _post(other, 'tests/base', 'pending')
    assert watch(other, (SHA,), deadline_s=0, every_s=1, say=lambda _l: None, sleep=lambda _s: None) == 3


def test_the_cli_polls_every_two_minutes_and_never_faster_than_its_floor(monkeypatch) -> None:
    """2026-11-04: one workstation's watches read statuses ~19 times a minute on a 2-core Gitea host."""
    given: list[float] = []
    monkeypatch.setattr(forgewatch, 'client_for', lambda _root: None)
    monkeypatch.setattr(forgewatch, 'watch', lambda *_a, every_s, **_k: given.append(every_s) or 0)
    forgewatch.main([SHA])
    forgewatch.main([SHA, '--every-seconds', '1'])
    forgewatch.main([SHA, '--every-seconds', '45'])
    assert given == [forgewatch.EVERY_S, forgewatch.FLOOR_S, 45.0]
    assert (forgewatch.EVERY_S, forgewatch.FLOOR_S) == (120.0, 30.0)


def test_a_part_a_failed_job_posted_error_reads_red_and_a_pending_one_does_not() -> None:
    """claude-code-config #6: the job's ``error`` (jobparts.produce/absent) is a red the watch reports and settles on.

    PLANTED CONTROL: the same row ``pending`` (absent) keeps the watch waiting to its deadline.
    """
    forge, said = StateForge(), []
    forge.call(
        'POST',
        f'{forge.repo}/statuses/{SHA}',
        {'context': 'tests/base@windows', 'state': 'error', 'description': "unreachable: cannot run 'npm'"},
    )
    assert watch(forge, (SHA,), deadline_s=0, every_s=1, say=said.append) == 1
    assert said == ["tests/base@windows: error unreachable: cannot run 'npm'"]
    other = StateForge()
    _post(other, 'tests/base@windows', 'pending')
    assert watch(other, (SHA,), deadline_s=0, every_s=1, say=lambda _l: None, sleep=lambda _s: None) == 3


def test_a_head_is_not_green_while_its_base_part_is_absent() -> None:
    """A head is green only by the session watch's one green (:func:`forgewatch._green`).

    A consumer PR, 2026-11-14: ``watch <sha> --stream`` said ``green`` on ``tests/security`` alone, while
    ``forge merge ready`` read ``tests/base`` UNCLAIMED.

    PLANTED CONTROL: once ``tests/base`` ends in success the same watch settles green.
    """
    forge, said = StateForge(), []
    _post(forge, 'tests/security', 'success')
    assert watch(forge, (SHA,), deadline_s=0, every_s=1, say=said.append, sleep=lambda _s: None, stream=True) == 3
    assert f'{SHA[:12]} green' not in said
    _post(forge, 'tests/base', 'success')
    said.clear()
    assert watch(forge, (SHA,), deadline_s=0, every_s=1, say=said.append, stream=True) == 0
    assert said[-1] == f'{SHA[:12]} green'
