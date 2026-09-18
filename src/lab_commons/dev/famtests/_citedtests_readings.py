"""THE READ half of the cited-test body: what a file's PROSE says, and what the tree actually holds.

SPLIT OUT OF :mod:`lab_commons.dev.famtests.citedtests` at the seam that module's own first sentence
names -- "the READERS" -- and at the same seam :mod:`lab_commons.dev.famtests._configrender_readings`
and :mod:`lab_commons.dev.famtests._datedmemory_readings` already run on next door: everything here
is a READING and everything there is a VERDICT. A reading answers "what is on disk"; a verdict binds
a floor, compares against a declaration and names a remedy. The import runs ONE WAY, and the public
surface is unchanged -- every name here is re-exported by ``citedtests``, so a consumer has one
import and never learns where the seam falls.

NOTHING HERE RAISES ON AN OFFENDER. Every reader RETURNS THE SET, because a dangling citation is
pinned and reported in bulk -- the consumer that produced this body triaged 51 raw hits down to 11
across five narrowing steps, which an exception firing on the first one cannot do.

WHY THE TWO QUESTIONS SHARE A BODY AND STILL PRODUCE TWO ARMS. A citation is written two ways -- a
``tests/...`` PATH and a bare FUNCTION name -- and the two consumer files that ask them are 5.45% and
0.85% repo-density respectively, so one is over its repo's move bar and one is under it. Read
together the split is obvious: what they SHARE is the walk, the prose reader, the history exemptions
and the resolution rule, none of which names a repo; what each KEEPS is which trees it walks, which
files are history keepers, and its own floors. Reading either file alone would have moved a walk and
left its twin holding a copy of it.

THE PROSE READER IS THE SCOPE CLAIM, and it was narrower than its own declaration for weeks. A guard
saying "a comment that points at a guard must point at a guard that EXISTS" that reads only ``#``
lines leaves every docstring citation green: MEASURED in the originating consumer 2026-09-03, 14
dangling citations were sitting in docstrings, in five different modules, none reachable by the
comment filter. So :func:`prose_lines` reads BOTH, and ordinary string literals deliberately remain
out -- a path in code is DATA the code answers for, and a fixture naming a file that must NOT exist
is a legitimate use this scan has no business failing.

RESOLUTION IS BY PREFIX AND BY MODULE STEM, AND THAT IS A DELIBERATE WEAKENING STATED HERE RATHER
THAN LEFT IN THE CODE. Test names in this family are long, a comment that wraps one splits it across
two lines, and a citation is routinely written as a bare module stem with the ``.py`` left off. A
scanner that reported both as dangling would be mostly noise, and a mechanism that cries wolf is
deleted rather than obeyed. The cost is that a wrong name which happens to prefix a real one passes.
It is still strictly stronger than no check and it CANNOT PRODUCE A FALSE ALARM, which is what
decides whether a mechanism survives contact.

EVERY REPO-SHAPED FACT ARRIVES AS A KEYWORD ARGUMENT WITH NO DEFAULT, because the diff between the
consumers IS the repo boundary rather than a guess. Which directories hold POINTERS, which root
configs exist, what the file-level waiver header says, where ``tests/`` is, and which files keep
DATED narratives are five different answers in three repos -- and a guessed exemption set is the
worst of them, because it does not raise: it removes files from the population, and the scan then
reports clean over a tree it stopped reading. That is the ``LAB_CZ_BASE_REF`` shape exactly -- THE
FAILURE MODE OF A GUESSED ANSWER IS NOT AN ERROR, IT IS A WIDER SCOPE.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable
    from pathlib import Path

__all__ = [
    'CITED_FUNCTION',
    'CITED_PATH',
    'comment_blocks',
    'dangling_function_citations',
    'dangling_path_citations',
    'defined_test_functions',
    'defined_test_modules',
    'docstring_citation_count',
    'prose_lines',
    'resolves',
    'scanned_files',
]

#: A repo-relative test MODULE path, matched on the ``test_*.py`` suffix so the token is unambiguous.
#: The ``tests/`` prefix is required, which is what keeps this pattern off the bare-name form below:
#: one defect must never be reported by two mechanisms with two messages.
CITED_PATH = re.compile(r'(?<![\w/])(tests/[\w/]*test_[\w]+\.py)')

#: A test NAME in prose: a bare function name, or a bare ``test_x.py`` FILENAME with no directory on
#: it. THE BARE FILENAME WAS A HOLE IN BOTH PATTERNS and it hid a real defect -- the path form
#: requires a ``tests/`` prefix and the name form used to exclude anything ending ``.py``, so a
#: module cited by THREE priced timeout marks as the precedent their sizing copied was invisible to
#: both while not existing at all. The six-character floor keeps ``test_x`` scratch names out.
CITED_FUNCTION = re.compile(r'(?<![\w/])(test_[a-z0-9_]{6,}(?:\.py)?)(?![\w/])')


def prose_lines(path: Path) -> tuple[tuple[int, str], ...]:
    """Every line of PROSE in a module -- its ``#`` comments AND its docstrings -- as ``(lineno, text)``.

    Args:
        path: the file to read. A file that does not parse still yields its comment lines, because a
            syntax error is a reason to lose the docstrings and not a reason to stop scanning.

    Returns:
        Line numbers with their stripped text, sorted and de-duplicated. Docstring lines are yielded
        for the whole span of the string, since a wrapped citation sits on a continuation line.

    """
    text = path.read_text(encoding='utf-8', errors='replace')
    lines = text.splitlines()
    out = [(i, line.strip()) for i, line in enumerate(lines, 1) if line.strip().startswith('#')]
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return tuple(sorted(set(out)))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = node.body[0] if node.body else None
        if not (isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant) and isinstance(doc.value.value, str)):
            continue
        out.extend((i, lines[i - 1].strip()) for i in range(doc.lineno, (doc.end_lineno or doc.lineno) + 1))
    return tuple(sorted(set(out)))


def comment_blocks(lines: Iterable[tuple[int, str]]) -> tuple[tuple[frozenset[int], str], ...]:
    """Contiguous runs of prose lines, as ``(line numbers, joined text)``.

    BLOCK GRANULARITY, NOT LINE, because a dated narrative routinely puts its marker on one line and
    the name on the next, and a per-line reader would take that name for a live pointer. The
    exemption a consumer then applies is per SENTENCE rather than per block -- see
    :func:`dangling_function_citations` -- and that correction is load-bearing: checking the whole
    block silenced a LIVE pointer in the originating repo because an unrelated "used to" three lines
    earlier sat in the same run.
    """
    out: list[tuple[set[int], str]] = []
    prev: int | None = None
    for lineno, text in lines:
        if prev is not None and lineno == prev + 1:
            nums, joined = out[-1]
            nums.add(lineno)
            out[-1] = (nums, f'{joined} {text}')
        else:
            out.append(({lineno}, text))
        prev = lineno
    return tuple((frozenset(nums), text) for nums, text in out)


def scanned_files(
    root: Path,
    *,
    pointer_dirs: Collection[str],
    root_configs: Collection[str],
    waiver_header: str,
    waiver_dirs: Collection[str],
) -> tuple[Path, ...]:
    """The population whose prose is read: the pointer trees, the root configs, and waiver headers.

    Args:
        root: the consumer's checkout.
        pointer_dirs: directories where a citation is always a POINTER and never a record -- one
            repo answers ``('src', 'scripts')`` and another has no ``scripts/`` at all. NO DEFAULT.
        root_configs: root configuration filenames to read as prose. ``#`` starts a comment in all
            three of the usual formats, so they need no separate reader. NO DEFAULT: this was added
            after a lint config cited a guard deleted weeks earlier and survived, for one reason --
            the walk was two ``.py`` trees and a ``.toml`` at the root is in neither.
        waiver_header: the file-level header that makes a file a pointer WHEREVER it lives, because
            it names the ratchet governing the file it heads. NO DEFAULT; each repo words it.
        waiver_dirs: the trees searched for that header. NO DEFAULT -- it is the one part of this
            walk that deliberately reaches INTO ``tests/``.

    Returns:
        Sorted, de-duplicated, with ``__pycache__`` dropped.

    """
    pointers = [p for d in pointer_dirs if (root / d).is_dir() for p in (root / d).rglob('*.py')]
    pointers += [root / name for name in root_configs if (root / name).exists()]
    waivers = [
        p
        for d in waiver_dirs
        if (root / d).is_dir()
        for p in (root / d).rglob('*.py')
        if waiver_header in p.read_text(encoding='utf-8', errors='replace')
    ]
    return tuple(sorted({p for p in (*pointers, *waivers) if '__pycache__' not in p.parts}))


def defined_test_functions(root: Path, *, test_dir: str) -> frozenset[str]:
    """Every ``def test_*`` under *test_dir* -- the set a function citation resolves against.

    Read by regex rather than by AST deliberately: a test tree routinely holds a fixture file that
    does not parse under the running interpreter, and losing its names would turn every citation of
    them into a false alarm. A ``def`` line is not a shape a regex can misread.
    """
    pattern = re.compile(r'^\s*(?:async\s+)?def\s+(test_\w+)', re.MULTILINE)
    found: set[str] = set()
    for path in (root / test_dir).rglob('*.py'):
        if '__pycache__' in path.parts:
            continue
        found.update(pattern.findall(path.read_text(encoding='utf-8', errors='replace')))
    return frozenset(found)


def defined_test_modules(root: Path, *, test_dir: str) -> frozenset[str]:
    """Every ``test_*.py`` STEM under *test_dir*.

    A citation is routinely written as a bare module stem with the ``.py`` left off. Those name real
    FILES, so reporting them as missing FUNCTIONS would be a false alarm, and the path arm already
    owns the form that spells the suffix out.
    """
    return frozenset(p.stem for p in (root / test_dir).rglob('test_*.py') if '__pycache__' not in p.parts)


def resolves(token: str, *, defined: Collection[str], modules: Collection[str]) -> bool:
    """Exactly, as a module stem, or as a wrapped fragment -- see this module's docstring.

    The prefix AND suffix arms are both needed because a wrap can fall on either side of the name.
    """
    token = token.removesuffix('.py')
    names = frozenset(defined) | frozenset(modules)
    if token in names:
        return True
    return any(name.startswith(token) or name.endswith(token) for name in names)


def dangling_path_citations(
    root: Path,
    *,
    files: Collection[Path],
    history_keepers: Collection[str],
) -> tuple[str, ...]:
    """Every prose line citing a ``tests/...`` module that is not on disk, as ``path:line -> cited``.

    Args:
        root: the checkout the cited path is resolved against.
        files: what :func:`scanned_files` returned, passed in so one walk feeds both arms.
        history_keepers: repo-relative paths whose prose is a DATED LOG rather than directions to a
            reader -- rewriting a path inside one falsifies the record. NO DEFAULT, and a consumer
            must assert each of them still exists: an exemption naming a deleted file is a silent
            widening, because it stops covering anything at all.

    """
    keepers = frozenset(history_keepers)
    out: list[str] = []
    for path in sorted(files):
        rel = path.relative_to(root).as_posix()
        if rel in keepers:
            continue
        for lineno, text in prose_lines(path):
            out += [f'{rel}:{lineno} -> {cited}' for cited in CITED_PATH.findall(text) if not (root / cited).exists()]
    return tuple(out)


def dangling_function_citations(
    root: Path,
    *,
    files: Collection[Path],
    history_keepers: Collection[str],
    history_markers: Collection[str],
    not_citations: Collection[str],
    defined: Collection[str],
    modules: Collection[str],
) -> tuple[str, ...]:
    """Every prose sentence naming a test FUNCTION that resolves to nothing, as ``path:line -> cited``.

    Args:
        root: the checkout, used only to spell each hit repo-relative.
        files: what :func:`scanned_files` returned.
        history_keepers: whole files exempt as dated logs -- see :func:`dangling_path_citations`.
        history_markers: phrases that make a SENTENCE a record rather than a pointer -- "was
            DELETED", "Split out of ``x``", "Replaces ``x``". NO DEFAULT and deliberately narrow:
            each is meant to sit immediately before the token it excuses, because a bare "replaces"
            anywhere in a block covered a genuine stale pointer two files over.
        not_citations: tokens that look like a test name and are not one -- ``test_files``,
            ``test_module``. NO DEFAULT: it is vocabulary, and one repo's vocabulary silently
            removing another's real citations is the guessed-exclusion failure.
        defined: what :func:`defined_test_functions` returned.
        modules: what :func:`defined_test_modules` returned.

    """
    keepers = frozenset(history_keepers)
    vocabulary = frozenset(not_citations)
    out: list[str] = []
    for path in sorted(files):
        rel = path.relative_to(root).as_posix()
        if rel in keepers:
            continue
        for nums, text in comment_blocks(prose_lines(path)):
            for sentence in re.split(r'(?<=[.;])\s+', text):
                if any(marker in sentence for marker in history_markers):
                    continue
                out.extend(
                    f'{rel}:{min(nums)} -> {token}'
                    for token in CITED_FUNCTION.findall(sentence)
                    if token not in vocabulary and not resolves(token, defined=defined, modules=modules)
                )
    return tuple(out)


def docstring_citation_count(files: Collection[Path]) -> int:
    """How many citations sit on DOCSTRING lines -- the floor the file count cannot supply.

    Reaching every file says nothing about reaching their prose. A regression putting
    :func:`prose_lines` back to comments only leaves a file-count floor green and this number on the
    floor, which is the one reading that can tell the two apart.
    """
    return sum(
        len(CITED_PATH.findall(text)) + len(CITED_FUNCTION.findall(text))
        for path in files
        for _, text in prose_lines(path)
        if not text.startswith('#')
    )
