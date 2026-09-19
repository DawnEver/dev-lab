"""ONE PLACE MAY SPELL A VENV INTERPRETER -- the resolver. Everywhere else consults it.

THE DEFECT THIS CONVICTS, MEASURED 2026-09-19. ``.venv/Scripts/python.exe`` is a file macOS does not
have. The LIVE code in this kit never had that problem --
:data:`lab_commons.dev.venvpath.CANDIDATE_RELATIVE_PATHS` probes BOTH layouts and always did. The
spelling spread through PROSE: the consumption recipe in
:mod:`lab_commons.dev.hook_adoption`'s module docstring wrote the Windows path literally, and that
recipe was copied VERBATIM into ``scripts/deny_rules.py`` in two consuming repos, where it stopped
being prose and became live code naming a file half the fleet does not have.

SO THE SUBJECT IS NOT "A DOCSTRING", IT IS "SOURCE SOMEBODY WILL PASTE", and drawing that line is
the whole design of this module. A guard that scanned every docstring would convict the paragraph
EXPLAINING the retirement -- which is the one place a retired spelling is supposed to appear, per
this family's own integration rule -- and the honest-looking repair would be to delete the
explanation. A guard that scanned no docstring would have missed the only site that actually
shipped the defect. What is scanned is therefore:

* every string literal in executable position, because that is what runs and what gets rendered
  into a tracked artefact; and
* every ``::`` LITERAL BLOCK inside a docstring, because reStructuredText literal blocks are how
  this kit writes a recipe, and a recipe is source with an indent in front of it.

Narrative docstring text and ``#`` comments are NOT scanned. They are where the retirement is
recorded, and :mod:`lab_commons.dev.venvpath` itself is where the replacement is named.

BOTH SIDES, because a ratchet has two. The hardcoding side is
:func:`assert_only_the_resolver_spells_a_venv_interpreter`. The other side is
:func:`assert_the_resolver_is_still_consulted`: a resolver nothing calls is exactly as wrong as a
hardcoded path, and it FAILS SILENTLY -- if ``glob_for`` stopped normalising, every derived row
would go back to naming one platform and no scan above would notice, because the offending spelling
would be in a consuming repo's ``Remedy`` rather than in this tree. That arm is expressed as a
BEHAVIOUR rather than as an import check: the two concrete spellings must derive the SAME row. An
import can be present and unused; two inputs that converge cannot be faked.

THE CONTROL IS NOT OPTIONAL AND TAKES NO ARGUMENT.
:func:`assert_a_planted_recipe_is_convicted` plants the exact shape that shipped -- a Windows-only
interpreter inside a docstring literal block -- and drives the REAL reader. Without it the property
arm passes on a reader whose regex stopped matching, which is indistinguishable from a clean tree.
It plants the NARRATIVE case too, and asserts the reader does NOT convict it, because a guard that
cannot be satisfied gets switched off.

THE POPULATION CARRIES A FLOOR. A scan that read no files reports what a clean tree reports. The
floor is on FILES READ, and the sanctioned set is pinned as a NAMED SET rather than a count -- an
integer cannot say WHICH module stopped resolving, and this family has an incident where a
disagreeing count pin was edited down to meet a broken table.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

from lab_commons.dev.allow_adoption import glob_for
from lab_commons.dev.floors import assert_floor
from lab_commons.dev.venvpath import VENV_INTERPRETER_GLOB, VENV_LAYOUTS, venv_interpreter

__all__ = [
    'SANCTIONED_SPELLERS',
    'Spelling',
    'assert_a_planted_recipe_is_convicted',
    'assert_only_the_resolver_spells_a_venv_interpreter',
    'assert_the_resolver_is_still_consulted',
    'scannable_text',
    'spellings_in',
]

#: The modules allowed to spell a concrete venv interpreter, as a NAMED SET of repo-relative POSIX
#: paths. A NAME and not a count: an integer cannot say WHICH module stopped resolving, and the
#: repair for a disagreement is to make the module consult the resolver, never to raise the digit.
#:
#: Exactly one entry, and that is the claim. :mod:`lab_commons.dev.venvpath` holds the layouts as
#: data; ``githooks.bootstrap`` authored them and now re-exports, which is why it is NOT here.
SANCTIONED_SPELLERS: Final[frozenset[str]] = frozenset({'lab_commons/dev/venvpath.py'})

#: A concrete venv interpreter. Spelled INDEPENDENTLY of the resolver's own pattern, deliberately:
#: a guard that imported the thing it judges would go green the moment that pattern narrowed, which
#: is the failure mode where a detector and its subject agree with each other and with nothing else.
_CONCRETE: Final = re.compile(
    r'(?:\.[/\\])?\.venv[/\\](?:Scripts[/\\]python(?:\.exe)?|bin[/\\]python[\d.]*)',
)

#: A reStructuredText literal block opener: a line whose content ends in ``::``. What follows,
#: indented, is a RECIPE -- source with an indent in front of it -- and is scanned.
_OPENS_BLOCK: Final = re.compile(r'::\s*$')

#: The two things a finding can be, and the two different repairs they carry.
_CODE: Final = 'code'
_RECIPE: Final = 'recipe'


@dataclass(frozen=True, slots=True)
class Spelling:
    """ONE concrete venv-interpreter spelling, with enough to repair it without re-running the scan.

    *where* is ``'code'`` or ``'recipe'``. The two have different repairs -- a code site consults
    :func:`lab_commons.dev.venvpath.venv_interpreter`, a recipe site shows the reader that call --
    so the reason names which, rather than reporting a location and leaving the reader to look.
    """

    path: str
    line: int
    text: str
    where: str

    def __str__(self) -> str:
        """The offender as one repair-shaped line, path first so a reader can sort by file."""
        return f'{self.path}:{self.line}: {self.text!r} in {self.where}'


def _literal_blocks(doc: str, base: int) -> list[tuple[int, str]]:
    """Every ``::``-introduced indented block in *doc*, as ``(line number, text)``.

    Line numbers are offset by *base* so a finding points at the real file rather than at an
    offset into a string nobody can open.
    """
    out: list[tuple[int, str]] = []
    lines = doc.splitlines()
    index = 0
    while index < len(lines):
        if not _OPENS_BLOCK.search(lines[index]):
            index += 1
            continue
        opener = len(lines[index]) - len(lines[index].lstrip())
        index += 1
        while index < len(lines):
            line = lines[index]
            if line.strip() and (len(line) - len(line.lstrip())) <= opener:
                break
            out.append((base + index, line))
            index += 1
    return out


def scannable_text(source: str) -> tuple[tuple[int, str, str], ...]:
    """Every ``(line, text, where)`` of *source* this guard judges, *where* being code or recipe.

    NARRATIVE DOCSTRING TEXT AND COMMENTS ARE EXCLUDED, and that exclusion is the module's whole
    argument -- see the module docstring. Returned as triples rather than scanned in place so a
    control can inspect WHAT was selected, which is the difference between a guard that found
    nothing and one that looked at nothing.

    A file that does not parse yields NOTHING rather than raising: this walks a tree that may hold
    a fixture, and an unparseable file is the caller's other guard, not a reason this one cannot
    report on the files it could read.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    holders: set[int] = set()
    out: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        doc = ast.get_docstring(node, clean=False)
        holder = node.body[0] if node.body else None
        if doc is None or not isinstance(holder, ast.Expr):
            continue
        holders.add(id(holder.value))
        out.extend((line, text, _RECIPE) for line, text in _literal_blocks(doc, holder.lineno))
    out.extend(
        (node.lineno, node.value, _CODE)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in holders
    )
    return tuple(out)


