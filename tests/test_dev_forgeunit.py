"""D16/D18: shared results on the forge (first wins, a differing one alarms) and a unit offered as a Job, served.

The forge's attachment listing and upload are an in-memory fake (``forgerecords`` itself is tested against
the HTTP fake in ``test_dev_forgerecords.py``); archives are stdlib gzip tars.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from lab_commons.box.demand import Demand
from lab_commons.compute.execute import OFFERED, LocalExecutor, Where
from lab_commons.compute.graph import Graph
from lab_commons.compute.store import Nondeterministic, Record, ResultStore, result_hash
from lab_commons.compute.unit import Engine, Unit, environment_here

from dev_lab.dev import forgeunit
from dev_lab.dev.artefacts import Config, FolderStore
from dev_lab.dev.artefactstores import Ref
from dev_lab.dev.forgealarm import NONDETERMINISM, Alarm
from dev_lab.dev.forgerecords import Attachment
from dev_lab.dev.forgerequest import UNIT, UndeclaredRequest, declared_request
from dev_lab.dev.forgeunit import ForgeResults, UnitJob, offering, result_name, unit_request

_GIT = shutil.which('git') or 'git'
UNIT_HASH = 'ab' * 32
SMALL = Demand(1, 0.5, 600, {})
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
    job = UnitJob(UNIT_HASH, Ref('forge', 'k.tar.gz', 10, 'f' * 64), Demand(2, 6.0, 7200, {}), ('femm', 'windows'))
    assert UnitJob.of(job.paths()) == job
    declared = unit_request(job.paths())
    assert declared.argv == ('-m', 'dev_lab.dev.forgeunit', *job.paths())
    assert (declared.needs, declared.cpu, declared.mem_gb, declared.wall_h) == ({'femm', 'windows'}, 2.0, 6.0, 2.0)
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
    assert [a.name for a in forge.held] == [result_name(UNIT_HASH, first.record.result_hash)]
    two = ResultStore(tmp_path / 'two', tier)
    two.put(*stored(two, '42', 'h2'))
    assert len(forge.held) == 1  # an identical later post is dropped
    three = ResultStore(tmp_path / 'three', tier)
    with pytest.raises(Nondeterministic, match='stands'):
        three.put(*stored(three, '43', 'h3'))
    assert [(a.kind, a.about) for a in rang] == [(NONDETERMINISM, UNIT_HASH)]
    assert len(forge.held) == 1
    fetched = ResultStore(tmp_path / 'four', tier).get(UNIT_HASH)
    assert fetched is not None
    assert (fetched.output('out').read_text(encoding='utf-8'), fetched.record.host) == ('42', 'h1')


def test_a_sized_compute_unit_keeps_its_positive_fractional_memory() -> None:
    job = UnitJob(UNIT_HASH, Ref('forge', 'k.tar.gz', 10, 'f' * 64), Demand(1, 0.25, 60, {}), ())
    assert UnitJob.of(job.paths()) == job


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'pyproject.toml').write_text('[tool.lab_commons.hpc]\ninstall = "uv sync"\n', encoding='utf-8')
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
    folder = FolderStore(tmp_path / 'artefacts', 'r')
    published: list[tuple[str, str, tuple[str, ...]]] = []
    monkeypatch.setattr(forgeunit, 'load_config', lambda _root: Config())
    monkeypatch.setattr(forgeunit, 'store_for', lambda *_a, **_k: folder)
    monkeypatch.setattr(forgeunit, 'resolve', lambda entry, dest, **_k: folder.get(Ref.of(entry), dest))
    monkeypatch.setattr(forgeunit, 'load_schedule', lambda _root: SimpleNamespace(request_label='request'))

    def publish(_root: Path, _client: object, producer: str, sha: str, **kw: tuple[str, ...]) -> SimpleNamespace:
        published.append((producer, sha, kw['paths']))
        return SimpleNamespace(number=12)

    monkeypatch.setattr(forgeunit, 'publish', publish)
    (tmp_path / 'n.txt').write_text('5', encoding='utf-8')
    unit = Unit(Engine.ours('t.square', env), f'{__name__}:square', {'n': tmp_path / 'n.txt', 'k': 1}, ('out',), SMALL)
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

    code = forgeunit.main(list(paths), cwd=repo, client=client, store=tmp_path / 'serve')
    assert code == 0
    assert RAN_HERE == ['square']  # the serve host ran it, in-process, with the same executor
    again = box.run(Graph({'sq': unit}))['sq']
    assert again.state == 'cached'  # the result came back through the shared tier: nothing runs
    assert again.result.output('out').read_text(encoding='utf-8') == '36'
    assert RAN_HERE == ['square']


def test_a_bundle_that_is_not_its_jobs_unit_is_refused(
    tmp_path: Path, forge: Forge, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    env = environment_here(repo)
    folder = FolderStore(tmp_path / 'artefacts', 'r')
    published: list[tuple[str, ...]] = []
    monkeypatch.setattr(forgeunit, 'load_config', lambda _root: Config())
    monkeypatch.setattr(forgeunit, 'store_for', lambda *_a, **_k: folder)
    monkeypatch.setattr(forgeunit, 'resolve', lambda entry, dest, **_k: folder.get(Ref.of(entry), dest))
    monkeypatch.setattr(forgeunit, 'load_schedule', lambda _root: SimpleNamespace(request_label='request'))
    monkeypatch.setattr(
        forgeunit, 'publish', lambda *_a, **kw: published.append(kw['paths']) or SimpleNamespace(number=1)
    )
    (tmp_path / 'n.txt').write_text('5', encoding='utf-8')
    unit = Unit(Engine.ours('t.square', env), f'{__name__}:square', {'n': tmp_path / 'n.txt', 'k': 1}, ('out',), SMALL)
    offering(repo, forge.client(), env.sha)(unit, 'cd' * 32, {'n': tmp_path / 'n.txt'})
    code = forgeunit.main(list(published[0]), cwd=repo, client=forge.client(), store=tmp_path / 's')
    assert code == 2
    assert RAN_HERE == []
    with pytest.raises(ValueError, match='cannot run it'):
        offering(repo, forge.client(), 'e' * 40)(unit, 'cd' * 32, {'n': tmp_path / 'n.txt'})
