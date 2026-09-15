"""A name that spells its unit is refused, and the TOKEN SET it was refused against is part of the answer.

THE DEFECT, from first principles. ``--slot-pitch-mm=12.5`` tells a reader the unit and hands pint
nothing: the value is a unitless float, so nothing downstream can convert it, and the unit is
recoverable only by the reader's memory of the flag's name. The user's ruling -- "所有 单位必须经过
pint 禁止任何这种 --slot-pitch-mm|slot_pitch_mm|conductor-width-mm" -- bans the SPELLING, and the ban
is what makes pint non-optional: once a name may not carry a unit, the value is the only place left
for one. This module is the naming half; :mod:`lab_commons.units` is the pint half. The token table is
DATA, in :mod:`lab_commons.dev._unit_tokens`, for the same reason
``tests/architecture/docs/test_enforced_registry.py`` keeps its table out of its checks: a table edited
through the module that reads it drifts away from what it describes.

WHAT IS SCANNED, and each surface is here because BOTH halves of the defect are present -- the name is
something a human types or reads, and the value cannot carry a unit:

* PYTHON -- parameter names in a ``def``/``async def``, every kind (positional-only, positional,
  keyword-only, ``*args``, ``**kwargs``), and every assignment target at MODULE or CLASS scope, which
  is where a dataclass/Pydantic field and a module constant are written. Also any string literal that
  is ENTIRELY a long flag (see the CLI note below).
* TOML -- every key in the document: assignment keys and table headers, bare, quoted or dotted. This
  is the worst offender of the four, because TOML is untyped: the value is a float with no room for a
  unit even in principle, so the name is the ONLY place the unit was ever written.
* CLI -- a string literal that is ENTIRELY a long flag, with or without the ``=value`` suffix the
  user's own example carries (``--slot-pitch-mm=12.5``). The record names the flag, not the argument.
* JSON/JSONL -- every key, which is the same untyped-value defect as TOML with a different parser.
  Included rather than skipped because it is exact (the parse says what a key is, nothing is guessed);
  the caveat is stated below.

A NAME IS NOT A VIOLATION WHEN THE THING IT BINDS IS PROVABLY A QUANTITY. The rule exists so the unit
lives in the VALUE, and ``Q_0A_per_mm2 = Q_(0.0, 'A/mm^2')`` already satisfies that completely: the
name RESTATES the unit redundantly rather than carrying it in place of the value. Flagging that is a
false positive, and false positives are how a check teaches people to write waivers -- here it would
make the family's own naming convention (``Q_1mm``, ``Q_0Nm``, and the ``XType`` NewTypes that come
from ``get_quantity_type``) illegal in three repos at once. So exactly two things are exempt, and
both are PROOFS rather than guesses:

* an ASSIGNMENT whose right-hand side constructs a quantity -- ``Q_(...)``, ``ureg.Quantity(...)``,
  ``Quantity(...)``. A comment cannot buy the exemption, because the AST does not contain comments;
* a PARAMETER or a DECLARED FIELD whose ANNOTATION is a quantity spelling, taken as the terminal name
  ending in ``Quantity`` or ``Type``. ``Type`` is in the set on measurement rather than on taste: the
  family declares its quantity types as ``LengthType``/``TorqueType`` via
  ``lab_commons.units.get_quantity_type``, and MEASURED 2026-09-15 in motronics, of the annotations
  written on a unit-suffixed name, 822 are ``float`` and 181 are absent -- all of them still
  violations -- while ``LengthType`` appears ONCE and that one IS a quantity.

NOTHING WIDER, and the boundary is a measurement: 120 assignments in motronics have a unit-suffixed
name and a ``BinOp`` right-hand side, and NONE of them contains a quantity constructor, so exempting
``depth_mm = float(depth_m) * 1000.0`` would be a guess about a type the AST cannot see -- which is
what "provably" exists to exclude. Everything else is unchanged: a bare ``float``, ``int`` or
unannotated name ending in a unit token is still a violation.

THE CARVE-OUT IS REPORTED, NOT SILENT. :attr:`Scan.exempt` carries the records it swallowed, so
"0 violations" can never be read as "the carve-out ate the tree": the count and the names are the same
fact, and a carve-out that starts swallowing bare floats arrives as records rather than as silence.

WHAT IS DELIBERATELY NOT SCANNED, because a surface that is silently absent reads exactly like a clean
one:

* A FUNCTION-LOCAL assignment -- AND THIS IS A MEASURED MISS RATHER THAN A HYPOTHETICAL ONE.
  ``src/lab_commons/log.py:199`` reads ``elapsed_sec = end - start``: a bare seconds float whose unit
  lives in its name, which IS the defect, and this boundary does not see it. The trade is still the
  right one, and the same boundary is what spares ``Q_pi_rad = Q_(np.pi, 'rad')`` in
  ``tests/test_em.py:57``, whose value is already a Quantity. The two are indistinguishable at the
  syntax level without the right-hand-side test above -- which is a rule for DECLARED things, not for
  the inside of a function, and widening it to every local would trade a known miss for a false
  positive on every quantity-valued local in the family.
* A CALL-SITE keyword argument. It binds either a parameter, which is caught at its ``def``, or a
  vendor API whose keyword names are not ours to rename.
* A flag mentioned INSIDE a longer string -- the literal must be the whole string (with the ``=value``
  form counted as part of it). Measured consequence in both directions: a flag named in PROSE is not a
  violation, while the guard's own control, which has to write the flag down as an EXPECTED VALUE in
  order to assert that it is caught, IS one -- four times over in ``tests/test_dev_units.py``. That is
  why the rule row that scans this repo exempts that file, and why the exemption is TWO-SIDED: a
  scanner cannot refuse a spelling while being forbidden to write it down, so the file must stay
  violating and the exemption must be deleted the day it stops being.
* camelCase (``slotPitchMm``). There is no separator to anchor on, and splitting on case boundaries
  would match the tail of ordinary words.
* ``deg_c``/``deg_f``, whose trailing segment is the EXCLUDED ``c``/``f``. Named here rather than left
  to be discovered: it is a violation this registry cannot see.
* YAML, shell and CI files, and prose. No stdlib YAML parser exists, and a hand-rolled key scanner for
  an indentation language would be the guessing this rule exists to refuse; the family's manifests are
  TOML.

A RECORDED VENDOR ARTIFACT IS THE ONE REAL FALSE POSITIVE, and it is the CALLER's to settle rather
than this module's to guess: a key in a recorded third-party deck was not authored here and cannot be
renamed. That is what :attr:`lab_commons.dev.profile.RepoProfile.exempt` is for -- an exemption
carries a written reason, so the hole is a sentence somebody had to write.

THE FLOOR. :func:`scan_files` returns a :class:`Scan` that carries the TOKEN SET it searched for and
the number of files it read, because "found nothing" and "searched for nothing" are the same empty
tuple and only one of them is evidence. A file whose suffix is not a scanned surface is NAMED in
:attr:`Scan.skipped` rather than dropped, for the same reason. The scanner takes its file list as an
ARGUMENT and never walks a tree itself -- the house pattern, so a control can drive this real function
against a planted tree instead of re-implementing its logic and agreeing with itself by construction.
"""

