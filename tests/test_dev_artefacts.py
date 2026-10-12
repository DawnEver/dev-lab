"""THE ARTEFACT STORE: declared outputs only, write-once, sha-verified, cleaned by age then by cap.

Every backend is exercised against temp dirs: ``folder`` directly, ``rclone`` through a FAKE rclone (a
Python script mapping ``remote:path`` onto a temp dir), ``zstd`` through a fake that copies stdin. No
test touches a real remote, a real rclone config, or any synced folder.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from lab_commons.dev import artefacts
from lab_commons.dev.artefacts import (
    ArtefactRefused,
    Config,
    FolderStore,
    ForgeStore,
    MissingOutput,
    RcloneStore,
    Ref,
)
from lab_commons.dev.forgework import GITEA, Client

SHA = 'a' * 40
WHEN = datetime(2026, 10, 11, 9, 30, 5, tzinfo=UTC)
RUN = artefacts.run_id(SHA, 'linux', WHEN)

_FAKE_ZSTD = """
import shutil, sys
out = sys.argv[sys.argv.index('-o') + 1]
with open(out, 'wb') as f:
    shutil.copyfileobj(sys.stdin.buffer, f)
"""

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
    items = [{'Path': p.relative_to(root).as_posix(), 'Size': p.stat().st_size}
             for p in sorted(root.rglob('*')) if p.is_file()]
    print(json.dumps(items))
elif verb == 'copyto':
    src, dst = args[1], args[2]
    if ':' in src[2:]:
        Path(dst).parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(local(src), dst)
    else:
        target = local(dst)
        if '--immutable' in flags and target.exists():
            sys.stderr.write('immutable file modified'); sys.exit(1)
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(src, target)
elif verb == 'cat':
    sys.stdout.write(local(args[1]).read_text())
elif verb == 'deletefile':
    local(args[1]).unlink()
elif verb == 'rmdirs':
    root = local(args[1])
    for d in sorted((p for p in root.rglob('*') if p.is_dir()), key=lambda p: -len(p.parts)):
        if not any(d.iterdir()):
            d.rmdir()
else:
    sys.exit(2)
"""


def _script(where: Path, name: str, body: str) -> tuple[str, ...]:
    path = where / f'{name}.py'
    path.write_text(textwrap.dedent(body), encoding='utf-8')
    return (sys.executable, str(path))


@pytest.fixture
def zstd(tmp_path: Path) -> tuple[str, ...]:
    tools = tmp_path / 'tools'
    tools.mkdir(exist_ok=True)
    return _script(tools, 'zstd', _FAKE_ZSTD)


@pytest.fixture
def rclone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[tuple[str, ...], Path]:
    tools, cloud = tmp_path / 'tools', tmp_path / 'cloud'
    tools.mkdir(exist_ok=True)
    cloud.mkdir()
    monkeypatch.setenv('FAKE_RCLONE_ROOT', str(cloud))
    return _script(tools, 'rclone', _FAKE_RCLONE), cloud


def _archive(tmp_path: Path, content: bytes = b'payload') -> Path:
    path = tmp_path / 'in.tar.zst'
    path.write_bytes(content)
    return path


# --- names and layout -------------------------------------------------------------------------


def test_the_run_id_is_sha12_platform_and_utc_stamp_and_its_day_folder_follows() -> None:
    assert RUN == 'aaaaaaaaaaaa-linux-20261011T093005Z'
    assert artefacts.object_key('lab', RUN) == 'lab/2026/10/11/aaaaaaaaaaaa-linux-20261011T093005Z'


@pytest.mark.parametrize(
    'bad',
    ['a:b', 'a*b', 'a?b', 'a"b', 'a<b', 'a>b', 'a|b', 'a\\b', 'trail.', 'trail ', 'caf\u00e9', '', 'x' * 401],
)
def test_a_name_onedrive_cannot_hold_is_refused(bad: str) -> None:
    with pytest.raises(ArtefactRefused):
        artefacts.check_key(f'lab/{bad}')


def test_planted_control_a_short_ascii_key_is_accepted() -> None:
    artefacts.check_key('lab/2026/10/11/aaaaaaaaaaaa-linux-20261011T093005Z.tar.zst')


# --- declared outputs -------------------------------------------------------------------------


