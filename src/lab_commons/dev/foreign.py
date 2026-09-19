"""FOREIGN DATA IN THE LEAF -- the scan that tells three kinds apart, and the two-sided arm.

WHAT THIS REFUSES. This package is the family's leaf: three repos import it and it imports none of
them. Its README's tier-1 rule -- "contains no concept from any single project's domain" -- and
`.claude/rules/statement-and-mechanism.md` -- "a STATEMENT is universal; a MECHANISM is a path in
ONE tree" -- were both being read on every turn while the `dev` layer absorbed a consumer's rows
and a consumer's tree paths as shipped source. Prose does not hold a line; a scan with a floor and a
named waiver set does.

THREE KINDS, BECAUSE THEY ARE NOT EQUALLY WRONG, and collapsing them is how the finding would have
become unactionable:

* :data:`DATA` -- an executable string constant naming a sibling repo. The worst kind: it is a
  DECISION about another tree, shipped, and it runs.
* :data:`PATH` -- a path-shaped executable constant that does NOT resolve in this checkout. That is
  the definition rather than "a path that looks foreign", and it is what makes the reading portable:
  a mechanism this repo cannot resolve is a mechanism in a tree this repo does not have, whoever
  owns that tree. No sibling checkout is required to take the measurement.
* :data:`PROSE` -- a docstring or comment naming a sibling. The least wrong: a docstring saying
  where a finding came from is evidence. It is counted and ceilinged, never waived row by row.

THE ARM IS TWO-SIDED, as a ratchet must be. An unwaived finding reds -- nothing new arrives. A
waived handle whose finding is GONE also reds -- the waiver may not outlive its row, which is what
makes every eviction mechanical: delete the row, delete its handle, the suite agrees. A one-sided
version would let the registry fill with waivers nothing uses, which is the same defect as the data
it was built to evict.

THE WAIVER IS A NAMED SET, never a count, for the reason the rules page already gives: an integer
cannot say WHICH row moved, so when it disagrees the honest-looking repair is to edit the digit.
The set is DATA in :mod:`lab_commons.dev._foreign_rows`; nothing here decides who is a sibling.

NO ARGUMENT HAS A DEFAULT. A missing row must be a REFUSAL, never a silent fall-back to another
repo's data -- which is the failure this whole module is about, one layer in.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lab_commons.dev.floors import assert_floor

__all__ = [
    'DATA',
    'PATH',
    'PROSE',
    'Finding',
    'ForeignData',
    'StaleWaiver',
    'assert_no_foreign_data',
    'assert_prose_is_falling',
    'classify_text',
    'is_unresolved_path',
    'kinds',
    'modules_read',
    'scan',
]

#: An executable constant naming a sibling repo.
DATA: Final = 'data'

#: A path-shaped executable constant that does not resolve in the tree being scanned.
PATH: Final = 'path'

#: A docstring or comment naming a sibling repo.
PROSE: Final = 'prose'

#: PROSE IS DECIDED BY LENGTH, NOT BY POSITION, and this constant is that claim. A row`s ``why=``
#: field is a paragraph explaining a decision -- it sits in executable position and is prose by
#: SUBJECT, and reading it as a live value would report 22 sentences as data about a sibling while
#: the four values that really are data (`'wdg-lab'`, `'pareto'`) drowned in them. A string long
#: enough to be a sentence is prose wherever it lives; a short one is a VALUE. MEASURED: every real
#: datum found in this package is under 20 characters and every justification over 200.
_SENTENCE: Final = 120

#: A path-shaped literal that names a FILE: at least one separator, only the characters a
#: repo-relative POSIX path uses, and a source-or-config EXTENSION on the last segment. The
#: extension is not decoration -- without it the reading swallows `rad/s`, `A/m`, `application/json`
#: and `refs/remotes/origin`, all of which are path-SHAPED and none of which is a mechanism. A
#: string carrying a brace, a percent or a star is a TEMPLATE or a GLOB: it names a shape rather
#: than a file, so "does it resolve" is not a question about it and it is not read here.
_PATHLIKE: Final = re.compile(
    r'^[A-Za-z_.][\w.-]*(?:/[\w.-]+)*/[\w.-]+\.(?:py|sh|js|json|ya?ml|toml|md|cfg|ini|txt|ps1)$'
)


class ForeignData(AssertionError):
    """The leaf carries a sibling's data or a sibling's tree path that nothing has evicted."""


class StaleWaiver(AssertionError):
    """A handle is evicted-by-design but the scan no longer finds it -- a waiver nothing uses."""


@dataclass(frozen=True, slots=True)
class Finding:
    """One foreign datum, with the handle its waiver is spelled as.

    The module path is REPO-RELATIVE with POSIX separators, so a handle means the same thing on
    every box: an absolute path would name one checkout, and a waiver keyed by one checkout is a
    waiver nobody else can honour.
    """

    module: str
    lineno: int
    kind: str
    text: str
    sibling: str | None = None

    @property
    def handle(self) -> str:
        """``'<module>::<kind>'`` -- one waiver per module per kind, never per occurrence.

        Per OCCURRENCE would pin a line number, and a line number moves when anything above it
        does; per MODULE alone would let a new kind arrive under an existing waiver. The pair is the
        coarsest handle that still cannot admit something nobody decided on.
        """
        return f'{self.module}::{self.kind}'


def classify_text(text: str, siblings: tuple[str, ...]) -> str | None:
    """Which sibling *text* names, longest spelling first -- or ``None``.

    Args:
        text: the string to read.
        siblings: the repo names, LONGEST FIRST. Order is the caller's because the data half owns
            it: ``motronics`` is a prefix of ``motronics-studio``, and a finding that misnames its
            subject sends the reader to the wrong tree.

    Returns:
        The sibling named, or ``None``.

    """
    lowered = text.lower()
    for name in siblings:
        if name.lower() in lowered:
            return name
    return None


def is_unresolved_path(text: str, repo_root: Path) -> bool:
    """Is *text* a repo-relative path that does NOT exist under *repo_root*?

    THE DEFINITION IS "DOES NOT RESOLVE", not "looks like somebody else's". A path this repo cannot
    resolve is a path in a tree this repo does not have, and that reading needs no sibling checkout
    to take -- so the measurement is the same on a developer's box, in CI, and inside a wheel.

    Args:
        text: the string constant to read.
        repo_root: the checkout the path is resolved against. NO DEFAULT: resolving against a
            guessed root is how a scan silently answers a different question.

    Returns:
        ``True`` when the text is path-shaped and names nothing here.

    """
    stripped = text.strip()
    if not _PATHLIKE.match(stripped) or '..' in stripped.split('/'):
        return False
    return not (repo_root / stripped).exists()


def _docstring_ids(tree: ast.Module) -> set[int]:
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    found: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, 'body', None)
        if not isinstance(node, holders) or not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            found.add(id(first.value))
    return found


def _kind_of(text: str, *, is_docstring: bool, sibling: str | None, repo_root: Path) -> str | None:
    """Which kind *text* is, or ``None`` -- the whole classification, in one place a reader can hold.

    ORDER IS THE MEANING. A docstring is prose whatever it says; a SENTENCE is prose wherever it
    sits; only then is a short string carrying a sibling name a live VALUE; and a path is judged
    last, because a path constant naming no sibling is still a mechanism in a tree that is not here.
    """
    if is_docstring:
        return PROSE if sibling else None
    if sibling and len(text) > _SENTENCE:
        return PROSE
    if sibling and not is_unresolved_path(text, repo_root):
        return DATA
    if is_unresolved_path(text, repo_root):
        return PATH
    return None


def _read_module(path: Path, module: str, repo_root: Path, siblings: tuple[str, ...]) -> list[Finding]:
    source = path.read_text(encoding='utf-8')
    tree = ast.parse(source)
    docstrings = _docstring_ids(tree)
    out: list[Finding] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        text = node.value
        sibling = classify_text(text, siblings)
        kind = _kind_of(text, is_docstring=id(node) in docstrings, sibling=sibling, repo_root=repo_root)
        if kind is not None:
            shown = text.strip() if kind == PATH else text[:120]
            out.append(Finding(module, node.lineno, kind, shown, sibling))
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            sibling = classify_text(token.string, siblings)
            if sibling:
                out.append(Finding(module, token.start[0], PROSE, token.string.strip()[:120], sibling))
    return out


def scan(
    source_root: Path, *, repo_root: Path, siblings: tuple[str, ...], exclude: tuple[str, ...]
) -> tuple[Finding, ...]:
    """Every foreign datum under *source_root*, with the count of modules read bound by its caller.

    Args:
        source_root: the package tree to walk.
        repo_root: the checkout a path constant is resolved against, and the root module paths are
            reported relative to.
        siblings: the sibling repo names, longest spelling first.
        exclude: repo-relative modules that may name a sibling -- the registry of the violation
            cannot record who the siblings are without spelling them. By NAME, never by a pattern:
            a pattern is what widens during a red suite.

    Returns:
        Findings, ordered by module then line.

    """
    findings: list[Finding] = []
    for path in sorted(source_root.rglob('*.py')):
        module = path.relative_to(repo_root).as_posix()
        if module in exclude:
            continue
        findings.extend(_read_module(path, module, repo_root, siblings))
    return tuple(sorted(findings, key=lambda f: (f.module, f.lineno)))


def kinds(findings: tuple[Finding, ...], wanted: str) -> tuple[Finding, ...]:
    """The findings of one kind, published so a caller can count or print without re-walking."""
    return tuple(f for f in findings if f.kind == wanted)


def modules_read(source_root: Path, exclude: tuple[str, ...], repo_root: Path) -> int:
    """How many modules a :func:`scan` over the same arguments would read -- the floor's input."""
    return sum(1 for p in source_root.rglob('*.py') if p.relative_to(repo_root).as_posix() not in exclude)


