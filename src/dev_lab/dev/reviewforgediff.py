"""THE FORGE'S OWN DIFF, read: which paths and blobs it changes, so a review bundle can be held to it.

Split out of :mod:`dev_lab.dev.reviewbundle` (2026-11-20, MODULE-SIZE-ALARM) along its own seam: that module
prepares, loads and materializes a bundle; this one parses ``git diff`` headers as a forge renders them (quoted
paths, renames, copies, mode lines, gitlinks) and refuses a bundle whose paths or blob ids differ.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final

from dev_lab.dev.reviewbundle import NO_BLOB, Bundle, BundleRefused

__all__ = ['matches_forge']

_UNKNOWN: Final = '?'  # a forge section with no ``index`` line: the blob is unchanged, its id unsaid
_GITLINK: Final = '160000'
_INDEX: Final = re.compile(r'index ([0-9a-f]+)\.\.([0-9a-f]+)(?: ([0-7]+))?')
_MODE: Final = re.compile(r'(old mode|new mode|new file mode|deleted file mode) ([0-7]+)')
_MOVE: Final = re.compile(r'(rename|copy) (from|to) (.+)')
_OCTAL: Final = re.compile(r'[0-7]{3}')
_ESCAPES: Final = {'a': 7, 'b': 8, 't': 9, 'n': 10, 'v': 11, 'f': 12, 'r': 13, '"': 34, '\\': 92}
_BODY: Final = ('--- ', '+++ ', '@@', 'Binary files ', 'GIT binary patch')


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
    return mine is None if NO_BLOB.fullmatch(theirs) else mine is not None and mine.startswith(theirs)


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
