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
    _post(forge, 'tests/linux', 'pending')

    def sleep(_s: float) -> None:
        _post(forge, 'tests/linux', 'success')

    code = watch(forge, (SHA,), deadline_s=50, every_s=1, say=said.append, clock=lambda: next(ticks), sleep=sleep)
    assert code == 0
    assert said == ['tests/linux: pending pending', 'tests/linux: success success']
    assert {s['state'] for s in forge.statuses[SHA]} == {'pending', 'success'}, 'watch posted nothing'


def test_a_red_settles_with_one_and_a_pending_meets_the_deadline() -> None:
    forge = StateForge()
    _post(forge, 'tests/linux', 'failure')
    assert watch(forge, (SHA,), deadline_s=0, every_s=1, say=lambda _l: None) == 1
    other = StateForge()
    _post(other, 'tests/linux', 'pending')
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
