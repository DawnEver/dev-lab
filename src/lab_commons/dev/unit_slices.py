"""The unit-in-name gap the gate does NOT see, measured as NAMED SLICES -- reported, never a verdict.

WHY THIS EXISTS. :func:`lab_commons.dev.units.scan_files` refuses a unit in a name on the DECLARED surface: parameters,
module/class-scope assignments, TOML/JSON keys and whole flag literals. Measured 2026-10-19 in the largest consumer,
that surface holds about 2.7k of about 13k real sites. The rest is not clean, it is UNSEEN, and a ratchet over an
unseen class is a ratchet over nothing. So every class the scan leaves out is measured here as its own slice, and a
slice is a NAMED SET of ``path:line:name`` sites rather than a count (``NAMED-SETS-NOT-COUNTS``): a consumer that later
ratchets on one can see WHICH site left and which arrived (``RATCHET-TWO-SIDES``), where a count would hide a swap.

THE SLICES, one per unseen class, each a declared row of :data:`SLICES`:

* ``python_local`` -- a FUNCTION-LOCAL assignment target ending in a unit token (``elapsed_sec``-shaped). The quantity
  carve-out of the gate applies unchanged: ``span_mm = Q_(1, 'mm')`` is EXEMPT, reported as such.
* ``python_attribute`` -- an attribute assignment target, ``self.gap_mm = ...``, at any scope.
* ``function_name`` -- a ``def`` whose name ends in a unit token (``def width_mm(...)``): a getter returning a bare
  float whose unit lives in the function's name is the same defect.
* ``si_letter`` -- the DECLARED surface again (parameters, module/class assignments), searched for the SI letters
  the shared registry excludes: :data:`SI_LETTERS`. The exclusion is the registry's KNOWING GAP; this slice is its size.
* ``output_key`` -- a string literal used as a KEY in Python source -- a ``dict`` display key or a subscript store
  ``row['torque_nm'] = ...`` -- because that key is what a JSON/JSONL/CSV file written by the source will carry.
* ``rust_identifier`` -- an identifier in a ``.rs`` file ending in a unit token, comments and string literals removed.
* ``comment_unit`` -- a numeric literal bound to a name that spells NO unit, while the comment on its line does
  (``FACE = 0.8  # mm``). The gate reads an AST and an AST has no comments, so this unit is invisible to it.
* ``absolute_tolerance`` -- a numeric literal passed as ``atol=``/``abs_tol=``, or bound to a name whose last segment
  is a tolerance word (:data:`TOLERANCE_SEGMENTS`) and that is not relative. ``TOLERANCE-CARRIES-A-UNIT``: an absolute
  tolerance is a statement about the unit of its inputs, and a suffix-free one does not even say which.

DECLARED NON-UNITS ARE DATA. :data:`DECLARED_EXCEPTIONS` names every spelling a slice would otherwise count and that the
census ruled is not a unit, each with its reason, and a site it removes goes to the slice's ``exempt`` set rather than
vanishing -- the same reported-not-silent carve-out :class:`lab_commons.dev.units.Scan` keeps. Rust parameters on a
pyo3 boundary (``#[pyfunction]``, a ``#[pymethods]`` impl, a ``#[pyo3(...)]`` attribute) are legitimate plain f64 at
the FFI seam and are exempt the same way.

THE BOUNDARY OF THE INSTRUMENT. Rust is read lexically, not parsed: an identifier is any word in code text, so a
``use`` path segment counts as much as a binding. The comment-unit detector reads a unit as a whole comment word in the
shared token table or an SI letter inside brackets (``[m]``, ``[N*m]``-style headers count only by their words). Both
are MEASUREMENTS to report, not refusals, which is the bar a lexical reader can honestly meet.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import sys
import tokenize
import warnings
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, NamedTuple

from lab_commons.dev._unit_tokens import UNIT_TOKENS
from lab_commons.dev.datedlog import dated_log
from lab_commons.dev.rules import tracked_files
from lab_commons.dev.units import _exempt_annotation, _exempt_assignment, trailing_token

__all__ = [
    'DECLARED_EXCEPTIONS',
    'SI_LETTERS',
    'SLICES',
    'TOLERANCE_SEGMENTS',
    'Report',
    'Site',
    'Slice',
    'main',
    'measure',
]

#: Every slice, in report order. A slice not in this tuple is never produced, and every one in it is always
#: produced -- an empty set and an absent key would otherwise read alike.
SLICES: Final[tuple[str, ...]] = (
    'python_local',
    'python_attribute',
    'function_name',
    'si_letter',
    'output_key',
    'rust_identifier',
    'comment_unit',
    'absolute_tolerance',
)

#: The SI letters the shared registry excludes and the ``si_letter`` slice measures. ``gb`` is not a registry row at
#: all; it is here because the census found gigabytes in names, and a slice is where an unregistered spelling is sized.
SI_LETTERS: Final[frozenset[str]] = frozenset({'gb', 'kw', 'm', 's', 'v', 'w'})

#: A last segment that makes a name a TOLERANCE. A name carrying a relative marker anywhere is relative and free.
TOLERANCE_SEGMENTS: Final[frozenset[str]] = frozenset({'atol', 'eps', 'epsilon', 'tol', 'tolerance'})
#: The slices decided by a name's unit SUFFIX -- the only ones a declared non-unit applies to. ``comment_unit`` and
#: ``absolute_tolerance`` are decided by a comment and a tolerance word; `atol=` has no separator and is no variable.
_SUFFIX_SLICES: Final[frozenset[str]] = frozenset(SLICES) - {'comment_unit', 'absolute_tolerance'}
_RELATIVE_SEGMENTS: Final[frozenset[str]] = frozenset({'rel', 'relative', 'rtol'})
_ABSOLUTE_KEYWORDS: Final[frozenset[str]] = frozenset({'abs_tol', 'atol'})


class _Exception(NamedTuple):
    """One declared non-unit: how it matches a lower-cased name, and why it is not a unit."""

    kind: str  # 'prefix' | 'suffix' | 'segment' | 'bare'
    value: str
    reason: str


#: The census's rulings (motronics HANDOFF 2026-10-19, "Legitimate exceptions"), as data. ``segment`` matches the
#: LAST segment, ``suffix``/``prefix`` the lower-cased name, ``bare`` a name with no separator at all.
DECLARED_EXCEPTIONS: Final[tuple[_Exception, ...]] = (
    _Exception('suffix', '_bar', 'a THRESHOLD or a bus bar (`TORQUE_BAR`), never a pressure in this family.'),
    _Exception('prefix', 'psi_', 'the Greek psi as FLUX LINKAGE (`psi_m`, `psi_s`); its trailing letter is an index.'),
    _Exception('segment', 'c', 'a coefficient or a count as often as celsius; ruled noise by the census.'),
    _Exception('segment', 'a', 'area, amplitude or an article as often as ampere; ruled noise by the census.'),
    _Exception('segment', 'n', 'a count or a size (`top_n`); a count is what an int already is.'),
    _Exception('segment', 'h', 'height, a harmonic or a headroom as often as an hour.'),
    _Exception('segment', 'min', 'a MINIMUM (`v_min`, `r_min`), never a minute.'),
    _Exception('bare', '', 'a name with no separator is a VARIABLE (`s`, `m`, `v` in a validator), not a suffix.'),
)


class Site(NamedTuple):
    """One measured site: ``(path, line, name)``, comparable and sortable as the tuple it reads as."""

    path: str
    line: int
    name: str

    def key(self) -> str:
        """``path:line:name``, the spelling a named set is written in."""
        return f'{self.path}:{self.line}:{self.name}'


@dataclass(frozen=True, slots=True)
class Slice:
    """One slice: the sites it COUNTS and the sites a declared exception removed, both sorted."""

    sites: tuple[Site, ...]
    exempt: tuple[Site, ...]


@dataclass(frozen=True, slots=True)
class Report:
    """Every slice, plus the floor facts: how many files were read and which were handed in and not read."""

    slices: Mapping[str, Slice]
    files_read: int
    skipped: tuple[str, ...]
    unparsed: tuple[str, ...] = ()

    def as_json(self) -> dict[str, object]:
        """The report as JSON: per slice, its count and its NAMED SET of ``path:line:name`` keys."""
        return {
            'files_read': self.files_read,
            'skipped': list(self.skipped),
            'unparsed': list(self.unparsed),
            'slices': {
                name: {
                    'count': len(part.sites),
                    'sites': [site.key() for site in part.sites],
                    'exempt': [site.key() for site in part.exempt],
                }
                for name, part in self.slices.items()
            },
        }


def _declared_exception(name: str) -> bool:
    """Whether *name* is a declared non-unit."""
    lowered = name.lower()
    segments = re.split(r'[_-]', lowered)
    for row in DECLARED_EXCEPTIONS:
        if (
            (row.kind == 'suffix' and lowered.endswith(row.value))
            or (row.kind == 'prefix' and lowered.startswith(row.value))
            or (row.kind == 'segment' and segments[-1] == row.value)
            or (row.kind == 'bare' and len(segments) == 1)
        ):
            return True
    return False


class _Collector:
    """Accumulates sites per slice; a site a declared exception removes goes to that slice's exempt set."""

    def __init__(self) -> None:
        self.sites: dict[str, set[Site]] = {name: set() for name in SLICES}
        self.exempt: dict[str, set[Site]] = {name: set() for name in SLICES}

    def add(self, slice_name: str, site: Site, *, exempt: bool = False) -> None:
        declared = slice_name in _SUFFIX_SLICES and _declared_exception(site.name)
        (self.exempt if exempt or declared else self.sites)[slice_name].add(site)

    def report(self, files_read: int, skipped: Iterable[str], unparsed: Iterable[str]) -> Report:
        return Report(
            slices={name: Slice(tuple(sorted(self.sites[name])), tuple(sorted(self.exempt[name]))) for name in SLICES},
            files_read=files_read,
            skipped=tuple(sorted(skipped)),
            unparsed=tuple(sorted(unparsed)),
        )


