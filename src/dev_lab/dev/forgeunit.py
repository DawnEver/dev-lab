"""THE FORGE TIER OF THE COMPUTE SYSTEM -- results every host reads, and a unit OFFERED as a Job (D16, D17, D18).

SHARED RESULTS (:class:`ForgeResults`, the :class:`~lab_commons.compute.store.SharedTier` of a
:class:`~lab_commons.compute.store.ResultStore`). A result is one archive attached to the records home
(:func:`dev_lab.dev.forgerecords.attach`, so the upload goes through the durable outbox and is idempotent by
name), named ``unit-<unit hash>-g<generation>-<result hash>.tar.gz``: the name alone says which unit, which
generation and which outputs, so the FIRST attachment for a unit hash and generation is its result, an
identical later post is a no-op, and a differing one sounds the ``nondeterminism`` alarm
(:mod:`dev_lab.dev.forgealarm`) and raises -- the first stands. An archive over :data:`MAX_UPLOAD_BYTES` (the
forge attachment limit, :data:`~dev_lab.dev.artefactstores.ATTACHMENT_LIMIT_MB`) is refused with
:class:`~lab_commons.compute.store.TooLarge`, never attached. A TOMBSTONE closing a generation is a small
``grave-<unit hash>-<generation>.json`` attachment through the same outbox; every host reads it (``graves``).

A UNIT OFFERED (:func:`offering`, the ``offer`` a :class:`~lab_commons.compute.execute.LocalExecutor` calls when
``--where`` lets a unit this box cannot run go elsewhere). Its BUNDLE -- ``unit.json`` (engine, version,
environment, entry, parameters, outputs, demand) plus every input file under ``files/`` -- goes up through the
artefact store (:func:`dev_lab.dev.artefacts.store_for`), and the Job is a request for the built-in
producer :data:`~dev_lab.dev.forgerequest.UNIT` (:func:`dev_lab.dev.forgepublish.publish`), its
``paths`` naming the unit hash, the bundle's ref, its size and its needs (:class:`UnitJob`).

THE SERVE SIDE IS THE SAME LOCAL EXECUTOR (:func:`main`, the producer's argv): a serve host claims the Job as it
claims any request, and in the tree at the Job's sha fetches the bundle, refuses one whose unit hash is not the
Job's, runs the unit with :class:`~lab_commons.compute.execute.LocalExecutor` against a store backed by
:class:`ForgeResults` -- which uploads the result -- and exits 0 when the unit has a result.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from lab_commons.box.demand import CPU, MEM_GB, cores, seats
from lab_commons.compute.execute import CACHED, RAN, LocalExecutor, Offer, presence_check
from lab_commons.compute.graph import Graph
from lab_commons.compute.model import Demand
from lab_commons.compute.presence import cached
from lab_commons.compute.store import Nondeterministic, Result, ResultStore, Tombstone, TooLarge
from lab_commons.compute.unit import Engine, Environment, Unit, environment_here
from lab_commons.config import config_path
from lab_commons.log import emit
from lab_commons.temp import TEMP_PREFIX

from dev_lab.dev.artefactpack import pack, unpack
from dev_lab.dev.artefacts import load_config, resolve, store_for
from dev_lab.dev.artefactstores import ARCHIVE, ATTACHMENT_LIMIT_MB, MB, Ref, run_id
from dev_lab.dev.forgealarm import NONDETERMINISM, Alarm, sound
from dev_lab.dev.forgepublish import publish
from dev_lab.dev.forgerecordkeep import UNIT_RESULT
from dev_lab.dev.forgerecords import attach, listing
from dev_lab.dev.forgerequest import UNIT, Declared, UndeclaredRequest
from dev_lab.dev.forgeschedule import load_schedule
from dev_lab.dev.forgework import Client, client_for

__all__ = [
    'GRAVE',
    'MAX_UPLOAD_BYTES',
    'ForgeResults',
    'UnitJob',
    'grave_name',
    'main',
    'offering',
    'offering_for',
    'result_name',
    'unit_request',
]

_HASH: Final = r'[0-9a-f]{64}'
#: The bundle's manifest, beside ``files/``.
MANIFEST: Final = 'unit.json'
#: The largest result archive the shared tier uploads: the forge's attachment limit, declared once there.
MAX_UPLOAD_BYTES: Final = ATTACHMENT_LIMIT_MB * MB
#: A tombstone attachment (:func:`grave_name`).
GRAVE: Final = re.compile(r'^grave-(?P<unit>[0-9a-f]{64})-(?P<generation>\d+)\.json$')


def result_name(unit_hash: str, generation: int, result_hash: str) -> str:
    """The attachment name of a result: the unit, its generation and its outputs."""
    return f'unit-{unit_hash}-g{generation}-{result_hash}{ARCHIVE}'


def grave_name(unit_hash: str, generation: int) -> str:
    """The attachment name of the tombstone closing *generation* of *unit_hash*."""
    return f'grave-{unit_hash}-{generation}.json'


@dataclass(frozen=True)
class ForgeResults:
    """The shared tier on *client*'s forge (the module docstring)."""

    client: Client
    alarm: Callable[[Alarm], object] = sound
    max_bytes: int | None = MAX_UPLOAD_BYTES

    def _posted(self, unit_hash: str, generation: int) -> list[tuple[str, str]]:
        """``(download url, result hash)`` of each result posted for *unit_hash*'s *generation*, first first."""
        found = ((item, UNIT_RESULT.match(item.name)) for item in listing(self.client))
        return [
            (item.url, m['result'])
            for item, m in found
            if m and m['unit'] == unit_hash and int(m['generation']) == generation and item.name.endswith(ARCHIVE)
        ]

    def fetch(self, unit_hash: str, generation: int, dest: Path) -> Path | None:
        """*generation*'s first posted result, unpacked into *dest*; ``None`` when none is posted."""
        posted = self._posted(unit_hash, generation)
        if not posted:
            return None
        with tempfile.TemporaryDirectory(prefix=TEMP_PREFIX) as scratch:
            archive = Path(scratch) / 'result'
            archive.write_bytes(self.client.download(posted[0][0]))
            return unpack(archive, dest)

    def post(self, result: Result, generation: int) -> None:
        """Attach *result* as *generation*'s unless one is there; a differing one alarms and raises.

        Raises:
            Nondeterministic: *generation* already holds a different result.
            TooLarge: the archive is over :attr:`max_bytes`; nothing is attached.

        """
        record = result.record
        posted = self._posted(record.unit_hash, generation)
        if posted:
            if posted[0][1] == record.result_hash:
                return
            alarm = Alarm(
                NONDETERMINISM,
                self.client.forge.repo,
                f'unit {record.unit_hash[:12]} gave two different results',
                f'{record.engine} {record.version}: {record.host} computed {record.result_hash[:16]}; the first '
                f'posted, {posted[0][1][:16]}, stands. A unit must be deterministic: find the unread input.',
                about=record.unit_hash,
            )
            self.alarm(alarm)
            raise Nondeterministic(alarm.body)
        with tempfile.TemporaryDirectory(prefix=TEMP_PREFIX) as scratch:
            files = sorted(p for p in result.path.rglob('*') if p.is_file())
            name = result_name(record.unit_hash, generation, record.result_hash)
            archive = pack(result.path, files, Path(scratch) / name).path
            size = archive.stat().st_size
            if self.max_bytes is not None and size > self.max_bytes:
                raise TooLarge(result, size, self.max_bytes)
            attach(self.client, archive)

    def _graves(self, unit_hash: str) -> dict[int, str]:
        """The download url of each tombstone posted for *unit_hash*, by generation (the first posted wins)."""
        found: dict[int, str] = {}
        for item in listing(self.client):
            m = GRAVE.match(item.name)
            if m and m['unit'] == unit_hash:
                found.setdefault(int(m['generation']), item.url)
        return found

    def bury(self, tombstone: Tombstone) -> None:
        """Attach *tombstone*; one already posted for its generation is a no-op."""
        if tombstone.generation in self._graves(tombstone.unit_hash):
            return
        with tempfile.TemporaryDirectory(prefix=TEMP_PREFIX) as scratch:
            grave = Path(scratch) / grave_name(tombstone.unit_hash, tombstone.generation)
            grave.write_bytes(tombstone.to_bytes())
            attach(self.client, grave)

    def graves(self, unit_hash: str) -> tuple[Tombstone, ...]:
        """Every tombstone posted for *unit_hash*, by generation."""
        return tuple(
            Tombstone(**json.loads(self.client.download(url))) for _, url in sorted(self._graves(unit_hash).items())
        )


