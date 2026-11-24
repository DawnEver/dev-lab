"""MEMORY-SHAPE, one entry's text: its shape, a merge's citations, and the in-place edits that are not narrative.

:mod:`dev_lab.dev.memoryadds` refuses every edit under ``.claude/memory/`` but these, each recognized
whole by the predicates here (the rulings and the formats are stated in that module's docstring):
the volatile-field migration (:func:`only_volatile_stripped`), a privacy redaction (:func:`only_redacted`), an approved
amendment (:func:`only_amended`) and an approved redacting rename
(:func:`only_renamed_redacting`). An added entry must carry :data:`REQUIRED_KEYS`
(:func:`shape_problems`) and a merged one must cite (:func:`merged_entry_problems`). Pure text: no git, no files.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    'AMENDMENT_NOTE',
    'FRONTMATTER',
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
# A quote translated in place (D26, 2026-11-17) is marked ``(user, translated)`` after it.
AMENDMENT_NOTE: Final = 'Amended {day}: {reason} -- approved: "{approved}"'
# REDACTING-RENAME (user ruling 2026-11-14): an account-like token leaves a published entry's FILE NAME. The
# new name keeps the directory and suffix, and its stem's ``-`` tokens are the old ones with ONE contiguous
# run replaced by :data:`RENAME_PLACEHOLDER` or dropped; the entry gains an amendment note whose reason says
# ``renamed``, and its text is otherwise the old text, a redaction of it or a one-for-one amendment of it.
RENAME_PLACEHOLDER: Final = 'user'
_RENAMED = re.compile(r'\brenamed\b', re.IGNORECASE)
_AMEND_LINE = re.compile(r'> Amended \d{4}-\d{2}-\d{2}: \S.*? -- approved: "[^"]*\S[^"]*"(?: \(user, translated\))?')


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


_NOTE_HEAD: Final = len('> Amended yyyy-mm-dd: ')


def _notes_rewritten(old_notes: list[str], new_notes: list[str]) -> bool | None:
    """Whether the existing notes were rewritten in place; ``None`` when they were not kept one-for-one.

    *new_notes* is *old_notes* plus ONE added note; each kept note is unchanged or keeps its date and
    ``Amended`` prefix with only its reason and quote replaced (a quote translated per D26, 2026-11-17).
    """
    if len(new_notes) != len(old_notes) + 1:
        return None
    for skip in range(len(new_notes)):
        kept = new_notes[:skip] + new_notes[skip + 1 :]
        if all(was[:_NOTE_HEAD] == now[:_NOTE_HEAD] for was, now in zip(old_notes, kept, strict=True)):
            return old_notes != kept
    return None


def only_amended(old: str, new: str) -> bool:
    """An approved amendment: ONE new note, plus one-for-one line replacements or a frontmatter completion.

    One-for-one: the other lines replaced, none added or removed -- an existing note included, which keeps
    its date (:func:`_notes_rewritten`). Completion (user ruling 2026-11-13): the missing
    :data:`REQUIRED_KEYS` added to a published entry's frontmatter and nothing else changed.
    """
    old_lines, new_lines = lf(old).splitlines(), lf(new).splitlines()
    rewritten = _notes_rewritten(
        [line for line in old_lines if _AMEND_LINE.fullmatch(line)],
        [line for line in new_lines if _AMEND_LINE.fullmatch(line)],
    )
    if rewritten is None:
        return False
    before = [line for line in old_lines if line.strip() and not _AMEND_LINE.fullmatch(line)]
    if (completed := _completed(old, new)) is not None:
        return before == [line for line in completed if line.strip() and not _AMEND_LINE.fullmatch(line)]
    after = [line for line in new_lines if line.strip() and not _AMEND_LINE.fullmatch(line)]
    return len(before) == len(after) and (before != after or rewritten)


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
