"""L3: the rclone large-object store a result's oversize files travel through, sha256-checked on arrival."""

from __future__ import annotations

import json
import shutil
import subprocess
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
from lab_commons.config import CONFIG_ENV
from lab_commons.storage import Storage, declared

from dev_lab.dev import forgeunit
from dev_lab.dev.artefactstores import ArtefactRefused, RcloneStore
from dev_lab.dev.largeobjects import OBJECTS_PREFIX, RcloneObjects, StoreUnreached, run_objects

UNIT = 'ab' + 'e' * 62
BIG = b'\x02' * 6000
SMALL = b'{"v":1}'

_FAKE_RCLONE = """
import json, os, shutil, sys
from pathlib import Path
base = Path(os.environ['FAKE_RCLONE_ROOT'])
argv = sys.argv[1:]
at = next(i for i, a in enumerate(argv) if a in {'lsd', 'lsjson', 'copyto'})
args = [a for a in argv[at:] if not a.startswith('-')]
flags = [a for a in argv if a.startswith('--')]
with open(base / 'calls.jsonl', 'a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\\n')
def local(spec):
    remote, _, path = spec.partition(':')
    target = (base / remote / path).resolve()
    if not target.is_relative_to(base.resolve()):  # 'bucket:/results' joins to C:/results: never off the fake disk
        sys.stderr.write(f'fake rclone: {spec} resolves outside the fake remote root'); sys.exit(5)
    return target
verb = args[0]
if verb == 'lsd':
    if not (base / args[1].rstrip(':')).is_dir():
        sys.stderr.write('ERROR : AccessDenied'); sys.exit(1)
    print('          -1 2026-11-23 00:00:00        -1 bucket')
elif verb == 'lsjson':
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


@pytest.mark.parametrize(('spec', 'refused'), [('bucket:/results/d6/x', True), ('bucket:results/d6/x', False)])
def test_the_fake_remote_never_writes_off_its_root(
    tmp_path: Path, cloud: tuple[tuple[str, ...], Path], spec: str, *, refused: bool
) -> None:
    """A rooted remote path joined onto the fake's dir is C:/results/...: refused, so no test leaks to the drive root.

    PLANTED CONTROL: the relative spelling of the same object lands under the fake root.
    """
    rclone, root = cloud
    source = tmp_path / 'one.bin'
    source.write_bytes(b'1')
    run = subprocess.run([*rclone, 'copyto', str(source), spec], capture_output=True, text=True, check=False)
    assert (run.returncode == 5) is refused, run.stderr
    assert (root / 'bucket' / 'results' / 'd6' / 'x').is_file() is not refused


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


def _family(tmp_path: Path, *, runs: str | None = 'bucket:vault', placed: bool = True) -> Storage:
    """A family declaring the remote ``bucket`` (every machine reaching it) and, unless ``None``, its run store."""
    secret = tmp_path / 'secrets' / 'bucket'
    if placed:
        secret.parent.mkdir(parents=True, exist_ok=True)
        secret.write_text('secret_access_key = "s3cr3t"\n', encoding='utf-8')
    remote = {'type': 's3', 'secret_keys': ['secret_access_key'], 'reach': {'credentials_file': str(secret)}}
    return declared({}, {'storage': {'remotes': {'bucket': remote}, **({'runs': runs} if runs else {})}})


def _checkout(tmp_path: Path) -> Path:
    tree = tmp_path / 'repo'
    tree.mkdir()
    return tree


def test_a_declared_reached_run_store_puts_and_gets_sha256_checked(
    tmp_path: Path, cloud: tuple[tuple[str, ...], Path]
) -> None:
    """Declared and reached: the door proves the listing, then objects go up and come back re-hashed."""
    rclone, root = cloud
    (root / 'bucket').mkdir()
    conf = tmp_path / 'conf' / 'rclone.conf'
    objects = run_objects(_checkout(tmp_path), declared=_family(tmp_path), rclone=rclone, to=conf)
    assert objects is not None
    assert (objects.remote, objects.prefix) == ('bucket:vault', OBJECTS_PREFIX)
    assert objects.rclone[-1] == f'--config={conf}', 'every call reads the rendered config, never a default'
    big = tmp_path / 'big.bin'
    big.write_bytes(BIG)
    ref = objects.put(big)
    assert objects.get(ref, tmp_path / 'back.bin').read_bytes() == BIG
    (root / 'bucket' / 'vault' / ref.ref).write_bytes(b'tampered')
    with pytest.raises(ArrivalMismatch):
        objects.get(ref, tmp_path / 'again.bin')


@pytest.mark.parametrize('placed', ['yes', ''], ids=['listing-refused', 'no-secret-placed'])
def test_a_declared_unreached_run_store_is_refused_by_name_with_its_door(
    tmp_path: Path, cloud: tuple[tuple[str, ...], Path], placed: str
) -> None:
    """PLANTED CONTROL: declared but not reached is refused naming the store and its door, never a local fallback."""
    rclone, _root = cloud  # no bucket directory: the listing is refused
    door = r"store 'bucket:vault'.*secretplace enter --remote bucket.*distribute --remote bucket.*storage check bucket"
    with pytest.raises(StoreUnreached, match=door):
        run_objects(_checkout(tmp_path), declared=_family(tmp_path, placed=bool(placed)), rclone=rclone,
                    to=tmp_path / 'c.conf')  # fmt: skip


def test_an_undeclared_run_store_is_none_so_an_oversize_result_stays_local(tmp_path: Path) -> None:
    """PLANTED CONTROL: no ``[storage] runs`` -- no store, nothing probed (an oversize result is TooLarge)."""
    assert run_objects(_checkout(tmp_path), declared=_family(tmp_path, runs=None), rclone=('absent',)) is None


def test_the_unit_runner_refuses_a_declared_unreached_store_before_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The compute-unit path reads the family declaration with no flag, and an unreached store refuses the Job (2)."""
    machine = tmp_path / 'machine.toml'
    machine.write_text(
        "[storage]\nruns = 'bucket:vault'\n[storage.remotes.bucket]\ntype = 's3'\n"
        "secret_keys = ['secret_access_key']\n[storage.remotes.bucket.reach]\n"
        f"credentials_file = '{(tmp_path / 'none').as_posix()}'\n",
        encoding='utf-8',
    )
    monkeypatch.setenv(CONFIG_ENV, str(machine))
    assert forgeunit.main(['unit=x'], cwd=_checkout(tmp_path), client=object()) == 2  # type: ignore[arg-type]


def test_a_bare_remote_takes_the_key_relative_never_from_the_root() -> None:
    assert RcloneStore('bucket:', 'r').at('results/d6/x') == 'bucket:results/d6/x', 'bucket:/results is the drive root'
    assert RcloneStore('drive:base/', 'r').at('k') == 'drive:base/k'