@dataclass(frozen=True)
class UnitJob:
    """What a unit Job's request carries: the unit hash, its bundle's ref, its size, its wall and its needs."""

    unit_hash: str
    bundle: Ref
    demand: Demand
    wall_s: int
    needs: tuple[str, ...]

    def paths(self) -> tuple[str, ...]:
        """The request ``paths`` spelling: ``key=value`` tokens, no quote, no space."""
        ref, d = self.bundle, self.demand
        return (
            f'unit={self.unit_hash}',
            f'bundle={ref.backend}|{ref.key}|{ref.bytes}|{ref.sha256}',
            f'size={cores(d)}|{d[MEM_GB]}|{self.wall_s}',
            f'needs={"+".join(self.needs)}',
        )

    @classmethod
    def of(cls, paths: Sequence[str]) -> UnitJob:
        """The inverse of :meth:`paths`.

        Raises:
            UndeclaredRequest: a token missing, unreadable, or a size that is not positive.

        """
        tokens = dict(one.partition('=')[::2] for one in paths)
        spelling = f'producer {UNIT!r} takes paths unit=, bundle=, size=, needs= ({list(paths)!r})'
        if not re.fullmatch(_HASH, tokens.get('unit', '')):
            msg = f'{spelling}: no unit hash'
            raise UndeclaredRequest(msg)
        try:
            backend, key, size, sha256 = tokens['bundle'].split('|')
            cpu, mem_gb, wall_s = tokens['size'].split('|')
            needs = tuple(filter(None, tokens['needs'].split('+')))
            job = cls(
                tokens['unit'],
                Ref(backend, key, int(size), sha256),
                Demand({CPU: int(cpu), MEM_GB: float(mem_gb)}),
                int(wall_s),
                needs,
            )
        except (KeyError, ValueError) as why:
            msg = f'{spelling}: {why}'
            raise UndeclaredRequest(msg) from None
        if cores(job.demand) <= 0:
            msg = f'{spelling}: a compute unit requires positive cpu, not a coreless resource claim'
            raise UndeclaredRequest(msg)
        return job