def test_only_declared_outputs_are_collected_and_a_missing_one_fails_loudly(tmp_path: Path) -> None:
    (tmp_path / 'out').mkdir()
    (tmp_path / 'out' / 'field.h5').write_bytes(b'f')
    (tmp_path / 'out' / 'undeclared.log').write_bytes(b'u')
    (tmp_path / 'summary.json').write_bytes(b's')
    found = artefacts.collect(tmp_path, ['out/*.h5', 'summary.json'])
    assert [p.relative_to(tmp_path).as_posix() for p in found] == ['out/field.h5', 'summary.json']
    with pytest.raises(MissingOutput, match=r'out/\*\.vtu.*nope\.txt'):
        artefacts.collect(tmp_path, ['out/*.h5', 'out/*.vtu', 'nope.txt'])


@pytest.mark.parametrize('escape', ['../secret', '/etc/passwd', 'C:/x'])
def test_an_output_outside_the_work_tree_is_refused(tmp_path: Path, escape: str) -> None:
    with pytest.raises(ArtefactRefused):
        artefacts.collect(tmp_path, [escape])


def test_nothing_declared_packs_nothing(tmp_path: Path) -> None:
    (tmp_path / 'big.bin').write_bytes(b'x')
    assert artefacts.collect(tmp_path, []) == []


def test_pack_writes_one_tar_of_exactly_the_declared_files(tmp_path: Path, zstd: tuple[str, ...]) -> None:
    tree = tmp_path / 'tree'
    (tree / 'out').mkdir(parents=True)
    (tree / 'out' / 'a.txt').write_bytes(b'A')
    (tree / 'skip.txt').write_bytes(b'S')
    dest = artefacts.pack(tree, artefacts.collect(tree, ['out/a.txt']), tmp_path / 'x.tar.zst', zstd=zstd)
    with tarfile.open(fileobj=io.BytesIO(dest.read_bytes())) as tar:  # the fake zstd stores the tar as is
        assert tar.getnames() == ['out/a.txt']


# --- config is data ---------------------------------------------------------------------------


def _pyproject(root: Path, table: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'pyproject.toml').write_text(table, encoding='utf-8')
    return root


def test_the_config_table_is_read_with_its_defaults(tmp_path: Path) -> None:
    root = _pyproject(
        tmp_path / 'r',
        '[tool.lab_commons.artefacts]\nbackend = "rclone"\nremote = "onedrive-uon:Sync/hpc-results"\ncap_gb = 20\n',
    )
    assert artefacts.load_config(root) == Config('rclone', 'onedrive-uon:Sync/hpc-results', 100, 3, 20.0)


def test_no_table_means_forge_only(tmp_path: Path) -> None:
    assert artefacts.load_config(_pyproject(tmp_path / 'r', '')) == Config()


@pytest.mark.parametrize(
    'table',
    [
        'backend = "s3"',
        'backend = "rclone"',  # no remote
        'backend = "forge"\nthreshold_mb = 200',  # above the attachment limit
        'colour = "red"',
    ],
)
def test_a_bad_config_is_refused_naming_the_key(tmp_path: Path, table: str) -> None:
    with pytest.raises(ArtefactRefused, match=r'tool\.lab_commons\.artefacts'):
        artefacts.load_config(_pyproject(tmp_path / 'r', f'[tool.lab_commons.artefacts]\n{table}\n'))


def test_the_reader_folder_comes_from_machine_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / 'home' / 'config.toml'
    config.parent.mkdir()
    config.write_text(f'[artefacts]\nfolder = "{(tmp_path / "mirror").as_posix()}"\n', encoding='utf-8')
    monkeypatch.setenv('LAB_COMMONS_CONFIG', str(config))
    store = artefacts.reader('lab')
    assert isinstance(store, FolderStore)
    assert store.root == tmp_path / 'mirror'


# --- the backends: write-once, sha-verified, listed, deleted -------------------------------------


def _stores(tmp_path: Path, rclone: tuple[tuple[str, ...], Path]) -> list[artefacts.ArtefactStore]:
    return [FolderStore(tmp_path / 'folder', 'lab'), RcloneStore('drive:hpc', 'lab', rclone=rclone[0])]


