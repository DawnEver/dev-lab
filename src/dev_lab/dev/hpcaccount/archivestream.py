"""THE ACCOUNT HALF OF ``hpcaccount archive``: one file, standard library only, streamed to the account's interpreter.

The data lives on the account, so the account sends it: the workstation streams THIS FILE on stdin (``python -
<spec>``, :mod:`dev_lab.dev.hpcaccount.archive`) after proving the account reaches the store, and hands it the
account's own rclone and config in the spec. Nothing is imported from the account's kit, so its version never
decides what an archive is (as :mod:`dev_lab.dev.accountsweep`).

ONE DIRECTORY, ONE TAR STREAM, CUT INTO PARTS. ``tar -C <parent> -cf - --one-file-system <name>`` is read once and
cut into :data:`PART_BYTES`-sized parts, each piped to ``rclone rcat <dest>/part-NNNNN.tar`` while its sha256 and
the whole stream's are taken -- nothing is written on the account. A part, not one object: a stream of unknown size
uploads in a backend's default chunks, and S3's 10,000-part ceiling caps that at about 48 GiB; a 4 GiB part stays
far below it on every backend.

VERIFIED BY THE STORE'S OWN BYTES: each part is read back (``rclone hashsum sha256 --download``) and its sha256
compared with the one taken on the way up, and its listed size with the bytes sent. The manifest
(``<dest>/manifest.json``: source, tree state, parts with both hashes, the whole stream's sha256, ``verified``) is
written last; ``verified`` is true only when every part matched.

MODES (``spec['mode']``): ``plan`` reads the tree and the store and writes nothing; ``archive`` uploads, verifies and
writes the manifest -- a verified manifest of the SAME tree state is the archive already (nothing is sent), one of
an EARLIER state is never overwritten (refused, naming ``--as``); ``release`` is the clean door's precondition --
a verified manifest, every part present at its size, and the tree unchanged since (files, bytes, newest change).
Every outcome is the last line, ``ARCHIVE-VERDICT <json>``; a refusal exits 0 with ``ok`` false so its words reach
the caller intact.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import IO

__all__ = [
    'MANIFEST',
    'MODES',
    'PART_BYTES',
    'VERDICT',
    'Refused',
    'archive',
    'main',
    'part_name',
    'plan',
    'read_manifest',
    'release',
    'tree_state',
    'upload',
    'verify',
]

#: Bytes per part: well under every backend's streamed-upload ceiling (S3: 10,000 chunks of 5 MiB).
PART_BYTES = 4 << 30
#: The manifest's name under the destination.
MANIFEST = 'manifest.json'
#: The verdict line's head; the rest of the line is JSON.
VERDICT = 'ARCHIVE-VERDICT '
_CHUNK = 1 << 20


class Refused(Exception):
    """An archive, plan or release that cannot proceed; the message names why and what to do."""


def part_name(index: int) -> str:
    """The object name of part *index*."""
    return f'part-{index:05d}.tar'


def tree_state(path: Path) -> dict[str, int]:
    """*path*'s files (every inode, the root included), bytes (non-directories) and newest change, on one filesystem."""
    top = path.lstat()
    files, size, newest = 1, 0, int(top.st_mtime)
    for here, dirs, names in os.walk(path):
        kept = []
        for name in dirs:
            info = Path(here, name).lstat()
            files, newest = files + 1, max(newest, int(info.st_mtime))
            if info.st_dev == top.st_dev and not Path(here, name).is_symlink():
                kept.append(name)
        dirs[:] = kept
        for name in names:
            info = Path(here, name).lstat()
            files, size, newest = files + 1, size + info.st_size, max(newest, int(info.st_mtime))
    return {'files': files, 'bytes': size, 'newest': newest}


def _rclone(spec: dict, *args: str) -> list[str]:
    return [*spec['rclone'], '--config', str(Path(spec['config']).expanduser()), *args]


