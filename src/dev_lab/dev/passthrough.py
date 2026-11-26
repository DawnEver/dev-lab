"""NO-DETOUR: a module or crate file that only forwards to another owner names what the hop adds.

User-approved 2026-11-25 (principle ``no-detour``: every hop must add something). In a repo declaring its owner graph
(:mod:`dev_lab.dev.deptable`), a file is a PASS-THROUGH when it has at least one public function, every public
function only forwards, and it has no other public item:

* PYTHON: a module :func:`dev_lab.dev.pyfacts.forwards` reads as only forwarding (each public function passes its
  own parameters, unchanged, to one imported function; nothing else public) -- to a function of ANOTHER owner
  (``[python.owners]``, or a native crate's owner by ``[python.native]``) or of a SIBLING child
  (``[python.siblings."<package>"]``).
* RUST (:mod:`dev_lab.dev.rustsource`): a top-level ``pub fn`` whose body is one ``path(args)`` call (``return``
  allowed) passing its parameters in order, the path reaching ANOTHER workspace crate (directly or through ``use``).

It is refused unless the edge to that owner or crate names what the hop adds --
``{ name = "<target>", adds = "translation" | "policy" | "control" }`` in the importer's row. A forward within one
package, to a third-party package or to std is not judged. WHAT IT CANNOT SEE: a forward that renames, reorders or
defaults an argument, wraps the result, or forwards through a local alias reads as adding something.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev import deptable, ownerdag, pyfacts, rustdeps, rustsource
from dev_lab.dev.deptable import Declared, edge_to

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ['DOOR', 'RULE_ID', 'check', 'main', 'problems', 'refusal']

RULE_ID: Final = 'NO-DETOUR'
DOOR: Final = (
    'call the target directly and delete the hop (its callers move with it); when the hop adds a translation, a '
    'policy or one point of control, say so on the edge in dependencies.toml: '
    '<owner> = [{ name = "<target>", adds = "translation" | "policy" | "control" }]'
)
_DETAILS: Final = 'details: docs-src/dev/refusals.md#no-detour (dev-lab)'
_RUST_CALL: Final = re.compile(
    r'((?:::)?[A-Za-z_]\w*(?:\s*::\s*[A-Za-z_]\w*)*)\s*(?:::\s*<.*?>\s*)?\((.*)\)', re.DOTALL
)


def _unadded(edges: tuple[deptable.Edge, ...], target: str) -> bool:
    edge = edge_to(edges, target)
    return edge is None or edge.adds is None


def _python_problems(root: Path, decl: Declared, files: list[str]) -> list[str]:
    tree = ownerdag.python_tree(root)
    if tree is None or not decl.owners:
        return []
    out: list[str] = []
    facts = pyfacts.facts(root, (f for f in files if f.endswith('.py')))  # the set OWNER-DAG asks: one journal
    for rel in sorted(facts):
        mine = ownerdag.owner_of_path(tree, rel)
        if mine is None or mine not in decl.owners:
            continue
        forwards = facts[rel].forwards or ()
        hops = [_hop(root, decl, tree, rel=rel, mine=mine, target=target) for _, target in forwards]
        if not hops or None in hops:
            continue
        names = ', '.join(name for name, _ in forwards)
        out += [
            f'{rel}: every public function forwards to {kind} {theirs} unchanged ({names}), and [{table}] '
            f'{origin} -> {theirs} names nothing the hop adds'
            for table, kind, origin, theirs, edges in sorted({h for h in hops if h is not None})
            if _unadded(edges, theirs)
        ]
    return out


def _hop(
    root: Path, decl: Declared, tree: ownerdag.PythonTree, *, rel: str, mine: str, target: str
) -> tuple[str, str, str, str, tuple[deptable.Edge, ...]] | None:
    """``(table, kind, from, to, edges of from)`` for a forward crossing an owner or a sibling edge, else ``None``."""
    theirs = ownerdag.owner_of_name(tree, decl, target)
    if theirs is None:
        return None
    if theirs != mine:
        return 'python.owners', 'owner', mine, theirs, decl.owners[mine]
    if (hop := ownerdag.sibling_hop(root, tree, rel, target)) is None:
        return None
    parent, child, other = hop
    return f'python.siblings."{parent}"', 'sibling', child, other, decl.siblings.get(parent, {}).get(child, ())


def _rust_forward(fn: rustsource.FreeFn, bound: dict[str, str], crates: Iterable[str], own: str) -> str | None:
    body = re.sub(r'^return\s+', '', fn.body).strip().removesuffix(';').strip()
    call = _RUST_CALL.fullmatch(body)
    if call is None or None in fn.params or rustsource.split_top(call.group(2)) != list(fn.params):
        return None
    head, _, rest = re.sub(r'\s*::\s*', '::', call.group(1)).removeprefix('::').partition('::')
    target = bound.get(head, head).partition('::')[0].replace('-', '_') if rest or head in bound else ''
    return target if target in crates and target != own else None


def _rust_problems(root: Path, decl: Declared, files: list[str]) -> list[str]:
    if not decl.crates:
        return []
    crates = rustdeps.crates(root, files)
    out: list[str] = []
    for crate in sorted((c for c in crates.values() if c.name in decl.crates), key=lambda c: c.name):
        prefix = f'{crate.directory}/src/' if crate.directory else 'src/'
        for rel in (f for f in files if f.startswith(prefix) and f.endswith('.rs')):
            code = rustsource.code_of((root / rel).read_text(encoding='utf-8'))
            items, bound = rustsource.free_functions(code), rustsource.bindings(code)
            targets = [_rust_forward(fn, bound, crates, crate.name) for fn in items.functions]
            if items.other_public or not targets or None in targets:
                continue
            names = ', '.join(fn.name for fn in items.functions)
            out += [
                f'{rel}: every pub fn forwards to crate {theirs} unchanged ({names}), and [rust.crates] '
                f'{crate.name} -> {theirs} names nothing the hop adds'
                for theirs in sorted({t for t in targets if t is not None})
                if _unadded(decl.crates[crate.name], theirs)
            ]
    return out


def problems(root: Path, decl: Declared, files: Iterable[str]) -> list[str]:
    """Every pass-through over the repo-relative *files* whose edge names nothing the hop adds."""
    files = sorted(files)
    return _python_problems(root, decl, files) + _rust_problems(root, decl, files)


def _report(found: list[str]) -> str:
    return '\n'.join([f'{RULE_ID}: {len(found)} refusal(s)', *found, f'door: {DOOR}', _DETAILS])


def check(root: Path) -> None:
    """The always-on family check: raise naming every pass-through in *root*'s tracked tree (when declared)."""
    if found := ownerdag.judged(root, problems):
        raise AssertionError(_report(found))


def refusal(root: Path) -> str | None:
    """What ``verify`` refuses on; ``None`` when clean or undeclared (not judged)."""
    found = ownerdag.judged(root, problems) if deptable.declared(root) else None
    return _report(found) if found else None


def main(argv: list[str] | None = None, *, cwd: Path | None = None) -> int:
    """Judge the tracked tree; exit 1 on a refusal, 0 when clean or undeclared (and say which)."""
    del argv
    root = cwd or Path.cwd()
    if not deptable.declared(root):
        emit(f'{RULE_ID}: {root.name} holds no {deptable.FILE}, so this repo is not judged (opt-in)', flush=True)
        return 0
    if not (found := ownerdag.judged(root, problems)):
        return 0
    emit(_report(found), flush=True)
    return 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
