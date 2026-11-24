"""``verify --serial`` / ``--price`` stand for pytest arguments appended last, so they win over a configured width."""

from __future__ import annotations

import argparse

import pytest

from dev_lab.dev import verify


@pytest.fixture(autouse=True)
def _xdist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify, 'serial_width', lambda: ['-n', '0'])


@pytest.mark.parametrize(
    ('serial', 'price', 'expected'),
    [
        (False, False, ()),
        (True, False, ('-n', '0')),
        (False, True, ('--timeout=0', '--durations=0', '-n', '0')),
    ],
)
def test_each_mode_names_exactly_its_arguments(*, serial: bool, price: bool, expected: tuple[str, ...]) -> None:
    assert verify._mode_args(argparse.Namespace(serial=serial, price=price)) == expected