def unit_request(paths: Sequence[str]) -> Declared:
    """The built-in :data:`~dev_lab.dev.forgerequest.UNIT` producer for a Job's *paths*: run this module."""
    job = UnitJob.of(paths)
    return Declared(
        UNIT,
        ('-m', __name__, *paths),
        frozenset(job.needs),
        float(cores(job.demand)),
        job.demand[MEM_GB],
        job.wall_s / 3600,
    )


def _manifest(unit: Unit) -> dict[str, Any]:
    engine = unit.engine
    return {
        'engine': {
            'name': engine.name,
            'version': engine.version,
            'environment': asdict(engine.environment) if engine.environment else None,
        },
        'entry': unit.entry,
        'params': dict(unit.params),
        'files': sorted(set(unit.inputs) - set(unit.params)),
        'outputs': list(unit.outputs),
        'demand': dict(unit.demand),
        'wall_s': unit.wall_s,
    }


def _unit_of(tree: Path) -> tuple[Unit, dict[str, Path]]:
    raw = json.loads((tree / MANIFEST).read_text(encoding='utf-8'))
    env = raw['engine']['environment']
    engine = Engine(raw['engine']['name'], raw['engine']['version'], Environment(**env) if env else None)
    files = {name: tree / 'files' / name for name in raw['files']}
    unit = Unit(
        engine, raw['entry'], {**raw['params'], **files}, tuple(raw['outputs']), Demand(raw['demand']), raw['wall_s']
    )
    return unit, files


