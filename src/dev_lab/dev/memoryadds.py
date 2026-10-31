"""MEMORY-SHAPE, the merge half: memory is ADDED to -- never edited, deleted or moved away.

THE RULE (user rulings 2026-10-31, the four-layer plan). A memory entry is immutable once written: a
correction is a NEW entry naming the old one in ``corrects:``, and a consolidation is a NEW entry naming
its sources in ``merged_from:``. So a change touching ``**/.claude/memory/**`` may only ADD a file.
Two shapes are not edits:

* a task leaving the tasks layer -- ``git mv .claude/tasks/<slug> .claude/memory/...`` -- is how a
  closed task becomes history, and it is the one rename into memory;
* the one-shot four-layer migration, which removes only the volatile frontmatter fields
  (:data:`VOLATILE_FIELDS`) a reader used to rewrite on every read. A change whose ONLY difference is
  those lines is that migration and nothing else.

A MERGED ENTRY CITES. An added entry with ``merged_from:`` stays within ONE scope (every source sits
under the entry's own ``.claude/memory/``) and every body paragraph names a source file, so each
claim keeps its evidence after the sources stop being read.

WHERE IT RUNS. :func:`pending` judges the merge being committed (the ``commit-msg`` hook, beside
:mod:`dev_lab.dev.mergeaudit`): the INDEX against the first parent, so both what the merge brings in
and what its resolution rewrote are read. :func:`problems_between` judges a lane against its base
(``base...head``).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import lab_commons.launch as _door

__all__ = ['VOLATILE_FIELDS', 'MemoryAddsError', 'merged_entry_problems', 'pending', 'problems_between']

#: Frontmatter fields the migration strips: per-read bookkeeping, never content.
VOLATILE_FIELDS = ('accessed', 'tier', 'count')

_GIT = shutil.which('git') or 'git'
_GIT_TIMEOUT_S = 120
_MEMORY = '.claude/memory/'
_TASK = re.compile(r'(?:^|/)\.claude/tasks/[^/]+/')
_FRONTMATTER = re.compile(r'\A---\r?\n(.*?)\r?\n---\r?\n?', re.DOTALL)
_MERGED_FROM = re.compile(r'^merged_from:\s*(.*)$', re.MULTILINE)
_VOLATILE = re.compile(rf'^(?:{"|".join(VOLATILE_FIELDS)}):')
_CITATION = re.compile(r'[\w./-]*[\w-]\.(?:md|py|rs|mjs|js|ts|toml|json|txt|yaml|yml|csv)\b')


class MemoryAddsError(RuntimeError):
    """git could not be read, so nothing could be judged."""


def _git(root: Path, *args: str) -> str:
    done = _door.run([_GIT, '-C', str(root), *args], capture_output=True, check=False, timeout=_GIT_TIMEOUT_S)
    if done.returncode != 0:
        msg = f'git {" ".join(args)} failed: {done.stderr.decode("utf-8", "replace").strip()}'
        raise MemoryAddsError(msg)
    return done.stdout.decode('utf-8', 'replace')


def _is_memory(path: str) -> bool:
    return _MEMORY in f'/{path}'


def _scope(path: str) -> str:
    return f'/{path}'.split(f'/{_MEMORY}', 1)[0].lstrip('/')


def _only_volatile_stripped(old: str, new: str) -> bool:
    match = _FRONTMATTER.match(old)
    if match is None:
        return False
    head = '\n'.join(line for line in match.group(1).splitlines() if not _VOLATILE.match(line))
    return old != new and f'---\n{head}\n---\n' + old[match.end() :] == new.replace('\r\n', '\n')


def merged_entry_problems(path: str, text: str) -> tuple[str, ...]:
    """Why the entry at *path* (repo-relative) fails as a merge: out-of-scope sources, uncited paragraphs."""
    match = _FRONTMATTER.match(text)
    sources = _MERGED_FROM.search(match.group(1)) if match else None
    if sources is None:
        return ()
    scope = _scope(path)
    out = [
        f'{path}: merged_from {source} is outside the scope {scope or "<root>"}/{_MEMORY}'
        for source in re.findall(r'[^\s\[\],\'"]+', sources.group(1))
        if '..' in source or (_MEMORY in f'/{source}' and _scope(source) != scope)
    ]
    body = text[match.end() :] if match else text
    in_fence = False
    for paragraph in re.split(r'\n\s*\n', body.replace('\r\n', '\n')):
        lines = [line for line in paragraph.strip().splitlines() if line.strip()]
        fences = sum(line.lstrip().startswith('```') for line in lines)
        prose = not in_fence and fences == 0 and lines and not all(line.startswith('#') for line in lines)
        in_fence ^= fences % 2 == 1
        if prose and not _CITATION.search(paragraph):
            out.append(f'{path}: a merged paragraph cites no source file: "{lines[0][:60]}"')
    return tuple(out)


def _changes(root: Path, *spec: str) -> list[tuple[str, str, str]]:
    """``(status, old, new)`` rows of ``git diff -M --name-status`` over *spec*."""
    fields = _git(root, 'diff', '-M', '--name-status', '-z', *spec).split('\0')
    rows: list[tuple[str, str, str]] = []
    while fields and fields[0]:
        status = fields.pop(0)
        old = fields.pop(0)
        new = fields.pop(0) if status[0] in 'RC' else old
        rows.append((status[0], old, new))
    return rows


def _judge(root: Path, old_rev: str, new_rev: str, rows: list[tuple[str, str, str]]) -> tuple[str, ...]:
    out: list[str] = []
    for status, old, new in rows:
        if status == 'A' and _is_memory(new):
            out.extend(merged_entry_problems(new, _git(root, 'show', f'{new_rev}:{new}')))
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
    """The merge being committed in *root*: the INDEX against HEAD; empty when no merge is in progress."""
    merge_head = Path(root) / _git(root, 'rev-parse', '--git-path', 'MERGE_HEAD').strip()
    if not merge_head.is_file():
        return ()
    tree = _git(root, 'write-tree').strip()
    return _judge(root, 'HEAD', tree, _changes(root, 'HEAD', tree))
