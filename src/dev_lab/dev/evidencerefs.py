"""EVIDENCE-OUTLIVES-OUTPUT -- a tracked value never names output-tree content as its provenance.

TRACKED-CITES-NO-EPHEMERAL (:mod:`dev_lab.dev.ephemeralrefs`) judges prose, comments and the literal a
READ call takes. A recorded verdict cites its evidence elsewhere: a docstring ``MEASURED on output/...``,
a ``note=``/``source=`` field, ``repo_root() / 'output/...'`` read two statements later, a TOML/YAML
value, a JSON field. This is the tier for THOSE, with the same predicate (:func:`ephemeralrefs.judge`:
a git-ignored path, an untracked path under a stray root, a machine-local path) and its own escapes, narrowed to
CONTENT (:data:`CONTENT`) -- a recorded citation names a run or a file, a configured place names neither:

1. PYTHON -- every string constant, docstrings included, EXCEPT a constant inside a WRITE call
   (:data:`WRITE_VERBS`, an ``open`` whose mode writes): code may still write to ``output/``. A literal
   right of ``/`` is relative to its base and passes, unless the base is a repo-root call
   (:data:`ROOT_CALLS`) or a repo-root name (:data:`ROOT_NAMES`): then it is repo-relative and judged.
2. DATA -- ``.toml``/``.yaml``/``.yml`` text outside ``#`` comments (the comments are the prose tier's),
   and every line of a ``.json`` file. An escape's own ``token`` in ``pyproject.toml`` names what it escapes.

A ``<placeholder>`` shape passes; dated memory and archived code are records and are skipped, as in
the prose tier. Escapes are ``[tool.dev_lab.evidence_refs]`` in ``pyproject.toml``, the shape and the
count-equals-ceiling rule of ``[tool.dev_lab.ephemeral_refs]``; a consumer with a backlog starts at
its measured count and the ceiling only falls.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Final

from dev_lab.dev.codeplace import is_archived
from dev_lab.dev.ephemeralrefs import DATED_MEMORY, Citation, Escapes, judge
from dev_lab.dev.family import declared_table
from dev_lab.dev.rules import tracked_files

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ['CONTENT', 'ROOT_CALLS', 'ROOT_NAMES', 'RULE', 'WRITE_VERBS', 'citations_in', 'load_escapes', 'scan']

RULE: Final = 'EVIDENCE-OUTLIVES-OUTPUT'
REMEDY: Final = (
    'move the evidence into a dated memory entry or a tracked fixture and cite that, '
    'or declare an escape in [tool.dev_lab.evidence_refs]'
)
#: Calls whose argument is a WRITE target: every constant inside one is exempt.
WRITE_VERBS: Final = frozenset({
    'write_text', 'write_bytes', 'mkdir', 'makedirs', 'touch', 'savefig', 'to_csv', 'to_json', 'to_parquet',
    'savez', 'savez_compressed', 'save', 'run_output_dir',
})  # fmt: skip
#: A call returning the repo root: a literal joined onto it is repo-relative.
ROOT_CALLS: Final = frozenset({'repo_root', 'find_repo_root', 'project_root', 'git_root'})
#: A name bound to the repo root: a literal joined onto it is repo-relative.
ROOT_NAMES: Final = frozenset({'REPO', 'REPO_ROOT', 'ROOT', 'PROJECT_ROOT', '_REPO', '_ROOT', '_REPO_ROOT'})

#: CONTENT, not a place: a dated run segment (``26/01/01``) or a last segment with a file suffix. A place a tool
#: writes (``output/cache/pytest``) is configuration, and a machine-local path is the code tier's, not evidence.
CONTENT: Final = re.compile(r'(?:^|/)\d{2}/\d{2}/\d{2}(?:/|$)|\.[A-Za-z0-9]{1,8}/?$')
_DATA_HASH: Final = frozenset({'.toml', '.yaml', '.yml'})
_RAW = re.compile(r'[^\s`\'"()\[\]{}|,;=]+')


def load_escapes(root: Path) -> Escapes:
    """Read ``[tool.dev_lab.evidence_refs]`` from *root*'s ``pyproject.toml``; absent is empty."""
    project = root / 'pyproject.toml'
    data = tomllib.loads(project.read_text(encoding='utf-8')) if project.is_file() else {}
    table = declared_table(data, 'evidence_refs', {})
    entries = {(row['file'], row['token']): row.get('reason', '') for row in table.get('escapes', [])}
    return Escapes(entries=entries, ceiling=int(table.get('ceiling', 0)))


