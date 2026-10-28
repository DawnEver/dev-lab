"""A BODY THAT JUDGES THE BOX CARRIES ITS NEED -- the test calling it must wear the resource marker.

WHAT EARNED IT, MEASURED 2026-10-19 on a consumer's first Linux part. The cluster produces a part in
``~/ci/trees/<sha>``: a detached worktree of a bare cache with no hooks installed, no session branches,
no trunk checked out, and no ``node``. Every consumer test that ran a famtests body against ITS OWN
checkout went red there -- hooks not installed, ``NotVisibleOnOrigin``, a worktree "outside", every
agent-guard arm for want of a host ``node`` -- and none of those reds was about the commit. They were about the host.
A part may only judge what its host can measure (NOT COVERED IS NOT PASSED): such a test belongs to the
part whose need-set names the resource (:mod:`lab_commons.hpc.needsets`), and the host that lacks it
hands it to that part (the run record's ``handed``) rather than failing or passing it.

THE NEED IS THE BODY'S FACT, so it is declared HERE, once (:data:`NEEDS`), and a consumer cannot
forget it: :func:`assert_box_bodies_are_marked` reads the consumer's test files and refuses a test
that calls a body without the marker its need names, or a need the consumer's
``[tool.lab_commons.tests] resources`` does not declare (an undeclared marker selects nothing, so the
test would land in ``base`` and on the cluster again).

TWO KINDS OF NEED, because two different facts are missing on the cluster:

* ``always`` -- the body needs the resource whatever it is pointed at: the box's own ``node``, which the
  live hook runs on. DRIVING an engine needs no host resource since 2026-10-28: it runs on the locked
  Node (:mod:`dev_lab.dev.jsrun`), so the guard and allow-guard bodies carry no row.
* ``live`` -- the body needs it only when pointed at THE LIVE CHECKOUT (``workstation``). The same
  body pointed at a tree the test plants judges that tree, which any host has. The reading is
  syntactic and says which: an argument built from the test function's own parameters or locals
  (``tmp_path``, a fixture, a tree planted in the body) is planted; anything else -- a module
  constant ``ROOT``, no argument at all -- is the live checkout. In a non-test helper a parameter is
  UNKNOWN and convicts, because the default must be the one that cannot pass a missing marker.
* A call under ``pytest.raises`` needs nothing: it tests the body REFUSING (no node, no engine), and
  that refusal is exactly what a host without the resource can measure.

WHAT IS DELIBERATELY NOT HERE. ``origin`` checks (``visibility.assert_origin_branch_set``) read the repo's remote,
which the per-repo cluster
cache carries; marking them would hand a measurable check to a narrower part.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from lab_commons.hpc.needsets import read_vocabulary

from dev_lab.dev.workstation import WORKSTATION

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path

__all__ = ['NEEDS', 'Need', 'UnmarkedNeed', 'assert_box_bodies_are_marked', 'unmarked']


@dataclass(frozen=True)
class Need:
    """What a body needs: *always*, and additionally when it reads the *live* checkout."""

    always: frozenset[str] = frozenset()
    live: frozenset[str] = frozenset()


_PKG: Final = 'dev_lab.dev.famtests'
_LIVE: Final = Need(live=frozenset({WORKSTATION}))
_HOST_NODE: Final = Need(always=frozenset({WORKSTATION}))

#: ``qualified body name -> its need``; the ONE place a famtests body's host need is stated.
NEEDS: Final[Mapping[str, Need]] = {
    f'{_PKG}.agentguard.assert_node_is_available': _HOST_NODE,
    f'{_PKG}.hookinstall.assert_declared_hooks_are_installed': _LIVE,
    f'{_PKG}.hookinstall.assert_hooks_dir_is_the_one_git_consults': _LIVE,
    f'{_PKG}.visibility.assert_readable': _LIVE,
    f'{_PKG}.visibility.assert_one_pushable_branch': _LIVE,
    f'{_PKG}.visibility.assert_local_only_branches': _LIVE,
    f'{_PKG}.worktreeplace.assert_every_worktree_stays_inside': _LIVE,
}

_MARKERS_TABLE: Final = '[tool.lab_commons.tests] resources'


class UnmarkedNeed(AssertionError):
    """A test calls a body needing a resource it does not mark, or the repo does not declare."""


def _aliases(tree: ast.Module) -> dict[str, str]:
    """``local name -> qualified name`` for every import of the famtests package in *tree*."""
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(_PKG):
            for alias in node.names:
                found[alias.asname or alias.name] = f'{node.module}.{alias.name}'
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(_PKG) and alias.asname:
                    found[alias.asname] = alias.name
    return found


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and (head := _dotted(node.value)):
        return f'{head}.{node.attr}'
    return None


def _resolve(func: ast.expr, aliases: Mapping[str, str]) -> str | None:
    name = _dotted(func)
    if name is None:
        return None
    head, _, rest = name.partition('.')
    if head in aliases:
        return f'{aliases[head]}.{rest}' if rest else aliases[head]
    return name


def _marks(decorators: list[ast.expr]) -> set[str]:
    """The ``pytest.mark.<name>`` names among *decorators* (a list value spreads)."""
    names: set[str] = set()
    for item in decorators:
        target = item.func if isinstance(item, ast.Call) else item
        if isinstance(target, (ast.List, ast.Tuple)):
            names |= _marks(list(target.elts))
            continue
        dotted = _dotted(target) or ''
        if dotted.startswith('pytest.mark.'):
            names.add(dotted.split('.')[2])
    return names


def _module_marks(tree: ast.Module) -> set[str]:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(_dotted(t) == 'pytestmark' for t in node.targets):
            return _marks([node.value])
    return set()


def _refusal(expr: ast.expr) -> bool:
    """``pytest.raises(...)``: a body called under it is tested REFUSING, which needs no resource."""
    return isinstance(expr, ast.Call) and _dotted(expr.func) == 'pytest.raises'


def _local_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    args = func.args
    names = {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]}
    names |= {n.id for n in ast.walk(func) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    return names


def _call_needs(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    aliases: Mapping[str, str],
    helpers: Mapping[str, set[str]],
    *,
    planted_locals: bool,
) -> set[str]:
    """What *func*'s calls need; with *planted_locals* an argument built from its own names is planted."""
    local = _local_names(func) if planted_locals else set()
    expected = {
        id(call)
        for block in ast.walk(func)
        if isinstance(block, (ast.With, ast.AsyncWith)) and any(_refusal(item.context_expr) for item in block.items)
        for statement in block.body
        for call in ast.walk(statement)
    }
    needed: set[str] = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.Call) or id(node) in expected:
            continue
        name = _resolve(node.func, aliases)
        if name in helpers:
            needed |= helpers[name]
        need = NEEDS.get(name or '')
        if need is None:
            continue
        needed |= need.always
        arguments = [*node.args, *(k.value for k in node.keywords)]
        used = {n.id for a in arguments for n in ast.walk(a) if isinstance(n, ast.Name)}
        if not (used & local):
            needed |= need.live
    return needed


