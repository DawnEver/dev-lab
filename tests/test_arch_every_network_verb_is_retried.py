"""NETWORK-RETRY-THEN-REPORT, BY CONSTRUCTION: every network argv the kit spells reaches the ONE retry door.

INCIDENTS 2026-10-19 (consumer-a): ``dep --sync`` ran ``uv sync`` raw and one forge auth blip failed it; a
``git ls-remote`` reach probe, a host refresh's ``git fetch`` and a workstation's ``git clone`` ran raw too.
The primitive is :func:`dev_lab.dev.netverb.run_network_verb`; which argv is a network verb is
:func:`dev_lab.dev.netverb.is_network_verb`, read here rather than restated.

THE SCAN. Every list or tuple literal in ``src`` whose program is ``git``/``uv`` (a constant, or a name
spelling one: ``_GIT``, ``programs.git``, ``*git``) and whose constant words make a network verb, must be
handed to a ROUTER at its argv position -- directly, or through a name bound to it in the same function.
A module that cannot reach the door is EXEMPT BY NAME with its reason; the set is the ceiling.

THE BLIND SPOT, NAMED: a helper that PREPENDS the program (``_git(root, 'clone', ...)``,
``_git(plan, ctx, name, ['fetch', ...])``) spells no program in its literal and is not seen here. Measured
2026-10-19: ``supervise/deploy.py``'s fetch (server-side, capped runner), ``lockcheck``'s local ``--shared``
clone and the famtests' local bare-repository fixtures are of that shape.
"""

from __future__ import annotations

import ast
from typing import Final

import pytest
from _arch_corpus import assert_floor, parse, rel, source_modules

from dev_lab.dev.netverb import is_network_verb

#: Callables that run a network argv through the retry door, and the argv's positional index in each.
ROUTERS: Final = {'run_network_verb': 0, 'network': 2}

#: Modules whose network argv cannot reach the door, each with the reason. The set is the ceiling: a
#: module leaves it by routing its argv, never by a broader pattern.
EXEMPT: Final[dict[str, str]] = {
    'src/dev_lab/dev/_dep_project.py': 'builds the `uv sync`/`uv lock` argv _dep_network.run_change routes through '
    'run_network_verb by is_network_verb',
    'src/dev_lab/dev/dep.py': 'pip_argv returns the uv pip argv _dep_network.run_change routes',
    'src/dev_lab/dev/hpchost/steps.py': 'runs on the cluster host through its own run-or-print Step, whose '
    'refusal the deploy reports per repo',
    'src/dev_lab/dev/hpchost/account.py': 'runs on the cluster host; its ls-remote is a read-access probe whose '
    'exit code IS the answer',
}

#: The kit's network argv literals; MEASURED 2026-10-19 above it (a floor refuses an unread corpus).
NETWORK_FLOOR = 15

_PROGRAMS: Final = ('git', 'uv')


def _text(node: ast.expr) -> str:
    if isinstance(node, ast.Starred):
        return _text(node.value)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ''


def _program(node: ast.expr) -> str:
    """``git``/``uv`` when *node* spells that program (``'git'``, ``_GIT``, ``programs.git``, ``uv_binary``)."""
    word = _text(node).lower().strip('_')
    return next((name for name in _PROGRAMS if word == name or word.startswith(f'{name}_')), '')


def is_network_literal(node: ast.AST) -> bool:
    """Whether *node* is an argv literal :func:`is_network_verb` calls a network verb."""
    if not isinstance(node, (ast.List, ast.Tuple)) or not node.elts:
        return False
    program = _program(node.elts[0])
    if not program:
        return False
    words = [
        element.value if isinstance(element, ast.Constant) and isinstance(element.value, str) else '<value>'
        for element in node.elts[1:]
        if not isinstance(element, ast.Starred)
    ]
    return is_network_verb([program, *words])


def _routed_argvs(scope: ast.AST) -> set[int]:
    """The ids of every node handed to a router at its argv position, directly or by a name bound in *scope*."""
    bound: dict[str, list[ast.AST]] = {}
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            bound.setdefault(node.targets[0].id, []).append(node.value)
        if isinstance(node, ast.NamedExpr):
            bound.setdefault(node.target.id, []).append(node.value)
    routed: set[int] = set()
    for node in ast.walk(scope):
        if not isinstance(node, ast.Call):
            continue
        index = ROUTERS.get(_text(node.func))
        if index is None or len(node.args) <= index:
            continue
        argv = node.args[index]
        routed.add(id(argv))
        if isinstance(argv, ast.Name):
            routed.update(id(value) for value in bound.get(argv.id, ()))
    return routed


def unrouted(tree: ast.Module) -> list[int]:
    """The line of every network argv literal in *tree* that no router receives."""
    scopes = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    routed = set().union(*(_routed_argvs(scope) for scope in scopes)) if scopes else set()
    return [node.lineno for node in ast.walk(tree) if is_network_literal(node) and id(node) not in routed]


def test_every_network_argv_in_the_kit_reaches_the_retry_door() -> None:
    modules = source_modules()
    found = {rel(path): parse(path) for path in modules}
    total = sum(1 for tree in found.values() for node in ast.walk(tree) if is_network_literal(node))
    assert_floor(total, NETWORK_FLOOR, 'network argv literals in src')
    raw = {path: lines for path, tree in found.items() if path not in EXEMPT and (lines := unrouted(tree))}
    assert raw == {}, f'route these through dev_lab.dev.netverb.run_network_verb: {raw}'
    stale = sorted(path for path in EXEMPT if path not in found or not unrouted(found[path]))
    assert stale == [], f'exempt modules with no raw network argv left -- delete their rows: {stale}'


@pytest.mark.parametrize(
    ('body', 'flagged'),
    [
        ("def f():\n    run(['git', 'fetch', 'origin'])\n", True),
        ("def f(root):\n    run([_GIT, '-C', str(root), 'push', 'origin', 'HEAD'])\n", True),
        ("def f(p):\n    step.change('x', [*p.git, 'clone', '-q', 'u', 'd'])\n", True),
        ("def f(uv):\n    run((uv, 'sync', '--frozen'))\n", True),
        ("def f():\n    run(['git', 'submodule', 'update', '--init'])\n", True),
        ("def f():\n    run_network_verb(['git', 'fetch', 'origin'])\n", False),
        ("def f():\n    c = ['uv', 'lock']\n    run_network_verb(c, timeout=1)\n", False),
        ("def f(s):\n    network(s, 'w', ['git', 'clone', 'u', 'd'])\n", False),
        ("def f():\n    run(['git', 'status'])\n", False),
        ("def f():\n    run(['git', 'log', '--', 'fetch'])\n", False),
        ("def f():\n    run(['uv', 'pip', 'list'])\n", False),
    ],
)
def test_a_planted_raw_network_argv_is_flagged_and_a_routed_one_passes(body: str, *, flagged: bool) -> None:
    """PLANTED, both directions: a raw verb is found, a routed one and a local verb are not."""
    assert bool(unrouted(ast.parse(body))) is flagged
