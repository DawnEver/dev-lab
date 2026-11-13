"""MEMORY-SHAPE, the change half: memory is ADDED to -- never edited, deleted or moved away.

THE RULE (user rulings 2026-10-31, the four-layer plan). A memory entry is immutable once written: a
correction is a NEW entry naming the old one in ``corrects:``, and a consolidation is a NEW entry naming
its sources in ``merged_from:``. So a change touching ``**/.claude/memory/**`` may only ADD a file.
Three shapes are not narrative edits:

* a task leaving the tasks layer -- ``git mv .claude/tasks/<slug> .claude/memory/...`` -- is how a
  closed task becomes history, and it is the one rename into memory;
* the one-shot four-layer migration, which removes only the volatile frontmatter fields
  (:data:`VOLATILE_FIELDS`) a reader used to rewrite on every read. A change whose ONLY difference is
  those lines is that migration and nothing else;
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
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.hpc.declared import pyproject_at
from lab_commons.log import emit

from dev_lab.dev.lanepolicy import policy_at, policy_from

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = [
    'REQUIRED_KEYS',
    'VOLATILE_FIELDS',
    'MemoryAddsError',
    'main',
    'merged_entry_problems',
    'pending',
    'problems_between',
]

#: The frontmatter keys every entry declares (MEMORY-SHAPE): ``name`` is an index's key, ``description`` what a
#: reader decides on unopened. An ADDED entry lacking one is refused at commit, not by a later tree scan.
REQUIRED_KEYS: Final = ('name', 'description')

#: Frontmatter fields the migration strips: per-read bookkeeping, never content.
VOLATILE_FIELDS = ('accessed', 'tier', 'count')

_GIT = shutil.which('git') or 'git'
_GIT_TIMEOUT_S = 120
_ZERO = '0' * 40
_EMPTY_TREE: Final = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'  # git's empty tree: the base before a first push
_REF_LINE_FIELDS: Final = 4  # git pre-push: <local ref> <local sha> <remote ref> <remote sha>
_MEMORY = '.claude/memory/'
_TASK = re.compile(r'(?:^|/)\.claude/tasks/[^/]+/')
_FRONTMATTER = re.compile(r'\A---\n(.*?)\n---(?:\n|\Z)', re.DOTALL)
_MERGED_FROM = re.compile(r'^merged_from:\s*(.*)$', re.MULTILINE)
_VOLATILE = re.compile(rf'^(?:{"|".join(VOLATILE_FIELDS)}):')
_CITATION = re.compile(r'[\w./-]*[\w-]\.(?:md|py|rs|mjs|js|ts|toml|json|txt|yaml|yml|csv)\b')
REDACTION_NOTE: Final = 'Redacted {day}: site markers removed (public repo).'
# A redaction swaps a site span for a placeholder token or one of these neutral role phrases -- nothing else.
REDACTION_ROLES: Final = (
    "the private consumer's",
    'the private consumer repo',
    'the private consumer',
    "the second private consumer's",
    'the second private consumer',
    'an optimisation consumer',
    "the integrator workstation's",
    'the integrator workstation',
)
_PLACEHOLDER = re.compile('|'.join([r'<[a-z][a-z0-9-]*>', *(re.escape(role) for role in REDACTION_ROLES)]))
_NOTE_LINE = re.compile(r'> ' + re.escape(REDACTION_NOTE).replace(re.escape('{day}'), r'\d{4}-\d{2}-\d{2}'))
# THE EXCEPTIONAL CASE (user ruling 2026-11-13): a published line that is WRONG -- a misstated fact, a
# mistranslated quote, a character a family rule forbids -- is corrected IN PLACE when the user approved it.
# The entry gains this note (its reason and the user's words, both non-empty); every other change replaces
# a line one-for-one, so nothing is added or removed and git history keeps the original. A disagreement
# with a past conclusion is still a NEW entry with ``corrects:``: this note is for content that is wrong.
AMENDMENT_NOTE: Final = 'Amended {day}: {reason} -- approved: "{approved}"'
_AMEND_LINE = re.compile(r'> Amended \d{4}-\d{2}-\d{2}: \S.*? -- approved: "[^"]*\S[^"]*"')
_MANUAL = re.compile(r'(?:^|/)\.claude/memory/(\d{4})/(\d{2})/(\d{2})/manual\.md\Z')
_MANUAL_ROW = re.compile(r'- \[([ x])\] (MANUAL-(\d{8})-\d{3,}) \[(?:HIGH|MEDIUM|LOW)\] .+ \((\d{4}-\d{2}-\d{2})\)')


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


def missing_keys(text: str) -> tuple[str, ...]:
    """The :data:`REQUIRED_KEYS` *text*'s frontmatter does not declare (all of them when it has none)."""
    match = _FRONTMATTER.match(_lf(text))
    head = match.group(1).splitlines() if match else []
    return tuple(key for key in REQUIRED_KEYS if not any(line.startswith(f'{key}:') for line in head))


def _only_amended(old: str, new: str) -> bool:
    """An approved amendment: ONE new note, the other lines replaced one-for-one, none added or removed."""
    old_lines, new_lines = _lf(old).splitlines(), _lf(new).splitlines()
    notes = sum(1 for line in new_lines if _AMEND_LINE.fullmatch(line))
    if notes != 1 + sum(1 for line in old_lines if _AMEND_LINE.fullmatch(line)):
        return False
    before = [line for line in old_lines if line.strip() and not _AMEND_LINE.fullmatch(line)]
    after = [line for line in new_lines if line.strip() and not _AMEND_LINE.fullmatch(line)]
    return len(before) == len(after) and before != after


