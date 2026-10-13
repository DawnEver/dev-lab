"""A MERGE MAY NOT LOSE OR REWRITE A TEST IN SILENCE -- the three-way audit at test granularity.

THE PREMISE. The tests ARE the feature inventory: every registry, verb set and capability table a
consumer cares about is pinned by one. So a merge can drop a feature past every gate in exactly one
way -- the conflict resolution deletes or rewrites the test that would have caught it, and the gate
then runs green against the weakened specification. A second hand-written feature list would be a
second source of truth that goes stale; this module reads the one that already exists.

THE RULE. For a merge ``M`` of parents ``O`` and ``T`` over base ``B``, each test's EXPECTED body is
what git's own three-way rule gives: ``O == B`` takes ``T``, ``T == B`` takes ``O``, equal changes
take that change, and different changes have no expectation. A test whose body in ``M`` is not the
expectation is a :class:`Deviation`:

* :data:`LOST` -- expected present, absent in ``M``;
* :data:`ALTERED` -- ``M`` holds a body (or a presence) the clean merge would not;
* :data:`CONFLICTED` -- both sides changed it differently; whatever ``M`` holds was a human choice.

Every deviation must be NAMED in the merge commit by a trailer line carrying a reason, and a line
naming a deviation the merge does not hold is refused too -- an over-claiming ledger is a ledger
nobody can read. A clean merge needs no line at all.

IDENTITY IS THE NAME, NOT THE PATH: a test keyed ``Class::test_x`` survives an upstream split of its
file. A name defined twice anywhere in the four trees is keyed ``path::name`` everywhere instead, so
the key set is one function of the inputs. A body is fingerprinted with docstrings stripped and
comments gone (``ast`` drops them): prose is not specification.

WHEN IT RUNS: AT COMMIT, ON THE ONE MERGE BEING COMMITTED. A merge's deviations are a fact about
that merge, known the moment it is recorded, so :func:`main` is the ``commit-msg`` hook (the family
base's ``merge-audit`` row): while ``MERGE_HEAD`` exists it audits the INDEX against HEAD and
MERGE_HEAD and refuses the commit with the unnamed list and the remedy; any other commit costs one
file check. Push admission does no audit (user ruling 2026-10-10: a push must never block
development -- auditing 152 unpublished merges held one for over twenty minutes).

WHAT THIS DOES NOT SEE, stated so nobody reads it as more: a fixture or helper that changed under an
unchanged test body. That change still runs under the gate; what is audited here is the
specification the gate is held to.
"""

from __future__ import annotations

import ast
import hashlib
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

from lab_commons.dev.forge import _GIT
from lab_commons.dev.lanepolicy import load_policy
from lab_commons.log import emit

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

__all__ = [
    'ALTERED',
    'CONFLICTED',
    'LOST',
    'TRAILER',
    'Deviation',
    'MergeAuditError',
    'audit',
    'classify',
    'judge',
    'main',
    'pending',
    'read_tests',
    'unnamed',
]

LOST: Final = 'LOST'
ALTERED: Final = 'ALTERED'
CONFLICTED: Final = 'CONFLICTED'
#: The trailer key a merge commit names each deviation under: ``Merge-Audit: <KIND> <test> -- <reason>``.
TRAILER: Final = 'Merge-Audit'

_LINE: Final = re.compile(
    rf'^{TRAILER}:\s*(?P<kind>[A-Z]+)\s+(?P<test>\S+)(?:\s+--\s*(?P<reason>\S.*))?$', re.MULTILINE
)
_GIT_TIMEOUT_S: Final = 120
#: A two-parent merge is the one shape the rule is about; an octopus is refused, one lane at a time.
_PARENTS: Final = 2


class MergeAuditError(RuntimeError):
    """The audit could not read what it must judge -- refused, never read as a clean merge."""


@dataclass(frozen=True, order=True)
class Deviation:
    """One test the merge holds differently from a clean three-way merge."""

    kind: str
    test: str


def _is_test(name: str) -> bool:
    return name.startswith('test')


def _fingerprint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    if ast.get_docstring(node, clean=False) is not None:
        node.body = node.body[1:]
    return hashlib.sha256(ast.dump(node).encode()).hexdigest()[:16]


