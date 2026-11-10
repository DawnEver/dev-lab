"""THE FAMILY WATCH runs DAILY on every serving machine's kit tick, never only on the elected poller.

MEASURED 2026-11-10: ``family check`` ran on no schedule -- its step sat in the poller-only repo-wide pass, and the
poller's serve was paused. The family is machine-local (this machine's checkouts), so every serving machine reads
its own, once a day. PLANTED CONTROLS: another repo's tick reads nothing; a read that fails leaves no stamp.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dev_lab.dev.family import watch
from dev_lab.dev.family.members import Finding
from dev_lab.dev.forgealarm import FAMILY, Alarm
from dev_lab.dev.hpcaccount.spec import KIT

_NOW = datetime(2026, 11, 10, 9, tzinfo=UTC)


def _step(root: Path, stamp: Path, now: datetime, read: Callable[[], list[Finding]]) -> list[Alarm]:
    raised: list[Alarm] = []
    watch.step(root, 'r', say=lambda _line: None, alarm=raised.append, read=read, now=now, stamp=stamp)
    return raised


def test_the_watch_raises_each_finding_then_waits_a_day(tmp_path: Path) -> None:
    kit, stamp, reads = tmp_path / KIT, tmp_path / 'stamp.json', []

    def read() -> list[Finding]:
        reads.append(1)
        return [Finding('ai-lab', 'origin: 3 commits behind')]

    (one,) = _step(kit, stamp, _NOW, read)
    assert (one.kind, one.about) == (FAMILY, 'ai-lab:origin')
    assert _step(kit, stamp, _NOW + timedelta(hours=23), read) == [], 'within the day: not read again'
    assert len(reads) == 1
    assert len(_step(kit, stamp, _NOW + watch.EVERY, read)) == 1, 'a day on, it reads again'


def test_another_repos_tick_reads_nothing(tmp_path: Path) -> None:
    def read() -> list[Finding]:
        raise AssertionError

    assert _step(tmp_path / 'other-repo', tmp_path / 'stamp.json', _NOW, read) == [], 'PLANTED CONTROL'


def test_a_failed_read_leaves_no_stamp_so_the_next_tick_retries(tmp_path: Path) -> None:
    stamp = tmp_path / 'stamp.json'

    def read() -> list[Finding]:
        msg = 'forge unreachable'
        raise OSError(msg)

    with pytest.raises(OSError, match='unreachable'):
        _step(tmp_path / KIT, stamp, _NOW, read)
    assert not stamp.exists()