def assert_no_foreign_data(
    findings: tuple[Finding, ...],
    *,
    evicted: dict[str, str],
    synthetic: dict[str, str],
    read: int,
    floor: int,
) -> None:
    """BOTH SIDES: no unwaived foreign datum, and no waiver whose row is gone.

    THE TWO WAIVER SETS ARE SEPARATE ARGUMENTS AND THE MERGE HAPPENS HERE, in the machinery, where
    computing belongs. Their logic is identical and their MEANING is not: *evicted* is an eviction
    ORDER, *synthetic* is a set of path-shaped strings that name no tree at all. Folding them into
    one mapping would put rows in the eviction list that are never going anywhere, and a waiver list
    nobody believes is a waiver list nobody reads.

    Args:
        findings: the ``data`` and ``path`` findings to judge. The caller filters, because the
            ``prose`` kind is ceilinged rather than waived and mixing them would make every
            docstring a row somebody has to evict.
        evicted: ``handle -> why the deletion is not in this pass``. NO DEFAULT -- an empty mapping
            must be something a caller TYPED, never what it gets by saying nothing.
        synthetic: ``handle -> what the example illustrates``. NO DEFAULT, same reason.
        read: how many modules the scan reached.
        floor: the smallest reach that makes an empty result mean anything.

    Raises:
        ForeignData: a finding with no handle in either mapping.
        StaleWaiver: a handle in either mapping that the scan did not find.

    """
    assert_floor(read, floor=floor, what='the foreign-data scan')
    waived = {**evicted, **synthetic}
    seen = {f.handle for f in findings}
    unwaived = sorted({f.handle for f in findings} - set(waived))
    if unwaived:
        examples = {h: next(f.text for f in findings if f.handle == h) for h in unwaived}
        msg = (
            f'the leaf carries foreign data nothing has evicted: {unwaived}. This package is the '
            f'family`s LEAF -- a consumer`s rows and a consumer`s tree paths are that consumer`s to '
            f'hold, and a body here takes them as an argument with no default. Examples: {examples}. '
            f'Publish the parametrized body and pass the data in; do not add a handle to '
            f'`_foreign_rows.EVICTED` for a row that arrived TODAY.'
        )
        raise ForeignData(msg)
    stale = sorted(set(waived) - seen)
    if stale:
        msg = (
            f'evicted-by-design handles the scan no longer finds: {stale}. A waiver that outlives '
            f'its row is a waiver nothing uses, which is the same defect as the data it waived. If '
            f'the rows are gone, delete the handles in the SAME edit -- that is what makes the '
            f'eviction mechanical.'
        )
        raise StaleWaiver(msg)


