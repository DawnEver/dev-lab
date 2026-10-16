"""D4: demand is SHARED -- the forge's run records folded into the learned cache, once each, newest winning."""

from __future__ import annotations

import gzip
import json

import pytest

from lab_commons.compute import learned
from lab_commons.dev import forgedemand
from lab_commons.dev.forgerecords import Attachment
from lab_commons.dev.forgework import ForgeCallFailed

REPO = 'https://g/r.git'


class _Forge:
    """A forge holding *records* as attachments; counts downloads."""

    def __init__(self, records: dict[str, dict]) -> None:
        self.blobs = {f'u/{name}': gzip.compress(json.dumps(r).encode()) for name, r in records.items()}
        self.attached = [Attachment(i, name, f'u/{name}') for i, name in enumerate(records)]
        self.downloads: list[str] = []

    def download(self, url: str) -> bytes:
        self.downloads.append(url)
        return self.blobs[url]


@pytest.fixture
def forge(monkeypatch: pytest.MonkeyPatch) -> _Forge:
    fake = _Forge({
        'run-a.json.gz': {'peaks_mb': {'tests/x.py': 100.0, 'tests/y.py': 50.0}},
        'run-b.json.gz': {'peaks_mb': {'tests/x.py': 300.0}, 'durations': {'tests/x.py::t': 2.0}},
    })  # fmt: skip
    monkeypatch.setattr(forgedemand, 'listing', lambda client: tuple(client.attached))
    return fake


def test_every_attached_record_is_folded_once_and_the_newer_fact_wins(forge: _Forge) -> None:
    assert forgedemand.refresh(REPO, forge) == 2
    table = learned.learned(REPO)
    assert table['peaks_mb'] == {'tests/x.py': 300.0, 'tests/y.py': 50.0}, 'b (newer) replaced x; y kept from a'
    assert table['durations'] == {'tests/x.py::t': 2.0}
    assert forgedemand.refresh(REPO, forge) == 0, 'the cache remembers what it folded'
    assert len(forge.downloads) == 2


def test_no_forge_or_a_failing_one_folds_nothing_and_keeps_the_cache(forge: _Forge, monkeypatch) -> None:
    """PLANTED CONTROL: a down forge is not a refusal; the cache stands as last folded."""
    assert forgedemand.refresh(REPO, None) == 0

    def down(_client: object) -> tuple[Attachment, ...]:
        msg = 'unreachable'
        raise OSError(msg)

    monkeypatch.setattr(forgedemand, 'listing', down)
    assert forgedemand.refresh(REPO, forge) == 0
    assert learned.learned(REPO) == {}


def test_an_unreadable_record_is_skipped_and_retried_next_time(forge: _Forge) -> None:
    forge.blobs['u/run-a.json.gz'] = b'not gzip'
    assert forgedemand.refresh(REPO, forge) == 1
    assert learned.folded(REPO) == {'run-b.json.gz'}


def test_a_forge_error_on_one_download_is_not_fatal(forge: _Forge, monkeypatch) -> None:
    calls = iter([ForgeCallFailed.__new__(ForgeCallFailed), None])

    def flaky(url: str) -> bytes:
        failure = next(calls)
        if failure is not None:
            raise failure
        return forge.blobs[url]

    monkeypatch.setattr(forge, 'download', flaky)
    assert forgedemand.refresh(REPO, forge) == 1


def test_at_most_limit_records_are_read_newest_first(forge: _Forge) -> None:
    assert forgedemand.refresh(REPO, forge, limit=1) == 1
    assert learned.folded(REPO) == {'run-b.json.gz'}
