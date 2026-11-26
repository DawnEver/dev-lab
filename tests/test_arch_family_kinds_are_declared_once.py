"""FAMILY KINDS: every dated kind a dev-lab mechanism writes is in ``datedlog.FAMILY_KINDS``, and nothing else is.

WHY. Every adopter's ``[layout]`` admits the family's kinds without listing them (``dev_lab.dev.layout``), so a
mechanism that starts writing ``<output>/<yy>/<mm>/<dd>/<new kind>/`` without declaring it there is refused in
every repo at once -- or, worse, each repo copies the row by hand and the fact lives N times. This guard reads
the WRITERS and holds them against the constant, both ways.

WHAT IS A WRITER, read off the AST of every tracked module under ``src/``:

* a module-level ``KIND`` / ``*_KIND`` string constant (``LOG_KIND``, ``_RECORD_KIND``, ...);
* the kind of an ``output_dir(root, KIND)`` call, and the ``kind=`` of a ``dated_log`` call whose ``base`` is
  not resolved to somewhere outside ``output`` (a machine's ``~/.cache``);
* the segment right after a DATE in a path built by hand -- a ``/`` chain or a call's arguments where one element
  holds ``date_parts()``, a ``strftime('%y...')`` or an ``f'{...:%y...}'``, and the next resolves to a string.

A kind the scan finds that is no dated output of a checkout is NAMED in :data:`NOT_DATED_OUTPUT` with where it
really goes; that set is a ratchet too -- an entry the scan no longer finds is stale and reds.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from typing import TYPE_CHECKING, Final

from _arch_corpus import SOURCE_FLOOR, assert_floor, corpus_key, parse, source_modules

from dev_lab.dev.datedlog import FAMILY_KINDS

if TYPE_CHECKING:
    from pathlib import Path

#: Kinds a mechanism names that are NOT a checkout's dated output, each with where it really goes.
NOT_DATED_OUTPUT: Final = {
    'pytest': 'testtemp.KIND: a pytest base-temp entry under the system temp dir',
    'scripttest': 'testtemp.SCRIPT_KIND: a script suite temp entry under the system temp dir',
    'ruff': "rules._LINT_KIND: a lint row's mechanism, never a directory",
    'worker_died': 'test_outcomes.DEAD_WORKER_KIND: an outcome reason, never a directory',
    'deploy-fleet': "hpcaccount.fleet.KIND: a log under the machine's ~/.cache/dev-lab, not a checkout",
    'devhost': "backedup: a machine-file backup under the machine's ~/.cache/dev-lab, not a checkout",
}
#: The fewest kinds the scan must reach. MEASURED 2026-11-25: 20 (14 family + 6 named above); set below it.
KIND_FLOOR: Final = 18

_KIND_NAME: Final = re.compile(r'(?:^|_)KIND$')
_DATE_FORMAT: Final = '%y'


def _constants(tree: ast.Module) -> dict[str, str]:
    """The module-level ``NAME = 'text'`` (or annotated) bindings of *tree*."""
    out: dict[str, str] = {}
    for node in tree.body:
        target = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else None
        target = node.target if isinstance(node, ast.AnnAssign) else target
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if isinstance(target, ast.Name) and isinstance(value, ast.Constant) and isinstance(value.value, str):
            out[target.id] = value.value
    return out


def _resolve(node: ast.expr, local: dict[str, str], shared: dict[str, set[str]]) -> str | None:
    """*node* as a string: a literal, a module constant, or ``module.CONSTANT`` named once across the corpus."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return local.get(node.id)
    if isinstance(node, ast.Attribute) and len(shared.get(node.attr, ())) == 1:
        return next(iter(shared[node.attr]))
    return None


