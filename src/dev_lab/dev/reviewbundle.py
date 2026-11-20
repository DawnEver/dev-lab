"""A REVIEW BUNDLE: what a PR's review reads, built and judged on a host where no PR code ever runs.

The review splits in two (user decision 2026-11-03, the forge-bot on its own host). PREPARE (:func:`fetched`, then
:func:`prepare`) runs on the judge host itself since D77 -- over a bare, blobless fetch of the head that executes
nothing the head carries -- and writes ONE deterministic JSON document: the exact bytes of only
the changed files on both sides, their blob ids, and the PR's identity. The JUDGE decides which are BINARY, from
the bytes it verified (:attr:`Changed.binary`: a NUL in the first :data:`BINARY_PROBE` bytes of either side), and
hands the reviewer only the text ones (user decision 2026-11-03) -- never the producer's say-so, never the tree's
``.gitattributes``, which the PR author writes. JUDGE runs on the
reviewer host, which holds the reviewer's token and nothing an author can reach: it fetches a bundle, checks it, and
hands the declared command a directory of plain files -- never a checkout, an install or a process of the PR's.

THE JUDGE TRUSTS NOTHING THE PRODUCER WROTE THAT IT CAN READ OR DERIVE FROM THE FORGE (user decision 2026-11-03, D3).
The bundle therefore carries no diff and no declaration: the reviewer reads the FORGE's own diff of the PR
(:func:`judge` writes it as ``diff.patch``) and the declaration is read from the trusted integration branch through
the forge (:func:`dev_lab.dev.forgereview_declared.forge_review`). What the bundle carries -- the files' bytes --
is checked against the forge before any reviewer reads a byte, each failure a :class:`BundleRefused` naming why:

* :func:`load` -- the bytes hash to the digest the bundle was published under, the shape and version are known, every
  path stays inside the tree, and every file's bytes ARE the git blob the bundle names for it;
* :func:`current` -- the bundle names the PR the forge returns, its base branch, that PR's CURRENT head, and the
  merge base the FORGE computes for it: a bundle of an older push or another base is stale;
* :func:`~dev_lab.dev.reviewforgediff.matches_forge` -- the forge's own diff names exactly the bundle's paths and
  blob ids (its headers parsed with git's C quoting, renames split as the bundle splits them, any header it
  cannot parse refused): the producer cannot omit a file or swap its content.

THE REVIEWER'S RULES AND PRINCIPLES ARE NOT IN THE BUNDLE: they are the judge host's own install's
(:data:`dev_lab.dev.rules.RULES`, :mod:`dev_lab.dev.principles`), never a copy the untrusted side wrote.

NO REPOSITORY IS REACHABLE FROM THE JUDGE'S COMMAND THROUGH GIT'S DISCOVERY: the tree it reads holds no ``.git``,
and the command runs with ``GIT_DIR`` naming a path that does not exist (:func:`no_repo_env`), so a git it starts
with that environment -- however wrapped -- finds no repository. The argv check in :func:`judge` is a lint against a
declared ``git`` command, not that guarantee.

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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Final, Literal

import lab_commons.launch as _door
from lab_commons.temp import TEMP_PREFIX

from dev_lab.dev.reviewgitauth import git_env

if TYPE_CHECKING:
    from dev_lab.dev._forge_records import PullRequest

__all__ = [
    'BINARY_PROBE',
    'BLOB_MODES',
    'BUNDLE_FIELD',
    'NO_BLOB',
    'VERSION',
    'Bundle',
    'BundleRefused',
    'Changed',
    'blob_id',
    'current',
    'digest_of',
    'dump',
    'fetched',
    'is_binary',
    'judge',
    'load',
    'no_repo_env',
    'prepare',
]

#: The bundle format this module writes and the only one it reads (2: no producer diff, no declaration).
VERSION: Final = 2

#: The placeholder the judge's command carries; the materialized bundle directory replaces it.
BUNDLE_FIELD: Final = '{bundle}'

#: How many leading bytes of a side are searched for a NUL: git's own probe length, without its attributes.
BINARY_PROBE: Final = 8000

type Side = Literal['base', 'head']

_GIT_TIMEOUT_S: Final = 120
_SIDES: Final[tuple[Side, Side]] = ('base', 'head')
#: An all-zero blob id: no file on that side.
NO_BLOB: Final = re.compile(r'0+')
BLOB_MODES: Final = frozenset({'100644', '100755', '120000'})


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

    @property
    def binary(self) -> bool:
        """Whether its bytes are binary (:func:`is_binary`): listed to the reviewer, never written for it."""
        return is_binary(self.side('base'), self.side('head'))

    def side(self, which: Side) -> bytes | None:
        """The exact bytes of the *which* side; ``None`` when that side has no file."""
        text = self.base if which == 'base' else self.head
        return None if text is None else base64.b64decode(text, validate=True)


@dataclass(frozen=True)
class Bundle:
    """Everything a judge reads of one PR head that the forge cannot hand it directly (the module docstring)."""

    repo: str
    pr: int
    base_ref: str
    base_sha: str
    head_sha: str
    files: tuple[Changed, ...]
    version: int = VERSION


def blob_id(data: bytes) -> str:
    """The git blob id of *data*."""
    return hashlib.sha1(b'blob %d\0' % len(data) + data, usedforsecurity=False).hexdigest()


def is_binary(*sides: bytes | None) -> bool:
    """Whether any side holds a NUL in its first :data:`BINARY_PROBE` bytes -- the content decides, nothing else."""
    return any(data is not None and b'\0' in data[:BINARY_PROBE] for data in sides)


def _git(root: Path, *args: str, ok: tuple[int, ...] = (0,)) -> tuple[int, bytes]:
    """``git *args``'s exit code (one of *ok*) and exact stdout bytes; :class:`OSError` naming any other."""
    done = _door.run(['git', *args], cwd=root, capture_output=True, timeout=_GIT_TIMEOUT_S, check=False, env=git_env())
    if done.returncode not in ok:
        msg = f'git {" ".join(args)} failed: {done.stderr.decode("utf-8", "replace").strip()[:300]}'
        raise OSError(msg)
    return done.returncode, done.stdout


