"""What a verdict is ABOUT -- a content address over the paths that were measured.

WHY THIS IS NOT A SHA AND NOT A GIT QUESTION. The stamp this replaces is ``HEAD + "-dirty"``, and
its limitation was MEASURED rather than argued: a run that reads a tree which MOVES underneath it
stamps the HEAD it started on, so the verdict names a commit that was never the input. Nothing in
a commit identifier can see that -- the identifier describes the repository, and the run describes
the FILES the suite actually imported. A content address is over exactly the second thing.

WHAT THE ADDRESS COVERS, stated here because a digest whose coverage is unstated is a number
nobody can check:

* the BYTE CONTENT of every file under the measured targets, at its path made RELATIVE to *root*
  (so the same content at a different absolute path on another machine addresses identically, and
  the same path with different content does not);
* the SORTED set of those (relative path, size, digest) triples, so reordering the caller's list
  cannot change the answer;
* a target that DOES NOT EXIST, recorded as ``absent``. Deletion is a change, and a walk that only
  sums what it finds would have read a deleted measured file as an unchanged tree -- the same
  silent-shrink shape the suite-side ratchets exist to refuse.

What it does NOT cover, said plainly so the gap is a finding rather than a surprise: file
PERMISSIONS and mtimes (two trees with identical bytes are the same tree for a verdict's purpose),
the git index, anything outside *root*, and any file under :data:`DEFAULT_IGNORES`.

WHY THE CARRIER IS A SUFFIXED DIGEST. The algorithm name rides in the returned string, so a stored
address that was computed under a different algorithm reads as a different address rather than as
a mismatch -- which is the failure mode where the honest-looking repair is to re-stamp everything.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Final

__all__ = ['ABSENT', 'DEFAULT_IGNORES', 'content_address', 'file_digest']

#: Names never measured, at ANY depth. They are VCS bookkeeping and interpreter caches: no build
#: reads them, and every one of them is rewritten by running the suite -- which would make the
#: address of an unchanged tree change for the sole reason that it was measured. The list is a
#: module CONSTANT rather than a parameter on purpose: an exclusion a caller can widen is a hole a
#: caller can widen, and a measured path silently dropped from an address is the defect this module
#: exists to make impossible.
DEFAULT_IGNORES: Final[tuple[str, ...]] = (
    '.git',
    '.hg',
    '.mypy_cache',
    '.pytest_cache',
    '.ruff_cache',
    '.ipynb_checkpoints',
    '__pycache__',
)

#: Suffixes never measured, for the same reason: a ``.pyc`` is the interpreter's copy of a source
#: whose content is ALREADY in the address.
_IGNORED_SUFFIXES: Final[tuple[str, ...]] = ('.pyc', '.pyo')

#: What an address records for a measured path that is not there. A word rather than an empty
#: string, so the record is legible in a disagreement dump and cannot collide with a real digest.
ABSENT: Final = 'absent'

_DIGEST_CHARS: Final = 16
_CHUNK: Final = 1 << 20


def file_digest(path: Path, *, algorithm: str = 'sha256') -> str:
    """The hex digest of one file's bytes, read in chunks so a large artifact is not slurped."""
    digest = hashlib.new(algorithm)
    with path.open('rb') as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _ignored(relative: Path) -> bool:
    """Whether *relative* is bookkeeping rather than measured source.

    Tested against EVERY PART, not just the leaf: a ``.git`` directory is pruned as a name, but its
    thousands of children have ordinary names, and a walk that checked only the leaf would measure
    the object database while reporting that it skipped the repository.
    """
    return any(part in DEFAULT_IGNORES for part in relative.parts) or relative.name.endswith(_IGNORED_SUFFIXES)


def _record(relative: Path, path: Path, algorithm: str) -> str:
    """One line of the address: ``<relative path>\\0<size>\\0<digest>``.

    The NUL separators are what make the line unambiguous: paths and digests are both text, and a
    space-joined record would let a path containing a space address the same as two files. The
    RELATIVE path is in the record because names are part of a tree's identity -- moving a function
    to another module is a change even when no byte of it moved.
    """
    return f'{relative.as_posix()}\0{path.stat().st_size}\0{file_digest(path, algorithm=algorithm)}'


def _iter_measured(base: Path, relative: Path, *, algorithm: str) -> Iterator[str]:
    """Every record *relative* contributes under *base*: itself, its walk, or ``absent``.

    TWO PATHS, because they answer two different questions and one of them is not a filesystem
    question at all: *base / relative* is what to READ, and *relative* is what to NAME in the
    address. Collapsing them would make the address depend on the process's working directory,
    which is the machine-specific fact the caller passed *root* to avoid.

    A directory that does not exist and a file that does not exist both record ``absent`` -- the
    question "did this path change" has one answer for a path that is gone, and splitting empty
    from missing would be a distinction the address does not need and a reader would misread.
    """
    absolute = base / relative
    if not absolute.exists():
        yield f'{relative.as_posix()}\0{ABSENT}'
        return
    if absolute.is_file():
        yield _record(relative, absolute, algorithm)
        return
    for child in sorted(absolute.rglob('*')):
        if not child.is_file():
            continue
        child_relative = relative / child.relative_to(absolute)
        if _ignored(child_relative):
            continue
        yield _record(child_relative, child, algorithm)


def content_address(
    root: Path,
    targets: Iterable[Path | str],
    *,
    algorithm: str = 'sha256',
    length: int = _DIGEST_CHARS,
) -> str:
    """The content address of the *targets*, as measured from *root*, as ``<algorithm>:<hex>``.

    *root* is what the targets are named RELATIVE to, so the address is a statement about a tree's
    layout and contents rather than about where that tree happens to sit on this disk. A target
    outside *root* is REFUSED rather than addressed absolutely: an absolute path would make the
    address machine-specific, which is the one property that makes it useless to a second reader.

    Raises:
        ValueError: a target is outside *root*, *length* names nothing, or nothing was measured.

    """
    if length <= 0:
        msg = f'a content address of {length} characters names nothing; a floor is required.'
        raise ValueError(msg)
    base = Path(root).resolve()
    measured: list[str] = []
    for target in targets:
        path = Path(target)
        candidate = path if path.is_absolute() else base / path
        resolved = candidate.resolve()
        if resolved != base and base not in resolved.parents:
            msg = (
                f'{path} is not under {base}, so it cannot be addressed RELATIVE to it. An address '
                f'keyed by an absolute path is a fact about one machine, and a verdict carrying one '
                f'cannot be checked by a reader who was not there.'
            )
            raise ValueError(msg)
        measured.extend(_iter_measured(base, resolved.relative_to(base), algorithm=algorithm))

    combined = hashlib.new(algorithm)
    for line in sorted(measured):
        combined.update(line.encode('utf-8'))
        combined.update(b'\n')
    # An address over NOTHING is refused rather than folded into a stable constant: "the tree did
    # not change" and "I measured no tree" would otherwise be the same string, which is the
    # vacuous-green shape one layer up from where it usually appears.
    if not measured:
        msg = (
            'no measured path produced a record, so there is nothing to address. An empty address '
            'is not a clean tree -- it is a run that measured nothing, and it would compare equal '
            'to every other run that measured nothing.'
        )
        raise ValueError(msg)
    return f'{algorithm}:{combined.hexdigest()[:length]}'