def _call_name(node: ast.AST) -> str:
    func = node.func if isinstance(node, ast.Call) else None
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ''


def _writes(call: ast.Call) -> bool:
    name = _call_name(call)
    if name in WRITE_VERBS:
        return True
    if name != 'open':
        return False
    modes = [kw.value for kw in call.keywords if kw.arg == 'mode']
    modes += call.args[1:2] if isinstance(call.func, ast.Name) else call.args[:1]
    return any(isinstance(m, ast.Constant) and isinstance(m.value, str) and set(m.value) & set('wax') for m in modes)


def _is_root(base: ast.expr) -> bool:
    if isinstance(base, ast.Call):
        return _call_name(base) in ROOT_CALLS
    return isinstance(base, ast.Name) and base.id in ROOT_NAMES


def _python_pieces(text: str) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    exempt: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _writes(node):
            exempt.update(id(sub) for sub in ast.walk(node))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and not _is_root(node.left):
            exempt.add(id(node.right))
    return [
        (const.lineno, const.value)
        for const in ast.walk(tree)
        if isinstance(const, ast.Constant) and isinstance(const.value, str) and id(const) not in exempt
    ]


def _pieces(name: str, text: str) -> list[tuple[int, str]]:
    suffix = Path(name).suffix.lower()
    if suffix in {'.py', '.pyi'}:
        return _python_pieces(text)
    if suffix in _DATA_HASH:
        return [(n, line.split('#', 1)[0]) for n, line in enumerate(text.splitlines(), 1)]
    if suffix == '.json':
        return list(enumerate(text.splitlines(), 1))
    return []


def _candidates(piece: str) -> Iterable[str]:
    for match in _RAW.finditer(piece):
        token = match.group().rstrip('.:!?*')
        norm = token.replace('\\', '/')
        if '/' in norm and '..' not in norm.split('/'):  # a parent step leaves the repo: no ignore rule judges it
            yield token


def citations_in(root: Path, names: Iterable[str]) -> tuple[list[Citation], int]:
    """Every refused evidence citation across *names*, and how many files were READ."""
    pending: list[tuple[str, int, str]] = []
    read = 0
    for name in names:
        if is_archived(name) or DATED_MEMORY.search(name):
            continue
        try:
            text = (root / name).read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        pieces = _pieces(name, text)
        if not pieces and Path(name).suffix.lower() not in {'.py', '.pyi', '.json', *_DATA_HASH}:
            continue
        read += 1
        pending.extend((name, line, token) for line, piece in pieces for token in _candidates(piece))
    verdicts = {
        token: why
        for token, why in judge(root, {token for _, _, token in pending}).items()
        if why != 'machine-local path' and CONTENT.search(token.replace('\\', '/'))
    }
    found = [
        Citation(path=name, line=line, token=token, why='records evidence at ' + verdicts[token])
        for name, line, token in pending
        if token in verdicts
    ]
    return found, read


def scan(root: Path, names: Iterable[str] | None = None) -> tuple[list[str], int]:
    """The problems (escapes applied) over *names*, default every tracked file, and the files read.

    With *names* omitted the escape set is judged too: orphaned, unreasoned, or not EQUAL to its ceiling.
    """
    full = names is None
    chosen = sorted(tracked_files(root)) if full else list(names)
    escapes = load_escapes(root)
    found, read = citations_in(root, chosen)
    declared = {token for _, token in escapes.entries}
    problems = [
        str(hit)
        for hit in found
        if (hit.path, hit.token) not in escapes.entries and not (hit.path == 'pyproject.toml' and hit.token in declared)
    ]
    if full:
        seen = {(hit.path, hit.token) for hit in found}
        problems.extend(
            f'escape {key} is ORPHANED; delete it and lower the ceiling' for key in escapes.entries if key not in seen
        )
        if len(escapes.entries) != escapes.ceiling:
            problems.append(
                f'{len(escapes.entries)} escapes against a ceiling of {escapes.ceiling}: they must be EQUAL'
            )
        problems.extend(f'escape {key} carries no reason' for key, why in escapes.entries.items() if not why.strip())
    return problems, read