from __future__ import annotations

import ast
import json
import re
import tomllib
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, NamedTuple

from lab_commons.dev._unit_tokens import EXCLUDED_TOKENS, UNIT_TOKENS

__all__ = [
    'SCANNED_SUFFIXES',
    'Scan',
    'Violation',
    'assert_registry_sane',
    'scan_files',
    'trailing_token',
]

#: A long CLI flag, ENTIRELY a string literal, with the ``=value`` form the user's own example is
#: written in (``--slot-pitch-mm=12.5``): that form is what a test or a CI step passes, and it is the
#: same defect as the bare flag. Lower-case only, matching the family's argparse surface -- no flag
#: measured in either tree carries an upper-case character, and widening further starts matching prose.
_FLAG: Final = re.compile(r'--[a-z0-9][a-z0-9-]*(?:=[^=\s]*)?')

#: The separator a name's segments are split on. Both are in the user's own example -- `slot_pitch_mm`
#: and `conductor-width-mm` -- and a kebab spelling is not a different defect.
_SEPARATORS: Final = re.compile(r'[_-]')

#: The last-segment patterns, per surface. WHAT is a key comes from a PARSE on every surface that has
#: a parser (so a comment, a string value or a docstring can never be a false positive); these
#: patterns only answer WHERE the line is, which is why they may be loose.
_TOML_KEY: Final = '(?<!\\w)["\']?{name}["\']?[ \\t]*(?:=|\\])'
_JSON_KEY: Final = '"{name}"[ \\t]*:'