def test_each_backend_puts_gets_lists_and_deletes(tmp_path: Path, rclone) -> None:
    for store in _stores(tmp_path, rclone):
        ref = store.put(RUN, _archive(tmp_path))
        assert ref == Ref(store.backend, f'lab/2026/10/11/{RUN}.tar.zst', 7, hashlib.sha256(b'payload').hexdigest())
        got = store.get(ref, tmp_path / 'back' / store.backend)
        assert got.read_bytes() == b'payload'
        assert store.list(None) == (ref,)
        store.delete(ref)
        assert store.list(None) == ()


def test_write_once_an_existing_object_is_never_overwritten(tmp_path: Path, rclone) -> None:
    for store in _stores(tmp_path, rclone):
        ref = store.put(RUN, _archive(tmp_path))
        with pytest.raises(ArtefactRefused, match='write-once'):
            store.put(RUN, _archive(tmp_path, b'different'))
        assert store.get(ref, tmp_path / 'g' / store.backend).read_bytes() == b'payload'
        assert store.put(RUN, _archive(tmp_path)) == ref, 'the same bytes again is the landed object, not a write'


def test_get_refuses_bytes_whose_sha256_does_not_match(tmp_path: Path) -> None:
    store = FolderStore(tmp_path / 'folder', 'lab')
    ref = store.put(RUN, _archive(tmp_path))
    (tmp_path / 'folder' / ref.key).write_bytes(b'tampered')
    with pytest.raises(ArtefactRefused, match='sha256'):
        store.get(ref, tmp_path / 'dest')
    assert not (tmp_path / 'dest').exists(), 'a mismatching download is never left behind'


def test_rclone_is_driven_by_argv_lists_and_uploads_immutably(tmp_path: Path, rclone) -> None:
    argv, cloud = rclone
    RcloneStore('drive:hpc', 'lab', rclone=argv).put(RUN, _archive(tmp_path))
    calls = [json.loads(line) for line in (cloud / 'calls.jsonl').read_text().splitlines()]
    uploads = [c for c in calls if c[0] == 'copyto']
    assert uploads, calls
    assert all('--immutable' in c for c in uploads)
    assert (cloud / 'drive' / 'hpc' / 'lab' / '2026' / '10' / '11' / f'{RUN}.tar.zst').is_file()


def test_list_older_than_reads_the_day_folder(tmp_path: Path) -> None:
    store = FolderStore(tmp_path / 'f', 'lab')
    old = store.put(artefacts.run_id(SHA, 'linux', WHEN - timedelta(days=5)), _archive(tmp_path))
    store.put(RUN, _archive(tmp_path))
    assert store.list(WHEN - timedelta(days=3)) == (old,)


# --- credentials --------------------------------------------------------------------------------