def spellings_in(files: Mapping[str, str], sanctioned: Iterable[str] = SANCTIONED_SPELLERS) -> tuple[Spelling, ...]:
    """Every concrete venv-interpreter spelling in *files*, outside the *sanctioned* set.

    Args:
        files: repo-relative POSIX path mapped to that file's SOURCE. A mapping and not a root, for
            the reason :mod:`lab_commons.dev._allow_settings` takes a parsed document: it lets the
            control drive THIS body against planted text rather than re-implementing it and
            agreeing with itself.
        sanctioned: the paths allowed to spell it. Passed so the control can plant an EMPTY set and
            prove the resolver itself would otherwise be convicted -- which is what shows the
            sanction is doing work rather than the pattern missing.

    """
    allowed = frozenset(sanctioned)
    return tuple(
        Spelling(path, line, found.group(0), where)
        for path in sorted(files)
        if path not in allowed
        for line, text, where in scannable_text(files[path])
        for found in _CONCRETE.finditer(text)
    )


def assert_only_the_resolver_spells_a_venv_interpreter(
    *,
    files: Mapping[str, str],
    sanctioned: Iterable[str] = SANCTIONED_SPELLERS,
    floor: int,
    what: str,
) -> None:
    """Raise unless every concrete venv-interpreter spelling is in the *sanctioned* set.

    Args:
        files: repo-relative POSIX path mapped to source, as :func:`spellings_in` takes it.
        sanctioned: the paths allowed to spell it.
        floor: the smallest file population this scan can read and still be evidence. NO DEFAULT:
            a family default would be one repo's number refusing another repo's tree, and a scan
            that read nothing reports exactly what a clean tree reports.
        what: the label the floor's refusal names. NO DEFAULT, for the reason
            :mod:`lab_commons.dev.floors` gives -- a borrowed label misdirects the reader to a
            guard that is not the one which failed.

    Raises:
        AssertionError: a file outside the sanctioned set spells a concrete venv interpreter.
        lab_commons.dev.floors.FloorUnmet: the scan read fewer files than *floor*.

    """
    assert_floor(len(files), floor=floor, what=what)
    found = spellings_in(files, sanctioned)
    if not found:
        return
    nt = venv_interpreter(os_name='nt')
    msg = (
        f'{what}: {len(found)} site(s) spell a venv interpreter instead of resolving it:\n  '
        + '\n  '.join(str(item) for item in found)
        + f'\n{nt!r} is a file macOS does not have, so a tracked artefact carrying it is wrong on half the '
        f'fleet -- silently, because a permission row that matches no command reads like one nobody needed. '
        f'Call lab_commons.dev.venvpath.venv_interpreter(os_name=...) for a command a human runs, or let '
        f'allow_adoption.glob_for render {VENV_INTERPRETER_GLOB!r} for a row that is tracked in git. A '
        f'recipe block shows the reader that call rather than its result.'
    )
    raise AssertionError(msg)


