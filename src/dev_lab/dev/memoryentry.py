"""MEMORY-SHAPE, one entry's text: its shape, a merge's citations, and the in-place edits that are not narrative.

:mod:`dev_lab.dev.memoryadds` refuses every edit under ``.claude/memory/`` but these, each recognized
whole by the predicates here (the rulings and the formats are stated in that module's docstring):
the volatile-field migration (:func:`only_volatile_stripped`), rem's dated manual task list
(:func:`only_manual_tasks_updated`), a privacy redaction (:func:`only_redacted`), an approved
amendment (:func:`only_amended`) and an approved redacting rename
(:func:`only_renamed_redacting`). An added entry must carry :data:`REQUIRED_KEYS`
(:func:`shape_problems`) and a merged one must cite (:func:`merged_entry_problems`). Pure text: no git, no files.
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    'AMENDMENT_NOTE',
    'FRONTMATTER',
    'MANUAL_PATH',
    'MANUAL_ROW',
    'MEMORY_DIR',
    'REDACTION_NOTE',
    'REDACTION_ROLES',
    'RENAME_PLACEHOLDER',
    'REQUIRED_KEYS',
    'VOLATILE_FIELDS',
    'is_memory',
    'lf',
    'merged_entry_problems',
    'missing_keys',
    'only_amended',
    'only_manual_tasks_updated',
    'only_redacted',
    'only_renamed_redacting',
    'only_volatile_stripped',
    'scope_of',
    'shape_problems',
]

#: The frontmatter keys every entry declares (MEMORY-SHAPE): ``name`` is an index's key, ``description`` what a
#: reader decides on unopened. An ADDED entry lacking one is refused at commit, not by a later tree scan.
REQUIRED_KEYS: Final = ('name', 'description')

#: Frontmatter fields the migration strips: per-read bookkeeping, never content.
VOLATILE_FIELDS = ('accessed', 'tier', 'count')

FRONTMATTER = re.compile(r'\A---\n(.*?)\n---(?:\n|\Z)', re.DOTALL)
MEMORY_DIR = '.claude/memory/'
_MERGED_FROM = re.compile(r'^merged_from:\s*(.*)$', re.MULTILINE)
_CITATION = re.compile(r'[\w./-]*[\w-]\.(?:md|py|rs|mjs|js|ts|toml|json|txt|yaml|yml|csv)\b')
_VOLATILE = re.compile(rf'^(?:{"|".join(VOLATILE_FIELDS)}):')
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
# REDACTING-RENAME (user ruling 2026-11-14): an account-like token leaves a published entry's FILE NAME. The
# new name keeps the directory and suffix, and its stem's ``-`` tokens are the old ones with ONE contiguous
# run replaced by :data:`RENAME_PLACEHOLDER` or dropped; the entry gains an amendment note whose reason says
# ``renamed``, and its text is otherwise the old text, a redaction of it or a one-for-one amendment of it.
RENAME_PLACEHOLDER: Final = 'user'
_RENAMED = re.compile(r'\brenamed\b', re.IGNORECASE)
MANUAL_PATH = re.compile(r'(?:^|/)\.claude/memory/(\d{4})/(\d{2})/(\d{2})/manual\.md\Z')
MANUAL_ROW = re.compile(r'- \[([ x])\] (MANUAL-(\d{8})-\d{3,}) \[(?:HIGH|MEDIUM|LOW)\] .+ \((\d{4}-\d{2}-\d{2})\)')


def lf(text: str) -> str:
    """*text* with CRLF line ends read as LF."""
    return text.replace('\r\n', '\n')


def only_volatile_stripped(old: str, new: str) -> bool:
    """The one-shot migration: *new* is *old* with only the :data:`VOLATILE_FIELDS` lines removed."""
    old, new = lf(old), lf(new)
    match = FRONTMATTER.match(old)
    if match is None or old == new:
        return False
    head = '\n'.join(line for line in match.group(1).splitlines() if not _VOLATILE.match(line))
    return f'---\n{head}\n---\n' + old[match.end() :] == new


def missing_keys(text: str) -> tuple[str, ...]:
    """The :data:`REQUIRED_KEYS` *text*'s frontmatter does not declare (all of them when it has none)."""
    match = FRONTMATTER.match(lf(text))
    head = match.group(1).splitlines() if match else []
    return tuple(key for key in REQUIRED_KEYS if not any(line.startswith(f'{key}:') for line in head))


def _completed(old: str, new: str) -> list[str] | None:
    """*new*'s lines minus the required keys it adds to *old*'s frontmatter; ``None`` when it adds none."""
    lacking = missing_keys(old)
    match = FRONTMATTER.match(lf(new))
    if not lacking or match is None or not FRONTMATTER.match(lf(old)):
        return None
    head = match.group(1).splitlines()
    kept = [line for line in head if not any(line.startswith(f'{key}:') for key in lacking)]
    if len(kept) == len(head):
        return None
    return ['---', *kept, '---', *lf(new)[match.end() :].splitlines()]


def only_amended(old: str, new: str) -> bool:
    """An approved amendment: ONE new note, plus one-for-one line replacements or a frontmatter completion.

    One-for-one: the other lines replaced, none added or removed. Completion (user ruling 2026-11-13): the
    missing :data:`REQUIRED_KEYS` added to a published entry's frontmatter and nothing else changed.
    """
    old_lines, new_lines = lf(old).splitlines(), lf(new).splitlines()
    notes = sum(1 for line in new_lines if _AMEND_LINE.fullmatch(line))
    if notes != 1 + sum(1 for line in old_lines if _AMEND_LINE.fullmatch(line)):
        return False
    before = [line for line in old_lines if line.strip() and not _AMEND_LINE.fullmatch(line)]
    if (completed := _completed(old, new)) is not None:
        return before == [line for line in completed if line.strip() and not _AMEND_LINE.fullmatch(line)]
    after = [line for line in new_lines if line.strip() and not _AMEND_LINE.fullmatch(line)]
    return len(before) == len(after) and before != after