def _only_redacted(old: str, new: str) -> bool:
    """A privacy redaction: the note is added and every other changed line only swaps spans for placeholders."""
    after_lines = _lf(new).splitlines()
    if not any(_NOTE_LINE.fullmatch(line) for line in after_lines):
        return False
    before = [line for line in _lf(old).splitlines() if line.strip()]
    after = [line for line in after_lines if line.strip() and not _NOTE_LINE.fullmatch(line)]
    if len(before) != len(after):
        return False
    for was, now in zip(before, after, strict=True):
        if was == now:
            continue
        literals = _PLACEHOLDER.split(now)
        if len(literals) == 1 or not re.fullmatch('.+?'.join(map(re.escape, literals)), was):
            return False
    return True


def _manual_rows(path: str, text: str) -> list[tuple[str, str, str]] | None:
    """Recognize rem task-engine's dedicated list, not a filename exemption for prose."""
    match = _MANUAL.search(path)
    if match is None:
        return None
    day = '-'.join(match.groups())
    try:
        date.fromisoformat(day)
    except ValueError:
        return None
    header = f'---\nname: manual-{day}\ndescription: Manual tasks created on {day}\nmetadata:\n  type: project\n---\n'
    text = _lf(text)
    if not text.startswith(header):
        return None
    lines = [line for line in text[len(header) :].splitlines() if line]
    if len(lines) % 2:
        return None
    rows = []
    ids: set[str] = set()
    for task, module in zip(lines[::2], lines[1::2], strict=True):
        row = _MANUAL_ROW.fullmatch(task)
        if (
            row is None
            or row[2] in ids
            or row[3] != day.replace('-', '')
            or row[4] != day
            or re.fullmatch(r' {6}module: \S.*', module) is None
        ):
            return None
        ids.add(row[2])
        rows.append((row[1], task[5:], module))
    return rows


def _only_manual_tasks_updated(path: str, old: str, new: str) -> bool:
    before, after = _manual_rows(path, old), _manual_rows(path, new)
    if before is None or after is None or len(after) < len(before):
        return False
    return all(a[1:] == b[1:] for a, b in zip(before, after[: len(before)], strict=True))


def merged_entry_problems(path: str, text: str, exists: Callable[[str], bool] | None = None) -> tuple[str, ...]:
    """Why the entry at *path* (repo-relative) fails as a merge.

    *exists* says a source is at the base or added by the same change.
    """
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


def _shape_problems(path: str, text: str) -> tuple[str, ...]:
    """An added entry's missing :data:`REQUIRED_KEYS`, as one refusal naming its exit."""
    if not path.endswith('.md') or not (lacking := missing_keys(text)):
        return ()
    why = (
        f'{path}: its frontmatter declares no {", ".join(lacking)} -- every entry opens with '
        '`---` / `name: <slug>` / `description: <one line>` / `---` (MEMORY-SHAPE); add them and commit'
    )
    return (why,)


def _judge(root: Path, old_rev: str, new_rev: str, rows: list[tuple[str, str, str]]) -> tuple[str, ...]:
    added = {new for status, _, new in rows if status in 'AC'}

    def exists(path: str) -> bool:
        """A source is at the base, or ADDED by the same change -- a merge and its sources may land together."""
        return path in added or _run(root, 'cat-file', '-e', f'{old_rev}:{path}')[0] == 0

    out: list[str] = []
    for status, old, new in rows:
        if status in 'AC' and _is_memory(new):
            text = _git(root, 'show', f'{new_rev}:{new}')
            out.extend((*_shape_problems(new, text), *merged_entry_problems(new, text, exists)))
        elif status == 'R' and _is_memory(new) and not _is_memory(old):
            if not _TASK.search(old):
                out.append(f'{new}: only a task (.claude/tasks/<slug>/) moves into memory, not {old}')
        elif status == 'M' and _is_memory(old):
            before, after = _git(root, 'show', f'{old_rev}:{old}'), _git(root, 'show', f'{new_rev}:{new}')
            if not (
                _only_volatile_stripped(before, after)
                or _only_manual_tasks_updated(old, before, after)
                or _only_redacted(before, after)
                or _only_amended(before, after)
            ):
                remedy = (
                    'a memory entry is immutable -- write a new entry with `corrects:` instead; a line that is WRONG '
                    'is corrected in place only with the user-approved note `> '
                    + AMENDMENT_NOTE.format(day='<yyyy-mm-dd>', reason='<why>', approved="<the user's words>")
                    + '` and lines replaced one-for-one'
                )
                if _MANUAL.search(old):
                    remedy += (
                        '; rem 2.2.0 task-list format/operation check failed: append tasks or toggle checkboxes '
                        'without changing existing task text, module or order'
                    )
                out.append(f'{old}: {remedy}')
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
        if status not in 'MDRT' or not _is_memory(old) or _MANUAL.search(old) or _MANUAL.search(new):
            return False
        if status in 'MRT' and _MANUAL_ROW.search(_git(root, 'show', f'{tree}:{new}')):
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