def _blob(root: Path, ident: str | None) -> bytes | None:
    return None if ident is None else _git(root, 'cat-file', 'blob', ident)[1]


def _raw(root: Path, base: str, head: str) -> list[tuple[str | None, str | None, str]]:
    """``(base blob, head blob, path)`` per changed file, renames split, gitlinks dropped."""
    fields = _git(root, 'diff', '--raw', '-z', '--no-renames', '--no-abbrev', base, head)[1].decode('utf-8').split('\0')
    rows = []
    for meta, path in zip(fields[0::2], fields[1::2], strict=False):
        old_mode, new_mode, old, new, _status = meta.lstrip(':').split(' ')
        if old_mode in BLOB_MODES or new_mode in BLOB_MODES:
            rows.append((None if NO_BLOB.fullmatch(old) else old, None if NO_BLOB.fullmatch(new) else new, path))
    return rows


def _changed(root: Path, old: str | None, new: str | None, path: str) -> Changed:
    sides = (_blob(root, ident) for ident in (old, new))
    base, head = (None if data is None else base64.b64encode(data).decode('ascii') for data in sides)
    return Changed(path, old, new, base, head)


def prepare(root: Path, *, repo: str, pull: PullRequest) -> Bundle:
    """The bundle of *pull*'s head against its merge base with ``origin/<pull.base>``, read from *root* (blobless)."""
    head = pull.head_sha
    merge_base = _git(root, 'merge-base', f'origin/{pull.base}', head)[1].decode('ascii').strip()
    rows = sorted(_raw(root, merge_base, head), key=lambda row: row[2])
    files = tuple(_changed(root, old, new, path) for old, new, path in rows)
    return Bundle(repo=repo, pr=pull.number, base_ref=pull.base, base_sha=merge_base, head_sha=head, files=files)


def fetched(root: Path, url: str, pull: PullRequest) -> Path:
    """A bare, blobless repository at *root* holding ``origin/<pull.base>`` and *pull*'s head, fetched from *url*.

    THE JUDGE PREPARES ITS OWN BUNDLE (D77): it fetches the head from the forge itself and builds the bundle with
    :func:`prepare`, so no CI job, artifact or pointer stands between the forge and the judge. THE HEAD IS UNTRUSTED
    AND NOTHING OF IT RUNS: the repository is bare (no tree is ever checked out, so no filter or attribute driver
    applies), created with an empty template and a hooks path that does not exist (no hook of any kind fires), never
    recurses into submodules, and admits only *url*'s own transport; :func:`prepare` then asks git for object ids
    and blob bytes alone. The forge's auth header is the one :func:`~dev_lab.dev.reviewgitauth.hold` holds.

    Raises:
        OSError: a git call failed, or the head the forge serves is not *pull*'s (it moved: retried next run).

    """
    root.mkdir(parents=True, exist_ok=True)
    scheme = url.split('://', 1)[0] if '://' in url else 'file'
    _git(root, 'init', '-q', '--bare', '--template=', '.')
    for key, value in (
        ('core.hooksPath', str(root / 'no-hooks')),
        ('submodule.recurse', 'false'),
        ('fetch.recurseSubmodules', 'false'),
        ('protocol.allow', 'never'),
        (f'protocol.{scheme}.allow', 'always'),
    ):
        _git(root, 'config', key, value)
    _git(root, 'remote', 'add', 'origin', url)
    _git(
        root, 'fetch', '-q', '--no-tags', '--no-recurse-submodules', '--filter=blob:none', 'origin',
        f'+refs/heads/{pull.base}:refs/remotes/origin/{pull.base}', f'+refs/pull/{pull.number}/head:refs/pull/head',
    )  # fmt: skip
    served = _git(root, 'rev-parse', 'refs/pull/head')[1].decode('ascii').strip()
    if served != pull.head_sha:
        msg = f'#{pull.number} moved: the forge serves {served[:12]}, not the listed {pull.head_sha[:12]}'
        raise OSError(msg)
    return root


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


