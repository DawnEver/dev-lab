"""The account half of ``hpcaccount archive``: tar parts up, read back, hashed, and a manifest the clean door trusts.

User ruling 2026-11-25: results of record are archived with hash verification BEFORE the local copy is deleted. The
instrument must be able to say no, so each planted control below makes one check fail: a store that returns other
bytes than it was sent, a part gone from the store, a tree changed after its archive, and an earlier archive that
an archive of a changed tree would overwrite.
"""

from __future__ import annotations

import ast
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from dev_lab.dev.hpcaccount import archivestream

#: A fake rclone over a local directory: ``<store root> --config <c> <verb> ...``; ``store:`` names the root.
FAKE_RCLONE = r"""
import hashlib, json, os, pathlib, sys
root, args = pathlib.Path(sys.argv[1]), sys.argv[4:]
def local(remote): return root / remote.split(':', 1)[1]
verb = args[0]
if verb == 'rcat':
    target = local(args[1]); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(sys.stdin.buffer.read())
elif verb == 'lsjson':
    folder = local(args[1])
    if not folder.is_dir(): sys.stderr.write('directory not found\n'); sys.exit(3)
    print(json.dumps([{'Path': p.name, 'Size': p.stat().st_size} for p in sorted(folder.iterdir())]))
elif verb == 'cat':
    sys.stdout.buffer.write(local(args[1]).read_bytes())
elif verb == 'hashsum':
    data = local(args[-1]).read_bytes()
    if os.environ.get('FAKE_RCLONE_CORRUPT'): data += b'x'
    print(hashlib.sha256(data).hexdigest() + '  ' + local(args[-1]).name)
else:
    sys.exit(f'fake rclone: unknown verb {verb}')
"""

_TAR = shutil.which('tar')


@pytest.fixture
def spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """A home holding ``work/data`` (a few files), a store root, and the spec the workstation would send."""
    home = tmp_path / 'home'
    data = home / 'work' / 'data'
    (data / 'deep').mkdir(parents=True)
    (data / 'a.csv').write_text('1,2,3\n' * 50, encoding='utf-8')
    (data / 'deep' / 'b.bin').write_bytes(bytes(range(256)) * 9)
    monkeypatch.setattr(Path, 'home', lambda: home)
    script = tmp_path / 'rclone.py'
    script.write_text(FAKE_RCLONE, encoding='utf-8')
    assert _TAR is not None, 'no tar on PATH: every runner (Linux, Git for Windows) carries one'
    return {
        'mode': 'archive', 'path': 'work/data', 'dest': 'store:bucket/archive/u1/work/data',
        'rclone': [sys.executable, str(script), str(tmp_path / 'store')], 'config': str(tmp_path / 'rclone.conf'),
        'part_bytes': 1000, 'tar': [_TAR],
    }  # fmt: skip


def _store(spec: dict[str, object]) -> Path:
    return Path(str(spec['rclone'][2])) / 'bucket' / 'archive' / 'u1' / 'work' / 'data'  # type: ignore[index]


def _run(spec: dict[str, object], mode: str) -> tuple[dict[str, object], list[str]]:
    said: list[str] = []
    try:
        verdict = archivestream.MODES[mode]({**spec, 'mode': mode}, said.append)
    except archivestream.Refused as refused:
        verdict = {'ok': False, 'verdict': 'refused', 'why': str(refused)}
    return verdict, said


def test_an_archive_is_parts_that_restore_the_tree_and_a_verified_manifest(spec: dict[str, object]) -> None:
    verdict, _ = _run(spec, 'archive')
    assert verdict['ok'], verdict
    manifest = json.loads((_store(spec) / archivestream.MANIFEST).read_text(encoding='utf-8'))
    assert manifest['verified'] is True
    assert len(manifest['parts']) > 1, 'part_bytes 1000 must cut the stream'
    assert all(p['sha256'] == p['remote_sha256'] for p in manifest['parts'])
    stream = b''.join((_store(spec) / p['name']).read_bytes() for p in manifest['parts'])
    with tarfile.open(fileobj=io.BytesIO(stream)) as tar:
        assert tar.extractfile('data/deep/b.bin').read() == bytes(range(256)) * 9  # type: ignore[union-attr]
    assert manifest['state'] == archivestream.tree_state(Path.home() / 'work' / 'data')


