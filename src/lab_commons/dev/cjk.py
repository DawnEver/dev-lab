"""The family's ONE "no CJK in tracked source" guard -- the scan, the exemptions, the floor.

THE USER DIRECTIVE, 2026-09-16, translated rather than quoted: across every repo in this family,
no content that git tracks may contain CJK (Chinese/Japanese/Korean) characters -- only English
letters, digits and symbols. Exempt: ``.claude/memory/``, ``attic/``, ``archived/``. It is not kept
here in the source language on purpose: this module is itself tracked, and a literal quotation would
be the one violation its own guard could never let through.

THE RULE AS RULED IS CJK, NOT NON-ASCII. Measured 2026-09-16, over ``motronics-studio``: refusing
CJK touches 287 tracked files; refusing every non-ASCII character touches 732, because this family
writes em dashes, ``~=``, a multiplication sign and other ordinary symbols constantly in its prose. The
user's own wording names the CJK script family, not the ASCII table, so :data:`CJK_RANGES` matches
exactly the five blocks below and nothing wider -- an em dash stays legal everywhere.

THE RANGES, and each is a real CJK block rather than a guess:

* ``U+3000-303F`` -- CJK Symbols and Punctuation (the ideographic space, full-width brackets).
* ``U+3400-4DBF`` -- CJK Unified Ideographs Extension A.
* ``U+4E00-9FFF`` -- CJK Unified Ideographs, the block that carries ordinary Chinese/Japanese text.
* ``U+F900-FAFF`` -- CJK Compatibility Ideographs.
* ``U+FF00-FFEF`` -- Halfwidth and Fullwidth Forms, which is where a full-width Latin letter or a
  full-width punctuation mark used inside CJK prose lives, and which plain "is this Han" tests miss.

THIS CANNOT BE A FLAT ASSERTION ON DAY ONE, and the ratchet shape is not a stylistic choice: measured
population at authoring time was 287 files / 22162 characters in motronics-studio alone, and a single
commit cannot clear that. So this module supplies the SCAN, the EXEMPTION LIST and the FLOOR; each
adopting repo supplies its own DECLARATION -- a named set of files still carrying CJK, exactly the
shape ``tests/test_arch_suppressions_are_a_named_set.py`` already uses for a suppression ratchet.
:func:`ratchet` is the two-sided check: a file with CJK and no declaration REFUSES; a declared file
that has been cleaned REFUSES too, so the declaration can only shrink and never rot into a permanent
waiver nobody re-reads.

TRACKED, NOT PRESENT. The corpus is ``git ls-files`` (:func:`lab_commons.dev.rules.tracked_files`,
reused rather than re-implemented): an untracked scratch file is not the subject the directive names,
and a mechanism keyed on the working tree would refuse content nobody will ever push.

BINARY FILES ARE SKIPPED, NAMED. A file is read as bytes and decoded as UTF-8; a
:class:`UnicodeDecodeError` means it is not text this guard can read at all (a compiled artefact, an
image checked in by accident) and it is recorded in :attr:`Scan.undecodable` rather than silently
treated as clean -- "not decodable" and "decodable and free of CJK" are different facts and the
first one is not evidence of the second.

FLOORS BEFORE ANY VERDICT. :func:`assert_floor` refuses a scan that read fewer files than the caller
declares as a floor, for the reason every scan-style guard in this family gives: a clean tree and an
unread one produce the same empty result, and only a floor tells them apart.

THERE IS NO CONTENT-BASED EXEMPTION, ONLY THE THREE PATH PREFIXES ABOVE, and this was a real design
question rather than an oversight: ``wdg-lab`` has a test that PASSES a CJK literal on purpose, to
assert a naming guard rejects non-ASCII input (``naming.assert_ascii(...)``, called with the CJK
character itself). Translating that literal would test a different string and stop testing the
rejection; waiving the file would open a permanent CJK island. Asked directly, the user's answer was
to translate -- which for THIS shape means a backslash-u ESCAPE SEQUENCE rather than English prose:
the source text becomes pure ASCII while the runtime value stays byte-identical, so the test goes on
testing exactly what it tested. THIS GUARD NEEDS NO SPECIAL CASE FOR IT, and that is the point of the
remedy rather than a coincidence: a backslash-u escape in source is eight plain ASCII characters --
a backslash, a ``u`` and six hex digits -- this module scans the FILE TEXT as it is
written, never a decoded runtime string, so an escaped literal contains no character in
:data:`CJK_RANGES` and passes on its own. A scanner that decoded escape sequences before matching
would refuse the very remedy it recommends, which is why :func:`find_cjk` operates on ``text`` taken
verbatim from ``read_bytes().decode('utf-8')`` and never through anything that interprets a backslash.

THE REFUSAL NAMES THE REMEDY AND THE FILE:LINE, and it is itself CJK-free by construction: it is an
f-string built from the offending path, line and code point, never from a repeated CJK literal.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, NamedTuple

__all__ = [
    'CJK_RANGES',
    'EXEMPT_PREFIXES',
    'Occurrence',
    'Scan',
    'VacuousScan',
    'assert_floor',
    'exempted',
    'find_cjk',
    'is_cjk',
    'ratchet',
    'remedy',
    'scan_files',
]

#: The five CJK blocks the directive refuses. See the module docstring for what each one is and why
#: the set stops here rather than widening to "any non-ASCII" -- that is a measured, not a guessed,
#: boundary.
CJK_RANGES: Final[tuple[tuple[int, int], ...]] = (
    (0x3000, 0x303F),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0xFF00, 0xFFEF),
)

#: Where CJK is permitted without a declaration. DATA, not a literal scattered through the scan, so
#: an adopting repo can read what it inherited rather than re-deriving it from behaviour.
EXEMPT_PREFIXES: Final[tuple[str, ...]] = ('.claude/memory/', 'attic/', 'archived/')


class VacuousScan(RuntimeError):
    """A scan reached fewer files than its floor, so finding nothing proves nothing."""


class Occurrence(NamedTuple):
    """One CJK character, at the place a reader will find it: ``(path, line, col, char)``.

    *path* is as the caller named it, or relative to *root* when :func:`scan_files` was given one --
    an absolute path is a fact about one box, and a reader elsewhere cannot check it. *line* and
    *col* are both 1-based, matching how an editor and a ``file:line`` citation both count.
    """

    path: str
    line: int
    col: int
    char: str


@dataclass(frozen=True, slots=True)
class Scan:
    """What a scan found, together with what it could not read -- the three facts are one answer.

    *occurrences* is every CJK character in a non-exempt, decodable, tracked file. *exempted* names
    every file the exemption list excused, and *undecodable* names every file that could not be read
    as UTF-8 text -- both NAMED rather than folded into a count, for the same reason
    :class:`~lab_commons.dev.units.Scan` names its own carve-outs: a count cannot say which file, and
    the honest-looking repair when a pin disagrees is to edit the number.
    """

    occurrences: tuple[Occurrence, ...]
    files_read: int
    exempted: tuple[str, ...]
    undecodable: tuple[str, ...]

    def __iter__(self) -> Iterator[Occurrence]:
        return iter(self.occurrences)


def is_cjk(char: str, ranges: Collection[tuple[int, int]] = CJK_RANGES) -> bool:
    """Whether *char* falls in one of *ranges* -- the one place a code point is checked."""
    point = ord(char)
    return any(lo <= point <= hi for lo, hi in ranges)


def find_cjk(text: str, ranges: Collection[tuple[int, int]] = CJK_RANGES) -> tuple[tuple[int, int, str], ...]:
    """Every ``(line, col, char)`` in *text* where a character falls in *ranges*. Both 1-based."""
    found: list[tuple[int, int, str]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        found.extend((line_no, col, char) for col, char in enumerate(line, start=1) if is_cjk(char, ranges))
    return tuple(found)


def exempted(name: str, prefixes: Collection[str] = EXEMPT_PREFIXES) -> bool:
    """Whether *name* (a repo-relative POSIX path) sits under one of *prefixes*."""
    return any(name.startswith(prefix) for prefix in prefixes)


def _named(path: Path, base: Path | None) -> str:
    """*path* as the record names it: as given, or relative to *base* when one was declared."""
    if base is None:
        return path.as_posix()
    resolved = path.resolve()
    if resolved != base and base not in resolved.parents:
        msg = f'{path} is not under {base}, so it cannot be named relative to it.'
        raise ValueError(msg)
    return resolved.relative_to(base).as_posix()


def scan_files(
    paths: Iterable[Path | str],
    *,
    exempt_prefixes: Collection[str] = EXEMPT_PREFIXES,
    root: Path | None = None,
) -> Scan:
    """Every CJK character in *paths*, skipping exempt and undecodable files. Never raises a verdict.

    *paths* is the caller's own list and is never walked: this function reads exactly the files it
    is handed, which is what lets a control drive it against a planted tree instead of a real
    checkout. Pair it with :func:`lab_commons.dev.rules.tracked_files` to scan a repo's real corpus.

    Raises:
        ValueError: *root* was declared and a path is not under it.
        OSError: a file could not be opened.

    """
    occurrences: list[Occurrence] = []
    skipped: list[str] = []
    undecodable: list[str] = []
    base = Path(root).resolve() if root is not None else None
    read = 0
    for item in paths:
        path = Path(item)
        named = _named(path, base)
        if exempted(named, exempt_prefixes):
            skipped.append(named)
            continue
        try:
            text = path.read_bytes().decode('utf-8')
        except UnicodeDecodeError:
            undecodable.append(named)
            continue
        read += 1
        occurrences.extend(Occurrence(named, line, col, char) for line, col, char in find_cjk(text))
    return Scan(
        occurrences=tuple(sorted(occurrences)),
        files_read=read,
        exempted=tuple(sorted(skipped)),
        undecodable=tuple(sorted(undecodable)),
    )


def assert_floor(reached: int, floor: int, what: str = 'CJK') -> None:
    """Raise unless *reached* (a scan's ``files_read``) meets *floor* -- naming what was scanned.

    A clean tree and an unread one both produce zero occurrences; only a floor set below a real
    measurement (never the exact count, which reds on every file added) tells them apart.
    """
    if reached < floor:
        msg = (
            f'the {what} scan reached only {reached} file(s), below the {floor} floor. Finding no CJK '
            f'is vacuous rather than clean: a clean tree and an unread one produce the same empty '
            f'result, and only one of them means the guard held. Fix the file list, do not lower the floor.'
        )
        raise VacuousScan(msg)


def remedy(occurrence: Occurrence) -> str:
    """One refusal line for *occurrence* -- the exact file:line and the remedy, no CJK in the text."""
    point = ord(occurrence.char)
    return (
        f'{occurrence.path}:{occurrence.line}: a CJK character (U+{point:04X}) at column {occurrence.col} is not '
        f'permitted in tracked source. Translate it to English letters, digits and symbols, faithfully rather '
        f'than by deleting the information. If the character must survive verbatim -- for example a test '
        f'asserting that a guard REJECTS non-ASCII input -- write it as a \\uXXXX escape sequence instead: the '
        f'source becomes plain ASCII while the runtime value stays byte-identical, so the test still tests '
        f'what it tested. Otherwise, if it belongs to an exemption this family already grants, move the '
        f'content under .claude/memory/, attic/ or archived/ instead of declaring it here.'
    )


def ratchet(occurrences: Sequence[Occurrence], declared: Collection[str]) -> tuple[str, ...]:
    """BOTH SIDES of the CJK ratchet: an undeclared file with CJK, and a declared file with none left.

    *declared* is the adopting repo's own named set of files it still carries CJK in -- the migration
    ledger. A file found here and not in *declared* refuses NAMING the remedy; a file in *declared*
    and not found here refuses too, because a waiver nothing uses reads as a decision nobody made.
    """
    by_path: dict[str, Occurrence] = {}
    for occurrence in occurrences:
        by_path.setdefault(occurrence.path, occurrence)
    found = frozenset(by_path)
    pinned = frozenset(declared)
    problems = [f'UNDECLARED CJK -- {remedy(by_path[path])}' for path in sorted(found - pinned)]
    problems.extend(
        f'ORPHANED CJK declaration {path!r} -- no CJK remains in this file; remove it from the declared '
        f'set in this same commit.'
        for path in sorted(pinned - found)
    )
    return tuple(problems)