def _numeric(node: ast.AST | None) -> bool:
    """Whether *node* is a numeric literal, optionally negated -- a bool is not a number here."""
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        node = node.operand
    return isinstance(node, ast.Constant) and type(node.value) in {int, float}


def _comments(text: str) -> dict[int, str]:
    """Line -> comment text, from the tokenizer, so a ``#`` inside a string is never a comment."""
    found: dict[int, str] = {}
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                found[token.start[0]] = token.string
    except (tokenize.TokenError, IndentationError):
        pass
    return found


_COMMENT_WORD: Final = re.compile(r'[A-Za-zµ][A-Za-z0-9µ]*')
_BRACKET: Final = re.compile(r'\[([^\]]*)\]')


def _comment_has_unit(comment: str, tokens: Collection[str]) -> bool:
    """Whether a comment spells a unit: a whole word in the token table, or an SI letter alone in brackets."""
    if any(word.lower() in tokens for word in _COMMENT_WORD.findall(comment)):
        return True
    return any(inner.strip().lower() in SI_LETTERS for inner in _BRACKET.findall(comment))


def _target_name(target: ast.expr) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    return target.attr if isinstance(target, ast.Attribute) else None


def _is_tolerance(name: str) -> bool:
    segments = re.split(r'[_-]', name.lower())
    return segments[-1] in TOLERANCE_SEGMENTS and not _RELATIVE_SEGMENTS.intersection(segments)