_TOKENS: Final[frozenset[str]] = frozenset(UNIT_TOKENS)

#: A right-hand side that CONSTRUCTS a quantity. The three spellings the family writes, and the same
#: set is what makes the exemption a PROOF: these calls return a ``pint.Quantity`` whatever the
#: arguments were, so the name is restating a unit the value already carries.
_QUANTITY_CALLS: Final[frozenset[str]] = frozenset({'Q_', 'Quantity'})

#: An annotation that declares a quantity, as a SUFFIX on the terminal name: `Quantity`,
#: `PintQuantity`, `PintQuantityType` and the family's `LengthType`/`TorqueType` all end in one of
#: these. The `Type` half is measured rather than assumed -- see the module docstring -- and the
#: narrow spelling is on purpose: a set that tried to enumerate type names would need a registry of
#: the family's type declarations, and this file already HAS a registry, for the other half.
_QUANTITY_SUFFIXES: Final[tuple[str, ...]] = ('Quantity', 'Type')

#: What every reader yields: ``(line, name, exempt)``. The third element is the carve-out's answer for
#: THIS name, computed where the syntax that proves it still exists -- a locator over raw text could
#: not see an annotation or a right-hand side, so it never reports an exemption.
_Signature = tuple[int, str, bool]


class Violation(NamedTuple):
    """One name that spells its unit, at the place a reader will find it.

    ``(path, line, name, token)`` -- the order is the record's shape, and it is a ``NamedTuple``
    rather than a dataclass so a record compares and sorts as the tuple it reads as, which is what
    makes a disagreement between two runs a readable diff.

    *path* is as the caller named it, or RELATIVE TO ``root`` when one was passed: a record naming an
    absolute path is a fact about one box, and a reader who was not there cannot check it.

    *name* is the name AS THE FILE WRITES IT -- the identifier for Python, the whole ``--flag`` for a
    CLI literal, the last dotted segment for a TOML/JSON key -- because stripping a flag to its token
    or a key to its leaf would hand a reader something they cannot search for.

    *line* is 1-based and is where the name appears in KEY POSITION (an assignment or a table header).
    A name that the parse found but no line names cannot happen for a well-formed file; the record is
    emitted with the line that was found, never with an invented one.
    """

    path: str
    line: int
    name: str
    token: str