def only_redacted(old: str, new: str) -> bool:
    """A privacy redaction: the note is added and every other changed line only swaps spans for placeholders."""
    after_lines = lf(new).splitlines()
    if not any(_NOTE_LINE.fullmatch(line) for line in after_lines):
        return False
    before = [line for line in lf(old).splitlines() if line.strip()]
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


def _redacting_name(old_path: str, new_path: str) -> bool:
    """*new_path* is *old_path* with one run of its stem's ``-`` tokens replaced by the placeholder or dropped."""
    old_dir, _, old_name = old_path.rpartition('/')
    new_dir, _, new_name = new_path.rpartition('/')
    old_stem, dot, old_suffix = old_name.rpartition('.')
    new_stem, new_dot, new_suffix = new_name.rpartition('.')
    if old_dir != new_dir or (dot, old_suffix) != (new_dot, new_suffix) or old_stem == new_stem or not new_stem:
        return False
    was, now = old_stem.split('-'), new_stem.split('-')
    head = next((i for i, (a, b) in enumerate(zip(was, now, strict=False)) if a != b), min(len(was), len(now)))
    tail = next((i for i, (a, b) in enumerate(zip(was[::-1], now[::-1], strict=False)) if a != b), len(now))
    tail = min(tail, len(was) - head, len(now) - head)
    replaced = now[head : len(now) - tail]
    return len(was) - tail > head and replaced in ([], [RENAME_PLACEHOLDER])


def only_renamed_redacting(old_path: str, new_path: str, old: str, new: str) -> bool:
    """REDACTING-RENAME: a same-directory placeholder rename carrying a new, approved ``renamed`` note.

    The note is the ONE amendment line *new* adds; without it, *new*'s text is *old*'s (blank lines aside), a
    redaction of it (:func:`only_redacted`), or *new* is a one-for-one amendment of it (:func:`only_amended`).
    """
    if not _redacting_name(old_path, new_path):
        return False
    old_lines, new_lines = lf(old).splitlines(), lf(new).splitlines()
    added = [line for line in new_lines if _AMEND_LINE.fullmatch(line) and line not in old_lines]
    if len(added) != 1 or not _RENAMED.search(added[0]):
        return False
    rest = [line for line in new_lines if line != added[0]]
    unchanged = [line for line in rest if line.strip()] == [line for line in old_lines if line.strip()]
    return unchanged or only_redacted(old, '\n'.join(rest)) or only_amended(old, new)


def _manual_rows(path: str, text: str) -> list[tuple[str, str, str]] | None:
    """Recognize rem task-engine's dedicated list, not a filename exemption for prose."""
    match = MANUAL_PATH.search(path)
    if match is None:
        return None
    day = '-'.join(match.groups())
    try:
        date.fromisoformat(day)
    except ValueError:
        return None
    header = f'---\nname: manual-{day}\ndescription: Manual tasks created on {day}\nmetadata:\n  type: project\n---\n'
    text = lf(text)
    if not text.startswith(header):
        return None
    lines = [line for line in text[len(header) :].splitlines() if line]
    if len(lines) % 2:
        return None
    rows = []
    ids: set[str] = set()
    for task, module in zip(lines[::2], lines[1::2], strict=True):
        row = MANUAL_ROW.fullmatch(task)
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


def only_manual_tasks_updated(path: str, old: str, new: str) -> bool:
    """Rem's manual list: tasks appended or checkboxes toggled, every existing row's text kept."""
    before, after = _manual_rows(path, old), _manual_rows(path, new)
    if before is None or after is None or len(after) < len(before):
        return False
    return all(a[1:] == b[1:] for a, b in zip(before, after[: len(before)], strict=True))


def is_memory(path: str) -> bool:
    """*path* (repo-relative) lies under some scope's ``.claude/memory/``."""
    return MEMORY_DIR in f'/{path}'


def scope_of(path: str) -> str:
    """The directory whose ``.claude/memory/`` holds *path* (``''`` for the root)."""
    return f'/{path}'.split(f'/{MEMORY_DIR}', 1)[0].lstrip('/')


def merged_entry_problems(path: str, text: str, exists: Callable[[str], bool] | None = None) -> tuple[str, ...]:
    """Why the entry at *path* (repo-relative) fails as a merge.

    *exists* says a source is at the base or added by the same change.
    """
    text = lf(text)
    match = FRONTMATTER.match(text)
    sources = _MERGED_FROM.search(match.group(1)) if match else None
    if sources is None:
        return ()
    scope = scope_of(path)
    home = f'{scope}/{MEMORY_DIR}' if scope else MEMORY_DIR
    out: list[str] = []
    for source in re.findall(r'[^\s\[\],\'"]+', sources.group(1)):
        full = source if is_memory(source) else home + source
        if '..' in source or scope_of(full) != scope:
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


def shape_problems(path: str, text: str) -> tuple[str, ...]:
    """An added entry's missing :data:`REQUIRED_KEYS`, as one refusal naming its exit."""
    if not path.endswith('.md') or not (lacking := missing_keys(text)):
        return ()
    why = (
        f'{path}: its frontmatter declares no {", ".join(lacking)} -- every entry opens with '
        '`---` / `name: <slug>` / `description: <one line>` / `---` (MEMORY-SHAPE); add them and commit'
    )
    return (why,)
