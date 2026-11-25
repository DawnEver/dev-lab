"""L3: ``storage.run_objects`` -- the family's run store, proven reached, as a :mod:`lab_commons.objects` store."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest
from lab_commons.compute.store import ArrivalMismatch
from lab_commons.config import CONFIG_ENV
from lab_commons.objects import OBJECTS_PREFIX
from lab_commons.storage import Storage, declared

from dev_lab.dev import forgeunit
from dev_lab.dev.storage import StoreUnreached, run_objects

BIG = b'\x02' * 6000

#: A stand-in rclone over a directory: ``lsd`` is the reach proof, the rest is the object store's traffic.
_FAKE_RCLONE = """
import json, os, shutil, sys
from pathlib import Path
base = Path(os.environ['FAKE_RCLONE_ROOT'])
argv = sys.argv[1:]
at = next(i for i, a in enumerate(argv) if a in {'lsd', 'lsjson', 'copyto', 'deletefile'})
args = [a for a in argv[at:] if not a.startswith('-')]
def local(spec):
    remote, _, path = spec.partition(':')
    target = (base / remote / path).resolve()
    if not target.is_relative_to(base.resolve()):
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
        target = local(dst); target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(src, target)
elif verb == 'deletefile':
    local(args[1]).unlink()
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
