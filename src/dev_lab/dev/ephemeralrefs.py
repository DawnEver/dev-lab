"""TRACKED-CITES-NO-EPHEMERAL -- a tracked file never references content git does not keep, nor a machine path.

EPHEMERAL MEANS UNTRACKED CONTENT IN A PLACE GIT NEVER KEEPS (user ruling 2026-10-28). Two places,
both derived, neither listed here: what the repo's own ignore rules ignore (``git check-ignore
--no-index --stdin``, so a repo that ignores a new cache directory is covered the moment it says so),
and the declared stray roots (``[tool.dev_lab.placement]``, the family's ``scratch/``), which are
NEVER ignored -- a one-off there must show in ``git status`` -- and never committed beyond their
README, so ``git check-ignore`` alone let every ``scratch/`` probe through. A path in either place
passes only when it is TRACKED (a re-included lock file, the scratch README). What git cannot judge
-- a path on another machine -- is the one declared list, :data:`MACHINE_LOCAL`.

NOT EPHEMERAL: an untracked path under a tracked root (``src/gone.py``) is a broken or cross-repo
link, not cited content that lives outside version control; measured 2026-10-28 that reading
refused ~10k such lines in consumer-a alone, almost all dated memory, so it is a different defect.

THREE PROPERTIES, over every tracked file (2 and 3 skip archived code, ``attic/``):

1. NO TRACKED FILE LIVES UNDER AN IGNORED ROOT (a ``git add -f`` into ``output/``):
   ``git ls-files -ci --exclude-standard``.
2. PROSE TIER -- ``.md``/``.rst``/``.txt`` text, and the COMMENTS of code and config (``#`` in
   Python, TOML, YAML, shell; ``//`` in Rust, JS, TS) -- cites no ignored in-repo path and no
   machine-local path, and no untracked path under a stray root.
3. CODE TIER -- Python only -- does not READ an ephemeral or machine-local path as an input: a string
   literal inside a call to a read verb (:data:`READ_VERBS`). WRITING to ``output/`` is what output
   is for, so a literal in any other position is not judged. This is an approximation by syntax and
   says so: a path built in one statement and read in another passes.

SHAPE IS ALLOWED, CONTENT IS NOT. A path with a ``<...>`` placeholder segment describes structure
(``output/logs/<yy>/<mm>/<dd>/<kind>/``) and is never judged; nor is a bare top-level directory name
with its slash (``scratch/``), which names a place and cites nothing in it. A locator suffix
(``:12``, ``#anchor``, ``::test``) is dropped before judging. Every other ephemeral path is a citation.

ESCAPES ARE ONE DECLARED SET, in the consumer's ``pyproject.toml``::

    [tool.dev_lab.ephemeral_refs]
    ceiling = 1
    escapes = [{file = "docs-src/x.md", token = "output/forge/outbox/", reason = "defines it"}]

The count must EQUAL the ceiling, so removing an escape forces the ceiling down in the same diff and
raising it is a visible edit, never a switch. Keyed by ``(file, token)`` -- a line number drifts.
"""

from __future__ import annotations

import ast
import io
import re
import sys
import tokenize
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev import venvpath
from dev_lab.dev.codeplace import FAMILY_STRAY_ROOTS, PlacementNotDeclared, declared_placement, is_archived
from dev_lab.dev.family import declared_table
from dev_lab.dev.rules import tracked_files

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping, Sequence

__all__ = [
    'MACHINE_LOCAL',
    'PORTABLE',
    'READ_VERBS',
    'Citation',
    'Escapes',
    'citations_in',
    'forced_under_ignored',
    'judge',
    'load_escapes',
    'main',
    'scan',
]

RULE: Final = 'TRACKED-CITES-NO-EPHEMERAL'
#: The one remedy every refusal prints.
REMEDY: Final = 'cite a tracked source or a <placeholder> shape, or declare an escape in [tool.dev_lab.ephemeral_refs]'

#: Paths no ignore file can judge because they are not in the repo: a drive letter, a home or
#: cluster root, a temp dir, the agent job tree. Matched at the START of a token.
MACHINE_LOCAL: Final[re.Pattern[str]] = re.compile(
    r'^(?:[A-Za-z]:/|/home/|/Users/|/gpfs0\d/|/mnt/[a-z]/|/tmp/|/var/tmp/|~/\.cache/'
    r'|%TEMP%|%TMP%|%LOCALAPPDATA%/Temp|\$TMPDIR|\$CLAUDE_JOB_DIR|(?:.*/)?\.claude-evans/jobs/)'
)

