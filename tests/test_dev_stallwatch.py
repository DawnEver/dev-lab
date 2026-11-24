"""A run is ended as STALLED only when it is silent AND idle for the derived window -- never for one alone."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dev_lab.dev.stallwatch import StallWatch, stall_window

if TYPE_CHECKING:
    from pathlib import Path


class _Box:
    def __init__(self) -> None:
        self.now = 0.0
        self.cpu = 0.0


def _watch(box: _Box) -> StallWatch:
    return StallWatch(window_s=100.0, clock=lambda: box.now, tree_cpu=lambda: box.cpu)


def test_silent_and_idle_past_the_window_is_a_stall_that_names_its_window() -> None:
    box = _Box()
    watch = _watch(box)
    box.now = 99.0
    assert watch.check() is None
    box.now = 101.0
    assert watch.check() == 'no output and no CPU in the run tree for 101 s (window 100 s, twice the per-test timeout)'


def test_output_alone_keeps_a_run_alive() -> None:
    """Planted control: silence is required, so a run that writes is never stalled however idle."""
    box = _Box()
    watch = _watch(box)
    box.now = 90.0
    watch.wrote()
    box.now = 150.0
    assert watch.check() is None


def test_cpu_alone_keeps_a_silent_run_alive() -> None:
    box = _Box()
    watch = _watch(box)
    box.now, box.cpu = 60.0, 5.0
    assert watch.check() is None
    box.now = 150.0
    assert watch.check() is None
    box.now = 161.0
    assert watch.check() is not None


@pytest.mark.parametrize(
    ('ini', 'window'),
    [('timeout = 300\n', 600.0), ('timeout = "45"\n', 90.0), ('addopts = "-q"\n', None), ('timeout = 0\n', None)],
)
def test_the_window_is_derived_from_the_declared_per_test_timeout(
    tmp_path: Path, ini: str, window: float | None
) -> None:
    (tmp_path / 'pyproject.toml').write_text(f'[tool.pytest.ini_options]\n{ini}', encoding='utf-8')
    assert stall_window(tmp_path) == window


def test_an_argv_timeout_outranks_the_declared_one_and_zero_turns_the_watch_off(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text('[tool.pytest.ini_options]\ntimeout = 300\n', encoding='utf-8')
    assert stall_window(tmp_path, ('--timeout=10', '--timeout=20')) == 40.0
    assert stall_window(tmp_path, ('--timeout=0',)) is None