def test_an_rclone_config_readable_by_others_is_refused(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same file at mode 600 is accepted."""
    conf = tmp_path / 'rclone.conf'
    conf.write_text('[drive]\n', encoding='utf-8')
    with pytest.raises(ArtefactRefused, match='600'):
        artefacts.check_rclone_config(conf, repo=tmp_path / 'repo', mode_of=lambda _p: 0o644)
    artefacts.check_rclone_config(conf, repo=tmp_path / 'repo', mode_of=lambda _p: 0o600)


def test_an_rclone_config_inside_the_repo_is_refused(tmp_path: Path) -> None:
    conf = tmp_path / 'repo' / 'rclone.conf'
    conf.parent.mkdir()
    conf.write_text('[drive]\n', encoding='utf-8')
    conf.chmod(0o600)
    with pytest.raises(ArtefactRefused, match='never in a repo'):
        artefacts.check_rclone_config(conf, repo=tmp_path / 'repo')


# --- cleanup ------------------------------------------------------------------------------------


def _put_at(store: FolderStore, tmp_path: Path, when: datetime, sha: str = SHA, size: int = 10) -> Ref:
    return store.put(artefacts.run_id(sha, 'linux', when), _archive(tmp_path, b'x' * size))


def test_cleanup_drops_old_days_keeps_pins_then_trims_oldest_to_the_cap(tmp_path: Path) -> None:
    store = FolderStore(tmp_path / 'f', 'lab')
    pinned = _put_at(store, tmp_path, WHEN - timedelta(days=9), sha='b' * 40)
    old = _put_at(store, tmp_path, WHEN - timedelta(days=4))
    oldest_recent = _put_at(store, tmp_path, WHEN - timedelta(days=2))
    newest = _put_at(store, tmp_path, WHEN)
    gone = artefacts.clean(store, now=WHEN, retain_days=3, cap_bytes=25, pinned=frozenset({'b' * 12}))
    assert set(gone) == {old, oldest_recent}
    assert set(store.list(None)) == {pinned, newest}
    assert not (tmp_path / 'f' / 'lab' / '2026' / '10' / '07').exists(), 'an emptied day folder is removed'


def test_planted_control_nothing_young_and_under_the_cap_is_deleted(tmp_path: Path) -> None:
    store = FolderStore(tmp_path / 'f', 'lab')
    kept = _put_at(store, tmp_path, WHEN - timedelta(days=1))
    assert artefacts.clean(store, now=WHEN, retain_days=3, cap_bytes=10**9, pinned=frozenset()) == ()
    assert store.list(None) == (kept,)


class _Forge:
    """Records-home assets plus keep-labelled issues/PRs; just the calls the forge backend makes."""

    def __init__(self) -> None:
        self.assets: list[dict[str, Any]] = []
        self.blobs: dict[str, bytes] = {}
        self.labelled: list[dict[str, Any]] = []
        self.heads: dict[int, str] = {}

    repo = '/api/v1/repos/o/r'

    backend = GITEA

    def call(self, method: str, path: str, body: object = None) -> object:
        if 'issues?' in path and 'labels=keep' in path:
            return self.labelled
        if path.endswith('/issues?state=all&type=issues&q=run+records&limit=50'):
            return [{'title': 'run records', 'number': 1}]
        if '/pulls/' in path:
            return {
                'number': 1,
                'title': '',
                'state': 'open',
                'body': '',
                'html_url': '',
                'user': {'login': 'x'},
                'head': {'ref': 'h', 'sha': self.heads[int(path.rsplit('/', 1)[1])]},
                'base': {'ref': 'b'},
            }
        if method == 'DELETE':
            ident = int(path.rsplit('/', 1)[1])
            self.assets = [a for a in self.assets if a['id'] != ident]
            return None
        return list(self.assets)

    def upload(self, path: str, *, field: str, filename: str, content: bytes, landed: object = None) -> object:
        del field, landed, path
        raw = {'id': len(self.assets) + 1, 'name': filename, 'size': len(content), 'browser_download_url': filename}
        self.assets.append(raw)
        self.blobs[filename] = content
        return raw

    def download(self, url: str) -> bytes:
        return self.blobs[url]


def test_the_forge_backend_is_write_once_and_verified_too(tmp_path: Path) -> None:
    forge = _Forge()
    store = ForgeStore(cast('Client', forge))
    ref = store.put(RUN, _archive(tmp_path))
    assert ref.key == f'{RUN}.tar.zst'
    assert store.get(ref, tmp_path / 'd').read_bytes() == b'payload'
    with pytest.raises(ArtefactRefused, match='write-once'):
        store.put(RUN, _archive(tmp_path, b'other'))
    assert store.list(None) == (ref,)
    store.delete(ref)
    assert store.list(None) == ()


def test_keep_labels_pin_the_shas_their_issue_or_pr_names() -> None:
    forge = _Forge()
    forge.labelled = [
        {'number': 3, 'body': f'results of {"c" * 40} please'},
        {'number': 4, 'body': '', 'pull_request': {}},
    ]
    forge.heads[4] = 'd' * 40
    assert artefacts.pinned(cast('Client', forge)) == frozenset({'c' * 12, 'd' * 12})


# --- choosing the store by size --------------------------------------------------------------------


def test_small_goes_to_the_forge_large_to_the_configured_backend(tmp_path: Path) -> None:
    config = Config('folder', str(tmp_path / 'big'), threshold_mb=1)
    forge = _Forge()
    small = artefacts.store_for(config, cast('Client', forge), 'lab', size=1024)
    large = artefacts.store_for(config, cast('Client', forge), 'lab', size=2 * 1024 * 1024)
    assert (small.backend, large.backend) == ('forge', 'folder')


def test_too_large_for_the_forge_with_no_backend_is_refused_naming_the_key() -> None:
    with pytest.raises(ArtefactRefused, match=r'tool\.lab_commons\.artefacts'):
        artefacts.store_for(Config(), cast('Client', _Forge()), 'lab', size=200 * 1024 * 1024)