def _is_date(node: ast.AST) -> bool:
    """Whether *node* holds a calendar date: ``date_parts()``, ``.strftime('%y..')`` or ``f'{..:%y..}'``."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            name = sub.func.attr if isinstance(sub.func, ast.Attribute) else getattr(sub.func, 'id', '')
            if name == 'date_parts':
                return True
            first = sub.args[0] if sub.args else None
            if name == 'strftime' and isinstance(first, ast.Constant) and _DATE_FORMAT in str(first.value):
                return True
        if isinstance(sub, ast.FormattedValue) and sub.format_spec is not None and _DATE_FORMAT in ast.unparse(sub):
            return True
    return False


def _div_chain(node: ast.BinOp) -> list[ast.expr]:
    """``a / b / c`` flattened to ``[a, b, c]``."""
    left = (
        _div_chain(node.left) if isinstance(node.left, ast.BinOp) and isinstance(node.left.op, ast.Div) else [node.left]
    )
    return [*left, node.right]


def _after_date(elements: list[ast.expr]) -> list[ast.expr]:
    """Each element that follows a date element: the kind segment of a hand-built dated path."""
    return [elements[i + 1] for i in range(len(elements) - 1) if _is_date(elements[i])]


def _base_outside_output(call: ast.Call, local: dict[str, str], shared: dict[str, set[str]]) -> bool:
    base = next((k.value for k in call.keywords if k.arg == 'base'), None)
    text = None if base is None else _resolve(base, local, shared)
    return text is not None and not text.startswith('output')


def _kind_nodes(tree: ast.Module, local: dict[str, str], shared: dict[str, set[str]]) -> list[ast.expr]:
    found: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', '')
            if name == 'output_dir' and len(node.args) > 1:
                found.append(node.args[1])
            if name == 'dated_log' and not _base_outside_output(node, local, shared):
                found += [k.value for k in node.keywords if k.arg == 'kind']
            found += _after_date([a.value if isinstance(a, ast.Starred) else a for a in node.args])
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            found += _after_date(_div_chain(node))
    return found


def written_kinds(paths: tuple[Path, ...]) -> dict[str, list[str]]:
    """Every dated kind the modules at *paths* name, -> the modules naming it -- pure over its argument."""
    trees = {path: parse(path) for path in paths}
    local = {path: _constants(tree) for path, tree in trees.items()}
    shared: dict[str, set[str]] = defaultdict(set)
    for constants in local.values():
        for name, value in constants.items():
            shared[name].add(value)
    out: dict[str, list[str]] = defaultdict(list)
    for path, tree in trees.items():
        kinds = {value for name, value in local[path].items() if _KIND_NAME.search(name)}
        kinds |= {k for n in _kind_nodes(tree, local[path], shared) if (k := _resolve(n, local[path], shared))}
        for kind in kinds:
            out[kind].append(corpus_key(path))
    return dict(out)


def _scanned() -> dict[str, list[str]]:
    modules = source_modules()
    assert_floor(len(modules), SOURCE_FLOOR, 'family-kind writer')
    found = written_kinds(modules)
    assert_floor(len(found), KIND_FLOOR, 'family-kind')
    return found


def test_every_kind_a_mechanism_writes_is_a_family_kind() -> None:
    """A writer of a kind absent from ``FAMILY_KINDS`` reds: every adopter's layout would refuse what it writes."""
    found = _scanned()
    stray = {kind: sites for kind, sites in found.items() if kind not in FAMILY_KINDS and kind not in NOT_DATED_OUTPUT}
    assert not stray, (
        f'these modules write dated kinds no FAMILY_KINDS row declares: {stray}. Declare each in '
        f'dev_lab.dev.datedlog.FAMILY_KINDS with the formats it writes, or name it in NOT_DATED_OUTPUT with where '
        f'it really goes.'
    )


def test_every_family_kind_has_a_writer_the_scan_finds() -> None:
    """The scan's floor is the constant itself: a family kind no writer names is a dead row, or a blind scan."""
    found = _scanned()
    dead = sorted(set(FAMILY_KINDS) - set(found))
    assert not dead, f'FAMILY_KINDS declares {dead}, which no scanned writer names: drop the row or fix the scan'


def test_every_named_exemption_is_still_found() -> None:
    found = _scanned()
    stale = sorted(set(NOT_DATED_OUTPUT) - set(found))
    assert not stale, f'NOT_DATED_OUTPUT names {stale}, which no scanned module names any more: drop them'
    assert not set(NOT_DATED_OUTPUT) & set(FAMILY_KINDS)


def test_planted_writers_of_undeclared_kinds_are_each_found(tmp_path) -> None:
    """THE PLANTED CONTROL: each writer shape, naming a kind no family row declares, is found -- else green is blind."""
    module = tmp_path / 'planted.py'
    module.write_text(
        'from pathlib import Path\n'
        "CENSUS_KIND = 'census'\n"
        "_TRIAGE = 'triage'\n"
        'def a(root): return output_dir(root, _TRIAGE)\n'
        "def b(root): return dated_log(root, 'x.log', base='output/logs', kind='record')\n"
        "def c(now): return Path('output/logs') / f'{now:%y/%m/%d}' / 'commit' / 'x.json'\n"
        "def d(root): return output_path(root, 'logs', *date_parts(), 'gate', 'x.jsonl')\n"
        "def e(home): return dated_log(home, 'x.log', base='.cache/x', kind='machine')\n",
        encoding='utf-8',
    )
    found = written_kinds((module,))
    assert set(found) == {'census', 'triage', 'record', 'commit', 'gate'}, found
    assert not set(found) & set(FAMILY_KINDS)