_CALLABLES: Final = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_BINDINGS: Final = (ast.Assign, ast.AnnAssign, ast.AugAssign)


def _read_python(path: str, text: str, tokens: Collection[str], out: _Collector) -> None:  # noqa: C901 -- one branch per node kind; the set is the slice list
    """Feed every Python slice from one module, in a single descent carrying the local flag down."""
    comments = _comments(text)
    with warnings.catch_warnings():
        # A measured tree's own escape-sequence warnings are its business, not this report's output.
        warnings.simplefilter('ignore', SyntaxWarning)
        tree = ast.parse(text)
    pending: list[tuple[ast.AST, bool]] = [(tree, False)]
    while pending:
        node, local = pending.pop()
        below = local or isinstance(node, _CALLABLES)
        pending.extend((child, below) for child in ast.iter_child_nodes(node))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if trailing_token(node.name, tokens):
                out.add('function_name', Site(path, node.lineno, node.name))
            arguments = node.args
            every = (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, arguments.vararg, arguments.kwarg)
            for argument in every:
                if argument is not None and trailing_token(argument.arg, SI_LETTERS):
                    site = Site(path, argument.lineno, argument.arg)
                    out.add('si_letter', site, exempt=_exempt_annotation(argument.annotation))
        elif isinstance(node, _BINDINGS):
            _read_binding(node, path=path, local=local, tokens=tokens, comments=comments, out=out)
        elif isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str) and trailing_token(key.value, tokens):
                    out.add('output_key', Site(path, key.lineno, key.value))
        elif isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg in _ABSOLUTE_KEYWORDS and _numeric(keyword.value):
                    out.add('absolute_tolerance', Site(path, keyword.value.lineno, keyword.arg))


