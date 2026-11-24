"""BASELINES LIVE IN THE RUN STORE -- a repo keeps ONE lock, never the data a test compares against.

User ruling 2026-11-24 (H2). Every recorded data file a test compares against (a golden, a reference curve, a
vendor export) lives in the family's run store -- the content-addressed large-object store
(:func:`dev_lab.dev.largeobjects.run_objects`, ``[storage] runs``). The repo keeps :data:`LOCK`
(``tests/baselines.lock``): one JSON row per baseline -- ``test`` (the test id comparing against it), ``sha256``
(its content hash), ``name``, ``command`` (what produced it) and ``source_sha`` (the commit it was produced at).
A test reads a baseline through the local cache, ``output/cache/<store>/baselines/<sha256>``, re-hashed on
every read: a cache entry that no longer hashes is refetched, never served.

THE DOOR, generic for any family repo::

    python -m dev_lab.dev.baselines get <name> [<name> ...]      # fetch into the cache, print each path
    python -m dev_lab.dev.baselines put <file> --name N --test T --command "<cmd>" [--source-sha S]
    python -m dev_lab.dev.baselines verify [--commit <sha>]

``verify`` refuses (1) a malformed lock, (2) a tracked DATA file under ``tests/`` (code and in-code expected
values only, :func:`data_files`), and with ``--commit`` (3) a commit that REWRITES a baseline -- a lock row whose
hash moved -- without quoting old and new numbers in its message, one line per rewritten name::

    baseline <name>: old <number> new <number>

(:func:`unquoted`; a golden may only agree better, and an unquoted rewrite is an unchecked claim). An added row
is no rewrite. Each refusal names its cause and this door.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Final, Protocol

from lab_commons.log import emit

__all__ = [
    'CACHE',
    'CODE_NAMES',
    'CODE_SUFFIXES',
    'DOOR',
    'LOCK',
    'RULE',
    'LockRefused',
    'Row',
    'Store',
    'data_files',
    'get',
    'main',
    'parse_lock',
    'put',
    'read_lock',
    'rewritten',
    'unquoted',
    'write_lock',
]

#: The one lock a repo keeps, relative to its root.
LOCK: Final = PurePosixPath('tests/baselines.lock')
#: The local cache root, relative to the repo root; ``<store>/baselines/<sha256>`` beneath it.
CACHE: Final = PurePosixPath('output/cache')
DOOR: Final = 'python -m dev_lab.dev.baselines'
#: What may be tracked under ``tests/``: code, and the files a Rust test crate cannot exist without.
CODE_SUFFIXES: Final = frozenset({'.py', '.pyi', '.rs', '.js', '.mjs', '.cjs', '.ts', '.tsx'})
CODE_NAMES: Final = frozenset({'Cargo.toml', 'Cargo.lock', LOCK.name})
_GIT: Final = shutil.which('git') or 'git'
_SHA256: Final = re.compile(r'^[0-9a-f]{64}$')
_NUMBER: Final = r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?'


class LockRefused(ValueError):
    """The lock, a lookup in it, or a rewrite is refused -- the message names the row and the door."""


class Store(Protocol):
    """A content-addressed store: :meth:`put` a file and get its sha256; :meth:`get` those bytes back."""

    name: str

    def put(self, path: Path) -> str:
        """Store *path*; its sha256."""
        ...

    def get(self, sha256: str, dest: Path) -> Path:
        """The bytes of *sha256* written to *dest*."""
        ...


@dataclass(frozen=True)
class Row:
    """One baseline: the test comparing against it, its hash, its name, and how and where it was produced."""

    test: str
    sha256: str
    name: str
    command: str
    source_sha: str


def read_lock(lock: Path) -> list[Row]:
    """The rows of *lock*, sorted by name; absent is none; a malformed row is refused by its line."""
    return parse_lock(lock.read_text(encoding='utf-8'), where=str(lock)) if lock.is_file() else []


def parse_lock(text: str, *, where: str) -> list[Row]:
    """The rows lock *text* (read from *where*) holds, sorted by name; a malformed row is refused by its line."""
    lock = where
    rows: dict[str, Row] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            row = Row(**{key: str(payload[key]) for key in Row.__dataclass_fields__})
        except (json.JSONDecodeError, KeyError, TypeError) as why:
            fields = list(Row.__dataclass_fields__)
            msg = f'{lock} line {number}: not a baseline row {fields} ({why}); write it with {DOOR} put'
            raise LockRefused(msg) from why
        if not _SHA256.match(row.sha256):
            msg = f'{lock} line {number}: sha256 {row.sha256!r} is not a sha256 hex digest; write it with {DOOR} put'
            raise LockRefused(msg)
        if row.name in rows:
            msg = f'{lock} line {number}: baseline {row.name!r} is locked twice'
            raise LockRefused(msg)
        rows[row.name] = row
    return [rows[name] for name in sorted(rows)]


def write_lock(lock: Path, rows: Iterable[Row]) -> None:
    """Write *rows* to *lock*, one sorted JSON row per line, so a rewrite is a one-line diff."""
    lock.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda row: row.name)
    lock.write_text(
        ''.join(json.dumps(asdict(row), sort_keys=True) + '\n' for row in ordered), encoding='utf-8', newline='\n'
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def put(root: Path, source: Path, *, name: str, test: str, command: str, source_sha: str, store: Store) -> Row:
    """Store *source* and lock it as *name* (replacing that name's row); the row written."""
    row = Row(test=test, sha256=store.put(source), name=name, command=command, source_sha=source_sha)
    lock = root / LOCK
    write_lock(lock, [*(one for one in read_lock(lock) if one.name != name), row])
    return row


def get(root: Path, name: str, *, store: Store) -> Path:
    """The cached path of baseline *name*, fetched when the cache lacks it or no longer hashes."""
    rows = {row.name: row for row in read_lock(root / LOCK)}
    if name not in rows:
        msg = f'baseline {name!r} is not in {root / LOCK} ({sorted(rows)}); add it with {DOOR} put'
        raise LockRefused(msg)
    row = rows[name]
    cached = root / CACHE / store.name / 'baselines' / row.sha256
    if cached.is_file() and _sha256(cached) == row.sha256:
        return cached
    store.get(row.sha256, cached)
    if _sha256(cached) != row.sha256:
        cached.unlink()
        msg = f'baseline {name!r}: the store returned bytes that do not hash to {row.sha256[:16]}; discarded'
        raise LockRefused(msg)
    return cached


def rewritten(old: Iterable[Row], new: Iterable[Row]) -> tuple[str, ...]:
    """The names locked in both *old* and *new* whose hash moved -- a rewrite; an added row is none."""
    before = {row.name: row.sha256 for row in old}
    return tuple(sorted(row.name for row in new if row.name in before and before[row.name] != row.sha256))


def unquoted(names: Iterable[str], message: str) -> tuple[str, ...]:
    """The rewritten *names* whose ``baseline <name>: old <number> new <number>`` line *message* lacks."""
    return tuple(
        name
        for name in names
        if not re.search(rf'^baseline {re.escape(name)}: old {_NUMBER}\S* new {_NUMBER}', message, re.MULTILINE)
    )


def data_files(tracked: Iterable[str]) -> list[str]:
    """The tracked paths under ``tests/`` that are data, not code (:data:`CODE_SUFFIXES`, :data:`CODE_NAMES`)."""
    found = []
    for path in tracked:
        pure = PurePosixPath(path)
        if pure.parts[:1] == ('tests',) and pure.suffix not in CODE_SUFFIXES and pure.name not in CODE_NAMES:
            found.append(path)
    return sorted(found)


@dataclass(frozen=True)
class _RunStore:
    """The family run store (:class:`~dev_lab.dev.largeobjects.RcloneObjects`) as a :class:`Store`."""

    name: str
    objects: object

    def put(self, path: Path) -> str:
        return self.objects.put(path).sha256  # type: ignore[attr-defined]

    def get(self, sha256: str, dest: Path) -> Path:
        from lab_commons.compute.store import Ref  # noqa: PLC0415

        objects = self.objects
        key = f'{objects.prefix}/{sha256[:2]}/{sha256}'  # type: ignore[attr-defined]
        return objects.get(Ref(objects.backend, key, 0, sha256), dest)  # type: ignore[attr-defined]


def _run_store(root: Path) -> Store:
    from lab_commons import storage  # noqa: PLC0415 -- the network door is reached only by get and put

    from dev_lab.dev.largeobjects import run_objects  # noqa: PLC0415

    declared = storage.declared()
    objects = run_objects(root, declared=declared)
    if objects is None:
        msg = 'the family declares no run store ([storage] runs); baselines have nowhere to live'
        raise LockRefused(msg)
    return _RunStore(str(declared.runs_remote), objects)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        [_GIT, '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8', check=True, timeout=120
    ).stdout


def _rows_at(root: Path, rev: str) -> list[Row]:
    try:
        text = _git(root, 'show', f'{rev}:{LOCK}')
    except subprocess.CalledProcessError:
        return []
    return parse_lock(text, where=f'{rev}:{LOCK}')


def _verify(root: Path, commit: str | None) -> list[str]:
    refusals = []
    try:
        read_lock(root / LOCK)
    except LockRefused as why:
        refusals.append(str(why))
    tracked = _git(root, 'ls-files', '--', 'tests').splitlines()
    refusals += [
        f'{path}: a tracked data file under tests/ -- move it to the run store with {DOOR} put and delete it'
        for path in data_files(tracked)
    ]
    if commit:
        names = rewritten(_rows_at(root, f'{commit}^'), _rows_at(root, commit))
        message = _git(root, 'log', '-1', '--format=%B', commit)
        refusals += [
            f'{commit[:12]} rewrites baseline {name!r} without quoting its numbers: add the line '
            f'"baseline {name}: old <number> new <number>" to the commit message'
            for name in unquoted(names, message)
        ]
    return refusals


#: The rule a staged rewrite without its numbers breaks; its refusal leads with it (docs-src/dev/refusals.md).
RULE: Final = 'BASELINE-REWRITE-QUOTED'


def _check_message(root: Path, message: str) -> int:
    """The commit-msg row: the STAGED lock against HEAD's, judged against *message* before the commit exists."""
    missing = unquoted(rewritten(_rows_at(root, 'HEAD'), _rows_at(root, '')), message)
    for name in missing:
        emit(
            f'{RULE}: this commit rewrites baseline {name!r} without quoting its numbers.\n'
            f'add the line "baseline {name}: old <number> new <number>" to the message and commit again\n'
            f'details: docs-src/dev/refusals.md#{RULE.lower()} (dev-lab)',
            err=True,
        )
    return 1 if missing else 0


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m dev_lab.dev.baselines {get,put,verify}``; exit 0 done, 1 refused."""
    parser = argparse.ArgumentParser(prog=DOOR, description='Baselines in the run store, one lock in the repo.')
    sub = parser.add_subparsers(dest='verb', required=True)
    fetch = sub.add_parser('get', help='fetch baselines into the local cache and print each path')
    fetch.add_argument('names', nargs='+')
    store = sub.add_parser('put', help='store a file and lock it')
    store.add_argument('file', type=Path)
    store.add_argument('--name', required=True)
    store.add_argument('--test', required=True, help='the test id comparing against it')
    store.add_argument('--command', required=True, help='the command that produced it')
    store.add_argument('--source-sha', default='', help='the commit it was produced at (default: HEAD)')
    hook = sub.add_parser('check-message', help='commit-msg row: refuse an unquoted staged rewrite')
    hook.add_argument('message_file', type=Path)
    check = sub.add_parser('verify', help='refuse a malformed lock, tracked test data, an unquoted rewrite')
    check.add_argument('--commit', default=None, help='also judge this commit`s lock rewrites against its message')
    parsed = parser.parse_args(argv)
    root = Path.cwd()
    try:
        if parsed.verb == 'get':
            target = _run_store(root)
            for name in parsed.names:
                emit(str(get(root, name, store=target)))
        elif parsed.verb == 'put':
            sha = parsed.source_sha or _git(root, 'rev-parse', 'HEAD').strip()
            row = put(
                root, parsed.file, name=parsed.name, test=parsed.test, command=parsed.command, source_sha=sha,
                store=_run_store(root),
            )  # fmt: skip
            emit(f'locked {row.name} = {row.sha256} in {LOCK}')
        elif parsed.verb == 'check-message':
            return _check_message(root, parsed.message_file.read_text(encoding='utf-8'))
        else:
            refusals = _verify(root, parsed.commit)
            for line in refusals:
                emit(f'baselines: refused -- {line}', err=True)
            return 1 if refusals else 0
    except LockRefused as why:
        emit(f'baselines: refused -- {why}', err=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
