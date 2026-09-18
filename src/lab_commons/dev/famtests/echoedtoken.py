"""A CLAUSE MAY NOT CHECK ITS OWN ECHO -- the shape that makes an assertion structurally unfailable.

THE DEFECT, MEASURED 2026-09-18 INSIDE THIS PACKAGE'S OWN
:func:`lab_commons.dev.famtests.boundedremedy.assert_each_state_names_its_own_remedy`. The arm took
a ``wider_tier`` word, handed it to :func:`lab_commons.dev.bounded.wall_reason`, and then asserted
``wider_tier in text`` over the three sentences that function returned. All three INTERPOLATE the
argument, so the clause held for any string whatever: driven on ``'ZZZ_NO_SUCH_TIER_ANYWHERE'`` it
passed in both consumer labs and in the kit. That is ``taste.md``'s sharpest shape -- a TRUE claim
no test could have failed -- and it was invisible because the arm around it convicts for real
reasons and the dead clause rode along.

WHY THIS PACKAGE IS WHERE IT HAPPENS. A shared assertion body's whole job is to assert on text some
other module PRODUCES, and every one of those bodies takes the repo's own words as arguments with no
default. Those two facts together ARE the precondition: the moment the producer interpolates the
very token the asserter looks for, the clause degenerates. Nothing about it looks wrong on the page.

WHAT SEPARATES A DEAD CLAUSE FROM A LIVE ONE, and it is not the syntax -- it is whether the producer
INTERPOLATES the token or FILTERS on it. :func:`lab_commons.dev.famtests.allowguard.
assert_the_scan_can_still_see` plants ``denied_entry`` into a settings file, runs the real rules
engine over it and asserts the row comes back in ``scan.refused``. The token reaches the producer,
and the clause still convicts, because ``contradictions`` SELECTS rather than echoes -- proved by
its sibling clause requiring ``harmless_entry`` to be ABSENT from the same container. An
interpolator cannot pass that pair. So the scanner below keys on DATA FLOW rather than on the
comparison alone: a site is named only when the searched container is derived from a call that
RECEIVED the token.

THE FALSE POSITIVES THAT RULE REMOVES, both measured on this package the same day. A first, coarser
pass flagged every ``param in container`` where the parameter was passed to any call in the same
function, and named five sites; three were honest. ``_citedtests_readings.resolves`` searches a
``names`` set built from two OTHER parameters, and ``agentguard.reason_for`` searches rows read off
a committed JSON file -- in both, the only place the token flows is into the refusal MESSAGE, which
is written after the test has already decided. Flagging those is how a guard gets deleted rather
than obeyed.

WHAT THIS DOES NOT PROVE, and it is the axis every offender set here is blind to. This reads DATA
FLOW inside one function body, so it sees an echo through a local variable and not an echo through a
file, an attribute or a second function. ``allowguard`` is exactly that case -- the token reaches
the producer through a settings file on disk -- and it is cleared here for a reason this scanner
cannot check. The population is therefore a LOWER BOUND on the shape, which is the honest reading of
any intraprocedural scan and the reason the floor below counts FUNCTIONS READ rather than offenders.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

from lab_commons.dev import floors

if TYPE_CHECKING:
    from collections.abc import Collection
    from pathlib import Path

__all__ = [
    'EchoScan',
    'EchoedToken',
    'assert_no_clause_checks_its_own_echo',
    'assert_the_scanner_still_convicts',
    'echoed_tokens',
    'take_scan',
]

#: How many times the taint set is grown before it is called settled. An assignment chain inside one
#: assertion body is short -- the measured worst case in this package is two hops, producer call to
#: dict to loop variable -- and a bound is stated here because this module is itself under the
#: family rule that every wait declares a ceiling.
_TAINT_PASSES = 4

#: The line, within :data:`_PLANTED_SOURCE`, the control requires the scanner to name, and the only
#: one. Spelled as data so the control's refusal can quote it rather than restate it.
_PLANTED_ECHO_LINE = 4

#: The planted tree, with the offender and its three honest neighbours in one file so a rule that
#: cannot tell them apart fails here rather than in a consumer's suite. Line 4 is the echo: ``say``
#: is handed ``word`` and the answer it returns is then searched for ``word``.
_PLANTED_SOURCE = '''def echo(word, say):
    """Line 4 below is the offender."""
    text = say(word=word)
    if word not in text:
        raise AssertionError(word)


def built_from_others(word, left, right):
    """The container comes from OTHER arguments, so an implementation can fail this."""
    names = set(left) | set(right)
    if word not in names:
        raise AssertionError(f'{word} missing')


def read_off_the_world(word, path):
    """The container is read off disk, and the token reaches only the refusal message."""
    rows = path.read_text()
    if word not in rows:
        raise AssertionError(f'{word} absent from {path}')
'''


class EchoedToken(AssertionError):
    """A clause searches for a token the same call was handed, so no implementation can fail it."""


@dataclass(frozen=True)
class EchoScan:
    """One walk, with the offender set and the number of function bodies its floor judges.

    The count is carried BESIDE the offenders because the number a floor needs is how many bodies
    were READ. A walk that parsed nothing and a walk that found nothing have the same empty offender
    tuple and nothing else in common, and this scanner's clean answer is the common one.
    """

    functions_read: int
    offenders: tuple[str, ...]


def _stored(node: ast.AST) -> set[str]:
    """Every name this assignment target binds, including the elements of a tuple unpack."""
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}


def _mentions(node: ast.AST) -> set[str]:
    """Every name read anywhere inside *node*, however deeply nested."""
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _fed_to_a_call(value: ast.AST, token: str) -> bool:
    """Whether *token* is handed to some call inside *value* as an argument.

    POSITIONAL AND KEYWORD BOTH, and the walk goes through each argument rather than testing the
    argument node itself: the measured site passes ``wider_tier=wider_tier`` at one level, and a
    body that wrapped its token in an ``f``-string first would otherwise walk free.
    """
    for call in (n for n in ast.walk(value) if isinstance(n, ast.Call)):
        for arg in [*call.args, *(kw.value for kw in call.keywords)]:
            if token in _mentions(arg):
                return True
    return False


def _tainted_by(fn: ast.AST, token: str) -> set[str]:
    """The local names whose value derives from a call that RECEIVED *token*.

    Intraprocedural and deliberately so -- see this module's last paragraph for what that cannot
    see. Growth stops when the set stops moving, or at :data:`_TAINT_PASSES`, whichever is first.
    """
    taint: set[str] = set()
    for _ in range(_TAINT_PASSES):
        before = set(taint)
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign | ast.AnnAssign):
                value = node.value
                if value is None:
                    continue
                if _fed_to_a_call(value, token) or (_mentions(value) & taint):
                    stores = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in stores:
                        taint |= _stored(target)
            elif isinstance(node, ast.For) and (_mentions(node.iter) & taint):
                taint |= _stored(node.target)
        if taint == before:
            break
    return taint


def _judging_comparisons(fn: ast.AST) -> list[ast.Compare]:
    """The membership tests that DECIDE a verdict -- an ``assert``, or an ``if`` that raises.

    THE SUBJECT IS AN ASSERTION AND NOT AN EXPRESSION, which is the distinction that keeps this off
    honest code. :func:`lab_commons.proc.kill_process_tree` writes ``[pid] if pid in tree else []``
    over a ``tree`` its own call built, and that branch is a real one: an unreadable process table
    returns an empty set, so both arms happen. Nothing there claims anything, so nothing there can
    be a claim that cannot fail.
    """
    out: list[ast.Compare] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.If) and not any(isinstance(n, ast.Raise) for b in node.body for n in ast.walk(b)):
            continue
        if not isinstance(node, ast.Assert | ast.If):
            continue
        if isinstance(node.test, ast.Compare):
            out.append(node.test)
    return out


def _echoes(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[int, str, str]]:
    """The ``(line, token, container)`` triples in ONE function body that check their own echo."""
    args = fn.args
    params = {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]}
    out: list[tuple[int, str, str]] = []
    for node in _judging_comparisons(fn):
        if len(node.ops) != 1 or not isinstance(node.ops[0], ast.In | ast.NotIn):
            continue
        left = node.left
        if not (isinstance(left, ast.Name) and left.id in params):
            continue
        container = node.comparators[0]
        if _mentions(container) & _tainted_by(fn, left.id):
            out.append((node.lineno, left.id, ast.unparse(container)))
    return out


def echoed_tokens(root: Path, *, roots: Collection[tuple[str, str]], exempt: Collection[str]) -> EchoScan:
    """Every clause under the declared roots that searches for a token its own producer was handed.

    Args:
        root: the consumer's checkout.
        roots: ``(directory, glob)`` pairs -- the trees to walk and what a file in each is called. NO
            DEFAULT: the shape lives wherever a repo keeps its SHARED assertion bodies, and this
            family spells that directory differently in every tree. A guessed pair walks a directory
            that is not there and reports clean, which is why the floor below is mandatory.
        exempt: repo-relative paths whose own source carries the shape as DATA -- the consumer's
            control fixture, and any file that plants an offender on purpose. NO DEFAULT, and a
            consumer must assert each one exists: an exemption naming a deleted file covers nothing
            while still reading as a decision.

    Returns:
        An :class:`EchoScan`. Offenders are spelled ``path:line: fn(): token ... container``, sorted
        by path then line, so the set is comparable and can be pinned.

    """
    skip = frozenset(exempt)
    hits: list[str] = []
    read = 0
    for directory, pattern in roots:
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob(pattern)):
            rel = path.relative_to(root).as_posix()
            if '__pycache__' in path.parts or rel in skip:
                continue
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            except (OSError, SyntaxError):
                continue
            for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)):
                read += 1
                hits.extend(
                    f'{rel}:{line}: {fn.name}(): {token} is searched for in {where}, which was built from it'
                    for line, token, where in _echoes(fn)
                )
    return EchoScan(functions_read=read, offenders=tuple(hits))


def take_scan(root: Path, *, roots: Collection[tuple[str, str]], exempt: Collection[str]) -> EchoScan:
    """Walk *root* once -- the reading :func:`echoed_tokens` returns, under the name the arms use.

    Published as its own name because every other body in this package hands its arms a ``take_scan``
    result, and a consumer that has to remember which module spells it differently is one edit away
    from calling the arm twice over two different walks.
    """
    return echoed_tokens(root, roots=roots, exempt=exempt)


def assert_no_clause_checks_its_own_echo(scan: EchoScan, *, floor: int, headroom: int) -> None:
    """THE CHECK, with the FLOOR BOUND FIRST so a walk that parsed nothing cannot read as clean.

    Args:
        scan: what :func:`take_scan` returned.
        floor: the consumer's MEASURED count of function bodies the walk reads, set below the real
            population. NO DEFAULT -- one repo's number handed to another is a floor nothing
            measured, and this scanner's clean answer is the common one, so a silent walk is the
            state it is most likely to hide behind.
        headroom: how far past its floor that population may grow before the floor is re-measured.
            NO DEFAULT: a floor measured against a smaller tree refuses only a total collapse, and a
            floor sitting ON its population is a countdown whose only repair is editing the digit.

    Raises:
        lab_commons.dev.floors.FloorUnmet: the walk read fewer bodies than the floor.
        lab_commons.dev.floors.SlackFloor: the floor has stopped binding.
        EchoedToken: at least one clause searches for a token its own producer was handed.

    """
    floors.assert_floor(scan.functions_read, floor=floor, what='echoed-token')
    floors.assert_floor_still_binds(scan.functions_read, floor=floor, headroom=headroom, what='echoed-token')
    if scan.offenders:
        msg = (
            'a clause that searches for a token the producer INTERPOLATES holds for any string '
            'whatever, so it is green for reasons no implementation can take away. Assert the '
            'property the token was standing in for, or delete the clause -- a dead clause removed '
            'is better than a dead clause kept:\n  ' + '\n  '.join(scan.offenders)
        )
        raise EchoedToken(msg)


def assert_the_scanner_still_convicts(plant_root: Path, *, roots: Collection[tuple[str, str]]) -> None:
    """THE PLANTED CONTROL, in BOTH directions, driving the REAL scanner over a REAL tree.

    A scan that has never been shown to fire proves nothing when it is green, and the opposite error
    is just as fatal here: this shape's honest neighbours outnumbered its offenders four to one in
    the package it was found in, so a rule that names them gets deleted rather than obeyed. Every
    distinction is therefore planted at once -- the echo on its own line, beside a container built
    from OTHER arguments, one read off the world, and a token that reaches only the refusal MESSAGE,
    which is written after the test has already decided.

    Args:
        plant_root: an empty directory to plant into -- a consumer's ``tmp_path``. Taken as an
            argument so the control drives the SHIPPED scanner rather than a re-implementation,
            which would agree with itself and prove nothing.
        roots: the consumer's own ``(directory, glob)`` pairs, so the control exercises the walk THIS
            repo declares. The first pair is the one planted into; a repo whose first tree is not
            walked would otherwise pass a control over a tree it never reads.

    Raises:
        AssertionError: the scanner missed the planted echo, or named one of its honest neighbours.

    """
    pairs = list(roots)
    if not pairs:
        msg = 'the control was handed no roots, so it would walk nothing and pass in triumph'
        raise AssertionError(msg)
    directory, pattern = pairs[0]
    name = pattern.replace('*', 'planted') if '*' in pattern else 'planted.py'
    planted = plant_root / directory / name
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text(_PLANTED_SOURCE, encoding='utf-8')
    found = take_scan(plant_root, roots=pairs, exempt=()).offenders
    lines = sorted(int(hit.split(':')[1]) for hit in found)
    if lines != [_PLANTED_ECHO_LINE]:
        msg = (
            f'the scanner named lines {lines} and the one planted echo is on {_PLANTED_ECHO_LINE}. '
            f'The three neighbours must all be left alone: a container built from OTHER arguments, '
            f'one read off the world, and a token that reaches only the refusal message after the '
            f'test has decided. Naming any of them is how this guard gets deleted rather than '
            f'obeyed; missing the echo is the defect it exists for.'
        )
        raise AssertionError(msg)