@dataclass(frozen=True, slots=True)
class Scan:
    """What a scan found, TOGETHER WITH WHAT IT SEARCHED FOR -- the two facts are one answer.

    *tokens* is the token set this scan actually used, sorted, so a run whose set was narrowed (or
    widened for a domain repo -- see :mod:`lab_commons.dev._unit_tokens`) cannot be mistaken for a run
    that covered the default set. *files_read* is how many files were PARSED to produce these records,
    and *skipped* NAMES every file that was handed in and not read, because its suffix is not a
    scanned surface: a caller that passes a tree of ``.rs`` files gets ``files_read == 0``, and that
    is the signal -- not a clean tree.

    *exempt* is the other half of the same answer: the records the QUANTITY CARVE-OUT swallowed,
    reported as the records they would have been rather than as a count. "0 violations" and "the
    carve-out ate the tree" produce the same empty ``violations`` tuple, and only the exempt list can
    tell them apart -- and because it NAMES the names rather than counting them, a carve-out that
    starts exempting bare floats arrives as evidence instead of as a smaller number nobody can read.

    IT IS ITERABLE AND NOT COUNTABLE, and the asymmetry is load-bearing. ``for violation in scan``
    and ``tuple(scan)`` give the records, so the object reads as the tuple it carries; but there is
    deliberately no ``__len__``/``__bool__``, because a falsy scan would make "no violations" and
    "read nothing" the same branch -- the exact collapse the floor exists to prevent. A caller writes
    ``if scan.violations:`` and gets the floor facts in the message. ``tuple(scan)`` is the VIOLATIONS
    alone: an exempt name is not a violation and must never reach a report as one. That is also why
    the exempt records are a separate tuple rather than a flag on :class:`Violation` -- a filter a
    caller can forget is a filter that ends up in the output.
    """

    violations: tuple[Violation, ...]
    exempt: tuple[Violation, ...]
    tokens: tuple[str, ...]
    files_read: int
    skipped: tuple[str, ...]

    def __iter__(self) -> Iterator[Violation]:
        return iter(self.violations)


def assert_registry_sane(tokens: Iterable[str], excluded: Mapping[str, str]) -> None:
    """Raise unless the two token tables are usable AS TABLES.

    Three properties, and each has a measured failure behind it rather than a taste:

    * NO OVERLAP. A token in both tables is a row that refuses and permits the same name, and which
      one wins is then a detail of dictionary order.
    * EVERY EXCLUSION CARRIES A REASON. An exclusion whose reason is blank is indistinguishable from
      a hole somebody widened during a red suite, and the exclusion is the cheaper repair.
    * THE INCLUDED SET IS SORTED, LOWER-CASE AND UNIQUE. The machinery compares a lower-cased segment
      against these rows, so a row that is not lower-case can never match and would sit in the table
      LOOKING like coverage -- a declaration that lies, in the one file whose whole job is to declare.

    Takes its two facts as ARGUMENTS rather than reading the module constants, so a control can plant
    a bad row and drive THIS function, which is also why it is public: the import below is one caller,
    not the only one.

    Raises:
        ValueError: naming the offending row, because a refusal that does not say which row failed is
            a refusal nobody can act on.

    """
    included = list(tokens)
    both = sorted(set(included) & set(excluded))
    if both:
        msg = (
            f'unit tokens {both} appear in BOTH tables: the same name would be refused by one and '
            f'excused by the other, and which one wins would be an accident of lookup order.'
        )
        raise ValueError(msg)
    blank = sorted(token for token, reason in excluded.items() if not reason.strip())
    if blank:
        msg = (
            f'excluded token(s) {blank} carry no reason. An exclusion with no recorded collision '
            f'cannot be told from a hole widened to make a red suite green.'
        )
        raise ValueError(msg)
    if included != sorted(set(included)) or any(token != token.lower() for token in included):
        msg = (
            f'UNIT_TOKENS must be SORTED, unique and lower-case; got {included}. A row that is not '
            f'lower-case can never match a lower-cased segment -- it would read as coverage while '
            f'covering nothing -- and an unsorted table makes the diff of a removal unreadable. The '
            f'two halves are one check because both are properties of the same table, and a table '
            f'that is wrong either way is wrong in the same way: it says more than it does.'
        )
        raise ValueError(msg)


# The registry is consulted at IMPORT, not merely at test time: a table that only a test reads is a
# table the library ships regardless of whether it is usable.
assert_registry_sane(UNIT_TOKENS, EXCLUDED_TOKENS)


