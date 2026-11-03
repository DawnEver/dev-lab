"""A REVIEW BUNDLE: what a PR's review reads, built where PR code runs and judged where it never does.

The review splits in two (user decision 2026-11-03, the forge-bot on its own host). PREPARE runs on the CI runner
-- the untrusted side, holding no reviewer token -- and writes ONE deterministic JSON document: the diff from the
merge base to the head, the exact bytes of only the changed files on both sides, the base's ``pyproject.toml``
(the review declaration) and the PR's identity. JUDGE runs on the reviewer host, which holds the reviewer's token
and nothing an author can reach: it fetches a bundle, checks it, and hands the declared command a directory of
plain files -- never a checkout, an install or a process of the PR's.

WHAT THE JUDGE CHECKS before any reviewer reads a byte, each a :class:`BundleRefused` naming why:

* :func:`load` -- the bytes hash to the digest the bundle was published under, the version is known, every path
  stays inside the tree, and every file's bytes ARE the git blob the bundle names for it;
* :func:`current` -- the bundle names the PR the forge returns, its base branch, and that PR's CURRENT head: a
  bundle of an older push is stale;
* :func:`matches_forge` -- the forge's own diff of the PR (fetched by the judge, never the producer) names the same
  paths and blob ids: the producer cannot omit a file or swap its content.

THE REVIEWER'S RULES AND PRINCIPLES ARE NOT IN THE BUNDLE: they are the judge host's own install's
(:data:`dev_lab.dev.rules.RULES`, :mod:`dev_lab.dev.principles`), never a copy the untrusted side wrote.

READ BLOBLESS: :func:`prepare` asks git for ``--raw`` ids and one ``cat-file`` per changed blob, so a
``--filter=blob:none`` clone fetches only those (the review job peaked at 554 MB with a whole-tree grep).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Final

import lab_commons.launch as _door

from dev_lab.dev.reviewgitauth import git_env

if TYPE_CHECKING:
    from dev_lab.dev._forge_records import PullRequest

__all__ = [
    'BUNDLE_FIELD',
    'DECLARATION',
    'VERSION',
    'Bundle',
    'BundleRefused',
    'Changed',
    'blob_id',
    'current',
    'digest_of',
    'dump',
    'judge',
    'load',
    'matches_forge',
    'prepare',
]

#: The bundle format this module writes and the only one it reads.
VERSION: Final = 1

#: The placeholder the judge's command carries; the materialized bundle directory replaces it.
BUNDLE_FIELD: Final = '{bundle}'

#: The review declaration's file, read at the merge base.
DECLARATION: Final = 'pyproject.toml'

_GIT_TIMEOUT_S: Final = 120
_SIDES: Final = ('base', 'head')
_NO_BLOB: Final = re.compile(r'0+')
_INDEX: Final = re.compile(r'^index ([0-9a-f]+)\.\.([0-9a-f]+)', re.MULTILINE)
_HEADER: Final = re.compile(r'^diff --git a/(.+?) b/(.+)$', re.MULTILINE)
_BLOB_MODES: Final = frozenset({'100644', '100755', '120000'})


class BundleRefused(ValueError):
    """The judge will not review this bundle; the message names why."""


@dataclass(frozen=True)
class Changed:
    """One changed path: its blob id and exact bytes (base64) on each side; ``None`` where a side has no file."""

    path: str
    base_blob: str | None
    head_blob: str | None
    base: str | None
    head: str | None

    def side(self, which: str) -> bytes | None:
        """The exact bytes of the *which* (``base`` or ``head``) side; ``None`` when that side has no file."""
        text = getattr(self, which)
        return None if text is None else base64.b64decode(text, validate=True)


@dataclass(frozen=True)
class Bundle:
    """Everything a judge reads of one PR head (the module docstring)."""

    repo: str
    pr: int
    base_ref: str
    base_sha: str
    head_sha: str
    diff: str
    declaration: str
    files: tuple[Changed, ...]
    version: int = VERSION


def blob_id(data: bytes) -> str:
    """The git blob id of *data*."""
    return hashlib.sha1(b'blob %d\0' % len(data) + data, usedforsecurity=False).hexdigest()


def _git(root: Path, *args: str, ok: tuple[int, ...] = (0,)) -> tuple[int, bytes]:
    """``git *args``'s exit code (one of *ok*) and exact stdout bytes; :class:`OSError` naming any other."""
    done = _door.run(['git', *args], cwd=root, capture_output=True, timeout=_GIT_TIMEOUT_S, check=False, env=git_env())
    if done.returncode not in ok:
        msg = f'git {" ".join(args)} failed: {done.stderr.decode("utf-8", "replace").strip()[:300]}'
        raise OSError(msg)
    return done.returncode, done.stdout