def _tests(tree: ast.Module) -> Iterator[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef, set[str]]]:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test'):
            yield node.name, node, _marks(node.decorator_list)
        elif isinstance(node, ast.ClassDef) and node.name.startswith('Test'):
            outer = _marks(node.decorator_list)
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith('test'):
                    yield f'{node.name}::{item.name}', item, outer | _marks(item.decorator_list)


def _helpers(tree: ast.Module, aliases: Mapping[str, str]) -> dict[str, set[str]]:
    """``helper name -> need`` for module-level non-test functions, closed over each other."""
    funcs = {
        n.name: n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith('test')
    }
    found: dict[str, set[str]] = {name: set() for name in funcs}
    while True:
        moved = False
        for name, func in funcs.items():
            need = _call_needs(func, aliases, found, planted_locals=False)
            if need != found[name]:
                found[name], moved = need, True
        if not moved:
            return {k: v for k, v in found.items() if v}


def unmarked(source: str) -> dict[str, frozenset[str]]:
    """``test name -> the markers it lacks`` for one test module's *source*."""
    tree = ast.parse(source)
    aliases = _aliases(tree)
    helpers = _helpers(tree, aliases)
    module = _module_marks(tree)
    missing: dict[str, frozenset[str]] = {}
    for name, func, marks in _tests(tree):
        lack = _call_needs(func, aliases, helpers, planted_locals=True) - marks - module
        if lack:
            missing[name] = frozenset(lack)
    return missing


def assert_box_bodies_are_marked(*, tests: Path, pyproject: str, floor: int) -> None:
    """Every test under *tests* calling a box body carries its markers, and *pyproject* declares them.

    Args:
        tests: the consumer's test tree, read recursively for ``test_*.py``.
        pyproject: the consumer's ``pyproject.toml`` TEXT, whose resources must name every need met.
        floor: the fewest box-body calls the scan must see -- a scan reading no call is an unread one,
            not a clean one. NO DEFAULT.

    Raises:
        UnmarkedNeed: a test lacks a marker, a need is undeclared, or the scan saw fewer calls than *floor*.

    """
    declared = set(read_vocabulary(pyproject).resources)
    lacking: list[str] = []
    seen = 0
    met: set[str] = set()
    for path in sorted(tests.rglob('test_*.py')):
        source = path.read_text(encoding='utf-8')
        if _PKG not in source:
            continue
        tree = ast.parse(source)
        aliases = _aliases(tree)
        helpers = _helpers(tree, aliases)
        for _, func, _ in _tests(tree):
            need = _call_needs(func, aliases, helpers, planted_locals=True)
            seen += bool(need)
            met |= need
        lacking += [f'  {path.relative_to(tests)}::{t}: mark {sorted(m)}' for t, m in unmarked(source).items()]
    if seen < floor:
        msg = f'the scan of {tests} saw {seen} test(s) calling a box body, under the floor {floor}: an unread scan'
        raise UnmarkedNeed(msg)
    if undeclared := sorted(met - declared):
        msg = f'{_MARKERS_TABLE} lacks {undeclared}: an undeclared marker selects nothing and the test runs in base'
        raise UnmarkedNeed(msg)
    if lacking:
        body = '\n'.join(lacking)
        msg = (
            f'{len(lacking)} test(s) judge this box without the resource marker their body needs '
            f'(dev_lab.dev.famtests.boxneeds.NEEDS); a host lacking it reds on the host, not the commit:\n{body}'
        )
        raise UnmarkedNeed(msg)