def _read_binding(  # noqa: C901 -- one branch per target kind; each feeds a different slice
    node: ast.Assign | ast.AnnAssign | ast.AugAssign,
    *,
    path: str,
    local: bool,
    tokens: Collection[str],
    comments: Mapping[int, str],
    out: _Collector,
) -> None:
    """The slices an assignment feeds: locals, attributes, SI letters, subscript keys, comment units, tolerances."""
    exempt = not isinstance(node, ast.AugAssign) and _exempt_assignment(node)
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    for target in targets:
        for leaf in ast.walk(target):
            if isinstance(leaf, ast.Name):
                if local and trailing_token(leaf.id, tokens):
                    out.add('python_local', Site(path, leaf.lineno, leaf.id), exempt=exempt)
                elif not local and trailing_token(leaf.id, SI_LETTERS):
                    out.add('si_letter', Site(path, leaf.lineno, leaf.id), exempt=exempt)
            elif isinstance(leaf, ast.Attribute) and isinstance(leaf.ctx, ast.Store):
                if trailing_token(leaf.attr, tokens):
                    out.add('python_attribute', Site(path, leaf.lineno, leaf.attr), exempt=exempt)
            elif (
                isinstance(leaf, ast.Subscript)
                and isinstance(leaf.ctx, ast.Store)
                and isinstance(leaf.slice, ast.Constant)
                and isinstance(leaf.slice.value, str)
                and trailing_token(leaf.slice.value, tokens)
            ):
                out.add('output_key', Site(path, leaf.lineno, leaf.slice.value))
        name = _target_name(target)
        if name is None or not _numeric(node.value):
            continue
        if _is_tolerance(name):
            out.add('absolute_tolerance', Site(path, target.lineno, name))
        unitless = trailing_token(name, tokens) is None and trailing_token(name, SI_LETTERS) is None
        if unitless and _comment_has_unit(comments.get(target.lineno, ''), tokens):
            out.add('comment_unit', Site(path, target.lineno, name))


_RUST_STRING: Final = re.compile(r'"(?:\\.|[^"\\])*"')
_RUST_IDENT: Final = re.compile(r'\b[A-Za-z_][A-Za-z0-9_]*\b')