def offering(
    root: Path,
    client: Client,
    sha: str,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Offer:
    """The ``offer`` of a :class:`~lab_commons.compute.execute.LocalExecutor`: bundle up, publish the Job at *sha*."""

    def offer(unit: Unit, unit_hash: str, files: Mapping[str, Path]) -> str:
        env = unit.engine.environment
        if env is not None and env.sha != sha:
            msg = f'unit {unit_hash[:12]} runs our code at {env.sha[:12]}; a Job at {sha[:12]} cannot run it'
            raise ValueError(msg)
        with tempfile.TemporaryDirectory(prefix=TEMP_PREFIX) as scratch:
            tree = Path(scratch) / 'bundle'
            (tree / 'files').mkdir(parents=True)
            (tree / MANIFEST).write_text(json.dumps(_manifest(unit), sort_keys=True), encoding='utf-8')
            for name, path in files.items():
                (shutil.copytree if path.is_dir() else shutil.copyfile)(path, tree / 'files' / name)
            bundle = pack(tree, sorted(p for p in tree.rglob('*') if p.is_file()), Path(scratch) / f'b{ARCHIVE}').path
            store = store_for(load_config(root), client, client.forge.repo, size=bundle.stat().st_size)
            ref = store.put(run_id(sha, UNIT, unit_hash[:16], now()), bundle)
        vendor = () if env is not None else (unit.engine.name,)
        job = UnitJob(unit_hash, ref, unit.demand, unit.wall_s, tuple(sorted({*vendor, *seats(unit.demand)})))
        issue = publish(root, client, UNIT, sha, label=load_schedule(root).request_label, paths=job.paths())
        return f'#{issue.number}'

    return offer


def offering_for(repo: Path, sha: str) -> Offer:
    """The ``offer`` for units of *repo* at *sha*, with this repo's forge client built here.

    THE ONE CALL A CONSUMER NEEDS. A product reaches it through an entry point
    (``acme.compute.offering = "dev_lab.dev.forgeunit:offering_for"``) and never imports the dev kit, so it
    must not know how a forge client is made: two names in its seam (``client_for`` and ``offering``) were two
    signatures to keep in step across repos (user ruling 2026-11-05).
    """
    return offering(repo, client_for(repo), sha)


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    client: Client | None = None,
    store: Path | None = None,
) -> int:
    """Run one offered unit here; exit 0 it has a result, 1 it failed, 2 the Job is refused (nothing ran)."""
    parser = argparse.ArgumentParser(prog=f'python -m {__name__}', description=__doc__.splitlines()[0])
    parser.add_argument('paths', nargs='+', help='the Job request paths: unit=, bundle=, size=, needs=')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    built = client_for(root) if client is None else client
    units = config_path().parent / 'units' if store is None else store
    try:
        job = UnitJob.of(args.paths)
    except UndeclaredRequest as refused:
        emit(f'[unit] refused: {refused}', err=True)
        return 2
    with tempfile.TemporaryDirectory(prefix=TEMP_PREFIX) as scratch:
        archive = resolve(job.bundle.manifest(), Path(scratch), client=built, repo=built.forge.repo)
        unit, files = _unit_of(unpack(archive, Path(scratch) / 'bundle'))
        if unit.unit_hash(files) != job.unit_hash:
            emit(f'[unit] refused: the bundle is not unit {job.unit_hash[:12]}', err=True)
            return 2
        here = environment_here(root) if unit.engine.environment else None
        executor = LocalExecutor(
            ResultStore(units, ForgeResults(built)),
            units / 'journal',
            present=presence_check(here, cached()),
        )
        outcome = executor.run(Graph({job.unit_hash[:12]: unit}))[job.unit_hash[:12]]
    emit(f'[unit] {job.unit_hash[:12]}: {outcome.state}{" -- " + outcome.why if outcome.why else ""}')
    return 0 if outcome.state in {RAN, CACHED} else 1


if __name__ == '__main__':
    sys.exit(main())
