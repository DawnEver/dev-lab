"""The allocation record's WRITER verb and the forge's READER of it (ruling 2026-10-23).

The record's format, the share it sets and the resolve every submitter applies are lab-commons'
(``lab_commons.hpc.allocation``, tested there); dev-lab owns only ``hpchost allocate``, which decides
shares, and :func:`dev_lab.dev.forgerecords.read_allocation`, the reader it installs as that port.
"""

from __future__ import annotations

import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from lab_commons.hpc.allocation import READER, RECORD, parse

from dev_lab.dev import forgerecords, hpchost
from dev_lab.dev.hpchost import allocate as verb

ROOT = Path(__file__).resolve().parents[1]


class _Store:
    """The forge records home, in memory: one mutable file."""

    def __init__(self, text: str | None = None) -> None:
        self.text = text

    def read(self) -> str | None:
        return self.text

    def write(self, text: str) -> None:
        self.text = text

    def clear(self) -> None:
        self.text = None


def test_allocate_writes_shows_and_clears_the_one_record(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _Store()
    monkeypatch.setattr(verb, 'allocation_store', lambda: store)
    # The expiry is derived from now: a literal date passes until that day and then is refused as past.
    until = (datetime.now(UTC) + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
    assert hpchost.main(['allocate', '--until', until.strftime('%Y-%m-%dT%H:%MZ'), 'a=64/240', 'b=32/120']) == 0
    written = parse(store.text or '')
    assert written.expires == until
    assert set(written.sessions) == {'a', 'b'}
    capsys.readouterr()
    assert hpchost.main(['allocate', '--show']) == 0
    shown = capsys.readouterr().out
    assert 'a' in shown
    assert until.isoformat() in shown
    assert hpchost.main(['allocate', '--clear']) == 0
    assert store.text is None
    # Planted control: shown with nothing stored, it says the share is derived.
    assert hpchost.main(['allocate', '--show']) == 0
    assert 'derived' in capsys.readouterr().out


def test_allocate_refuses_a_past_expiry_and_a_naive_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verb, 'allocation_store', _Store)
    with pytest.raises(SystemExit):
        hpchost.main(['allocate', '--until', '2000-01-01T00:00Z', 'a=1/1'])
    with pytest.raises(SystemExit):
        hpchost.main(['allocate', '--until', '2099-01-01T00:00', 'a=1/1'])
    with pytest.raises(SystemExit):
        hpchost.main(['allocate', '--until', '2099-01-01T00:00Z'])


def test_the_forge_installs_the_one_reader_lab_commons_loads() -> None:
    """``lab_commons.hpc`` reads the record through this entry point; without it a person's submit ignores it."""
    declared = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['entry-points']
    assert declared[READER] == {'forge': 'dev_lab.dev.forgerecords:read_allocation'}


def test_the_reader_reads_the_named_record_on_the_roots_forge(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    asked: list[tuple[object, str]] = []
    monkeypatch.setattr(forgerecords, 'client_for', lambda root: ('client', root))
    monkeypatch.setattr(forgerecords, 'read_named', lambda client, name: asked.append((client, name)) or b'{}')
    assert forgerecords.read_allocation(tmp_path) == b'{}'
    # Planted control: no root is the working directory's forge.
    assert forgerecords.read_allocation() == b'{}'
    assert asked == [(('client', tmp_path), RECORD), (('client', Path.cwd()), RECORD)]