#: The family's interpreter door and venv activation: fixed COMMAND spellings every bootstrap creates, not content in
#: the venv, derived from :data:`dev_lab.dev.venvpath.VENV_LAYOUTS` (the one place a layout is spelled). Anything
#: else under ``.venv/`` is judged like any ignored path.
PORTABLE: Final = frozenset(
    '/'.join(parts) for layout in venvpath.VENV_LAYOUTS.values() for parts in (layout, (*layout[:-1], 'activate'))
)

#: Call names that READ their argument. A literal ignored path inside one of these calls is an input.
READ_VERBS: Final = frozenset({
    'open', 'read_text', 'read_bytes', 'load', 'loads', 'loadtxt', 'genfromtxt', 'read_csv', 'read_json',
    'read_parquet', 'read_excel', 'imread', 'glob', 'rglob', 'iterdir', 'listdir', 'scandir', 'walk',
    'exists', 'is_file', 'is_dir', 'stat', 'copy', 'copyfile', 'copytree',
})  # fmt: skip

_PROSE: Final = frozenset({'.md', '.rst', '.txt'})
_HASH: Final = frozenset({'.toml', '.yaml', '.yml', '.sh', '.ps1', '.cfg', '.ini'})
_SLASH: Final = frozenset({'.rs', '.js', '.ts', '.c', '.h', '.cpp'})
_TOKEN = re.compile(r'[^\s`\'"()\[\]|,;=]+')
_PLACEHOLDER = re.compile(r'<[^>]*>')
_TRAILING = '.:!?*'
_PROBE: Final = 'ephemeralrefs-probe'
#: A locator suffix that is not part of the path: ``::test``, ``#anchor``, ``:line[:col]`` or ``:a-b``.
_SUFFIX = re.compile(r'(?:::.*|#.*|(?::\d+)+(?:-\d+)?)$')
_RELATIVE = re.compile(r'^[\w.+@-]+(?:/[\w.+@-]*)+$')


@dataclass(frozen=True)
class Citation:
    """One judged reference: the file, the line, the token, and why it is refused."""

    path: str
    line: int
    token: str
    why: str

    def __str__(self) -> str:
        """``path:line: why 'token'`` -- the form every refusal prints."""
        return f'{self.path}:{self.line}: {self.why} {self.token!r}'


@dataclass(frozen=True)
class Escapes:
    """The consumer's declared escape set: ``(file, token) -> reason``, and its ceiling."""

    entries: Mapping[tuple[str, str], str]
    ceiling: int


def load_escapes(root: Path) -> Escapes:
    """Read ``[tool.dev_lab.ephemeral_refs]`` from *root*'s ``pyproject.toml``; absent is empty."""
    project = root / 'pyproject.toml'
    data = tomllib.loads(project.read_text(encoding='utf-8')) if project.is_file() else {}
    table = declared_table(data, 'ephemeral_refs', {})
    entries = {(row['file'], row['token']): row.get('reason', '') for row in table.get('escapes', [])}
    return Escapes(entries=entries, ceiling=int(table.get('ceiling', 0)))


def _candidates(text: str) -> Iterable[str]:
    for match in _TOKEN.finditer(text):
        token = match.group().rstrip(_TRAILING)
        if '/' in token.replace('\\', '/') or MACHINE_LOCAL.match(token):
            yield token


def _pieces(path: str, text: str) -> list[tuple[int, str, bool]]:
    """``(line, text, is_read_input)`` for every judged piece of *path* by its tier."""
    suffix = Path(path).suffix.lower()
    if suffix in _PROSE:
        return [(n, line, False) for n, line in enumerate(text.splitlines(), 1)]
    if suffix in _HASH | _SLASH:
        mark = '#' if suffix in _HASH else '//'
        return [(n, line.split(mark, 1)[1], False) for n, line in enumerate(text.splitlines(), 1) if mark in line]
    if suffix in {'.py', '.pyi'}:
        return _python_pieces(text)
    return []