def assert_the_resolver_is_still_consulted() -> None:
    """THE OTHER SIDE: a resolver nothing calls is as wrong as a hardcoded path, and is SILENT.

    Expressed as a BEHAVIOUR and not as an import check: an import can be present and unused, and
    ``glob_for`` could go back to passing the command through with the line still at the top of the
    file. Two concrete spellings that CONVERGE cannot be faked -- if the normalisation stops, the
    Windows input renders a Windows row and the POSIX input renders a POSIX one, and they differ.

    Raises:
        AssertionError: the two platform spellings no longer derive one row, or the row that is
            written into a tracked file still names one platform.

    """
    tail = ' -m lab_commons.dev.verify'
    rendered = {name: glob_for(venv_interpreter(os_name=name) + tail) for name in VENV_LAYOUTS}
    distinct = set(rendered.values())
    if len(distinct) != 1:
        msg = (
            f'the {len(VENV_LAYOUTS)} platform spellings of one remedy derive {len(distinct)} different allow '
            f'rows {sorted(distinct)}. `.claude/settings.json` is TRACKED IN GIT, so a row that differs by the '
            f'machine that rendered it is wrong on the other one. `allow_adoption.glob_for` has stopped '
            f'consulting `venvpath.portable` -- a resolver nothing calls is as wrong as the hardcoded path it '
            f'replaced, and this is the arm that is not silent about it.'
        )
        raise AssertionError(msg)
    row = distinct.pop()
    if VENV_INTERPRETER_GLOB not in row:
        msg = (
            f'the derived row {row!r} does not carry {VENV_INTERPRETER_GLOB!r}. The platforms agree, so the arm '
            f'above passed, but they may be agreeing on a spelling neither of them can run.'
        )
        raise AssertionError(msg)


def assert_a_planted_recipe_is_convicted() -> None:
    """THE CONTROL: plant the shape that actually shipped, drive the REAL reader, and convict it.

    Three plants, because the reader makes three claims and a control that drove one of them would
    leave the other two asserted by prose:

    * a Windows-only interpreter in a docstring RECIPE BLOCK -- the site that shipped -- is caught,
      and is reported as a ``recipe``;
    * the same spelling in NARRATIVE docstring text is NOT caught, because that is where this
      family records a retirement and a guard that forbids the explanation gets switched off;
    * the sanctioned resolver itself IS caught once its sanction is withdrawn, which is what proves
      the green above comes from the sanction rather than from a pattern that stopped matching.

    Takes no argument, for the reason
    :func:`lab_commons.dev.famtests.depdoor.assert_a_port_declaring_neither_renders_both_gaps` takes
    none: a control the caller can parametrise is a control the caller can aim somewhere harmless.

    Raises:
        AssertionError: any of the three fails.

    """
    windows = venv_interpreter(os_name='nt')
    recipe = '\n'.join(
        (
            '"""A module whose docstring carries a consumption recipe.',
            '',
            'Wire it up::',
            '',
            f'    VERIFY = Remedy("verdict-entry-point", "{windows} -m lab_commons.dev.verify")',
            '"""',
            '',
        )
    )
    caught = spellings_in({'planted/recipe.py': recipe})
    if [item.where for item in caught] != [_RECIPE]:
        msg = (
            f'the planted recipe block spelling {windows!r} was read as {[str(x) for x in caught]}, not as one '
            f'`recipe` finding. This is the exact shape that shipped into two repos; a reader that misses it '
            f'reports a clean tree for the defect it was written against.'
        )
        raise AssertionError(msg)

    narrative = f'"""It used to read ``{windows}`` literally, and that spelling was the defect."""'
    if spellings_in({'planted/narrative.py': narrative}):
        msg = (
            f'the planted NARRATIVE mention of {windows!r} was convicted. Naming a retired spelling while '
            f"explaining its retirement is sanctioned by this family's integration rule, and a guard that "
            f'forbids the explanation is one somebody deletes the explanation to satisfy.'
        )
        raise AssertionError(msg)

    resolver = f'LAYOUT = "{windows}"'
    sanctioned_path = next(iter(SANCTIONED_SPELLERS))
    if spellings_in({sanctioned_path: resolver}):
        msg = f'{sanctioned_path} is sanctioned and was convicted anyway, so the sanction is not being applied'
        raise AssertionError(msg)
    if not spellings_in({sanctioned_path: resolver}, sanctioned=()):
        msg = (
            f'{sanctioned_path} was NOT convicted with its sanction withdrawn, so the green above is the pattern '
            f'failing to match rather than the sanction doing work. A scan that cannot convict its own exception '
            f'has no floor under that exception.'
        )
        raise AssertionError(msg)
