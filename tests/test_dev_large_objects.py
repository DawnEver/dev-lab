"""L3: the rclone large-object store a result's oversize files travel through, sha256-checked on arrival."""

from __future__ import annotations

import json
import shutil
import sys
import textwrap
from pathlib import Path

import pytest
from lab_commons.compute.store import (
    RECORD,
    REF_SUFFIX,
    ArrivalMismatch,
    Nondeterministic,
    Record,
    Result,
    ResultStore,
    Tombstone,
)

from dev_lab.dev import forgeunit
from dev_lab.dev.artefactstores import ArtefactRefused, RcloneObjects

UNIT = 'ab' + 'e' * 62
BIG = b'\x02' * 6000
SMALL = b'{"v":1}'

_FAKE_RCLONE = """
import json, os, shutil, sys
from pathlib import Path
base = Path(os.environ['FAKE_RCLONE_ROOT'])
args = [a for a in sys.argv[1:] if not a.startswith('-')]
flags = [a for a in sys.argv[1:] if a.startswith('--')]
with open(base / 'calls.jsonl', 'a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\\n')
def local(spec):
    remote, _, path = spec.partition(':')
    return base / remote / path
verb = args[0]
if verb == 'lsjson':
    root = local(args[1])
    if not root.is_dir():
        sys.stderr.write('directory not found'); sys.exit(3)
    print(json.dumps([{'Path': p.relative_to(root).as_posix(), 'Size': p.stat().st_size}
                      for p in sorted(root.rglob('*')) if p.is_file()]))
elif verb == 'copyto':
    src, dst = args[1], args[2]
    if ':' in src[2:]:
        Path(dst).parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(local(src), dst)
    else:
        target = local(dst)
        if '--immutable' in flags and target.exists():
            sys.stderr.write('immutable file modified'); sys.exit(1)
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(src, target)
else:
    sys.exit(2)
"""


@pytest.fixture
def cloud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[tuple[str, ...], Path]:
    """A fake rclone over a directory standing in for the remote."""
    root = tmp_path / 'cloud'
    root.mkdir()
    script = tmp_path / 'rclone.py'
    script.write_text(textwrap.dedent(_FAKE_RCLONE), encoding='utf-8')
    monkeypatch.setenv('FAKE_RCLONE_ROOT', str(root))
    return (sys.executable, str(script)), root


def _uploads(root: Path) -> int:
    calls = [json.loads(line) for line in (root / 'calls.jsonl').read_text().splitlines()]
    return sum(1 for call in calls if call[0] == 'copyto' and '--immutable' in call)


class Shared:
    """A shared tier in a directory with an upload limit: first post per generation wins."""

    def __init__(self, root: Path, max_bytes: int) -> None:
        """A tier under *root* that uploads nothing over *max_bytes*."""
        root.mkdir(parents=True, exist_ok=True)
        self.root, self.max_bytes = root, max_bytes

    def fetch(self, unit_hash: str, generation: int, dest: Path) -> Path | None:
        """The posted result, copied to *dest*."""
        held = self.root / f'{unit_hash}-g{generation}'
        if not held.is_dir():
            return None
        shutil.copytree(held, dest, dirs_exist_ok=True)
        return dest

    def post(self, result: Result, generation: int) -> None:
        """Keep *result*; a different one for the generation is nondeterminism."""
        held = self.root / f'{result.record.unit_hash}-g{generation}'
        if held.is_dir():
            if Record.read(held / RECORD).result_hash != result.record.result_hash:
                raise Nondeterministic(result.record.unit_hash)
            return
        shutil.copytree(result.path, held)

    def bury(self, tombstone: Tombstone) -> None:
        """No graves in these tests."""

    def graves(self, unit_hash: str) -> tuple[Tombstone, ...]:
        """None."""
        del unit_hash
        return ()


def _record() -> Record:
    return Record(UNIT, 'ours.solve', 'v', 'env', 'h1', 't0', 't1', '', local_only=False)


def test_a_file_goes_up_once_and_comes_back_whole(tmp_path: Path, cloud: tuple[tuple[str, ...], Path]) -> None:
    rclone, root = cloud
    objects = RcloneObjects('bucket:', 'results', rclone)
    big = tmp_path / 'big.bin'
    big.write_bytes(BIG)
    ref = objects.put(big)
    assert ref.bytes == len(BIG)
    assert ref.ref.startswith('results/')
    assert objects.put(big) == ref, 'the same bytes again is the object already there'
    assert _uploads(root) == 1
    got = objects.get(ref, tmp_path / 'back' / 'big.bin')
    assert got.read_bytes() == BIG


def test_a_tampered_object_is_a_miss_never_a_value(tmp_path: Path, cloud: tuple[tuple[str, ...], Path]) -> None:
    """PLANTED CONTROL: the remote hands back other bytes; nothing is left at the destination."""
    rclone, root = cloud
    objects = RcloneObjects('bucket:', 'results', rclone)
    big = tmp_path / 'big.bin'
    big.write_bytes(BIG)
    ref = objects.put(big)
    (root / 'bucket' / ref.ref).write_bytes(BIG + b'!')
    dest = tmp_path / 'back' / 'big.bin'
    with pytest.raises(ArrivalMismatch, match='arrived hashing'):
        objects.get(ref, dest)
    assert not dest.exists()


def test_a_scratch_prefix_is_refused_and_a_durable_one_is_not() -> None:
    """The bucket ages scratch/ out, so no durable object is ever keyed there; any other prefix is admitted."""
    with pytest.raises(ArtefactRefused, match='scratch'):
        RcloneObjects('bucket:', 'scratch/results')
    assert RcloneObjects('bucket:', 'vendor/scratch-free').prefix == 'vendor/scratch-free'


def test_an_oversize_result_travels_by_ref_and_arrives_whole(
    tmp_path: Path, cloud: tuple[tuple[str, ...], Path]
) -> None:
    rclone, root = cloud
    shared = Shared(tmp_path / 'shared', max_bytes=1000)
    objects = RcloneObjects('bucket:', 'results', rclone)
    one = ResultStore(tmp_path / 'one', shared, objects=objects)
    two = ResultStore(tmp_path / 'two', shared, objects=objects)
    one.put_files({'solved.ans': BIG, 'value.json': SMALL}, _record())
    posted = next(shared.root.glob(f'{UNIT}-g0'))
    assert (posted / f'solved.ans{REF_SUFFIX}').is_file()
    got = two.get(UNIT)
    assert isinstance(got, Result)
    assert got.files['solved.ans'].read_bytes() == BIG
    ref = json.loads((posted / f'solved.ans{REF_SUFFIX}').read_text())
    (root / 'bucket' / ref['ref']).write_bytes(b'tampered')
    three = ResultStore(tmp_path / 'three', shared, objects=objects)
    with pytest.raises(ArrivalMismatch):
        three.get(UNIT)
    assert not three.path(UNIT).exists()


def test_the_unit_runner_builds_a_large_object_store_only_when_a_remote_is_named() -> None:
    """PLANTED CONTROL: no remote means no store, so an oversize result stays local (TooLarge), never a guess."""
    built = forgeunit.large_objects('vendor-results:vendor-results')
    assert isinstance(built, RcloneObjects)
    assert (built.remote, built.prefix) == ('vendor-results:vendor-results', forgeunit.OBJECTS_PREFIX)
    assert forgeunit.large_objects(None) is None
    with pytest.raises(ArtefactRefused, match='scratch'):
        forgeunit.large_objects('vendor-results:vendor-results', 'scratch')