def _read_rust(path: str, text: str, tokens: Collection[str], out: _Collector) -> None:  # noqa: C901 -- a lexer's state machine
    """Feed ``rust_identifier`` from one ``.rs`` file, lexically, with the pyo3 signature seam exempt.

    A pyo3 SIGNATURE is the text from ``fn`` up to its first ``{`` when the fn follows ``#[pyfunction]`` or sits
    directly in a ``#[pymethods]`` impl; a ``#[pyo3(...)]`` attribute line is boundary too.
    """
    depth = 0
    in_block_comment = False
    pyfunction_next = False
    pymethods_next = False
    pymethods_depth: int | None = None
    in_signature = False
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw
        if in_block_comment:
            end = line.find('*/')
            if end < 0:
                continue
            line, in_block_comment = line[end + 2 :], False
        line = re.sub(r'/\*.*?\*/', ' ', _RUST_STRING.sub('""', line))
        if '/*' in line:
            line, in_block_comment = line[: line.index('/*')], True
        line = line.split('//', 1)[0]
        stripped = line.strip()
        boundary = stripped.startswith('#[pyo3')
        if stripped.startswith('#[pyfunction'):
            pyfunction_next = True
        if stripped.startswith('#[pymethods'):
            pymethods_next = True
        if pymethods_next and re.match(r'(pub\s+)?impl\b', stripped):
            pymethods_depth, pymethods_next = depth, False
        in_impl = pymethods_depth is not None and depth == pymethods_depth + 1
        if re.search(r'\bfn\b', stripped) and (pyfunction_next or in_impl):
            in_signature, pyfunction_next = True, False
        for match in _RUST_IDENT.finditer(line):
            name = match.group(0)
            if trailing_token(name, tokens):
                out.add('rust_identifier', Site(path, number, name), exempt=boundary or in_signature)
        if in_signature and '{' in line:
            in_signature = False
        depth += line.count('{') - line.count('}')
        if pymethods_depth is not None and depth <= pymethods_depth:
            pymethods_depth = None


_READERS: Final = {'.py': _read_python, '.rs': _read_rust}


def measure(
    paths: Iterable[Path | str],
    *,
    root: Path | None = None,
    tokens: Collection[str] = frozenset(UNIT_TOKENS),
) -> Report:
    """Every slice over *paths*, which is the caller's list and is never walked. Never raises a verdict.

    A path is named relative to *root* when one is given. A file whose suffix no slice reads is NAMED in
    :attr:`Report.skipped`; a Python file that does not parse is NAMED in :attr:`Report.unparsed` and is not counted
    as read, because a file not read is not a clean one -- and one archived Python-2 file must not void a tree's report.
    """
    out = _Collector()
    skipped: list[str] = []
    unparsed: list[str] = []
    read = 0
    base = Path(root).resolve() if root is not None else None
    for item in paths:
        path = Path(item)
        named = path.resolve().relative_to(base).as_posix() if base is not None else path.as_posix()
        reader = _READERS.get(path.suffix.lower())
        if reader is None:
            skipped.append(named)
            continue
        try:
            reader(named, path.read_text(encoding='utf-8', errors='replace'), tokens, out)
        except SyntaxError:
            unparsed.append(named)
            continue
        read += 1
    return out.report(read, skipped, unparsed)


def _tracked(root: Path) -> list[Path]:
    return [root / name for name in sorted(tracked_files(root)) if Path(name).suffix.lower() in _READERS]


def main(argv: Sequence[str] | None = None) -> int:
    """``report <root> [--out FILE]``: print per-slice counts and write the named sets as JSON.

    The default JSON lands in THIS checkout's dated output tree (``output/logs/<yy>/<mm>/<dd>/units/``), never in
    *root*: the measured tree is read-only to this command.
    """
    parser = argparse.ArgumentParser(prog='python -m lab_commons.dev.units')
    sub = parser.add_subparsers(dest='verb', required=True)
    report = sub.add_parser('report', help='measure every unseen unit-in-name slice over a git checkout')
    report.add_argument('root', type=Path)
    report.add_argument('--out', type=Path, default=None, help='JSON file to write (default: dated output tree)')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    result = measure(_tracked(root), root=root)
    if args.out is None:
        args.out = dated_log(Path.cwd(), f'unit-slices-{root.name}.json', base='output/logs', kind='units')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {'root': root.name, **result.as_json()}
    args.out.write_text(json.dumps(payload, indent=1, sort_keys=False) + '\n', encoding='utf-8')
    width = max(len(name) for name in SLICES)
    lines = [f'files read: {result.files_read}  unparsed: {len(result.unparsed)}']
    lines += [
        f'{name:<{width}}  {len(part.sites):>6}  (exempt {len(part.exempt)})' for name, part in result.slices.items()
    ]
    lines.append(f'named sets: {args.out}')
    sys.stdout.write('\n'.join(lines) + '\n')
    return 0


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