def _blob(root: Path, ident: str | None) -> str | None:
    return None if ident is None else base64.b64encode(_git(root, 'cat-file', 'blob', ident)[1]).decode('ascii')


def _raw(root: Path, base: str, head: str) -> list[tuple[str | None, str | None, str]]:
    """``(base blob, head blob, path)`` per changed file, renames split, gitlinks dropped."""
    fields = _git(root, 'diff', '--raw', '-z', '--no-renames', '--no-abbrev', base, head)[1].decode('utf-8').split('\0')
    rows = []
    for meta, path in zip(fields[0::2], fields[1::2], strict=False):
        old_mode, new_mode, old, new, _status = meta.lstrip(':').split(' ')
        if old_mode in _BLOB_MODES or new_mode in _BLOB_MODES:
            rows.append((None if _NO_BLOB.fullmatch(old) else old, None if _NO_BLOB.fullmatch(new) else new, path))
    return rows


def prepare(root: Path, *, repo: str, pull: PullRequest, base: str) -> Bundle:
    """The bundle of *pull*'s head against its merge base with *base*, read from *root* (blobless is enough)."""
    head = pull.head_sha
    merge_base = _git(root, 'merge-base', base, head)[1].decode('ascii').strip()
    files = tuple(
        Changed(path, old, new, _blob(root, old), _blob(root, new))
        for old, new, path in sorted(_raw(root, merge_base, head), key=lambda row: row[2])
    )
    code, declaration = _git(root, 'show', f'{merge_base}:{DECLARATION}', ok=(0, 128))
    diff = _git(root, 'diff', '--no-renames', '--full-index', merge_base, head)[1]
    return Bundle(
        repo=repo, pr=pull.number, base_ref=pull.base, base_sha=merge_base, head_sha=head,
        diff=diff.decode('utf-8', 'replace'), declaration=declaration.decode('utf-8', 'replace') if code == 0 else '',
        files=files,
    )  # fmt: skip


