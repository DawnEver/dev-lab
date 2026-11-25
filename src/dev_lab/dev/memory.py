"""MEMORY, WRITTEN AND SEARCHED THROUGH ONE DOOR: a repo's ``.claude/memory/`` at its root, no index (user, 2026-11-23).

The rem plugin is retired; its two kept duties are this module's. Memory stays in each repo's root
(``<root>/.claude/memory/YYYY/MM/DD/<slug>.md``) and nothing derives an index from it: a search reads the files.

* ``add`` -- a NEW dated entry with the :data:`~dev_lab.dev.memoryentry.REQUIRED_KEYS` frontmatter; an existing
  file is refused (an entry is never edited: a correction is a new entry naming it in ``corrects:``).
* ``amend`` -- the user-approved in-place correction: ONE line replaced one-for-one, plus the amendment note.
* ``redact`` -- a privacy redaction: a span swapped for a placeholder or role, plus the redaction note.
* ``rename`` -- the redacting rename: the file name loses an account-like run, plus a ``renamed`` note.
* ``search`` -- every entry holding ALL the query terms (case-insensitive), best first: a term in the
  frontmatter weighs :data:`HEAD_WEIGHT` body hits.

Each write is judged by the SAME predicate the commit check (:mod:`dev_lab.dev.memoryadds`) applies --
:mod:`dev_lab.dev.memoryentry` is the one source of every shape -- so a door never writes what a commit refuses.
A refusal names its cause and exits 2; nothing is written.

``python -m dev_lab.dev.memory {add|amend|redact|rename|search} ...`` (``--root``: the repo, default the cwd).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev import memoryentry as entry
from dev_lab.dev.depversions import today

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    'HEAD_WEIGHT',
    'Hit',
    'MemoryRefused',
    'add',
    'amend',
    'main',
    'memory_dir',
    'redact',
    'rename',
    'search',
]

#: How many body hits one frontmatter hit is worth: a name or description says what the entry is about.
HEAD_WEIGHT: Final = 5
_SLUG: Final = re.compile(r'[a-z0-9][a-z0-9-]*')


class MemoryRefused(ValueError):
    """A memory write the shape rules refuse; the message names the cause and the door."""


@dataclass(frozen=True, slots=True)
class Hit:
    """One search result: the entry's repo-relative path, its description and its score."""

    path: str
    description: str
    score: int


def memory_dir(root: Path) -> Path:
    """The repo's one memory tree: ``<root>/.claude/memory``."""
    return root / entry.MEMORY_DIR.rstrip('/')


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _entry_path(root: Path, rel: str) -> Path:
    path = (root / rel).resolve()
    if not entry.is_memory(_rel(root, path)) or not path.is_file():
        msg = f'{rel}: not a memory entry of {memory_dir(root)} -- name an existing .claude/memory/ file'
        raise MemoryRefused(msg)
    return path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')


def add(root: Path, name: str, description: str, body: str, *, day: date | None = None) -> Path:
    """Write the new entry ``<memory>/YYYY/MM/DD/<name>.md``; refused when it exists or its shape fails."""
    if not _SLUG.fullmatch(name):
        msg = f'{name!r}: an entry name is a lowercase kebab-case slug (MEMORY-SHAPE)'
        raise MemoryRefused(msg)
    if not description.strip() or '\n' in description:
        msg = 'the description is one non-empty line: what a reader decides on unopened (MEMORY-SHAPE)'
        raise MemoryRefused(msg)
    day = day or today()
    path = memory_dir(root) / f'{day:%Y}' / f'{day:%m}' / f'{day:%d}' / f'{name}.md'
    if path.exists():
        msg = (
            f'{_rel(root, path)}: exists -- an entry is never rewritten; add a new one naming it in `corrects:`, '
            'or correct a wrong line with `amend`'
        )
        raise MemoryRefused(msg)
    text = f'---\nname: {name}\ndescription: {description.strip()}\n---\n\n{entry.lf(body).strip()}\n'
    if problems := entry.shape_problems(_rel(root, path), text):
        raise MemoryRefused('\n'.join(problems))
    _write(path, text)
    return path


def _note(template: str, **fields: str) -> str:
    return '> ' + template.format(day=today().isoformat(), **fields)


def amend(root: Path, rel: str, line: int, text: str, *, reason: str, approved: str) -> Path:
    """Replace line *line* (1-based) of the entry with *text* and add the approved amendment note."""
    path = _entry_path(root, rel)
    old = entry.lf(path.read_text(encoding='utf-8'))
    lines = old.splitlines()
    if not 1 <= line <= len(lines):
        msg = f'{rel}: has {len(lines)} lines, not a line {line}'
        raise MemoryRefused(msg)
    lines[line - 1] = text
    new = '\n'.join([*lines, '', _note(entry.AMENDMENT_NOTE, reason=reason, approved=approved)]) + '\n'
    if not entry.only_amended(old, new):
        msg = (
            f'{rel}: not an amendment -- one line replaced one-for-one, a non-empty reason and the user`s '
            'approving words; a different conclusion is a NEW entry with `corrects:`'
        )
        raise MemoryRefused(msg)
    _write(path, new)
    return path


