"""A REVIEW BUNDLE: what a PR's review reads, built where PR code runs and judged where it never does.

The review splits in two (user decision 2026-11-03, the forge-bot on its own host). PREPARE runs on the CI runner --
the untrusted side, holding no reviewer token -- and writes ONE deterministic JSON document: the exact bytes of only
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
* :func:`matches_forge` -- the forge's own diff names exactly the bundle's paths and blob ids (its headers parsed
  with git's C quoting, renames split as the bundle splits them, any header it cannot parse refused): the producer
  cannot omit a file or swap its content.

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

from dev_lab.dev.reviewgitauth import git_env
from dev_lab.dev.writeroots import TEMP_PREFIX

if TYPE_CHECKING:
    from dev_lab.dev._forge_records import PullRequest

__all__ = [
    'BINARY_PROBE',
    'BUNDLE_FIELD',
    'VERSION',
    'Bundle',
    'BundleRefused',
    'Changed',
    'blob_id',
    'current',
    'digest_of',
    'dump',
    'is_binary',
    'judge',
    'load',
    'matches_forge',
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
_NO_BLOB: Final = re.compile(r'0+')
_UNKNOWN: Final = '?'  # a forge section with no ``index`` line: the blob is unchanged, its id unsaid
_GITLINK: Final = '160000'
_BLOB_MODES: Final = frozenset({'100644', '100755', '120000'})
_INDEX: Final = re.compile(r'index ([0-9a-f]+)\.\.([0-9a-f]+)(?: ([0-7]+))?')
_MODE: Final = re.compile(r'(old mode|new mode|new file mode|deleted file mode) ([0-7]+)')
_MOVE: Final = re.compile(r'(rename|copy) (from|to) (.+)')
_OCTAL: Final = re.compile(r'[0-7]{3}')
_ESCAPES: Final = {'a': 7, 'b': 8, 't': 9, 'n': 10, 'v': 11, 'f': 12, 'r': 13, '"': 34, '\\': 92}
_BODY: Final = ('--- ', '+++ ', '@@', 'Binary files ', 'GIT binary patch')


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
        if old_mode in _BLOB_MODES or new_mode in _BLOB_MODES:
            rows.append((None if _NO_BLOB.fullmatch(old) else old, None if _NO_BLOB.fullmatch(new) else new, path))
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


def _unquote(text: str, at: int) -> tuple[str, int]:
    """Git's C-quoted string opening at ``text[at]``: its value and the index past its closing quote."""
    out, i = bytearray(), at + 1
    while i < len(text):
        char = text[i]
        if char == '"':
            return out.decode('utf-8'), i + 1
        if char == '\\' and text[i + 1 : i + 2] in _ESCAPES:
            out.append(_ESCAPES[text[i + 1]])
            i += 2
        elif char == '\\' and _OCTAL.fullmatch(text[i + 1 : i + 4]):
            out.append(int(text[i + 1 : i + 4], 8))
            i += 4
        elif char == '\\':
            msg = f'a quoted path holds an unknown escape: {text[:200]!r}'
            raise BundleRefused(msg)
        else:
            out += char.encode('utf-8')
            i += 1
    msg = f'an unterminated quoted path: {text[:200]!r}'
    raise BundleRefused(msg)


def _token(text: str) -> str:
    """One whole path token, C-quoted or bare."""
    if not text.startswith('"'):
        return text
    value, end = _unquote(text, 0)
    if end != len(text):
        msg = f'trailing text after a quoted path: {text[:200]!r}'
        raise BundleRefused(msg)
    return value


def _header_paths(rest: str) -> tuple[str, str] | None:
    """``(a, b)`` of a ``diff --git`` header's remainder, prefixes stripped; ``None`` when it is ambiguous."""
    if rest.startswith('"'):
        first, end = _unquote(rest, 0)
        if rest[end : end + 1] != ' ':
            return None
        second = _token(rest[end + 1 :])
    elif ' "' in rest:  # a bare path never holds a quote (git would have quoted it)
        cut = rest.index(' "')
        first, second = rest[:cut], _token(rest[cut + 1 :])
    else:  # ``a/P b/P``: the one split where both sides name the same path
        size = (len(rest) - 5) // 2
        first, second = rest[: 2 + size], rest[3 + size :]
        if len(rest) % 2 == 0 or first[2:] != second[2:]:
            return None
    if not (first.startswith('a/') and second.startswith('b/')):
        return None
    return first[2:], second[2:]


