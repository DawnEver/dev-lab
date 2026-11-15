"""MEMORY-SHAPE, the change half: memory is ADDED to -- never edited, deleted or moved away.

THE RULE (user rulings 2026-10-31, the four-layer plan). A memory entry is immutable once written: a
correction is a NEW entry naming the old one in ``corrects:``, and a consolidation is a NEW entry naming
its sources in ``merged_from:``. So a change touching ``**/.claude/memory/**`` may only ADD a file.
Three shapes are not narrative edits:

* a task leaving the tasks layer -- ``git mv .claude/tasks/<slug> .claude/memory/...`` -- is how a
  closed task becomes history, and it is the one rename into memory;
* the one-shot four-layer migration, which removes only the volatile frontmatter fields
  (:data:`dev_lab.dev.memoryentry.VOLATILE_FIELDS`) a reader used to rewrite on every read. A change
  whose ONLY difference is those lines is that migration and nothing else;
* rem's dedicated dated manual task list: append tasks or toggle existing checkboxes, never
  rewrite task text or turn narrative memory into a task list. Both versions must match the format.

The task-list protocol is authored by rem 2.2.0, ``scripts/task-engine.js`` functions ``handleAdd``
and ``handleMark``. This classifier recognizes that version's complete output, not arbitrary Markdown.
If its producer changes format, update this boundary and its planted controls together; never
broaden narrative-memory admission to make a malformed manual file pass.

A MERGED ENTRY CITES. An added entry with ``merged_from:`` names sources that are memory files of its
OWN scope existing at the base the change is judged against or added by that same change, and every
body paragraph names a source file, so each claim keeps its evidence after the sources stop being read.

WHERE IT RUNS -- two family hook rows, so no route past it is left:

* ``commit`` (commit-msg, EVERY commit, a merge included): the INDEX against HEAD, so a plain commit and
  a merge's resolution are read alike (:func:`pending`); an entry not yet on ``origin/<integration>`` is a
  draft its author may still edit or delete. The branch is named by HEAD's manifest, else -- a first adoption --
  by the commit's own staged one; with neither, nothing is published yet;
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
from lab_commons.hpc.declared import pyproject_at
from lab_commons.log import emit

from dev_lab.dev.lanepolicy import policy_at, policy_from
from dev_lab.dev.memoryentry import (
    AMENDMENT_NOTE,
    MANUAL_PATH,
    MANUAL_ROW,
    is_memory,
    merged_entry_problems,
    only_amended,
    only_manual_tasks_updated,
    only_redacted,
    only_volatile_stripped,
    shape_problems,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    'MemoryAddsError',
    'main',
    'pending',
    'problems_between',
]

_GIT = shutil.which('git') or 'git'
_GIT_TIMEOUT_S = 120
_ZERO = '0' * 40
_EMPTY_TREE: Final = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'  # git's empty tree: the base before a first push
_REF_LINE_FIELDS: Final = 4  # git pre-push: <local ref> <local sha> <remote ref> <remote sha>
_TASK = re.compile(r'(?:^|/)\.claude/tasks/[^/]+/')


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
    added = {new for status, _, new in rows if status in 'AC'}

    def exists(path: str) -> bool:
        """A source is at the base, or ADDED by the same change -- a merge and its sources may land together."""
        return path in added or _run(root, 'cat-file', '-e', f'{old_rev}:{path}')[0] == 0

    out: list[str] = []
    for status, old, new in rows:
        if status in 'AC' and is_memory(new):
            text = _git(root, 'show', f'{new_rev}:{new}')
            out.extend((*shape_problems(new, text), *merged_entry_problems(new, text, exists)))
        elif status == 'R' and is_memory(new) and not is_memory(old):
            if not _TASK.search(old):
                out.append(f'{new}: only a task (.claude/tasks/<slug>/) moves into memory, not {old}')
        elif status == 'M' and is_memory(old):
            before, after = _git(root, 'show', f'{old_rev}:{old}'), _git(root, 'show', f'{new_rev}:{new}')
            if not (
                only_volatile_stripped(before, after)
                or only_manual_tasks_updated(old, before, after)
                or only_redacted(before, after)
                or only_amended(before, after)
            ):
                remedy = (
                    'a memory entry is immutable -- write a new entry with `corrects:` instead; a line that is WRONG '
                    'is corrected in place only with the user-approved note `> '
                    + AMENDMENT_NOTE.format(day='<yyyy-mm-dd>', reason='<why>', approved="<the user's words>")
                    + '` and lines replaced one-for-one, or only the missing name/description frontmatter added'
                )
                if MANUAL_PATH.search(old):
                    remedy += (
                        '; rem 2.2.0 task-list format/operation check failed: append tasks or toggle checkboxes '
                        'without changing existing task text, module or order'
                    )
                out.append(f'{old}: {remedy}')
        elif status in 'DRT' and is_memory(old):
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
    into = _integration(root, tree)
    rows = _published_only(root, tree, into, _not_as_upstream_holds(root, tree, into, _changes(root, 'HEAD', tree)))
    return _judge(root, 'HEAD', tree, rows)


def _integration(root: Path, tree: str) -> str | None:
    """The integration branch HEAD's manifest names, else the staged *tree*'s -- a first adoption's own.

    ``None`` when neither carries a ``pyproject.toml``: nothing names a branch, so nothing is published yet. A
    manifest that exists and names no branch is refused (:func:`~dev_lab.dev.lanepolicy.policy_from`).
    """
    for rev in ('HEAD', tree):
        if text := pyproject_at(root, rev):
            return policy_from(text, f'{rev}:pyproject.toml').integration
    return None


def _published_only(
    root: Path, tree: str, into: str | None, rows: list[tuple[str, str, str]]
) -> list[tuple[str, str, str]]:
    """*rows* without edits, deletions and moves of a memory entry not yet on ``origin/<integration>``.

    Immutability starts when an entry is PUBLISHED: one added in an unpushed range is still a draft, and its
    author may cite, fix or drop it. The exemption covers ONLY that immutability rule for an ordinary entry:
    a rem task list (``manual.md``) and an entry whose new text is task-shaped stay judged, because the
    task-format and injection rules hold for drafts too. An entry the integration ref holds stays judged;
    without that ref nothing is a draft.
    """
    ref = f'origin/{into}'
    if into is None or _run(root, 'rev-parse', '--verify', '-q', ref)[0] != 0:
        return rows

    def draft(status: str, old: str, new: str) -> bool:
        if status not in 'MDRT' or not is_memory(old) or MANUAL_PATH.search(old) or MANUAL_PATH.search(new):
            return False
        if status in 'MRT' and MANUAL_ROW.search(_git(root, 'show', f'{tree}:{new}')):
            return False
        return _run(root, 'cat-file', '-e', f'{ref}:{old}')[0] != 0

    return [(status, old, new) for status, old, new in rows if not draft(status, old, new)]


def _not_as_upstream_holds(
    root: Path, tree: str, into: str | None, rows: list[tuple[str, str, str]]
) -> list[tuple[str, str, str]]:
    """*rows* without the paths staged EXACTLY as ``MERGE_HEAD`` or ``origin/<integration>`` holds them.

    Such a path is a change judged where it was made, not an edit by this commit -- two shapes, both measured
    2026-11-01 on a consumer lane:

    * a SYNC carries the integration line's history: an entry staged byte-for-byte as the merged side has it (or
      absent where that side deleted it). Reverting it to the lane's text would undo upstream inside the merge.
    * a RESTORE is the refusal's own remedy: an entry the lane once edited in place, put back to the integration
      line's text. Refusing it left the remedy uncommittable.

    A path staged as neither is still this commit's, and is judged.
    """
    differs: set[str] | None = None
    for ref in ('MERGE_HEAD', *(() if into is None else (f'origin/{into}',))):
        if _run(root, 'rev-parse', '--verify', '-q', ref)[0] != 0:
            continue
        against = set(_git(root, 'diff', '--no-renames', '--name-only', '-z', ref, tree).split('\0')) - {''}
        differs = against if differs is None else differs & against
    if differs is None:
        return rows
    return [(status, old, new) for status, old, new in rows if old in differs or new in differs]


def pushed(root: Path, ref_lines: str) -> tuple[str, ...]:
    """Git's pre-push stdin: each pushed sha judged since its merge-base with ``origin/<integration>``.

    Before the push that founds a repo, origin holds no integration ref and so no published entry: the
    whole pushed history is judged from the empty tree, where every memory path is an add.
    """
    integration = f'origin/{policy_at(root, "HEAD").integration}'
    founded = _run(root, 'rev-parse', '--verify', '-q', f'{integration}^{{commit}}')[0] == 0
    out: list[str] = []
    for line in ref_lines.splitlines():
        parts = line.split()
        if len(parts) != _REF_LINE_FIELDS or parts[1] == _ZERO:
            continue
        if founded:
            out.extend(problems_between(root, integration, parts[1]))
        else:
            out.extend(_judge(root, _EMPTY_TREE, parts[1], _changes(root, _EMPTY_TREE, parts[1])))
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
        (
            f'memory-adds: {args[0]} REFUSED -- it edits, deletes or moves memory, or adds a misshapen entry '
            '(MEMORY-SHAPE).'
        ),
        *(f'memory-adds:   {line}' for line in problems),
        (
            'memory-adds: Remedy: restore each entry as it was; a correction is a NEW entry with `corrects:`; '
            'an added entry declares its name and description.'
        ),
    ]
    emit('\n'.join(lines), err=True)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
