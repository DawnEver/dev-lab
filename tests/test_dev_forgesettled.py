"""A commit whose every part is settled is read once: its statuses never change, so no tick asks again.

THE INCIDENT (2026-10-24): every tick of every host read ``GET .../statuses/<sha>`` for every served head --
hundreds per repo in ten minutes -- though almost every head was long settled. The planted controls are a
head with a part still handed (not settled: read every tick) and a pending claim (not settled either).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lab_commons.hpc.needsets import BASE

from dev_lab.dev.forgesettled import SettledHistories, settled
from dev_lab.dev.forgestatus import status_history
from tests._forge_state import StateForge

if TYPE_CHECKING:
    from pathlib import Path

SHA = 'a' * 40


def _post(forge: StateForge, part: str, state: str, description: str) -> None:
    forge.call(
        'POST', f'{forge.repo}/statuses/{SHA}', {'context': f'tests/{part}', 'state': state, 'description': description}
    )


def _reads(forge: StateForge) -> int:
    return sum(one == f'GET {forge.repo}/statuses/{SHA}' for one in forge.asked)


def _cached(tmp_path: Path) -> StateForge:
    forge = StateForge()
    forge.cache_dir = tmp_path
    return forge


def test_a_settled_commit_is_read_once_across_ticks(tmp_path: Path) -> None:
    forge = _cached(tmp_path)
    _post(forge, BASE, 'success', 'scope=full ran=3 hands=linux:2')
    _post(forge, 'linux', 'failure', 'scope=full ran=2 hands=-')
    first = SettledHistories(forge)(SHA)
    again = SettledHistories(forge)(SHA)  # the next tick: a new reader, the same cache
    assert settled(first)
    assert again == first
    assert _reads(forge) == 1


def test_planted_control_a_part_still_handed_is_read_every_tick(tmp_path: Path) -> None:
    forge = _cached(tmp_path)
    _post(forge, BASE, 'success', 'scope=full ran=3 hands=linux:2')
    SettledHistories(forge)(SHA)
    SettledHistories(forge)(SHA)
    assert not settled(status_history(forge, SHA))
    assert _reads(forge) == 3


def test_planted_control_a_pending_claim_is_not_settled(tmp_path: Path) -> None:
    forge = _cached(tmp_path)
    _post(forge, BASE, 'success', 'scope=full ran=3 hands=-')
    _post(forge, BASE, 'pending', 'claimed by x')
    assert not settled(SettledHistories(forge)(SHA))


def test_one_reader_reads_a_commit_once_settled_or_not() -> None:
    forge = StateForge()  # no cache: the reader still memoizes within its tick
    _post(forge, BASE, 'pending', 'claimed by x')
    read = SettledHistories(forge)
    read(SHA)
    read(SHA)
    assert _reads(forge) == 1
