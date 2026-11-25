"""D16/D18: shared results on the forge (first wins, a differing one alarms) and a unit offered as a Job, served.

The forge's attachment listing and upload are an in-memory fake (``forgerecords`` itself is tested against
the HTTP fake in ``test_dev_forgerecords.py``); archives are stdlib gzip tars.
"""

from __future__ import annotations

import functools
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from _box_fake import quiet
from lab_commons import box as lab_box
from lab_commons.box import GB, Capacity
from lab_commons.compute.execute import OFFERED, LocalExecutor, Where
from lab_commons.compute.graph import Graph
from lab_commons.compute.model import Demand
from lab_commons.compute.store import Nondeterministic, Record, Result, ResultStore, Tombstone, TooLarge, result_hash
from lab_commons.compute.unit import Engine, Unit, environment_here

from dev_lab.dev import forgeunit
from dev_lab.dev.artifactfolder import FolderStore
from dev_lab.dev.artifacts import Config
from dev_lab.dev.artifactstores import ATTACHMENT_LIMIT_MB, MB, Ref, ref_of_entry
from dev_lab.dev.forgealarm import NONDETERMINISM, Alarm
from dev_lab.dev.forgerecords import Attachment
from dev_lab.dev.forgerequest import UNIT, UndeclaredRequest, declared_request
from dev_lab.dev.forgeunit import ForgeResults, UnitJob, grave_name, offering, result_name, unit_request

_GIT = shutil.which('git') or 'git'
UNIT_HASH = 'ab' * 32
SMALL = Demand(cpu=1, mem_gb=0.5)
RAN_HERE: list[str] = []


def square(inputs: Mapping[str, Any], work: Path) -> None:
    RAN_HERE.append('square')
    n = int(inputs['n'].read_text(encoding='utf-8')) + inputs['k']
    (work / 'out').write_text(str(n * n), encoding='utf-8')


@dataclass
class Forge:
    """The records home: attachments in a directory, listed in upload order."""

    root: Path
    held: list[Attachment] = field(default_factory=list)

    def listing(self, _client: object) -> tuple[Attachment, ...]:
        return tuple(self.held)

    def attach(self, _client: object, path: Path) -> Attachment:
        kept = self.root / path.name
        shutil.copyfile(path, kept)
        self.held.append(Attachment(len(self.held) + 1, path.name, str(kept)))
        return self.held[-1]

    def client(self) -> SimpleNamespace:
        return SimpleNamespace(forge=SimpleNamespace(repo='r'), download=lambda url: Path(url).read_bytes())


@pytest.fixture
def forge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Forge:
    (tmp_path / 'forge').mkdir()
    fake = Forge(tmp_path / 'forge')
    monkeypatch.setattr(forgeunit, 'listing', fake.listing)
    monkeypatch.setattr(forgeunit, 'attach', fake.attach)
    RAN_HERE.clear()
    return fake


def stored(store: ResultStore, text: str, host: str) -> tuple[Path, Record]:
    where = store.staging()
    (where / 'out').write_text(text, encoding='utf-8')
    return where, Record(UNIT_HASH, 'e', 'v', '', host, 't0', 't1', result_hash(where, ('out',)), local_only=False)


def test_a_job_spells_its_unit_bundle_size_and_needs_as_paths() -> None:
    job = UnitJob(
        UNIT_HASH, Ref('forge', 'k.tar.gz', 10, 'f' * 64), Demand(cpu=2, mem_gb=6.0), 7200, ('femm', 'windows')
    )
    assert UnitJob.of(job.paths()) == job
    declared = unit_request(job.paths())
    assert declared.argv == ('-m', 'dev_lab.dev.forgeunit', *job.paths())
    assert (declared.needs, declared.cpu, declared.mem, declared.wall) == ({'femm', 'windows'}, 2.0, 6.0 * GB, 7200.0)
    assert declared_request(Path(), 'c' * 40, UNIT, job.paths()) == declared  # the built-in producer
    with pytest.raises(UndeclaredRequest, match='no unit hash'):
        UnitJob.of(('unit=xyz', *job.paths()[1:]))
    with pytest.raises(UndeclaredRequest, match='size'):
        UnitJob.of(job.paths()[:2])
    with pytest.raises(UndeclaredRequest):
        UnitJob.of((*job.paths()[:2], 'size=0|6.0|7200', job.paths()[3]))  # PLANTED: an unsized Job is refused