def dump(bundle: Bundle) -> tuple[bytes, str]:
    """*bundle*'s canonical bytes and their digest: the same bundle always writes the same bytes."""
    data = json.dumps(asdict(bundle), sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return data, digest_of(data)


def digest_of(data: bytes) -> str:
    """``sha256:<hex>`` of *data*."""
    return f'sha256:{hashlib.sha256(data).hexdigest()}'


def _inside(path: str) -> None:
    pure = PurePosixPath(path)
    if not path or pure.is_absolute() or '..' in pure.parts or '\\' in path or ':' in path:
        msg = f'path {path!r} would escape the bundle tree'
        raise BundleRefused(msg)


def _checked(raw: dict[str, Any]) -> Changed:
    one = Changed(**raw)
    _inside(one.path)
    for which, blob in zip(_SIDES, (one.base_blob, one.head_blob), strict=True):
        try:
            data = one.side(which)
        except binascii.Error:
            msg = f'{one.path}: its {which} bytes are not base64'
            raise BundleRefused(msg) from None
        if (blob is None) != (data is None) or (data is not None and blob_id(data) != blob):
            msg = f'{one.path}: its {which} bytes are not the blob {blob} the bundle names'
            raise BundleRefused(msg)
    return one


def load(data: bytes, digest: str) -> Bundle:
    """The bundle *data* holds, refused unless it hashes to *digest* and every file is the blob it names."""
    if digest_of(data) != digest:
        msg = f'bundle hash {digest_of(data)} is not the published {digest}'
        raise BundleRefused(msg)
    raw = json.loads(data)
    if raw.get('version') != VERSION:
        msg = f'bundle version {raw.get("version")!r} is not {VERSION}'
        raise BundleRefused(msg)
    raw['files'] = tuple(_checked(one) for one in raw['files'])
    return Bundle(**raw)


def current(bundle: Bundle, pull: PullRequest, *, repo: str) -> None:
    """Refuse *bundle* unless it is of *pull* -- the forge's answer, now -- at its current head and base."""
    if (bundle.repo, bundle.pr) != (repo, pull.number):
        msg = f'bundle is of pull {bundle.repo}#{bundle.pr}, not {repo}#{pull.number}'
        raise BundleRefused(msg)
    if bundle.base_ref != pull.base:
        msg = f'bundle base {bundle.base_ref!r} is not the pull base {pull.base!r}'
        raise BundleRefused(msg)
    if bundle.head_sha != pull.head_sha:
        msg = f'bundle head {bundle.head_sha[:12]} is stale: the pull head is {pull.head_sha[:12]}'
        raise BundleRefused(msg)


def _named(diff: str) -> dict[str, tuple[str, str]]:
    """``path -> (base id, head id)`` from a unified diff's headers and ``index`` lines (ids may be abbreviated)."""
    headers = [*_HEADER.finditer(diff)]
    ends = [later.start() for later in headers[1:]] + [len(diff)]
    named = {}
    for header, end in zip(headers, ends, strict=True):
        if index := _INDEX.search(diff, header.end(), end):
            named[header.group(2)] = (index.group(1), index.group(2))
    return named


def _same(theirs: str, mine: str | None) -> bool:
    """One forge ``index`` id (maybe abbreviated; all zeros for no file) names the bundle's blob *mine*."""
    return mine is None if _NO_BLOB.fullmatch(theirs) else mine is not None and mine.startswith(theirs)


def matches_forge(bundle: Bundle, forge_diff: str) -> None:
    """Refuse *bundle* unless the forge's own diff of the PR names the same paths and blobs."""
    theirs = _named(forge_diff)
    ours = {one.path: (one.base_blob, one.head_blob) for one in bundle.files}
    if sorted(theirs) != sorted(ours):
        msg = f'the forge diff changes {sorted(theirs)}; the bundle holds {sorted(ours)}'
        raise BundleRefused(msg)
    for path, ids in theirs.items():
        if not all(_same(t, m) for t, m in zip(ids, ours[path], strict=True)):
            msg = f'{path}: the forge diff names blobs {ids[0]}..{ids[1]}, the bundle {ours[path]}'
            raise BundleRefused(msg)


def _materialize(bundle: Bundle, tree: Path) -> None:
    for one in bundle.files:
        for which in _SIDES:
            if (data := one.side(which)) is not None:
                dest = tree / which / one.path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
    (tree / 'diff.patch').write_bytes(bundle.diff.encode('utf-8'))
    (tree / 'bundle.json').write_bytes(dump(bundle)[0])


def judge(bundle: Bundle, command: Sequence[str], *, run: Callable[[tuple[str, ...]], str]) -> str:
    """The declared *command*'s output over *bundle* materialized as plain files (``{bundle}``: that directory).

    *run* starts the ONE process; a command that names git is refused, since the judge holds no checkout.
    """
    if any(PurePosixPath(arg.replace('\\', '/')).name.removesuffix('.exe') == 'git' for arg in command):
        msg = f'the judge command {list(command)} runs git: a judge reads the bundle, never a checkout'
        raise BundleRefused(msg)
    if BUNDLE_FIELD not in command:
        msg = f'the judge command {list(command)} names no {BUNDLE_FIELD}: it would read no bundle'
        raise BundleRefused(msg)
    with tempfile.TemporaryDirectory(prefix='review-bundle-') as scratch:
        tree = Path(scratch)
        _materialize(bundle, tree)
        return run(tuple(str(tree) if arg == BUNDLE_FIELD else arg for arg in command))