def trailing_token(name: str, tokens: Collection[str] = _TOKENS) -> str | None:
    """The unit token *name*'s LAST segment spells, or ``None``. The one place matching happens.

    LAST SEGMENT ONLY, on ``_`` and ``-`` alike, case-insensitively: ``radial_gap`` is not a
    violation and ``gap_rad`` is; ``deg_phase`` is not and ``phase_deg`` is. The two directions are
    not equally interesting -- the rule is about the SUFFIX a reader takes for a unit, and a token
    anywhere in a name is a different (and much noisier) claim, so the scan does not make it.

    *tokens* is a parameter because the default set is the SHARED one and a domain repo's profile is
    not: see :mod:`lab_commons.dev._unit_tokens` for the measurement that makes the single letters an
    opt-in rather than a default.
    """
    segment = _SEPARATORS.split(name.strip())[-1].strip('"\'').lower()
    return segment if segment in tokens else None


def _named(path: Path, base: Path | None) -> str:
    """*path* as the record names it: as given, or relative to *base* when one was declared.

    A path outside *base* is REFUSED rather than named absolutely, for the reason
    :func:`lab_commons.dev.content.content_address` gives at the same boundary: an absolute path is a
    fact about one machine, so a record carrying one cannot be checked by a reader who was not there.
    """
    if base is None:
        return path.as_posix()
    resolved = path.resolve()
    if resolved != base and base not in resolved.parents:
        msg = f'{path} is not under {base}, so it cannot be named relative to it.'
        raise ValueError(msg)
    return resolved.relative_to(base).as_posix()


