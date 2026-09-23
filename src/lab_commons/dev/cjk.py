"""The family's ONE "no CJK in tracked source" guard -- the scan, the exemptions, the floor.

THE USER DIRECTIVE, 2026-09-16, translated rather than quoted: across every repo in this family,
no content that git tracks may contain CJK (Chinese/Japanese/Korean) characters -- only English
letters, digits and symbols. Exempt: ``.claude/memory/``, ``attic/``, ``archived/`` (the last at the
repo root only, since 2026-09-23), and a ``<stem>.zh.md`` translation beside its English
``<stem>.md`` (:data:`TRANSLATION_SUFFIXES`). It is not kept
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

THERE IS NO CONTENT-BASED EXEMPTION, ONLY THE PATH PREFIXES AND THE TRANSLATION NAME ABOVE, and this was a real design
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

import re
import unicodedata
from collections import Counter
from collections.abc import Collection, Iterable, Iterator, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Final, NamedTuple

__all__ = [
    'CJK_RANGES',
    'EXEMPT_PREFIXES',
    'SOURCE_SUFFIX',
    'TRANSLATION_SUFFIXES',
    'NonAsciiScan',
    'Occurrence',
    'Scan',
    'VacuousScan',
    'assert_floor',
    'char_class',
    'exempted',
    'find_cjk',
    'is_cjk',
    'non_ascii_distance',
    'orphaned_translations',
    'ratchet',
    'remedy',
    'scan_files',
    'scan_non_ascii',
    'translation_exempted',
    'translation_source',
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
#:
#: TWO SHAPES, AND THE LEADING ``/`` IS WHAT TELLS THEM APART. A bare prefix matches as a path
#: SEGMENT ANYWHERE in the path; a prefix spelled with a leading ``/`` is ANCHORED AT THE REPO ROOT
#: and matches nowhere else. See :func:`exempted` for the match itself.
#:
#: ``.claude/memory/`` AND ``attic/`` MATCH AT ANY DEPTH, and this is measured rather than a stylistic
#: choice: motronics-studio's memory tree is SCOPED per module (``src/motronics/hamilton/.claude/memory/``,
#: ``rust/.claude/memory/``) and its ``attic/`` holds one subtree per migrated repo. A root-prefix-only
#: match on that tree reported 47,521 CJK characters under ``src/motronics/**`` when the real answer
#: is zero -- every one of them a nested memory file the prefix test could not see.
#:
#: ``archived/`` IS ROOT-ONLY (user directive, 2026-09-23). It names ONE repo-root directory in every
#: family repo that has it, and a segment match made ``x/archived/f.py`` exempt too -- a directory of
#: that name created anywhere in a source tree would have opened a CJK island nobody declared.
EXEMPT_PREFIXES: Final[tuple[str, ...]] = ('.claude/memory/', 'attic/', '/archived/')

#: THE TRANSLATION MECHANISM (``TRANSLATION-HAS-ITS-SOURCE``, user directive 2026-09-23). A tracked
#: document named ``<stem>.zh.md`` is a TRANSLATION, and it is exempt from this guard ONLY while its
#: English SOURCE ``<stem>.md`` sits beside it in the same corpus: the English page is the source of
#: truth and the translation is a rendering of it. An ORPHANED translation is not exempt -- it is
#: read like any other file, and :func:`orphaned_translations` refuses it by name, because a
#: translation with no source is simply non-English documentation under a different suffix.
TRANSLATION_SUFFIXES: Final[tuple[str, ...]] = ('.zh.md',)

#: What the source of a translation is named with: ``<stem>`` + this suffix.
SOURCE_SUFFIX: Final = '.md'


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
        """Iterate the occurrences, so the report can be read as its own rows."""
        return iter(self.occurrences)


def is_cjk(char: str, ranges: Collection[tuple[int, int]] = CJK_RANGES) -> bool:
    """Whether *char* falls in one of *ranges* -- the one place a code point is checked."""
    point = ord(char)
    return any(lo <= point <= hi for lo, hi in ranges)


@cache
def _pattern(ranges: tuple[tuple[int, int], ...]) -> re.Pattern[str]:
    """One compiled character class DERIVED from *ranges* -- never a second, retyped range list.

    Deriving it is the whole point: widening :data:`CJK_RANGES` stays a one-line change, and the
    fast path cannot drift away from the code points :func:`is_cjk` answers for. ``re.escape`` is
    applied to each endpoint so a range whose bounds are regex metacharacters (``-``, ``]``, ``^``)
    could not silently build a class that means something else.
    """
    spans = ''.join(f'{re.escape(chr(lo))}-{re.escape(chr(hi))}' for lo, hi in ranges)
    return re.compile(f'[{spans}]')


def find_cjk(text: str, ranges: Collection[tuple[int, int]] = CJK_RANGES) -> tuple[tuple[int, int, str], ...]:
    r"""Every ``(line, col, char)`` in *text* where a character falls in *ranges*. Both 1-based.

    THE PREFILTER SKIPS WORK, NEVER SOFTENS A VERDICT. Measured 2026-09-17 over motronics-studio
    (8489 tracked files, 93.9 M characters): the per-character walk cost 193.52 s and answering
    "does this text contain any CJK at all?" with the same class costs 0.66 s, because 7686 of
    those files contain none and the walk was proving that one character at a time. A text the
    class rejects provably holds no code point in *ranges* -- the class IS *ranges* -- so returning
    the empty tuple for it is the identical answer, reached without the walk. Text that does match
    pays the detailed pass, which reports exactly what it always did.

    The detailed pass scans each line with the same class rather than per character, keeping
    ``splitlines()`` as the line authority so every line and column is unchanged -- including the
    boundaries ``splitlines()`` counts that ``\\n`` alone does not.
    """
    pattern = _pattern(tuple(ranges))
    if not pattern.search(text):
        return ()
    found: list[tuple[int, int, str]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        found.extend((line_no, match.start() + 1, match.group()) for match in pattern.finditer(line))
    return tuple(found)


def exempted(name: str, prefixes: Collection[str] = EXEMPT_PREFIXES) -> bool:
    """Whether *name* (a repo-relative POSIX path) sits under one of *prefixes*.

    A prefix with a leading ``/`` is ANCHORED: it matches only at the repo root, so ``/archived/``
    exempts ``archived/f.py`` and not ``x/archived/f.py``. Any other prefix is checked both at the
    ROOT (``name.startswith(prefix)``) and as a SEGMENT nested deeper (``f'/{prefix}'`` appearing in
    *name*) -- see :data:`EXEMPT_PREFIXES` for the measured tree that made a root-only match wrong for
    those. The leading ``/`` in the nested check is what keeps ``notattic/x`` from matching
    ``attic/``: the prefix must start a path SEGMENT, not merely appear as a substring.
    """
    for prefix in prefixes:
        if prefix.startswith('/'):
            if name.startswith(prefix[1:]):
                return True
        elif name.startswith(prefix) or f'/{prefix}' in name:
            return True
    return False


def translation_source(name: str) -> str | None:
    """The English source a translation *name* renders (``a/b.zh.md`` -> ``a/b.md``), or ``None``.

    ``None`` means *name* is not a translation at all, so the translation mechanism has nothing to
    say about it. The answer is a NAME, not a verdict: whether that source exists is a fact about the
    corpus, which :func:`translation_exempted` and :func:`orphaned_translations` are handed.
    """
    for suffix in TRANSLATION_SUFFIXES:
        stem = name[: -len(suffix)]
        if name.endswith(suffix) and stem and not stem.endswith('/'):
            return stem + SOURCE_SUFFIX
    return None


def translation_exempted(name: str, corpus: Collection[str]) -> bool:
    """Whether *name* is a translation whose English source is also in *corpus* -- nothing else is."""
    source = translation_source(name)
    return source is not None and source in corpus


def orphaned_translations(corpus: Iterable[str]) -> tuple[str, ...]:
    """One refusal per translation in *corpus* with no English source in *corpus*, naming the remedy.

    *corpus* is repo-relative POSIX names -- a repo's tracked files. A translation whose source is
    absent is not exempt from anything, and saying so by name is the point: without this refusal an
    orphan would surface only as an anonymous CJK hit, and the cheapest-looking repair would be to
    declare it rather than to restore the page it was translated from.
    """
    names = frozenset(corpus)
    problems: list[str] = []
    for name in sorted(names):
        source = translation_source(name)
        if source is not None and source not in names:
            problems.append(
                f'ORPHANED TRANSLATION {name!r} -- its English source {source!r} is not tracked. The '
                f'English page is the source of truth and a translation is exempt only beside it: add '
                f'(or restore) {source!r} with the English text, or delete the translation.'
            )
    return tuple(problems)


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
    checkout. The paths handed over ARE the corpus the translation mechanism consults: a
    ``<stem>.zh.md`` is exempted only when ``<stem>.md`` is among them.
    Pair it with :func:`lab_commons.dev.rules.tracked_files` to scan a repo's real corpus.

    Raises:
        ValueError: *root* was declared and a path is not under it.
        OSError: a file could not be opened.

    """
    occurrences: list[Occurrence] = []
    skipped: list[str] = []
    undecodable: list[str] = []
    base = Path(root).resolve() if root is not None else None
    named_paths = [(Path(item), _named(Path(item), base)) for item in paths]
    corpus = frozenset(named for _, named in named_paths)
    read = 0
    for path, named in named_paths:
        if exempted(named, exempt_prefixes) or translation_exempted(named, corpus):
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
        f'content under .claude/memory/, attic/ or the repo-root archived/ instead of declaring it here; '
        f'a translated document is named <stem>.zh.md beside its English <stem>.md.'
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