def test_the_first_posted_result_wins_and_a_differing_one_alarms(tmp_path: Path, forge: Forge) -> None:
    rang: list[Alarm] = []
    tier = ForgeResults(forge.client(), alarm=rang.append)
    one = ResultStore(tmp_path / 'one', tier)
    first = one.put(*stored(one, '42', 'h1'))
    assert [a.name for a in forge.held] == [result_name(UNIT_HASH, 0, first.record.result_hash)]
    two = ResultStore(tmp_path / 'two', tier)
    two.put(*stored(two, '42', 'h2'))
    assert len(forge.held) == 1  # an identical later post is dropped
    three = ResultStore(tmp_path / 'three', tier)
    with pytest.raises(Nondeterministic, match='stands'):
        three.put(*stored(three, '43', 'h3'))
    assert [(a.kind, a.about) for a in rang] == [(NONDETERMINISM, UNIT_HASH)]
    assert len(forge.held) == 1
    fetched = ResultStore(tmp_path / 'four', tier).get(UNIT_HASH)
    assert isinstance(fetched, Result)
    assert (fetched.output('out').read_text(encoding='utf-8'), fetched.record.host) == ('42', 'h1')


def test_post_then_fetch_round_trips_by_generation(tmp_path: Path, forge: Forge) -> None:
    tier = ForgeResults(forge.client())
    store = ResultStore(tmp_path / 'one')  # local only: the tier is driven by hand
    results = []
    for gen, text in ((0, 'zero'), (1, 'one')):
        staged, record = stored(store, text, 'h1')
        results.append(ResultStore(tmp_path / f'g{gen}').put(staged, record))
        tier.post(results[-1], gen)
    assert [a.name for a in forge.held] == [
        result_name(UNIT_HASH, g, r.record.result_hash) for g, r in enumerate(results)
    ]
    for gen, text in ((0, 'zero'), (1, 'one')):
        got = tier.fetch(UNIT_HASH, gen, tmp_path / f'back{gen}')
        assert got is not None
        assert (got / 'out').read_text(encoding='utf-8') == text
    assert tier.fetch(UNIT_HASH, 2, tmp_path / 'back2') is None  # PLANTED: an unposted generation is a miss
    tier.post(results[1], 1)
    assert len(forge.held) == 2  # an identical post to its generation is a no-op


def test_a_grave_buried_on_one_host_is_seen_by_another(tmp_path: Path, forge: Forge) -> None:
    here, there = ForgeResults(forge.client()), ForgeResults(forge.client())
    one = ResultStore(tmp_path / 'one', here)
    one.put(*stored(one, '42', 'h1'))
    assert there.graves(UNIT_HASH) == ()  # PLANTED: nothing buried yet, nothing seen
    tombstone = one.invalidate(UNIT_HASH, 'a bad input', host='h1')
    assert forge.held[-1].name == grave_name(UNIT_HASH, 0)
    assert there.graves(UNIT_HASH) == (tombstone,)
    assert there.graves('cd' * 32) == ()
    there.bury(tombstone)
    assert [a.name for a in forge.held].count(grave_name(UNIT_HASH, 0)) == 1  # a second bury is a no-op
    missed = ResultStore(tmp_path / 'two', there).get(UNIT_HASH)
    assert missed == tombstone  # the other host's get answers the tombstone, not the buried result


