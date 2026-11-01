"""MEMORY-SHAPE, the change half: memory is ADDED to -- never edited, deleted or moved away.

THE RULE (user rulings 2026-10-31, the four-layer plan). A memory entry is immutable once written: a
correction is a NEW entry naming the old one in ``corrects:``, and a consolidation is a NEW entry naming
its sources in ``merged_from:``. So a change touching ``**/.claude/memory/**`` may only ADD a file.
Two shapes are not edits:

* a task leaving the tasks layer -- ``git mv .claude/tasks/<slug> .claude/memory/...`` -- is how a
  closed task becomes history, and it is the one rename into memory;
* the one-shot four-layer migration, which removes only the volatile frontmatter fields
  (:data:`VOLATILE_FIELDS`) a reader used to rewrite on every read. A change whose ONLY difference is
  those lines is that migration and nothing else.

A MERGED ENTRY CITES. An added entry with ``merged_from:`` names sources that are memory files of its
OWN scope existing at the base the change is judged against, and every body paragraph names a source
file, so each claim keeps its evidence after the sources stop being read.

WHERE IT RUNS -- two family hook rows, so no route past it is left:

* ``commit`` (commit-msg, EVERY commit, a merge included): the INDEX against HEAD, so a plain commit and
  a merge's resolution are read alike (:func:`pending`);
* ``push`` (pre-push): every pushed ref's range since its merge-base with ``origin/<integration>``
  (:func:`problems_between`), so a commit made with the hook bypassed still reds before it leaves.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.lanepolicy import policy_at

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = ['VOLATILE_FIELDS', 'MemoryAddsError', 'main', 'merged_entry_problems', 'pending', 'problems_between']

#: Frontmatter fields the migration strips: per-read bookkeeping, never content.
VOLATILE_FIELDS = ('accessed', 'tier', 'count')

_GIT = shutil.which('git') or 'git'
_GIT_TIMEOUT_S = 120
_ZERO = '0' * 40
_REF_LINE_FIELDS: Final = 4  # git pre-push: <local ref> <local sha> <remote ref> <remote sha>
_MEMORY = '.claude/memory/'
_TASK = re.compile(r'(?:^|/)\.claude/tasks/[^/]+/')
_FRONTMATTER = re.compile(r'\A---\n(.*?)\n---(?:\n|\Z)', re.DOTALL)
_MERGED_FROM = re.compile(r'^merged_from:\s*(.*)$', re.MULTILINE)
_VOLATILE = re.compile(rf'^(?:{"|".join(VOLATILE_FIELDS)}):')
_CITATION = re.compile(r'[\w./-]*[\w-]\.(?:md|py|rs|mjs|js|ts|toml|json|txt|yaml|yml|csv)\b')


class MemoryAddsError(RuntimeError):
    """git could not be read, so nothing could be judged."""


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    done = _door.run([_GIT, '-C', str(root), *args], capture_output=True, check=False, timeout=_GIT_TIMEOUT_S)
    return done.returncode, done.stdout.decode('utf-8', 'replace'), done.stderr.decode('utf-8', 'replace').strip()


def _git(root: Path, *args: str) -> str:
    code, out, err = _run(root, *args)
    if code != 0:
        msg = f'git {" ".join(args)} failed: {err}'
        raise MemoryAddsError(msg)
    return out


def _is_memory(path: str) -> bool:
    return _MEMORY in f'/{path}'


def _scope(path: str) -> str:
    return f'/{path}'.split(f'/{_MEMORY}', 1)[0].lstrip('/')


def _lf(text: str) -> str:
    return text.replace('\r\n', '\n')


def _only_volatile_stripped(old: str, new: str) -> bool:
    old, new = _lf(old), _lf(new)
    match = _FRONTMATTER.match(old)
    if match is None or old == new:
        return False
    head = '\n'.join(line for line in match.group(1).splitlines() if not _VOLATILE.match(line))
    return f'---\n{head}\n---\n' + old[match.end() :] == new


def merged_entry_problems(path: str, text: str, exists: Callable[[str], bool] | None = None) -> tuple[str, ...]:
    """Why the entry at *path* (repo-relative) fails as a merge; *exists* says a source is at the base."""
    text = _lf(text)
    match = _FRONTMATTER.match(text)
    sources = _MERGED_FROM.search(match.group(1)) if match else None
    if sources is None:
        return ()
    scope = _scope(path)
    home = f'{scope}/{_MEMORY}' if scope else _MEMORY
    out: list[str] = []
    for source in re.findall(r'[^\s\[\],\'"]+', sources.group(1)):
        full = source if _is_memory(source) else home + source
        if '..' in source or _scope(full) != scope:
            out.append(f'{path}: merged_from {source} is not a memory file of the scope {home}')
        elif exists is not None and not exists(full):
            out.append(f'{path}: merged_from {source} does not exist at the base ({full})')
    in_fence = False
    for paragraph in re.split(r'\n\s*\n', text[match.end() :]):
        lines = [line for line in paragraph.strip().splitlines() if line.strip()]
        fences = sum(line.lstrip().startswith('```') for line in lines)
        prose = not in_fence and fences == 0 and lines and not all(line.startswith('#') for line in lines)
        in_fence ^= fences % 2 == 1
        if prose and not _CITATION.search(paragraph):
            out.append(f'{path}: a merged paragraph cites no source file: "{lines[0][:60]}"')
    return tuple(out)


def _changes(root: Path, *spec: str) -> list[tuple[str, str, str]]:
    """``(status, old, new)`` rows of ``git diff -M -C --name-status`` over *spec*."""
    fields = _git(root, 'diff', '-M', '-C', '--name-status', '-z', *spec).split('\0')
    rows: list[tuple[str, str, str]] = []
    while fields and fields[0]:
        status = fields.pop(0)
        old = fields.pop(0)
        new = fields.pop(0) if status[0] in 'RC' else old
        rows.append((status[0], old, new))
    return rows


def _judge(root: Path, old_rev: str, new_rev: str, rows: list[tuple[str, str, str]]) -> tuple[str, ...]:
    def exists(path: str) -> bool:
        return _run(root, 'cat-file', '-e', f'{old_rev}:{path}')[0] == 0

    out: list[str] = []
    for status, old, new in rows:
        if status in 'AC' and _is_memory(new):
            out.extend(merged_entry_problems(new, _git(root, 'show', f'{new_rev}:{new}'), exists))
        elif status == 'R' and _is_memory(new) and not _is_memory(old):
            if not _TASK.search(old):
                out.append(f'{new}: only a task (.claude/tasks/<slug>/) moves into memory, not {old}')
        elif status == 'M' and _is_memory(old):
            before, after = _git(root, 'show', f'{old_rev}:{old}'), _git(root, 'show', f'{new_rev}:{new}')
            if not _only_volatile_stripped(before, after):
                out.append(f'{old}: a memory entry is immutable -- write a new entry with `corrects:` instead')
        elif status in 'DRT' and _is_memory(old):
            out.append(f'{old}: a memory entry is never deleted or moved ({status})')
    return tuple(out)


def problems_between(root: Path, base: str, head: str) -> tuple[str, ...]:
    """What the commits of *head* since its merge-base with *base* do to memory beyond adding to it."""
    since = _git(root, 'merge-base', base, head).strip()
    return _judge(root, since, head, _changes(root, f'{since}...{head}'))


def pending(root: Path) -> tuple[str, ...]:
    """The commit being made in *root* -- plain or merge: the INDEX against HEAD (nothing before a first commit)."""
    if _run(root, 'rev-parse', '--verify', '-q', 'HEAD')[0] != 0:
        return ()
    tree = _git(root, 'write-tree').strip()
    return _judge(root, 'HEAD', tree, _not_as_upstream_holds(root, tree, _changes(root, 'HEAD', tree)))


def _not_as_upstream_holds(root: Path, tree: str, rows: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """*rows* without the paths staged EXACTLY as ``MERGE_HEAD`` or ``origin/<integration>`` holds them.

    Such a path is a change judged where it was made, not an edit by this commit -- two shapes, both measured
    2026-11-01 on a motronics lane:

    * a SYNC carries the integration line's history: an entry staged byte-for-byte as the merged side has it (or
      absent where that side deleted it). Reverting it to the lane's text would undo upstream inside the merge.
    * a RESTORE is the refusal's own remedy: an entry the lane once edited in place, put back to the integration
      line's text. Refusing it left the remedy uncommittable.

    A path staged as neither is still this commit's, and is judged.
    """
    differs: set[str] | None = None
    for ref in ('MERGE_HEAD', f'origin/{policy_at(root, "HEAD").integration}'):
        if _run(root, 'rev-parse', '--verify', '-q', ref)[0] != 0:
            continue
        against = set(_git(root, 'diff', '--no-renames', '--name-only', '-z', ref, tree).split('\0')) - {''}
        differs = against if differs is None else differs & against
    if differs is None:
        return rows
    return [(status, old, new) for status, old, new in rows if old in differs or new in differs]


def pushed(root: Path, ref_lines: str) -> tuple[str, ...]:
    """Git's pre-push stdin: each pushed sha judged since its merge-base with ``origin/<integration>``."""
    integration = f'origin/{policy_at(root, "HEAD").integration}'
    out: list[str] = []
    for line in ref_lines.splitlines():
        parts = line.split()
        if len(parts) != _REF_LINE_FIELDS or parts[1] == _ZERO:
            continue
        out.extend(problems_between(root, integration, parts[1]))
    return tuple(out)


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m dev_lab.dev.memoryadds commit [<msg-file>]`` or ``... push``; ``1`` refuses."""
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(_git(Path.cwd(), 'rev-parse', '--show-toplevel').strip())
    try:
        if args[:1] == ['commit']:
            problems = pending(root)
        elif args[:1] == ['push']:
            problems = pushed(root, sys.stdin.read())
        else:
            emit('memory-adds: usage: memoryadds commit [<msg-file>] | push', err=True)
            return 1
    except (MemoryAddsError, ValueError) as error:
        problems = (str(error),)
    if not problems:
        return 0
    lines = [
        f'memory-adds: {args[0]} REFUSED -- it edits, deletes or moves memory (MEMORY-SHAPE).',
        *(f'memory-adds:   {line}' for line in problems),
        'memory-adds: Remedy: restore each entry as it was; a correction is a NEW entry with `corrects:`.',
    ]
    emit('\n'.join(lines), err=True)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
