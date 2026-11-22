"""A test's box keeps a free-space floor OF ITS OWN: the host's free disk never decides a test's result.

The box refuses a hold whose volumes are under the machine's ``[storage] free_floor_gb`` (default 50 GiB), and a
test's ledger lives under ``tmp_path`` -- the SYSTEM temp volume. A hosted Windows runner's system drive had
30 GiB free: every test that took a real hold was refused at once (``ledger.py: Refused``, dev-lab
tests/base@windows 2026-11-22, 112 tests through the box and the dependency door, more behind them). So the
suite's machine file (``tests/conftest.py::_a_box_of_its_own``) declares the test box's floor, and a child
process inherits it with the file's path.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from lab_commons.box import box_path
from lab_commons.box.disk import verdict
from lab_commons.compute import floor
from lab_commons.config import CONFIG_ENV
from lab_commons.storage import FREE_FLOOR_GB_DEFAULT, free_floor

_GIB = 1024**3
#: What the hosted Windows runner's system drive had free when the suite was refused.
_HOSTED_FREE = 30 * _GIB


def _refusal(monkeypatch: pytest.MonkeyPatch) -> str | None:
    """What the box says of a test's volumes (its ledger's and its cwd's, as ``hold`` asks) with 30 GiB free."""
    monkeypatch.setattr(floor, 'free_bytes', lambda _volume: _HOSTED_FREE)
    return verdict((box_path(), Path.cwd()), free_floor())[0]


def test_a_test_hold_is_not_refused_on_a_host_whose_temp_volume_is_under_the_machine_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _HOSTED_FREE < FREE_FLOOR_GB_DEFAULT * _GIB, 'the planted volume must sit under the default floor'
    assert _refusal(monkeypatch) is None


def test_a_test_that_declares_the_machine_default_is_refused_on_that_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL: the same reading under a declared 50 GiB floor is the refusal the hosted runner gave."""
    machine = Path(os.environ[CONFIG_ENV])
    machine.parent.mkdir(parents=True, exist_ok=True)
    machine.write_text(f'[storage]\nfree_floor_gb = {FREE_FLOOR_GB_DEFAULT}\n', encoding='utf-8')
    said = _refusal(monkeypatch)
    assert said is not None
    assert 'below the floor 50.0 GiB' in said


def test_the_machine_file_is_beside_the_tests_tmp_path_which_starts_empty(tmp_path: Path) -> None:
    """A test hands its whole ``tmp_path`` to a reader that refuses an entry it does not know (test_outcomes)."""
    assert list(tmp_path.iterdir()) == []
    assert tmp_path not in Path(os.environ[CONFIG_ENV]).parents


def test_a_child_process_reads_the_same_floor() -> None:
    """The floor rides in the machine FILE, so a child that inherits the environment keeps it (no in-process patch)."""
    declared = Path(os.environ[CONFIG_ENV])
    assert declared.is_file(), f'{CONFIG_ENV} names no file: a child process would fall back to the machine default'
    assert free_floor().bytes < _GIB
