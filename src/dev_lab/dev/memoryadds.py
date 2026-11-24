"""MEMORY-SHAPE, the change half: memory is ADDED to -- never edited, deleted or moved away.

THE RULE (user rulings 2026-10-31, the four-layer plan). A memory entry is immutable once written: a
correction is a NEW entry naming the old one in ``corrects:``, and a consolidation is a NEW entry naming
its sources in ``merged_from:``. So a change touching ``**/.claude/memory/**`` may only ADD a file.
Three shapes are not narrative edits (nothing is ever renamed INTO memory: a closed task is archived in the
global tasks repo by the task door, :func:`dev_lab.dev.taskledger.ledger`, user ruling 2026-11-23):

* the one-shot four-layer migration, which removes only the volatile frontmatter fields
  (:data:`dev_lab.dev.memoryentry.VOLATILE_FIELDS`) a reader used to rewrite on every read. A change
  whose ONLY difference is those lines is that migration and nothing else;
* an approved redacting rename (REDACTING-RENAME, user ruling 2026-11-14) -- the one move WITHIN memory: an
  account-like token leaves a published entry's file name, in the same directory, one run of the name's
  ``-`` tokens replaced by ``user`` or dropped, and the entry gains an amendment note whose reason says
  ``renamed`` (:func:`dev_lab.dev.memoryentry.only_renamed_redacting`). Git reads it as ``R`` or, when the
  text changed too, as ``D`` + ``A``; both are judged as the rename (:func:`_without_redacting_renames`);
* an approved attachment deletion (ATTACHMENT-DELETE, user ruling 2026-11-24) -- an ATTACHMENT (a memory file
  that is not an entry, :func:`dev_lab.dev.memoryentry.is_attachment`) leaves memory when the same pushed range
  adds an amendment note to an entry whose reason says ``deleted`` and names it under ``.claude/memory/``, with
  the user's words (:func:`dev_lab.dev.memoryentry.deletion_approved`); without one the deletion is refused by
  name. An entry is never deleted.

A MERGED ENTRY CITES. An added entry with ``merged_from:`` names sources that are memory files of its
OWN scope existing at the base the change is judged against or added by that same change, and every
body paragraph names a source file, so each claim keeps its evidence after the sources stop being read.

WHERE IT RUNS -- ONE family hook row, at the act that PUBLISHES: ``pre-push`` judges every pushed ref's range
since its merge-base with ``origin/<integration>`` (:func:`problems_between`). Immutability starts at publication,
and the range is what this push would publish, judged net: an entry the range adds and then edits or drops is a
draft (an add, or nothing), a restore to the integration line's text is no change, and a sync's merge-base moves
past what upstream changed -- so no exemption is needed for any of them. Every route a commit can take -- a plain
commit, a merge, a rebase, a cherry-pick, a commit made with the hook off -- reaches the push, which a commit-time
row never saw. A memory blob an ``origin`` ref already holds is published there, not added by the range, and is not
judged again.

An archived task directory (a ``TASK.md`` declaring ``kind: task``) is ONE entry: the files beside its TASK.md
need no frontmatter of their own.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.lanepolicy import policy_at
from dev_lab.dev.memoryentry import (
    AMENDMENT_NOTE,
    MEMORY_DIR,
    amendment_notes,
    deletion_approved,
    is_attachment,
    is_memory,
    merged_entry_problems,
    only_amended,
    only_redacted,
    only_renamed_redacting,
    only_volatile_stripped,
    shape_problems,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    'MemoryAddsError',
    'main',
    'problems_between',
    'pushed',
]

_GIT = shutil.which('git') or 'git'
_GIT_TIMEOUT_S = 120
_ZERO = '0' * 40
_EMPTY_TREE: Final = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'  # git's empty tree: the base before a first push
_REF_LINE_FIELDS: Final = 4  # git pre-push: <local ref> <local sha> <remote ref> <remote sha>


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


def _without_redacting_renames(
    root: Path, old_rev: str, new_rev: str, rows: list[tuple[str, str, str]]
) -> list[tuple[str, str, str]]:
    """*rows* without the memory moves that are admitted redacting renames, as ``R`` or as ``D`` + ``A``."""

    def admitted(old: str, new: str) -> bool:
        before, after = _git(root, 'show', f'{old_rev}:{old}'), _git(root, 'show', f'{new_rev}:{new}')
        return only_renamed_redacting(old, new, before, after)

    renamed = {(old, new) for status, old, new in rows if status == 'R' and is_memory(old) and admitted(old, new)}
    gone = [old for status, old, _ in rows if status == 'D' and is_memory(old)]
    for new in (new for status, _, new in rows if status == 'A' and is_memory(new)):
        old = next((old for old in gone if admitted(old, new)), None)
        if old is not None:
            gone.remove(old)
            renamed.add((old, new))
    olds, news = {old for old, _ in renamed}, {new for _, new in renamed}
    return [
        (status, old, new)
        for status, old, new in rows
        if not ((status in 'RD' and old in olds) or (status in 'RA' and new in news))
    ]


def _judge(root: Path, old_rev: str, new_rev: str, rows: list[tuple[str, str, str]]) -> tuple[str, ...]:
    rows = _without_redacting_renames(root, old_rev, new_rev, rows)
    added = {new for status, _, new in rows if status in 'AC'}

    def exists(path: str) -> bool:
        """A source is at the base, or ADDED by the same change -- a merge and its sources may land together."""
        return path in added or _run(root, 'cat-file', '-e', f'{old_rev}:{path}')[0] == 0

    out = list(_unapproved_deletions(root, old_rev, new_rev, rows))
    for status, old, new in rows:
        if status in 'AC' and is_memory(new):
            text = _git(root, 'show', f'{new_rev}:{new}')
            out.extend((*shape_problems(new, text), *merged_entry_problems(new, text, exists)))
        elif status == 'R' and is_memory(new) and not is_memory(old):
            out.append(
                f'{new}: nothing moves into memory, not {old}; write a new entry instead (a closed task is '
                'archived in the global tasks repo by `python -m dev_lab.dev.task close`, never in a checkout)'
            )
        elif status == 'M' and is_memory(old):
            before, after = _git(root, 'show', f'{old_rev}:{old}'), _git(root, 'show', f'{new_rev}:{new}')
            if not (
                only_volatile_stripped(before, after) or only_redacted(before, after) or only_amended(before, after)
            ):
                remedy = (
                    'a memory entry is immutable -- write a new entry with `corrects:` instead; a line that is WRONG '
                    'is corrected in place only with the user-approved note `> '
                    + AMENDMENT_NOTE.format(day='<yyyy-mm-dd>', reason='<why>', approved="<the user's words>")
                    + '` and lines replaced one-for-one, or only the missing name/description frontmatter added'
                )
                out.append(f'{old}: {remedy}')
        elif status in 'DRT' and is_memory(old) and not (status == 'D' and is_attachment(old)):
            out.append(f'{old}: a memory entry is never deleted or moved ({status})')
    return tuple(out)


def _unapproved_deletions(root: Path, old_rev: str, new_rev: str, rows: list[tuple[str, str, str]]) -> tuple[str, ...]:
    """ATTACHMENT-DELETE: each deleted attachment no amendment note the range adds approves, refused by name."""
    deleted = [old for status, old, _ in rows if status == 'D' and is_attachment(old)]
    if not deleted:
        return ()
    notes = _added_notes(root, old_rev, new_rev, rows)
    return tuple(
        f'{old}: a memory attachment is deleted only with approval (ATTACHMENT-DELETE) -- amend an entry with the '
        'user-approved note `> '
        + AMENDMENT_NOTE.format(day='<yyyy-mm-dd>', reason='deleted <attachment> <why>', approved="<the user's words>")
        + f'` naming {old.split(MEMORY_DIR, 1)[1]} in the same push'
        for old in deleted
        if not deletion_approved(old, notes)
    )


def _added_notes(root: Path, old_rev: str, new_rev: str, rows: list[tuple[str, str, str]]) -> set[str]:
    """The amendment note lines the range ADDS to memory entries: a note the base already held approves nothing."""
    out: set[str] = set()
    for status, old, new in rows:
        if status in 'ACM' and is_memory(new) and new.endswith('.md'):
            before = _git(root, 'show', f'{old_rev}:{old}') if status == 'M' else ''
            out |= amendment_notes(_git(root, 'show', f'{new_rev}:{new}')) - amendment_notes(before)
    return out


def problems_between(root: Path, base: str, head: str) -> tuple[str, ...]:
    """What the commits of *head* since its merge-base with *base* do to memory beyond adding to it.

    A memory path *head* holds byte-identical to an ``origin`` ref is published, not this range's: never re-judged.
    """
    since = _git(root, 'merge-base', base, head).strip()
    rows = _changes(root, f'{since}...{head}')
    published = _published(root, head, rows)
    return _judge(root, since, head, [row for row in rows if row[0] not in 'ACM' or row[2] not in published])


def _published(root: Path, head: str, rows: list[tuple[str, str, str]]) -> set[str]:
    """Memory paths whose blob in *head* is byte-identical to the one some ``origin`` ref holds.

    Such a path was judged where it was published; a range that carries it (a merge-base fallen back past an
    integration merge commit, #6602) neither adds nor edits it.
    """
    paths = sorted({new for status, _, new in rows if status in 'ACM' and is_memory(new)})
    refs = _git(root, 'for-each-ref', '--format=%(refname)', 'refs/remotes/origin').split()
    if not paths or not refs:
        return set()
    queries = [f'{rev}:{path}' for rev in (head, *refs) for path in paths]
    done = _door.run(
        [_GIT, '-C', str(root), 'cat-file', '--batch-check=%(objectname)'],
        input='\n'.join(queries).encode('utf-8'),
        capture_output=True,
        check=False,
        timeout=_GIT_TIMEOUT_S,
    )
    if done.returncode != 0:
        msg = f'git cat-file --batch-check failed: {done.stderr.decode("utf-8", "replace").strip()}'
        raise MemoryAddsError(msg)
    blobs = [line.split()[0] for line in done.stdout.decode('utf-8', 'replace').splitlines()]
    ours = dict(zip(paths, blobs[: len(paths)], strict=True))
    held = {(paths[i % len(paths)], blob) for i, blob in enumerate(blobs[len(paths) :])}
    return {path for path, blob in ours.items() if (path, blob) in held}


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
    """``python -m dev_lab.dev.memoryadds``: git's pre-push ref lines on stdin; ``1`` refuses the push."""
    del argv  # git's remote name and url; the judgement reads origin/<integration>
    root = Path(_git(Path.cwd(), 'rev-parse', '--show-toplevel').strip())
    try:
        problems = pushed(root, '' if sys.stdin.isatty() else sys.stdin.read())
    except (MemoryAddsError, ValueError) as error:
        problems = (str(error),)
    if not problems:
        return 0
    lines = [
        'memory-adds: push REFUSED -- it edits, deletes or moves memory, or adds a misshapen entry (MEMORY-SHAPE).',
        *(f'memory-adds:   {line}' for line in problems),
        (
            'memory-adds: Remedy: commit each entry back to the text origin/<integration> holds (the range is '
            'judged net, so no history is rewritten); a correction is a NEW entry with `corrects:`; an added entry '
            'declares its name and description.'
        ),
    ]
    emit('\n'.join(lines), err=True)
    return 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