def test_an_archive_of_the_same_tree_again_sends_nothing(spec: dict[str, object]) -> None:
    _run(spec, 'archive')
    first = (_store(spec) / archivestream.MANIFEST).read_bytes()
    verdict, said = _run(spec, 'archive')
    assert verdict['verdict'] == 'archived'
    assert any('nothing sent' in line for line in said)
    assert (_store(spec) / archivestream.MANIFEST).read_bytes() == first


def test_planted_control_a_store_returning_other_bytes_is_not_verified(
    spec: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('FAKE_RCLONE_CORRUPT', '1')
    verdict, said = _run(spec, 'archive')
    assert not verdict['ok']
    assert 'NOT verified' in str(verdict['why'])
    assert any('MISMATCH part-00000.tar' in line for line in said)
    assert json.loads((_store(spec) / archivestream.MANIFEST).read_text(encoding='utf-8'))['verified'] is False
    released, _ = _run(spec, 'release')
    assert not released['ok'], 'an unverified archive must never release the tree'


def test_release_holds_only_for_the_archived_unchanged_tree(spec: dict[str, object]) -> None:
    refused, _ = _run(spec, 'release')
    assert 'no archive manifest' in str(refused['why'])
    _run(spec, 'archive')
    released, _ = _run(spec, 'release')
    assert released['verdict'] == 'released'
    assert (released['parent'], released['name']) == (str(Path.home() / 'work'), 'data')


def test_planted_control_a_part_gone_from_the_store_refuses_the_release(spec: dict[str, object]) -> None:
    _run(spec, 'archive')
    (_store(spec) / archivestream.part_name(1)).unlink()
    refused, _ = _run(spec, 'release')
    assert 'no longer holds' in str(refused['why'])


def test_planted_control_a_tree_changed_since_refuses_the_release_and_is_never_overwritten(
    spec: dict[str, object],
) -> None:
    _run(spec, 'archive')
    (Path.home() / 'work' / 'data' / 'late.txt').write_text('new', encoding='utf-8')
    refused, _ = _run(spec, 'release')
    assert 'changed since it was archived' in str(refused['why'])
    again, _ = _run(spec, 'archive')
    assert 'never overwritten' in str(again['why'])
    assert '--as' in str(again['why'])


def test_a_plan_writes_nothing(spec: dict[str, object]) -> None:
    verdict, said = _run(spec, 'plan')
    assert verdict['verdict'] == 'planned'
    assert 'archive plan:' in said[0]
    assert not _store(spec).exists()


def test_the_streamed_file_runs_alone_and_ends_with_its_verdict(spec: dict[str, object]) -> None:
    """Streamed as the workstation streams it: ``python - <spec>``, isolated, nothing of dev-lab importable."""
    imported = {
        alias.name.split('.')[0]
        for node in ast.walk(ast.parse(Path(archivestream.__file__).read_text(encoding='utf-8')))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(node.module or '')])
    }
    assert imported <= set(sys.stdlib_module_names) | {'__future__'}, imported
    env = {**os.environ, 'HOME': str(Path.home()), 'USERPROFILE': str(Path.home())}
    done = subprocess.run(
        [sys.executable, '-I', '-', json.dumps({**spec, 'mode': 'plan'})],
        input=Path(archivestream.__file__).read_text(encoding='utf-8'), capture_output=True, text=True, env=env,
        check=True,
    )  # fmt: skip
    head, _, verdict = done.stdout.strip().splitlines()[-1].partition(' ')
    assert head + ' ' == archivestream.VERDICT
    assert json.loads(verdict)['verdict'] == 'planned'