# -- THE FINAL GOAL: no non-ASCII at all, measured as a DISTANCE rather than refused one site at a time.
#
# THE CJK RULE ABOVE IS THE RULE AS RULED ON 2026-09-16; THE USER'S FINAL GOAL (2026-09-23) IS WIDER:
# no non-ASCII character in any tracked file, under the SAME exemptions and the same translation
# mechanism. The population is far too large for one commit, so this half publishes a READING -- how
# far a corpus is from that goal, by file and by character class -- and a consumer asserts on it so
# the distance is shown as a real test failure until it reaches zero.

#: Unicode general categories, spelled for a reader. A character class is its category's name, so a
#: report groups an em dash with the other dashes and a multiplication sign with the math symbols.
_CATEGORY_NAMES: Final[dict[str, str]] = {
    'Lu': 'letter (upper)',
    'Ll': 'letter (lower)',
    'Lt': 'letter (title)',
    'Lm': 'letter (modifier)',
    'Lo': 'letter (other)',
    'Mn': 'mark',
    'Mc': 'mark',
    'Me': 'mark',
    'Nd': 'digit',
    'Nl': 'number',
    'No': 'number (other)',
    'Pc': 'punctuation (connector)',
    'Pd': 'dash',
    'Ps': 'bracket',
    'Pe': 'bracket',
    'Pi': 'quote',
    'Pf': 'quote',
    'Po': 'punctuation (other)',
    'Sm': 'math symbol',
    'Sc': 'currency symbol',
    'Sk': 'modifier symbol',
    'So': 'symbol (other)',
    'Zs': 'space',
    'Zl': 'line separator',
    'Zp': 'paragraph separator',
    'Cc': 'control',
    'Cf': 'format',
    'Co': 'private use',
    'Cn': 'unassigned',
}