def test_a_payload_over_the_upload_ceiling_is_refused_by_name(tmp_path: Path, forge: Forge) -> None:
    assert ForgeResults(forge.client()).max_bytes == ATTACHMENT_LIMIT_MB * MB  # the forge attachment limit
    record = Record(UNIT_HASH, 'e', 'v', '', 'h1', 't0', 't1', '', local_only=False)
    small = ResultStore(tmp_path / 'small', ForgeResults(forge.client(), max_bytes=4096))
    small.put_files({'out': b'x' * 64}, record)
    assert len(forge.held) == 1  # PLANTED: under the ceiling, it posts
    big = ResultStore(tmp_path / 'big', ForgeResults(forge.client(), max_bytes=4096))
    with pytest.raises(TooLarge, match='over the shared tier limit of 4096 bytes'):
        big.put_files({'out': bytes(range(256)) * 64}, replace(record, unit_hash='cd' * 32))
    assert len(forge.held) == 1
    tight = ForgeResults(forge.client(), max_bytes=8)  # the archive itself is checked before any upload
    with pytest.raises(TooLarge, match='limit of 8 bytes'):
        tight.post(ResultStore(tmp_path / 'small').get(UNIT_HASH), 1)
    assert len(forge.held) == 1


def test_a_sized_compute_unit_keeps_its_positive_fractional_memory() -> None:
    job = UnitJob(UNIT_HASH, Ref('forge', 'k.tar.gz', 10, 'f' * 64), Demand(cpu=1, mem_gb=0.25), 60, ())
    assert UnitJob.of(job.paths()) == job


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'pyproject.toml').write_text('[tool.lab_commons.hpc]\n', encoding='utf-8')
    for args in (('init', '-q'), ('add', 'pyproject.toml'), ('commit', '-q', '-m', 'init')):
        subprocess.run(
            [_GIT, '-c', 'user.name=t', '-c', 'user.email=t@t', *args], cwd=repo, check=True, capture_output=True,
            timeout=60,
        )  # fmt: skip
    return repo