def _defined(path: str, source: bytes) -> list[tuple[str, str]]:
    try:
        module = ast.parse(source, filename=path)
    except (SyntaxError, ValueError) as error:
        msg = f'{path}: unparseable ({error}) -- the audit refuses rather than read it as holding no test'
        raise MergeAuditError(msg) from error
    found: list[tuple[str, str]] = []
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_test(node.name):
            found.append((node.name, _fingerprint(node)))
        elif isinstance(node, ast.ClassDef) and node.name.startswith('Test'):
            found.extend(
                (f'{node.name}::{item.name}', _fingerprint(item))
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_test(item.name)
            )
    return found


def _is_test_file(path: str) -> bool:
    name = PurePosixPath(path).name
    return name.endswith('.py') and (name.startswith('test_') or name.endswith('_test.py'))


def _scan(sources: Mapping[str, bytes]) -> list[tuple[str, str, str]]:
    return [
        (path, name, fp)
        for path in sorted(sources)
        if _is_test_file(path)
        for name, fp in _defined(path, sources[path])
    ]


def _keyed(rows: Iterable[tuple[str, str, str]], shared: set[str]) -> dict[str, str]:
    return {(f'{path}::{name}' if name in shared else name): fp for path, name, fp in rows}


def read_tests(sources: Mapping[str, bytes], *, shared: set[str] | None = None) -> dict[str, str]:
    """``{test identity: body fingerprint}`` for the test files in *sources* (``{posix path: bytes}``).

    *shared* names identities defined more than once across the trees being compared; when omitted,
    the duplicates within *sources* alone decide.
    """
    rows = _scan(sources)
    if shared is None:
        shared = {name for name, n in Counter(name for _, name, _ in rows).items() if n > 1}
    return _keyed(rows, shared)


def classify(
    base: Mapping[str, str], ours: Mapping[str, str], theirs: Mapping[str, str], merged: Mapping[str, str]
) -> tuple[Deviation, ...]:
    """Every test *merged* holds differently from the clean three-way merge of the other three."""
    found: set[Deviation] = set()
    for test in {*base, *ours, *theirs, *merged}:
        b, o, t, m = base.get(test), ours.get(test), theirs.get(test), merged.get(test)
        if o == b:
            expected = t
        elif t in (b, o):
            expected = o
        else:
            found.add(Deviation(CONFLICTED, test))
            continue
        if m == expected:
            continue
        found.add(Deviation(LOST if m is None else ALTERED, test))
    return tuple(sorted(found))


def unnamed(found: Sequence[Deviation], message: str) -> tuple[str, ...]:
    """What the ledger in *message* fails to say about *found*; empty when every line matches."""
    named = {Deviation(m['kind'], m['test']) for m in _LINE.finditer(message) if m['reason']}
    problems = [
        f'{d.kind} {d.test}: not named -- add `{TRAILER}: {d.kind} {d.test} -- <reason>`'
        for d in sorted(set(found) - named)
    ]
    problems += [
        f'{d.kind} {d.test}: named, but the merge holds no such deviation -- delete the line'
        for d in sorted(named - set(found))
    ]
    return tuple(problems)


def _git(root: Path, *args: str, data: bytes | None = None) -> bytes:
    done = subprocess.run(
        [_GIT, '-C', str(root), *args], input=data, capture_output=True, check=False, timeout=_GIT_TIMEOUT_S
    )
    if done.returncode != 0:
        msg = f'git {" ".join(args)} failed: {done.stderr.decode("utf-8", "replace").strip()}'
        raise MergeAuditError(msg)
    return done.stdout


def _sources(root: Path, sha: str, roots: Sequence[str]) -> dict[str, bytes]:
    listed = _git(root, 'ls-tree', '-r', '-z', sha, '--', *roots).split(b'\0')
    blobs: dict[str, str] = {}
    for entry in filter(None, listed):
        meta, _, path = entry.decode('utf-8').partition('\t')
        if meta.split()[1] == 'blob' and _is_test_file(path):
            blobs[path] = meta.split()[2]
    if not blobs:
        return {}
    out = _git(root, 'cat-file', '--batch', data=''.join(f'{oid}\n' for oid in blobs.values()).encode())
    contents: dict[str, bytes] = {}
    cursor = 0
    for path in blobs:  # `--batch` answers in request order: `<oid> blob <size>\n<bytes>\n`
        header_end = out.index(b'\n', cursor)
        size = int(out[cursor:header_end].split()[2])
        contents[path] = out[header_end + 1 : header_end + 1 + size]
        cursor = header_end + 1 + size + 1
    return contents