def char_class(char: str) -> str:
    """The class a non-ASCII *char* is reported under: ``CJK`` for :data:`CJK_RANGES`, else its category."""
    if is_cjk(char):
        return 'CJK'
    return _CATEGORY_NAMES.get(unicodedata.category(char), unicodedata.category(char))


@dataclass(frozen=True, slots=True)
class NonAsciiScan:
    """Every non-ASCII character in a corpus, counted per FILE and per CLASS. Names, not just totals."""

    by_file: dict[str, Counter[str]]
    files_read: int

    @property
    def total(self) -> int:
        """How many non-ASCII characters remain across the corpus -- the headline distance."""
        return sum(sum(counts.values()) for counts in self.by_file.values())


def scan_non_ascii(
    paths: Iterable[Path | str],
    *,
    exempt_prefixes: Collection[str] = EXEMPT_PREFIXES,
    root: Path | None = None,
) -> NonAsciiScan:
    """Every non-ASCII character in *paths*, under exactly the exemptions :func:`scan_files` grants.

    Undecodable files are skipped exactly as there; a translation beside its source is exempt exactly
    as there, so the two readings can never disagree about which files are in scope.
    """
    base = Path(root).resolve() if root is not None else None
    named_paths = [(Path(item), _named(Path(item), base)) for item in paths]
    corpus = frozenset(named for _, named in named_paths)
    by_file: dict[str, Counter[str]] = {}
    read = 0
    for path, named in named_paths:
        if exempted(named, exempt_prefixes) or translation_exempted(named, corpus):
            continue
        try:
            text = path.read_bytes().decode('utf-8')
        except UnicodeDecodeError:
            continue
        read += 1
        if not text.isascii():
            by_file[named] = Counter(char_class(char) for char in text if not char.isascii())
    return NonAsciiScan(by_file=by_file, files_read=read)


def non_ascii_distance(scan: NonAsciiScan, *, top: int = 15) -> str:
    """The distance to an all-ASCII corpus, as a report a failing test can print verbatim.

    Totals first (characters, files), then the per-class breakdown across the corpus, then the *top*
    offending files with their own per-class counts -- the order a reader needs to price the work.
    """
    classes: Counter[str] = Counter()
    for counts in scan.by_file.values():
        classes.update(counts)
    ranked = sorted(scan.by_file.items(), key=lambda item: (-sum(item[1].values()), item[0]))
    lines = [
        f'{scan.total} non-ASCII character(s) remain in {len(scan.by_file)} of {scan.files_read} file(s) read.',
        'by character class: ' + ', '.join(f'{name} {count}' for name, count in classes.most_common()),
        f'top {min(top, len(ranked))} file(s):',
    ]
    lines.extend(
        f'  {sum(counts.values()):>6}  {name}  (' + ', '.join(f'{cls} {n}' for cls, n in counts.most_common()) + ')'
        for name, counts in ranked[:top]
    )
    return '\n'.join(lines)