def _python_pieces(text: str) -> list[tuple[int, str, bool]]:
    out: list[tuple[int, str, bool]] = []
    try:
        out.extend(
            (tok.start[0], tok.string[1:], False)
            for tok in tokenize.generate_tokens(io.StringIO(text).readline)
            if tok.type == tokenize.COMMENT
        )
        tree = ast.parse(text)
    except (SyntaxError, tokenize.TokenError):
        return out
    # A literal joined onto a base (`tmp_path / '<dir>/x'`) is relative to THAT base, not the repo.
    joined = {id(node.right) for node in ast.walk(tree) if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ''
        if name in READ_VERBS and not _writes(node, name):
            out.extend(
                (const.lineno, const.value, True)
                for const in ast.walk(node)
                if isinstance(const, ast.Constant) and isinstance(const.value, str) and id(const) not in joined
            )
    return out


def _writes(call: ast.Call, name: str) -> bool:
    """An ``open`` whose mode writes, appends or creates: a write target, not an input."""
    if name != 'open':
        return False
    modes = [kw.value for kw in call.keywords if kw.arg == 'mode']
    modes += call.args[1:2] if isinstance(call.func, ast.Name) else call.args[:1]
    return any(isinstance(m, ast.Constant) and isinstance(m.value, str) and set(m.value) & set('wax') for m in modes)


def _normal(token: str) -> str:
    norm = token.replace('\\', '/')
    return norm.removeprefix('./')


def _is_shape(norm: str) -> bool:
    segments = [s for s in norm.split('/') if s]
    return bool(_PLACEHOLDER.search(norm)) or (len(segments) == 1 and norm.endswith('/'))


def judge(root: Path, tokens: Collection[str]) -> dict[str, str]:
    """``token -> why`` for every token in *tokens* that is refused; one ``check-ignore`` call.

    A relative token is judged only when it is not TRACKED (as a file, or as a directory holding
    tracked files), after a ``:line``, ``#anchor`` or ``::test`` suffix is dropped; a glob is a shape.
    It is refused when git ignores it, or when it lies under a declared stray root (``scratch/``).

    A directory token (trailing slash) outside a stray root whose PARENT holds tracked files is an
    ignored root itself (``.claude/worktrees/``): it names a place and cites nothing in it, so it
    passes. ``output/forge/outbox/`` -- whose parent holds nothing tracked -- is content and does not.
    A bare machine-local root (``$TMPDIR``) passes the same way.
    """
    refused: dict[str, str] = {}
    local: dict[str, str] = {}
    for token in tokens:
        norm = _SUFFIX.sub('', _normal(token))
        if '://' in norm or norm in PORTABLE or _is_shape(norm):
            continue
        head = MACHINE_LOCAL.match(norm)
        if head:
            if norm[head.end() :].strip('/'):
                refused[token] = 'machine-local path'
        elif _RELATIVE.match(norm) and not norm.startswith('../'):
            local[token] = norm
    if local:
        refused.update(_judge_local(root, local))
    return refused


def _judge_local(root: Path, local: Mapping[str, str]) -> dict[str, str]:
    """``token -> why`` for the in-repo candidates (``token -> normalised path``) that are ephemeral."""
    tracked = tracked_files(root)
    lived = _tracked_dirs(tracked)
    strays = _stray_roots(root)
    probes: dict[str, list[str]] = {}
    for token, norm in local.items():
        path = norm.rstrip('/')
        stray = path.split('/', 1)[0] in strays
        if path in tracked or path in lived or (not stray and norm.endswith('/') and path.rpartition('/')[0] in lived):
            continue
        # A trailing slash is probed as a FILE inside it: `check-ignore --no-index` answers a bare
        # `dir/` wrongly (measured: every `x/` matched a blank line of the ignore file).
        probes.setdefault(f'{norm}{_PROBE}' if norm.endswith('/') else norm, []).append(token)
    ignored = _ignored(root, list(probes))
    refused: dict[str, str] = {}
    for probe, owners in probes.items():
        why = 'ignored path' if probe in ignored else 'untracked path' if probe.split('/', 1)[0] in strays else ''
        refused.update(dict.fromkeys(owners, why) if why else {})
    return refused


def _stray_roots(root: Path) -> set[str]:
    """The first segment of every declared stray root (``scratch``): untracked by rule, never ignored."""
    try:
        strays = declared_placement(root).stray_roots
    except PlacementNotDeclared:
        strays = FAMILY_STRAY_ROOTS
    return {stray.strip('/').split('/', 1)[0] for stray in strays}


def _tracked_dirs(tracked: Collection[str]) -> set[str]:
    """Every directory holding a tracked file, ``''`` for the root."""
    found = {''}
    for name in tracked:
        parts = name.split('/')[:-1]
        found.update('/'.join(parts[:depth]) for depth in range(1, len(parts) + 1))
    return found


def _ignored(root: Path, probes: Sequence[str]) -> set[str]:
    """The probes git's own ignore rules ignore (a negated ``!`` match is not); one call."""
    if not probes:
        return set()
    answer = _door.run(
        ['git', 'check-ignore', '--no-index', '--stdin', '-z', '-v'],
        input='\0'.join(probes) + '\0',
        capture_output=True,
        text=True,
        encoding='utf-8',
        cwd=root,
        check=False,
        timeout=300,
    )
    if answer.returncode not in {0, 1}:
        msg = f'git check-ignore failed in {root}: {answer.stderr.strip()}'
        raise RuntimeError(msg)
    fields = answer.stdout.split('\0')
    # -z -v: <source> NUL <line> NUL <pattern> NUL <path> NUL; a negated (!) match is NOT ignored.
    return {fields[i + 3] for i in range(0, len(fields) - 3, 4) if fields[i + 2] and not fields[i + 2].startswith('!')}


def citations_in(root: Path, names: Iterable[str]) -> tuple[list[Citation], int]:
    """Every refused citation across *names* (repo-relative), and how many files were READ.

    Archived code (:func:`dev_lab.dev.codeplace.is_archived`) is read-only history and is skipped, as by
    every family scan; property 1 still covers it, because it judges WHERE a file lives, not what it says.
    """
    pending: list[tuple[str, int, str, bool]] = []
    read = 0
    for name in names:
        if is_archived(name):
            continue
        file = root / name
        try:
            text = file.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        pieces = _pieces(name, text)
        read += 1
        pending.extend(
            (name, line, token, is_input)
            for line, piece, is_input in pieces
            for token in _candidates_of(piece, is_input=is_input)
        )
    verdicts = judge(root, {token for _, _, token, _ in pending})
    found = [
        Citation(path=name, line=line, token=token, why=('reads ' if is_input else 'cites ') + verdicts[token])
        for name, line, token, is_input in pending
        if token in verdicts
    ]
    return found, read


def _candidates_of(piece: str, *, is_input: bool) -> Iterable[str]:
    return (
        [piece.strip()]
        if is_input and piece.strip() and not any(c.isspace() for c in piece.strip())
        else _candidates(piece)
    )


def forced_under_ignored(root: Path) -> list[str]:
    """Tracked files git's own ignore rules would ignore -- each one was ``git add -f``-ed in."""
    answer = _door.run(
        ['git', 'ls-files', '-ci', '--exclude-standard', '-z'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        cwd=root,
        check=True,
        timeout=300,
    )
    return sorted(filter(None, answer.stdout.split('\0')))


def scan(root: Path, names: Iterable[str] | None = None) -> tuple[list[str], int]:
    """The problems (escapes applied) over *names*, default every tracked file, and the files read.

    With *names* given (the pre-commit's staged set) orphaned escapes are not judged: an escape for an
    unstaged file is not visible there.
    """
    full = names is None
    chosen = sorted(tracked_files(root)) if full else list(names)
    escapes = load_escapes(root)
    found, read = citations_in(root, chosen)
    problems = [str(hit) for hit in found if (hit.path, hit.token) not in escapes.entries]
    problems.extend(
        f'{name}: tracked under an ignored root (git add -f)'
        for name in forced_under_ignored(root)
        if name in set(chosen)
    )
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


def main(argv: Sequence[str] | None = None) -> int:
    """Pre-commit entry: ``python -m dev_lab.dev.ephemeralrefs <staged path>...``; 1 on a finding."""
    names = [Path(a).as_posix() for a in (sys.argv[1:] if argv is None else argv)]
    root = Path.cwd()
    problems, _ = scan(root, [n for n in names if (root / n).is_file()])
    for problem in problems:
        emit(f'[{RULE}] {problem}')
    if problems:
        emit(f'[{RULE}] {REMEDY}\n')
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