def audit(root: Path, merge: str, *, roots: Sequence[str]) -> tuple[Deviation, ...]:
    """The deviations of the two-parent merge commit *merge*, reading test files under *roots*."""
    parents = _git(root, 'rev-list', '--parents', '-n', '1', merge).decode().split()[1:]
    return _audit(root, merge, parents, merge, roots=roots)


def _pending_parents(root: Path) -> list[str] | None:
    """HEAD plus every ``MERGE_HEAD`` while a merge is being committed, else ``None``."""
    merge_head = root / _git(root, 'rev-parse', '--git-path', 'MERGE_HEAD').decode().strip()
    if not merge_head.is_file():
        return None
    head = _git(root, 'rev-parse', 'HEAD').decode().strip()
    return [head, *merge_head.read_text(encoding='utf-8').split()]


def _audit(
    root: Path, merge: str, parents: Sequence[str], merged: str, *, roots: Sequence[str]
) -> tuple[Deviation, ...]:
    """The deviations of *merged* (a commit or a tree) as the merge of *parents*; *merge* labels refusals."""
    if len(parents) != _PARENTS:
        msg = f'{merge}: {len(parents)} parents -- the audit judges a two-parent merge; merge lanes one at a time'
        raise MergeAuditError(msg)
    bases = _git(root, 'merge-base', '--all', *parents).decode().split()
    if len(bases) != 1:
        msg = f'{merge}: {len(bases)} merge bases (a criss-cross) -- merge through one integration branch instead'
        raise MergeAuditError(msg)
    shas = (bases[0], *parents, merged)
    trees = [_sources(root, sha, roots) for sha in shas]
    rows = [_scan(t) for t in trees]
    if not any(rows):
        msg = f'{merge}: no test under {list(roots)} in any of its trees -- a vacuous audit is refused'
        raise MergeAuditError(msg)
    counts = [Counter(name for _, name, _ in r) for r in rows]
    shared = {name for c in counts for name, n in c.items() if n > 1}
    base, ours, theirs, merged = (_keyed(r, shared) for r in rows)
    return classify(base, ours, theirs, merged)


def pending(root: Path, message: str, *, roots: Sequence[str]) -> tuple[str, ...]:
    """What *message* fails to name about the merge being committed in *root*; empty for a non-merge.

    The merged tree is the INDEX (``git write-tree``) -- exactly what the commit will record.
    """
    parents = _pending_parents(root)
    if parents is None:
        return ()
    tree = _git(root, 'write-tree').decode().strip()
    return judge(root, parents, tree, message, roots=roots, label='the merge being committed')


def judge(
    root: Path, parents: Sequence[str], merged: str, message: str, *, roots: Sequence[str], label: str = ''
) -> tuple[str, ...]:
    """What *message* fails to name about *merged* (a commit or a tree) as the merge of *parents*.

    The ONE judgement: the commit-msg hook (:func:`pending`), ``integrate merge`` and the integration
    branch's push guard (:mod:`lab_commons.dev.sessionbranch`) all call it.
    """
    return unnamed(_audit(root, label or merged, parents, merged, roots=roots), message)


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m lab_commons.dev.mergeaudit <commit-msg-file>`` -- the commit-msg hook; ``1`` refuses."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        emit('merge-audit: pass exactly the commit message file (git hands it to commit-msg)', err=True)
        return 1
    try:
        root = Path(_git(Path.cwd(), 'rev-parse', '--show-toplevel').decode().strip())
        message = Path(args[0]).read_text(encoding='utf-8', errors='replace')
        problems = pending(root, message, roots=load_policy(root).test_roots)
    except (MergeAuditError, OSError) as error:
        problems = (str(error),)
    if not problems:
        return 0
    remedy = (
        'merge-audit: Remedy: restore what the resolution dropped, or name each deviation in the message as '
        f'`{TRAILER}: <KIND> <test> -- <reason>` and commit again.'
    )
    lines = [
        'merge-audit: commit REFUSED -- this merge lost or rewrote tests without naming them.',
        *(f'merge-audit:   {line}' for line in problems),
        remedy,
    ]
    emit('\n'.join(lines), err=True)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