def _extended(lines: Sequence[str]) -> tuple[dict[str, str], set[str], re.Match[str] | None]:
    """A section's extended header: its mode, rename and copy lines by name, every mode it names, its index."""
    said: dict[str, str] = {}
    modes: set[str] = set()
    index = None
    for line in lines[1:]:
        if line.startswith(_BODY):
            break
        if found := _MODE.fullmatch(line):
            modes.add(found.group(2))
            said[found.group(1)] = found.group(2)
        elif found := _INDEX.fullmatch(line):
            index = found
            modes.update(filter(None, [found.group(3)]))
        elif found := _MOVE.fullmatch(line):
            said[f'{found.group(1)} {found.group(2)}'] = _token(found.group(3))
    return said, modes, index


def _section(lines: Sequence[str]) -> tuple[dict[str, tuple[str, str]], list[tuple[str, str]]]:
    """One ``diff --git`` section's ``{path: (base id, head id)}`` and the ``(base path, head path)`` blob pairs.

    Renames split into a deletion and an addition, as the bundle's ``--no-renames`` holds them; a gitlink is no
    entry; a copy is refused. A section without an ``index`` line keeps its blob: :data:`_UNKNOWN`, paired.
    """
    said, modes, index = _extended(lines)
    if _GITLINK in modes:
        return {}, []
    if 'copy from' in said or 'copy to' in said:
        msg = f'the forge diff reports a copy the bundle cannot verify: {lines[0][:200]!r}'
        raise BundleRefused(msg)
    old = '0' if 'new file mode' in said else index.group(1) if index else _UNKNOWN
    new = '0' if 'deleted file mode' in said else index.group(2) if index else _UNKNOWN
    if 'rename from' in said and 'rename to' in said:
        source, target = said['rename from'], said['rename to']
        return {source: (old, '0'), target: ('0', new)}, [] if index else [(source, target)]
    paths = _header_paths(lines[0].removeprefix('diff --git '))
    if paths is None or paths[0] != paths[1]:
        msg = f'the forge diff has a header this judge cannot parse: {lines[0][:200]!r}'
        raise BundleRefused(msg)
    return {paths[0]: (old, new)}, [] if index else [(paths[0], paths[0])]


def _named(diff: str) -> tuple[dict[str, tuple[str, str]], list[tuple[str, str]]]:
    """Every section of a unified diff: ``{path: (base id, head id)}`` (ids maybe abbreviated) and its blob pairs."""
    lines = diff.split('\n')
    starts = [at for at, line in enumerate(lines) if line.startswith('diff --git ')]
    named: dict[str, tuple[str, str]] = {}
    pairs: list[tuple[str, str]] = []
    for at, end in zip(starts, [*starts[1:], len(lines)], strict=True):
        entries, linked = _section(lines[at:end])
        if overlap := set(entries) & set(named):
            msg = f'the forge diff names {sorted(overlap)} twice'
            raise BundleRefused(msg)
        named.update(entries)
        pairs += linked
    return named, pairs


def _same(theirs: str, mine: str | None) -> bool:
    """One forge id (maybe abbreviated; all zeros for no file; :data:`_UNKNOWN` for unsaid) names the blob *mine*."""
    if theirs == _UNKNOWN:
        return mine is not None
    return mine is None if _NO_BLOB.fullmatch(theirs) else mine is not None and mine.startswith(theirs)


def matches_forge(bundle: Bundle, forge_diff: str) -> None:
    """Refuse *bundle* unless the forge's own diff of the PR names exactly the same paths and blobs."""
    theirs, pairs = _named(forge_diff)
    ours = {one.path: one for one in bundle.files}
    if sorted(theirs) != sorted(ours):
        msg = f'the forge diff changes {sorted(theirs)}; the bundle holds {sorted(ours)}'
        raise BundleRefused(msg)
    for path, (base_id, head_id) in theirs.items():
        mine = ours[path]
        if not (_same(base_id, mine.base_blob) and _same(head_id, mine.head_blob)):
            ids = f'{mine.base_blob}..{mine.head_blob}'
            msg = f'{path}: the forge diff names blobs {base_id}..{head_id}, the bundle {ids}'
            raise BundleRefused(msg)
    for source, target in pairs:
        if ours[source].base_blob != ours[target].head_blob:
            msg = f'{source} -> {target}: the forge diff keeps the blob, the bundle changes it'
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
    (tree / 'bundle.json').write_bytes(dump(bundle)[0])


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