def redact(root: Path, rel: str, span: str, placeholder: str) -> Path:
    """Swap every *span* in the entry for *placeholder* (``<kebab>`` or a declared role) and add the note."""
    path = _entry_path(root, rel)
    old = entry.lf(path.read_text(encoding='utf-8'))
    if not span or span not in old:
        msg = f'{rel}: does not hold {span!r}'
        raise MemoryRefused(msg)
    new = old.replace(span, placeholder).rstrip('\n') + '\n\n' + _note(entry.REDACTION_NOTE) + '\n'
    if not entry.only_redacted(old, new):
        roles = ', '.join(entry.REDACTION_ROLES)
        msg = f'{rel}: not a redaction -- the placeholder is a `<kebab-token>` or one of: {roles}'
        raise MemoryRefused(msg)
    _write(path, new)
    return path


def rename(root: Path, rel: str, new_name: str, *, approved: str) -> Path:
    """The redacting rename: the entry moves to *new_name* in its directory with a ``renamed`` amendment note."""
    path = _entry_path(root, rel)
    target = path.with_name(new_name)
    old_rel, new_rel = _rel(root, path), _rel(root, target)
    old = entry.lf(path.read_text(encoding='utf-8'))
    reason = f'renamed from {path.stem} to drop an account-like token'
    new = old.rstrip('\n') + '\n\n' + _note(entry.AMENDMENT_NOTE, reason=reason, approved=approved) + '\n'
    if target.exists() or not entry.only_renamed_redacting(old_rel, new_rel, old, new):
        msg = (
            f'{rel} -> {new_name}: not a redacting rename -- same directory and suffix, one run of the stem`s '
            f'`-` tokens replaced by `{entry.RENAME_PLACEHOLDER}` or dropped, onto no existing file'
        )
        raise MemoryRefused(msg)
    _write(target, new)
    path.unlink()
    return target


def _frontmatter(text: str) -> tuple[str, str]:
    match = entry.FRONTMATTER.match(text)
    return (match.group(1), text[match.end() :]) if match else ('', text)


def search(root: Path, terms: Sequence[str], *, limit: int = 20) -> list[Hit]:
    """Every entry under the repo's memory holding ALL *terms*, best first (ties: newest path first)."""
    words = [term.lower() for term in terms if term.strip()]
    if not words:
        msg = 'name at least one search term'
        raise MemoryRefused(msg)
    hits: list[Hit] = []
    for path in sorted(memory_dir(root).rglob('*.md'), reverse=True):
        text = entry.lf(path.read_text(encoding='utf-8', errors='replace'))
        head, body = _frontmatter(text)
        head_l, body_l = head.lower(), body.lower()
        if not all(word in head_l or word in body_l for word in words):
            continue
        score = sum(HEAD_WEIGHT * head_l.count(word) + body_l.count(word) for word in words)
        described = next((line[12:].strip() for line in head.splitlines() if line.startswith('description:')), '')
        hits.append(Hit(_rel(root, path), described, score))
    hits.sort(key=lambda hit: -hit.score)
    return hits[:limit]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.memory', description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='the repo (default: the cwd)')
    verbs = parser.add_subparsers(dest='verb', required=True)
    p = verbs.add_parser('add', help='a new dated entry; the body is read from stdin')
    p.add_argument('name')
    p.add_argument('description')
    p = verbs.add_parser('amend', help='an approved one-for-one line correction')
    p.add_argument('path')
    p.add_argument('line', type=int)
    p.add_argument('text')
    p.add_argument('--reason', required=True)
    p.add_argument('--approved', required=True, help='the user`s approving words, quoted')
    p = verbs.add_parser('redact', help='a privacy redaction')
    p.add_argument('path')
    p.add_argument('span')
    p.add_argument('placeholder')
    p = verbs.add_parser('rename', help='a redacting rename')
    p.add_argument('path')
    p.add_argument('new_name')
    p.add_argument('--approved', required=True)
    p = verbs.add_parser('search', help='entries holding every term, best first')
    p.add_argument('terms', nargs='+')
    p.add_argument('--limit', type=int, default=20)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """The CLI; a refusal is one stderr line and exit 2."""
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    try:
        if args.verb == 'search':
            for hit in search(root, args.terms, limit=args.limit):
                emit(f'{hit.path}: {hit.description}')
            return 0
        if args.verb == 'add':
            path = add(root, args.name, args.description, sys.stdin.read())
        elif args.verb == 'amend':
            path = amend(root, args.path, args.line, args.text, reason=args.reason, approved=args.approved)
        elif args.verb == 'redact':
            path = redact(root, args.path, args.span, args.placeholder)
        else:
            path = rename(root, args.path, args.new_name, approved=args.approved)
    except MemoryRefused as refused:
        emit(f'MEMORY-SHAPE: {refused}', err=True)
        return 2
    emit(_rel(root, path))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