def _parsed(data: bytes) -> Bundle:
    raw = json.loads(data)
    if raw.get('version') != VERSION:
        msg = f'bundle version {raw.get("version")!r} is not {VERSION}'
        raise BundleRefused(msg)
    raw['files'] = tuple(_checked(one) for one in raw['files'])
    return Bundle(**raw)


def load(data: bytes, digest: str) -> Bundle:
    """The bundle *data* holds, refused unless it hashes to *digest*, has the known shape, and each file is its blob."""
    if digest_of(data) != digest:
        msg = f'bundle hash {digest_of(data)} is not the published {digest}'
        raise BundleRefused(msg)
    try:
        return _parsed(data)
    except BundleRefused:
        raise
    except (ValueError, KeyError, TypeError, AttributeError) as bad:
        msg = f'the bundle is malformed: {type(bad).__name__}: {bad}'
        raise BundleRefused(msg) from None


def current(bundle: Bundle, pull: PullRequest, *, repo: str, merge_base: str) -> None:
    """Refuse *bundle* unless it is of *pull* -- the forge's answer, now -- at its head and the forge's *merge_base*."""
    if (bundle.repo, bundle.pr) != (repo, pull.number):
        msg = f'bundle is of pull {bundle.repo}#{bundle.pr}, not {repo}#{pull.number}'
        raise BundleRefused(msg)
    if bundle.base_ref != pull.base:
        msg = f'bundle base {bundle.base_ref!r} is not the pull base {pull.base!r}'
        raise BundleRefused(msg)
    if bundle.head_sha != pull.head_sha:
        msg = f'bundle head {bundle.head_sha[:12]} is stale: the pull head is {pull.head_sha[:12]}'
        raise BundleRefused(msg)
    if bundle.base_sha != merge_base:
        msg = f'bundle merge base {bundle.base_sha[:12]} is not the forge merge base {merge_base[:12]}'
        raise BundleRefused(msg)


def no_repo_env(tree: Path) -> dict[str, str]:
    """The environment overrides under which a git the judge's command starts finds no repository."""
    return {'GIT_DIR': str(tree / '.no-repository'), 'GIT_CEILING_DIRECTORIES': str(tree.parent)}


def _materialize(bundle: Bundle, diff: str, tree: Path) -> None:
    for one in bundle.files:
        if one.binary:
            continue
        for which in _SIDES:
            if (data := one.side(which)) is not None:
                dest = tree / which / one.path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
    (tree / 'diff.patch').write_bytes(diff.encode('utf-8'))
    (tree / 'bundle.json').write_bytes(_reviewer_doc(bundle))


def _reviewer_doc(bundle: Bundle) -> bytes:
    """The ``bundle.json`` the reviewer reads: the bundle, each file row carrying the judge's ``binary`` verdict.

    The reviewer (ai-lab's ``BundleSource``, which reads this :data:`VERSION`) never re-derives binary: it skips the
    file the judge did not write, by this flag, so the NUL probe (:func:`is_binary`) stays this module's alone.
    """
    doc = asdict(bundle)
    for row, one in zip(doc['files'], bundle.files, strict=True):
        row['binary'] = one.binary
    return json.dumps(doc, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def judge(
    bundle: Bundle, command: Sequence[str], *, diff: str, run: Callable[[tuple[str, ...], Mapping[str, str]], str]
) -> str:
    """The declared *command*'s output over *bundle* materialized as plain files (``{bundle}``: that directory).

    *diff* is the FORGE's diff of the PR (``diff.patch``), never the producer's. *run* starts the ONE process with
    the environment overrides it is handed (:func:`no_repo_env`). A command naming ``git`` is refused as a lint.
    """
    if any(PurePosixPath(arg.replace('\\', '/')).name.lower().removesuffix('.exe') == 'git' for arg in command):
        msg = f'the judge command {list(command)} runs git: a judge reads the bundle, never a checkout'
        raise BundleRefused(msg)
    if BUNDLE_FIELD not in command:
        msg = f'the judge command {list(command)} names no {BUNDLE_FIELD}: it would read no bundle'
        raise BundleRefused(msg)
    with tempfile.TemporaryDirectory(prefix=f'{TEMP_PREFIX}review-bundle-') as scratch:
        tree = Path(scratch) / 'bundle'
        tree.mkdir()
        _materialize(bundle, diff, tree)
        return run(tuple(str(tree) if arg == BUNDLE_FIELD else arg for arg in command), no_repo_env(tree))