def test_an_offered_unit_is_served_by_the_same_executor_and_its_result_comes_back(
    tmp_path: Path, forge: Forge, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    env = environment_here(repo)
    folder = FolderStore(tmp_path / 'artifacts', 'r')
    published: list[tuple[str, str, tuple[str, ...]]] = []
    monkeypatch.setattr(forgeunit, 'load_config', lambda _root: Config())
    monkeypatch.setattr(forgeunit, 'store_for', lambda *_a, **_k: folder)
    monkeypatch.setattr(forgeunit, 'resolve', lambda entry, dest, **_k: folder.get(ref_of_entry(entry), dest))
    monkeypatch.setattr(forgeunit, 'load_schedule', lambda _root: SimpleNamespace(request_label='request'))

    def publish(_root: Path, _client: object, producer: str, sha: str, **kw: tuple[str, ...]) -> SimpleNamespace:
        published.append((producer, sha, kw['paths']))
        return SimpleNamespace(number=12)

    monkeypatch.setattr(forgeunit, 'publish', publish)
    (tmp_path / 'n.txt').write_text('5', encoding='utf-8')
    unit = Unit(
        Engine.ours('t.square', env), f'{__name__}:square', {'n': tmp_path / 'n.txt', 'k': 1}, ('out',), SMALL, 600
    )
    client = forge.client()
    tier = ForgeResults(client)
    box = LocalExecutor(
        ResultStore(tmp_path / 'box', tier),
        tmp_path / 'box-journal',
        present=lambda _e: 'this box cannot',
        where=Where.ANYWHERE,
        offer=offering(repo, client, env.sha),
    )
    offered = box.run(Graph({'sq': unit}))['sq']
    assert (offered.state, offered.job) == (OFFERED, '#12')
    assert RAN_HERE == []
    [(producer, sha, paths)] = published
    assert (producer, sha) == (UNIT, env.sha)
    assert UnitJob.of(paths).unit_hash == offered.unit_hash

    size = Capacity(cpu=2.0, mem_bytes=2 * 1024**3, seats={})  # a box of known size, not this machine's load
    held = functools.partial(lab_box.hold, capacity=size, read=quiet(size))
    monkeypatch.setattr(forgeunit, 'LocalExecutor', functools.partial(LocalExecutor, hold=held))
    code = forgeunit.main(list(paths), cwd=repo, client=client, store=tmp_path / 'serve')
    assert code == 0
    assert RAN_HERE == ['square']  # the serve host ran it, in-process, with the same executor
    again = box.run(Graph({'sq': unit}))['sq']
    assert again.state == 'cached'  # the result came back through the shared tier: nothing runs
    assert again.result.output('out').read_text(encoding='utf-8') == '36'
    assert RAN_HERE == ['square']

    tombstone = box.store.invalidate(offered.unit_hash, 'a bad input', host='box')
    assert isinstance(box.store.get(offered.unit_hash), Tombstone)
    assert forgeunit.main(list(paths), cwd=repo, client=client, store=tmp_path / 'serve2') == 0
    assert RAN_HERE == ['square', 'square']  # the serve host's get answered the tombstone: a miss, so it ran
    fresh = box.run(Graph({'sq': unit}))['sq']
    assert fresh.state == 'cached'  # generation 1 came back through the shared tier
    assert box.store.history(offered.unit_hash)[0][0] == tombstone


def test_a_bundle_that_is_not_its_jobs_unit_is_refused(
    tmp_path: Path, forge: Forge, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    env = environment_here(repo)
    folder = FolderStore(tmp_path / 'artifacts', 'r')
    published: list[tuple[str, ...]] = []
    monkeypatch.setattr(forgeunit, 'load_config', lambda _root: Config())
    monkeypatch.setattr(forgeunit, 'store_for', lambda *_a, **_k: folder)
    monkeypatch.setattr(forgeunit, 'resolve', lambda entry, dest, **_k: folder.get(ref_of_entry(entry), dest))
    monkeypatch.setattr(forgeunit, 'load_schedule', lambda _root: SimpleNamespace(request_label='request'))
    monkeypatch.setattr(
        forgeunit, 'publish', lambda *_a, **kw: published.append(kw['paths']) or SimpleNamespace(number=1)
    )
    (tmp_path / 'n.txt').write_text('5', encoding='utf-8')
    unit = Unit(
        Engine.ours('t.square', env), f'{__name__}:square', {'n': tmp_path / 'n.txt', 'k': 1}, ('out',), SMALL, 600
    )
    offering(repo, forge.client(), env.sha)(unit, 'cd' * 32, {'n': tmp_path / 'n.txt'})
    code = forgeunit.main(list(published[0]), cwd=repo, client=forge.client(), store=tmp_path / 's')
    assert code == 2
    assert RAN_HERE == []
    with pytest.raises(ValueError, match='cannot run it'):
        offering(repo, forge.client(), 'e' * 40)(unit, 'cd' * 32, {'n': tmp_path / 'n.txt'})


def test_offering_for_is_the_one_call_a_consumer_needs(monkeypatch, tmp_path) -> None:
    """A consumer names a repo and a sha; the forge client is the dev kit's to build, never the consumer's."""
    built: list[object] = []
    sentinel = object()
    monkeypatch.setattr(forgeunit, 'client_for', lambda root: built.append(root) or sentinel)
    seen: list[tuple[object, object, str]] = []
    monkeypatch.setattr(forgeunit, 'offering', lambda root, client, sha: seen.append((root, client, sha)) or 'offer')
    assert forgeunit.offering_for(tmp_path, 'a' * 40) == 'offer'
    assert built == [tmp_path]
    assert seen == [(tmp_path, sentinel, 'a' * 40)]
    assert 'offering_for' in forgeunit.__all__


def _down(monkeypatch: pytest.MonkeyPatch) -> None:
    """The forge unreachable: every listing and upload drops its connection (an OSError, status 0)."""

    def dropped(*_args: object, **_kwargs: object) -> object:
        msg = 'connection dropped'
        raise ConnectionError(msg)

    monkeypatch.setattr(forgeunit, 'listing', dropped)
    monkeypatch.setattr(forgeunit, 'attach', dropped)


def _up(forge: Forge, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(forgeunit, 'listing', forge.listing)
    monkeypatch.setattr(forgeunit, 'attach', forge.attach)


def test_an_offline_post_is_held_and_lands_after_reconnection(
    tmp_path: Path, forge: Forge, monkeypatch: pytest.MonkeyPatch
) -> None:
    tier = ForgeResults(forge.client(), pending=tmp_path / 'pending')
    one = ResultStore(tmp_path / 'one', tier)
    _down(monkeypatch)
    put = one.put(*stored(one, '42', 'h1'))  # the put succeeds: the result is here, its post is held
    assert forge.held == []
    assert [p.name for p in (tmp_path / 'pending').iterdir()] == [result_name(UNIT_HASH, 0, put.record.result_hash)]
    grave = one.invalidate(UNIT_HASH, 'wrong deck', host='h1')
    assert len(list((tmp_path / 'pending').iterdir())) == 2  # the tombstone waits too
    _up(forge, monkeypatch)
    landed = tier.flush()
    assert [a.name for a in forge.held] == [
        result_name(UNIT_HASH, 0, put.record.result_hash),
        grave_name(UNIT_HASH, 0),
    ]
    assert len(landed) == 2
    assert not any((tmp_path / 'pending').iterdir())
    assert tier.graves(UNIT_HASH) == (grave,)
    assert tier.flush() == []  # nothing left: a second flush sends nothing


def test_a_flush_stops_at_the_first_unreachable_post_and_keeps_it(
    tmp_path: Path, forge: Forge, monkeypatch: pytest.MonkeyPatch
) -> None:
    tier = ForgeResults(forge.client(), pending=tmp_path / 'pending')
    one = ResultStore(tmp_path / 'one', tier)
    _down(monkeypatch)
    one.put(*stored(one, '42', 'h1'))
    lines = tier.flush()  # still down
    assert len(list((tmp_path / 'pending').iterdir())) == 1
    assert any('kept' in line and 'unreachable' in line for line in lines)


def test_without_a_pending_directory_an_offline_post_still_raises(
    tmp_path: Path, forge: Forge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PLANTED: the hold is opt-in by the caller's pending directory; without it nothing is silently kept."""
    one = ResultStore(tmp_path / 'one', ForgeResults(forge.client()))
    _down(monkeypatch)
    with pytest.raises(ConnectionError):
        one.put(*stored(one, '42', 'h1'))


def test_a_held_result_that_meets_a_differing_first_result_is_dropped_and_alarms(
    tmp_path: Path, forge: Forge, monkeypatch: pytest.MonkeyPatch
) -> None:
    rang: list[Alarm] = []
    tier = ForgeResults(forge.client(), alarm=rang.append, pending=tmp_path / 'pending')
    one = ResultStore(tmp_path / 'one', tier)
    _down(monkeypatch)
    one.put(*stored(one, '43', 'h1'))
    _up(forge, monkeypatch)
    two = ResultStore(tmp_path / 'two', ForgeResults(forge.client()))
    first = two.put(*stored(two, '42', 'h2'))  # another host posted first while this one was offline
    lines = tier.flush()
    assert [a.name for a in forge.held] == [result_name(UNIT_HASH, 0, first.record.result_hash)]  # the first stands
    assert [(a.kind, a.about) for a in rang] == [(NONDETERMINISM, UNIT_HASH)]
    assert any('dropped' in line for line in lines)
    assert not any((tmp_path / 'pending').iterdir())