def _run(spec: dict, *args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(_rclone(spec, *args), input=stdin, capture_output=True, check=False)


def _said(done: subprocess.CompletedProcess[bytes]) -> str:
    text = (done.stderr or done.stdout).decode('utf-8', 'replace').strip().splitlines()
    return text[-1] if text else f'exit {done.returncode}'


def read_manifest(spec: dict) -> dict | None:
    """The manifest at the destination, ``None`` when there is none."""
    listed = _run(spec, 'lsjson', spec['dest'])
    if listed.returncode != 0 or MANIFEST not in {e.get('Path') for e in json.loads(listed.stdout or b'[]')}:
        return None
    done = _run(spec, 'cat', f'{spec["dest"]}/{MANIFEST}')
    if done.returncode != 0:
        msg = f'the manifest at {spec["dest"]} is listed but cannot be read: {_said(done)}'
        raise Refused(msg)
    return json.loads(done.stdout)


def _pipe(pipe: IO[bytes] | None, what: str) -> IO[bytes]:
    if pipe is None:
        msg = f'{what} started without its pipe'
        raise Refused(msg)
    return pipe


class _Part:
    """One part on its way up: an ``rclone rcat`` fed while its sha256 is taken."""

    def __init__(self, spec: dict, index: int) -> None:
        self.name = part_name(index)
        self.hash = hashlib.sha256()
        self.bytes = 0
        self.proc = subprocess.Popen(_rclone(spec, 'rcat', f'{spec["dest"]}/{self.name}'), stdin=subprocess.PIPE)
        self.pipe = _pipe(self.proc.stdin, 'rclone rcat')

    def write(self, data: memoryview) -> None:
        self.pipe.write(data)
        self.hash.update(data)
        self.bytes += len(data)

    def close(self) -> dict[str, object]:
        self.pipe.close()
        if code := self.proc.wait():
            msg = f'rclone rcat {self.name} exited {code}: the part did not arrive'
            raise Refused(msg)
        return {'name': self.name, 'bytes': self.bytes, 'sha256': self.hash.hexdigest()}


def upload(spec: dict, path: Path) -> tuple[list[dict[str, object]], str, int]:
    """Send *path* as tar parts: the parts sent, the whole stream's sha256 and its bytes."""
    limit = int(spec['part_bytes'])
    tar = subprocess.Popen(
        [*spec['tar'], '-C', str(path.parent), '-cf', '-', '--one-file-system', path.name], stdout=subprocess.PIPE
    )
    out = _pipe(tar.stdout, 'tar')
    whole, sent, parts, part = hashlib.sha256(), 0, [], None
    try:
        while chunk := out.read(_CHUNK):
            view = memoryview(chunk)
            whole.update(view)
            sent += len(view)
            while view:
                part = part or _Part(spec, len(parts))
                take = min(len(view), limit - part.bytes)
                part.write(view[:take])
                view = view[take:]
                if part.bytes == limit:
                    parts.append(part.close())
                    part = None
        if part is not None:
            parts.append(part.close())
    except BrokenPipeError as broken:
        msg = f'rclone stopped reading a part: {broken}'
        raise Refused(msg) from broken
    finally:
        out.close()
    if code := tar.wait():
        msg = f'tar exited {code}: the tree changed or could not be read while it was archived; nothing is verified'
        raise Refused(msg)
    return parts, whole.hexdigest(), sent


def verify(spec: dict, parts: list[dict[str, object]]) -> list[str]:
    """Read each part back from the store and record its sha256 there; what disagrees (empty: every part matched)."""
    listed = _run(spec, 'lsjson', spec['dest'])
    sizes = {e['Path']: e['Size'] for e in json.loads(listed.stdout or b'[]')} if listed.returncode == 0 else {}
    wrong = []
    for part in parts:
        done = _run(spec, 'hashsum', 'sha256', '--download', f'{spec["dest"]}/{part["name"]}')
        got = done.stdout.decode('utf-8', 'replace').split()[:1] if done.returncode == 0 else []
        part['remote_sha256'] = got[0].lower() if got else ''
        if part['remote_sha256'] != part['sha256']:
            wrong.append(
                f'{part["name"]}: sent {part["sha256"]}, the store holds {part["remote_sha256"] or _said(done)}'
            )
        if sizes.get(part['name']) != part['bytes']:
            wrong.append(f'{part["name"]}: sent {part["bytes"]} bytes, the store lists {sizes.get(part["name"])}')
    return wrong


def _source(spec: dict) -> Path:
    path = Path.home() / spec['path']
    if not path.is_dir():
        msg = f'{path} is not a directory on this account'
        raise Refused(msg)
    return path


def plan(spec: dict, say: Callable[[str], None]) -> dict[str, object]:
    """What an archive would send and where; nothing is written."""
    path = _source(spec)
    state = tree_state(path)
    held = read_manifest(spec)
    parts = state['bytes'] // int(spec['part_bytes']) + 1
    say(f'archive plan: {path} -> {spec["dest"]} ({state["files"]} files, {state["bytes"]} bytes, '
        f'about {parts} part(s) of at most {spec["part_bytes"]} bytes)')  # fmt: skip
    if held is not None:
        same = held.get('state') == state
        say(f'archive plan: the store already holds a manifest (verified={held.get("verified")}, '
            f'{"the same" if same else "an EARLIER"} tree state, archived {held.get("archived_at")})')  # fmt: skip
    return {'ok': True, 'verdict': 'planned', 'source': str(path), 'state': state}


def archive(spec: dict, say: Callable[[str], None]) -> dict[str, object]:
    """Upload, verify and write the manifest; an archive already there of the same tree is the archive."""
    path = _source(spec)
    state = tree_state(path)
    held = read_manifest(spec)
    if held is not None and held.get('verified'):
        if held.get('state') == state:
            say(f'archive: {spec["dest"]} already holds a verified archive of this tree state; nothing sent')
            return {'ok': True, 'verdict': 'archived', 'source': str(path), 'manifest': held}
        msg = (
            f'{spec["dest"]} holds a verified archive of an EARLIER state of {path} (archived '
            f'{held.get("archived_at")}, {held.get("state")}; now {state}): an archive of record is never '
            'overwritten -- archive the changed tree under another name with --as <name>'
        )
        raise Refused(msg)
    say(f'archive: sending {path} ({state["files"]} files, {state["bytes"]} bytes) to {spec["dest"]}')
    parts, whole, sent = upload(spec, path)
    say(f'archive: sent {sent} bytes in {len(parts)} part(s); reading each back from the store')
    wrong = verify(spec, parts)
    after = tree_state(path)
    if after != state:
        wrong.append(f'the tree changed while it was archived: {state} before, {after} after')
    manifest = {
        'format': 1, 'source': str(path), 'dest': spec['dest'], 'archived_at': time.strftime('%Y-%m-%dT%H:%M:%SZ',
        time.gmtime()), 'state': state, 'tar_sha256': whole, 'tar_bytes': sent, 'parts': parts, 'verified': not wrong,
        'restore': f'concatenate the parts in order (rclone cat {spec["dest"]}/part-NNNNN.tar ...) into tar -xf -',
    }  # fmt: skip
    done = _run(spec, 'rcat', f'{spec["dest"]}/{MANIFEST}', stdin=json.dumps(manifest, indent=2).encode('utf-8'))
    if done.returncode != 0:
        wrong.append(f'the manifest could not be written: {_said(done)}')
    for line in wrong:
        say(f'archive: MISMATCH {line}')
    if wrong:
        msg = f'{len(wrong)} check(s) failed -- the archive is NOT verified and nothing may be cleaned; re-run it'
        raise Refused(msg)
    say(f'archive: verified -- every part read back from the store hashes as sent; manifest {spec["dest"]}/{MANIFEST}')
    return {'ok': True, 'verdict': 'archived', 'source': str(path), 'manifest': manifest}


def release(spec: dict, say: Callable[[str], None]) -> dict[str, object]:
    """The clean door's precondition: a verified manifest, every part there at its size, the tree unchanged."""
    path = _source(spec)
    held = read_manifest(spec)
    if held is None:
        msg = f'no archive manifest at {spec["dest"]}: archive first (hpcaccount archive ... --apply)'
        raise Refused(msg)
    parts = held.get('parts') or []
    if not held.get('verified') or not parts or any(p.get('sha256') != p.get('remote_sha256') for p in parts):
        msg = f'the archive at {spec["dest"]} is not verified: re-run hpcaccount archive ... --apply'
        raise Refused(msg)
    listed = _run(spec, 'lsjson', spec['dest'])
    sizes = {e['Path']: e['Size'] for e in json.loads(listed.stdout or b'[]')} if listed.returncode == 0 else {}
    if missing := [p['name'] for p in parts if sizes.get(p['name']) != p['bytes']]:
        msg = f'the store no longer holds {missing} at their archived size under {spec["dest"]}: re-run the archive'
        raise Refused(msg)
    if (now := tree_state(path)) != held.get('state'):
        msg = f'{path} changed since it was archived ({held.get("state")} then, {now} now): re-archive it with --as'
        raise Refused(msg)
    say(f'release: {path} is archived and verified at {spec["dest"]} ({len(parts)} part(s), tar sha256 '
        f'{held.get("tar_sha256")}) and unchanged since {held.get("archived_at")}')  # fmt: skip
    return {'ok': True, 'verdict': 'released', 'source': str(path), 'parent': str(path.parent), 'name': path.name}


MODES = {'plan': plan, 'archive': archive, 'release': release}


def main(argv: list[str]) -> int:
    """Run the spec's mode; the verdict is the last line."""
    spec = json.loads(argv[0])

    def say(line: str) -> None:
        sys.stdout.write(line + '\n')
        sys.stdout.flush()

    try:
        verdict = MODES[spec['mode']](spec, say)
    except (Refused, OSError) as refused:
        verdict = {'ok': False, 'verdict': 'refused', 'why': str(refused)}
    say(VERDICT + json.dumps(verdict))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