def _dotted_keys(node: object, prefix: str = '') -> Iterator[str]:
    """Every key in a parsed TOML/JSON document, as a dotted path -- tables included.

    Recursing through LISTS as well as mappings is what reaches an array of tables and a JSON array of
    objects, where a unit-suffixed key is exactly as untyped as anywhere else.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            yield f'{prefix}{key}'
            yield from _dotted_keys(value, f'{prefix}{key}.')
    elif isinstance(node, list):
        for item in node:
            yield from _dotted_keys(item, prefix)


def _strip_comment(line: str) -> str:
    """*line* with a TOML comment removed, quoted text left alone.

    Stripping is what keeps a comment out of the record entirely: a full-line comment strips to an
    empty string, so a comment that READS as an assignment (`# gap_mm = 12.5 ...`) cannot match. The
    rest is defence in depth -- the key set comes from the parse, so no line scan can invent a name --
    and a `#` mis-cut out of a string value can at worst move a line number.
    """
    quote, escaped = '', False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
        elif quote and char == '\\':
            escaped = True
        elif quote:
            quote = '' if char == quote else quote
        elif char in '"\'':
            # A branch per state rather than a ternary: this IS the state machine, and the escape and
            # comment branches either side of it are what make a quote inside a value not a delimiter.
            quote = char
        elif char == '#':
            return line[:index]
    return line


def _terminal(node: ast.AST) -> str:
    """The name an expression ENDS in: ``ureg.Quantity(...)`` ends in ``Quantity``, ``Q_(...)`` in ``Q_``.

    Recursing through the call and the attribute is what makes ``pint.Quantity`` and a bare
    ``Quantity`` the same spelling, and NOT recursing into a subscript is deliberate: a subscript's
    terminal would be its container (``Sequence[float]`` ends in ``Sequence``), and reading the
    argument instead would make ``dict[str, PathType]`` an annotation that proves a quantity.
    """
    if isinstance(node, ast.Call):
        return _terminal(node.func)
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ''


def _exempt_annotation(annotation: ast.expr | None) -> bool:
    """Whether an ANNOTATION proves the bound value is a quantity."""
    return annotation is not None and _terminal(annotation).endswith(_QUANTITY_SUFFIXES)


def _exempt_assignment(node: ast.Assign | ast.AnnAssign) -> bool:
    """Whether an ASSIGNMENT proves the bound value is a quantity -- by its annotation or its value.

    Both halves are proofs of the same kind and neither is a heuristic: the annotation is a declared
    quantity type, and the right-hand side is a call that RETURNS one whatever it was passed. A
    ``BinOp`` is deliberately not a proof even when one operand is a quantity -- it is a computation
    whose result type the AST cannot see, and no assignment in motronics with a unit-suffixed name and
    a ``BinOp`` right-hand side contains a quantity constructor at all.
    """
    if isinstance(node, ast.AnnAssign) and _exempt_annotation(node.annotation):
        return True
    return isinstance(node.value, ast.Call) and _terminal(node.value) in _QUANTITY_CALLS


def _locate(lines: Sequence[str], names: Iterable[str], pattern: str) -> Iterator[_Signature]:
    """``(line, name, False)`` for every line where one of *names* sits in key position.

    EVERY match is yielded rather than the first per name: two tables can share a leaf
    (``[motor] gap_mm`` and ``[stator] gap_mm``) and both lines are real violations, so collapsing
    them to one would under-report by exactly the case a reader is most likely to have.

    A flat ``False`` for the carve-out, and it is not a placeholder: an untyped key in TOML or JSON
    has no annotation and no expression, so there is nothing that could prove a quantity. The
    surfaces that CAN prove one are read by a parser that keeps the syntax, which is
    :func:`_python_signatures`.
    """
    patterns = [(name, re.compile(pattern.format(name=re.escape(name)))) for name in names]
    for number, raw in enumerate(lines, start=1):
        text = _strip_comment(raw)
        for name, compiled in patterns:
            if compiled.search(text):
                yield number, name, False


def _python_signatures(text: str) -> Iterator[_Signature]:
    """The names this module reads out of Python -- parameters, declared fields, and flag literals.

    The two scopes are separated by SUBTRACTION rather than by a scope-aware walk: every assignment
    inside a function is collected first and then skipped, which answers "is this a module/class
    field" without a second visitor to keep in step with this one.

    This is the one reader that can answer the carve-out, and it can because it reads an AST: an
    annotation and a right-hand side both survive the parse, and neither survives in the source text a
    locator would see. A comment cannot buy the exemption for the same reason -- ``ast`` discards
    comments, so ``GAP_MM = 1.0  # was Q_(1.0, 'mm')`` has a ``Constant`` for a value and no quantity
    anywhere in the tree.
    """
    tree = ast.parse(text)
    callables = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
    local = {
        id(inner)
        for outer in ast.walk(tree)
        if isinstance(outer, callables)
        for inner in ast.walk(outer)
        if isinstance(inner, (ast.Assign, ast.AnnAssign))
    }
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            arguments = node.args
            every = (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, arguments.vararg, arguments.kwarg)
            for argument in every:
                if argument is not None:
                    yield argument.lineno, argument.arg, _exempt_annotation(argument.annotation)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and id(node) not in local:
            exempt = _exempt_assignment(node)
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for leaf in ast.walk(target):
                    if isinstance(leaf, ast.Name):
                        # One answer for the whole statement, applied to every target: a chained
                        # assignment binds them all to the same value, so they cannot differ.
                        yield leaf.lineno, leaf.id, exempt
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            literal = _FLAG.fullmatch(node.value)
            if literal is not None:
                # The ARGUMENT half is dropped from the record: a reader greps for the flag, and
                # `--slot-pitch-mm` is the name the definition site writes. A flag is a spelling in a
                # string rather than a binding, so there is nothing that could prove a quantity.
                yield node.lineno, literal.group(0).split('=', 1)[0], False


def _toml_signatures(text: str) -> Iterator[tuple[int, str]]:
    """The names this module reads out of TOML. The PARSE decides what is a key; a pass locates it."""
    keys = sorted({dotted.rsplit('.', 1)[-1] for dotted in _dotted_keys(tomllib.loads(text))})
    yield from _locate(text.splitlines(), keys, _TOML_KEY)


def _json_signatures(text: str) -> Iterator[tuple[int, str]]:
    """The names this module reads out of JSON, with the same parse-then-locate split as TOML."""
    keys = sorted({dotted.rsplit('.', 1)[-1] for dotted in _dotted_keys(json.loads(text))})
    yield from _locate(text.splitlines(), keys, _JSON_KEY)


def _jsonl_signatures(text: str) -> Iterator[tuple[int, str]]:
    """The names this module reads out of JSONL. One document per line, so no locating pass is needed.

    A blank line is skipped -- a trailing newline is not a document -- and every other line is
    PARSED rather than pattern-matched, so a key inside a string value is not a key.
    """
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        for dotted in _dotted_keys(json.loads(line)):
            yield number, dotted.rsplit('.', 1)[-1], False


#: One reader per scanned surface: ``text -> (line, name)``. A mapping rather than a chain of suffix
#: tests so the scanned set is DATA -- :data:`SCANNED_SUFFIXES` is derived from it, and the Scan names
#: every file this mapping does not cover.
_READERS: Final[Mapping[str, Callable[[str], Iterator[_Signature]]]] = {
    '.json': _json_signatures,
    '.jsonl': _jsonl_signatures,
    '.py': _python_signatures,
    '.toml': _toml_signatures,
}

#: The suffixes this module reads. Public because a caller choosing its file list needs to know which
#: of them will be read, and because a suffix that is added here is a decision a reader can find.
SCANNED_SUFFIXES: Final[tuple[str, ...]] = tuple(sorted(_READERS))


def scan_files(
    paths: Iterable[Path | str],
    *,
    tokens: Collection[str] = _TOKENS,
    root: Path | None = None,
) -> Scan:
    """Every name in *paths* whose last segment spells a unit, as records, sorted. Never raises a verdict.

    It RETURNS violations rather than raising on them: what to do about a name that spells its unit is
    a policy each repo owns -- rename it, or record an exemption with its reason -- and a library that
    raised would be making that decision from here.

    *paths* is the caller's list and is never walked: this function reads exactly the files it is
    handed, which is what lets a control drive it against a planted tree. A file it cannot parse
    raises from the parser, and that is deliberate -- a file that was not read is not a file that was
    clean, and reporting zero violations for it is the vacuous green the floor exists to prevent.

    A name whose binding is PROVABLY a quantity is split out into :attr:`Scan.exempt` rather than
    dropped, so the caller can see what the carve-out did without having to re-run the scan under a
    different rule. It is never in :attr:`Scan.violations` and never in ``tuple(scan)``.

    Raises:
        ValueError: *root* was declared and a path is not under it.
        OSError, SyntaxError, tomllib.TOMLDecodeError, json.JSONDecodeError: a file could not be read
            or parsed, so its part of the answer does not exist.

    """
    chosen = frozenset(token.lower() for token in tokens)
    found: set[Violation] = set()
    exempt: set[Violation] = set()
    skipped: list[str] = []
    read = 0
    base = Path(root).resolve() if root is not None else None
    for item in paths:
        path = Path(item)
        named = _named(path, base)
        reader = _READERS.get(path.suffix.lower())
        if reader is None:
            skipped.append(named)
            continue
        read += 1
        for line, name, proven_quantity in reader(path.read_text(encoding='utf-8')):
            token = trailing_token(name, chosen)
            if token is None:
                continue
            record = Violation(named, line, name, token)
            # The token test comes FIRST and the carve-out second, so a name that spells no unit is
            # in neither tuple: the exempt list is what the carve-out SAVED from the rule, not a log
            # of every quantity the scan walked past.
            (exempt if proven_quantity else found).add(record)
    return Scan(
        violations=tuple(sorted(found)),
        exempt=tuple(sorted(exempt)),
        tokens=tuple(sorted(chosen)),
        files_read=read,
        skipped=tuple(sorted(skipped)),
    )