def assert_prose_is_falling(found: int, *, ceiling: int) -> None:
    """The PROSE half may only fall, and a ceiling that has been beaten must be RE-MEASURED.

    Two-sided for the ratchet's own reason: a ceiling well above the reading admits growth nobody
    decided on, so beating it is an instruction to lower it rather than a pass.

    Args:
        found: sibling mentions in docstrings and comments, now.
        ceiling: the last measurement. NO DEFAULT: a ceiling nobody typed is a ceiling nobody owns.

    Raises:
        ForeignData: the count grew past the ceiling, or fell below it without the ceiling moving.

    """
    if found > ceiling:
        msg = (
            f'sibling mentions in prose read {found}, above the {ceiling} ceiling. A docstring '
            f'naming the repo a finding came from is evidence, so this number is allowed to be '
            f'large -- it is not allowed to GROW. Name the SHAPE of the thing, not the repo that '
            f'has one: an example is a spelling waiting to be retired.'
        )
        raise ForeignData(msg)
    if found < ceiling:
        msg = (
            f'sibling mentions in prose read {found}, below the {ceiling} ceiling: RE-MEASURE it to '
            f'{found} in `_foreign_rows.PROSE_CEILING` in this edit. A ceiling left above its '
            f'reading is headroom nobody granted, and it is how the next {ceiling - found} arrive '
            f'without anyone deciding.'
        )
        raise ForeignData(msg)
