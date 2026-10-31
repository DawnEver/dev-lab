"""REVIEW-SCOPE: what one PR review reads, cut into slices a reviewer can hold, and how the slices merge.

The branch's own change, minus generated files, since the last reviewed head; each slice under the lens its
paths earn.

A HEAD IS NEVER HELD FOR ITS SIZE (D123, user ruling 2026-10-31 "too many files: then review by reading the
directories", superseding the 2026-10-26 hold-on-oversize). The budget bounds a SLICE (``max_diff_bytes``); past
the TOTAL (``max_total_bytes``), when one file alone outgrows a slice, or when a command that takes no paths would
need several slices, the head is ONE review of the whole range with no paths (:data:`WHOLE`, :attr:`Scope.structure`
says why): the method hands the reviewer the change map at the directory level, and it reads what it chooses.

* THE RANGE is ``<base>..<head>`` where *base* is the merge base with the integration branch -- a merge of
  ``integrate/main`` moves the merge base with it, so the branch's own change is what is read -- or, when an
  earlier head of the same PR was reviewed and no merge of the integration branch came after it, that head:
  a push is reviewed for what it added (:func:`own_base`).
* GENERATED files are not read: the family's whole-file renders (:data:`dev_lab.dev.famfiles.GENERATED`) and
  the globs the repo declares (``derived``). Their generator is reviewed, not its output.
* CODE ONLY (user ruling 2026-10-29): a review reads what executes -- source, tests, scripts, and the build and
  workflow config that runs -- never prose or data. :data:`CODE` and :data:`NOT_CODE` are that one classification
  (a repo overrides either: ``code``, ``not_code``); the caps and slices count code bytes only, and the comment
  says how many changed files were outside (:attr:`Scope.outside`). A 33-branch merge was held at 127 MB that
  was almost all memory, attic, docs and logs.
* A RENAME costs its own patch, not the file twice (D85): sized from one ``git diff -M`` (:func:`_diff`), a pure
  move costs its header and is listed (:attr:`Scope.moved`); the reviewer still reads its ``rename from/to``.
* A LENS per slice: ``strict`` for the paths that refuse or declare (``strict`` globs), ``light`` for prose
  (``light`` globs), ``standard`` for the rest. A slice holds one lens, so the command is told which.
"""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

from dev_lab.dev.famfiles import GENERATED
from dev_lab.dev.forgepulls import Marker, marker
from dev_lab.dev.forgereview_findings import merge_outputs
from dev_lab.dev.principles import payload

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

__all__ = [
    'CODE',
    'DISPOSED_FIELD',
    'FINDINGS_FIELD',
    'LENSES',
    'NOT_CODE',
    'ONLY_GENERATED',
    'PRINCIPLES_FIELD',
    'SUMMARY_FIELD',
    'WHOLE',
    'Budget',
    'Scope',
    'Slice',
    'gather',
    'git',
    'is_code',
    'landed_base',
    'lens_of',
    'own_base',
    'plan',
    'reviewable',
    'reviewed_heads',
]  # fmt: skip

#: The lens of the ONE slice an oversize head is reviewed as: no paths, so the method maps the whole range at the
#: directory level and the reviewer reads what it chooses (D123, user ruling 2026-10-31).
WHOLE: Final = 'standard'

#: What a head whose change is only generated files is posted as (``success``): nothing a reviewer reads.
ONLY_GENERATED: Final = 'nothing to review: every changed file is generated or not code'

#: What executes, by glob: a changed file is reviewed only if it matches one and no :data:`NOT_CODE` glob.
CODE: Final = (
    '**/*.py', '**/*.pyi', '**/*.rs', '**/*.js', '**/*.mjs', '**/*.cjs', '**/*.ts', '**/*.tsx', '**/*.sh',
    '**/*.ps1', '**/*.bat', '**/*.cmd', '**/*.c', '**/*.h', '**/*.cpp', '**/*.hpp', '**/*.toml', '**/*.yml',
    '**/*.yaml', '**/*.cfg', '**/*.ini', '**/Makefile', '**/Dockerfile', '**/justfile',
)  # fmt: skip

#: Never code though its extension says so: agent memory, archived code, and golden reference data (a motronics
#: golden is a TOML of measured values, 15 MB each). Each glob is narrow -- a hook under ``.claude/``, a ``logs``
#: package or a ``golden_*.py`` module executes and is read.
NOT_CODE: Final = ('**/.claude/memory/**', 'attic/**', '**/golden*.toml')

#: In the ``synthesis`` command: replaced by the merged slice findings' path.
FINDINGS_FIELD: Final = '{findings}'

#: Replaced by the path of a JSON file holding :func:`dev_lab.dev.principles.payload`, written under the run's
#: scratch: the method judges against the family's principles and owns no copy of them.
PRINCIPLES_FIELD: Final = '{principles}'

#: An argument exactly this expands, per call, into the engine's summary flags: ``--pr-body <file of the PR body>``
#: for the ONE designated call (the first slice), ``--no-summary`` for every other slice and the synthesis -- so the
#: summary is produced once per head (user ruling D83).
SUMMARY_FIELD: Final = '{summary}'

#: Replaced by the path of a JSON file ``{"disposed": [{"id", "reason"}]}``: the findings disposed earlier (the
#: forge's own dispositions only; an author's trailer never reaches the engine), which the engine drops and lists.
DISPOSED_FIELD: Final = '{disposed}'

#: The lenses, strictest first: a slice is reviewed under exactly one.
LENSES: Final = ('strict', 'standard', 'light')

_GIT_TIMEOUT_S: Final = 120

#: ``git diff -M``'s similarity threshold: a delete and an add this alike are one move, sized by its hunks. The
#: call passes ``-l0``: past git's default rename limit (1000) inexact detection is SKIPPED with a warning, and
#: the motronics 33-branch merge (1504 adds) read 318 edited moves as deletes plus adds.
_SIMILAR: Final = '50%'
_NUL: Final = chr(0)


@dataclass(frozen=True)
class Slice:
    """One reviewer's share: paths under one lens, and their diff size in bytes."""

    lens: str
    paths: tuple[str, ...]
    size: int


@dataclass(frozen=True)
class Scope:
    """What a head's review reads: the range and its slices; past the bounds, why it is one structure-level review."""

    range: str
    slices: tuple[Slice, ...] = ()
    structure: str | None = None  # why the head is ONE whole-range review (:data:`WHOLE`), or None
    outside: int = 0  # changed files that are not code: counted, never read
    moved: tuple[str, ...] = ()  # pure moves (new paths): read for their path change, cost ~0


def git(root: Path, *args: str, ok: Iterable[int] = (0,)) -> tuple[int, str]:
    """``git *args`` in *root*: its exit code (one of *ok*) and stdout; :class:`OSError` naming any other."""
    done = _door.run(
        ['git', *args], cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=_GIT_TIMEOUT_S, check=False,
    )  # fmt: skip
    if done.returncode not in tuple(ok):
        msg = f'git {" ".join(args)} failed: {done.stderr.strip()[:300]}'
        raise OSError(msg)
    return done.returncode, done.stdout


def _ancestor(root: Path, older: str, newer: str) -> bool:
    return git(root, 'merge-base', '--is-ancestor', older, newer, ok=(0, 1))[0] == 0


def own_base(root: Path, target: str, head: str, reviewed: Sequence[str]) -> str:
    """Where *head*'s review starts: the newest *reviewed* head it descends from with no later integration merge.

    *reviewed* is oldest first. Without such a head, the merge base with *target*.
    """
    base = git(root, 'merge-base', target, head)[1].strip()
    for earlier in reversed(reviewed):
        if earlier != head and _ancestor(root, base, earlier) and _ancestor(root, earlier, head):
            return earlier
    return base


def _whole(parts: Sequence[str], pattern: Sequence[str]) -> bool:
    """Whether *parts* match *pattern* segment by segment: ``**`` spans any number of segments."""
    if not pattern:
        return not parts
    if pattern[0] == '**':
        return any(_whole(parts[i:], pattern[1:]) for i in range(len(parts) + 1))
    return bool(parts) and fnmatchcase(parts[0], pattern[0]) and _whole(parts[1:], pattern[1:])


def _matches(path: str, globs: Iterable[str]) -> bool:
    """Whole-path glob match (``PurePath.full_match`` semantics, which needs 3.13; this repo declares 3.12)."""
    parts = path.split('/')
    return any(_whole(parts, glob.split('/')) for glob in globs)


def reviewable(path: str, derived: Iterable[str]) -> bool:
    """Whether *path* is read: not a family render, not a declared *derived* glob."""
    return path not in GENERATED and not _matches(path, derived)


def is_code(path: str, code: Iterable[str], not_code: Iterable[str]) -> bool:
    """Whether *path* executes: it matches a *code* glob and no *not_code* one."""
    return _matches(path, code) and not _matches(path, not_code)


def lens_of(path: str, strict: Iterable[str], light: Iterable[str]) -> str:
    """The lens *path* earns: ``strict`` first, then ``light``, else ``standard``."""
    if _matches(path, strict):
        return 'strict'
    return 'light' if _matches(path, light) else 'standard'


def _diff(root: Path, reviewed: str) -> tuple[dict[str, int], dict[str, str], tuple[str, ...]]:
    """``({path: bytes of its diff}, {old: new}, pure moves)`` over *reviewed*, from ONE ``git diff -M`` call.

    A rename is sized by its own patch -- the ``rename from/to`` header and the hunks it changed -- under its new
    path, and its old path costs 0 (it stays, so the slice holding the move reads it as one): a 33-branch merge with
    859 moves read as deletes plus adds measured 30 MB of code. A pure move (``R100``) is listed in the third item.
    """
    text = git(root, 'diff', f'-M{_SIMILAR}', '-l0', '-z', '--patch-with-raw', reviewed)[1]
    raw, _, patch = text.partition(_NUL * 2)
    fields = raw.split(_NUL)
    entries: list[tuple[str, ...]] = []
    at = 0
    while at < len(fields) and fields[at].startswith(':'):
        status = fields[at].split()[-1]
        span = 3 if status[0] in 'RC' else 2
        entries.append((status, *fields[at + 1 : at + span]))
        at += span
    names = [entry[-1] for entry in entries]
    chunks = [chunk for chunk in patch.split('diff --git ') if chunk]
    if len(chunks) == len(names):
        sizes = {name: len(chunk.encode()) for name, chunk in zip(names, chunks, strict=True)}
    else:  # unsplittable: share it out
        sizes = dict.fromkeys(names, len(patch.encode()) // max(len(names), 1))
    moves = {entry[1]: entry[2] for entry in entries if entry[0].startswith('R')}
    sizes |= dict.fromkeys(set(moves) - set(sizes), 0)
    pure = tuple(sorted(entry[2] for entry in entries if entry[0] == 'R100'))
    return sizes, moves, pure


def _group(path: str) -> str:
    return '/'.join(PurePosixPath(path).parts[:-1][:2]) or '.'


def _pack(lens: str, sizes: dict[str, int], budget: int, moves: Mapping[str, str]) -> list[Slice]:
    """*sizes*' paths in slices of at most *budget* bytes, a directory kept whole when it fits.

    A move's two paths (*moves*, ``{old: new}``) are one unit filed under the new path's directory: a slice
    holding only the old path reads a deletion the range never made.
    """
    paired = {old: new for old, new in moves.items() if old in sizes and new in sizes}
    groups: dict[str, list[tuple[str, ...]]] = {}
    for path in sorted(set(sizes) - set(paired)):
        unit = (path, *sorted(old for old, new in paired.items() if new == path))
        groups.setdefault(_group(path), []).append(unit)
    out: list[Slice] = []
    paths: list[str] = []
    size = 0
    for members in groups.values():
        cost = sum(sizes[path] for unit in members for path in unit)
        pieces = [[path for unit in members for path in unit]] if cost <= budget else [list(unit) for unit in members]
        for piece in pieces:
            piece_size = sum(sizes[path] for path in piece)
            if paths and size + piece_size > budget:
                out.append(Slice(lens, tuple(paths), size))
                paths, size = [], 0
            paths.extend(piece)
            size += piece_size
    if paths:
        out.append(Slice(lens, tuple(paths), size))
    return out


@dataclass(frozen=True)
class Budget:
    """The declared bounds and globs a scope is cut by (``[tool.dev_lab.review]``)."""

    slice_bytes: int
    total_bytes: int
    derived: tuple[str, ...] = ()
    strict: tuple[str, ...] = ()
    light: tuple[str, ...] = ()
    code: tuple[str, ...] = CODE
    not_code: tuple[str, ...] = NOT_CODE


def plan(
    root: Path,
    target: str,
    head: str,
    budget: Budget,
    reviewed: Sequence[str] = (),
    *,
    sliceable: bool = True,
) -> Scope:
    """The :class:`Scope` of *head*'s review against *target*, cut by *budget*.

    Past the bounds -- the total, one file over a slice, or several slices for a command that cannot be told a
    slice's paths (not *sliceable*) -- the head is ONE structure-level review of the whole range (:data:`WHOLE`).
    """
    reviewed_range = f'{own_base(root, target, head, reviewed)}..{head}'
    every, moves, pure = _diff(root, reviewed_range)
    read = {path: n for path, n in every.items() if reviewable(path, budget.derived)}
    sizes = {path: n for path, n in read.items() if is_code(path, budget.code, budget.not_code)}
    outside = len(read) - len(sizes)
    total = sum(sizes.values())
    moved = tuple(path for path in pure if path in sizes)
    by_lens: dict[str, dict[str, int]] = {}
    for path, n in sizes.items():
        by_lens.setdefault(lens_of(path, budget.strict, budget.light), {})[path] = n
    slices = [
        one for lens in LENSES if lens in by_lens for one in _pack(lens, by_lens[lens], budget.slice_bytes, moves)
    ]
    huge = sorted(path for path, n in sizes.items() if n > budget.slice_bytes)
    if total > budget.total_bytes:
        why = f'{total} reviewable code bytes > max_total_bytes={budget.total_bytes}'
    elif huge:
        why = f'{huge[0]} alone is over max_diff_bytes={budget.slice_bytes}'
    elif len(slices) > 1 and not sliceable:
        why = f'{len(slices)} slices, and the command takes no paths'
    else:
        return Scope(reviewed_range, tuple(slices), outside=outside, moved=moved)
    whole = Slice(WHOLE, (), total)
    return Scope(reviewed_range, (whole,), outside=outside, moved=moved, structure=why)


_REVIEWED: Final = re.compile(re.escape(marker(Marker.REVIEW, 'SHA')).replace('SHA', '(?P<sha>[0-9a-f]{7,40})'))


def reviewed_heads(bodies: Iterable[str]) -> tuple[str, ...]:
    """The heads the PR comment *bodies* (oldest first) record a review of, oldest first."""
    return tuple(found['sha'] for body in bodies if (found := _REVIEWED.search(body)))


def gather(
    reviewed: str, argvs: Sequence[Sequence[str]], synthesis: Sequence[str], run: Callable[..., str], root: Path, *,
    pr_body: str, disposed: Mapping[str, str],
) -> str:  # fmt: skip
    """The slices' outputs merged over *reviewed*; with several, the *synthesis* command's reading of them merged in.

    *synthesis* (empty: none) names the merged document's path as :data:`FINDINGS_FIELD`; every command names
    the principles file as :data:`PRINCIPLES_FIELD` and the *disposed* file as :data:`DISPOSED_FIELD`; the first
    slice alone is handed *pr_body* through :data:`SUMMARY_FIELD`, every other call ``--no-summary``.
    """
    with tempfile.TemporaryDirectory() as scratch:
        given = Path(scratch) / 'principles.json'
        given.write_text(json.dumps(payload()), encoding='utf-8')
        body = Path(scratch) / 'pr-body.md'
        body.write_text(pr_body, encoding='utf-8')
        gone = Path(scratch) / 'disposed.json'
        rows = [{'id': fid, 'reason': why} for fid, why in disposed.items()]
        gone.write_text(json.dumps({'disposed': rows}, ensure_ascii=False), encoding='utf-8')

        def filled(argv: Sequence[str], *, summarizes: bool = False) -> list[str]:
            flags = ['--pr-body', str(body)] if summarizes else ['--no-summary']
            return [
                one
                for arg in argv
                for one in (flags if arg == SUMMARY_FIELD else [arg.replace(PRINCIPLES_FIELD, str(given))
                                                                .replace(DISPOSED_FIELD, str(gone))])
            ]  # fmt: skip

        merged = merge_outputs([run(filled(argv, summarizes=not at), root) for at, argv in enumerate(argvs)], reviewed)
        if not synthesis or len(argvs) == 1:
            return merged
        path = Path(scratch) / 'findings.json'
        path.write_text(merged, encoding='utf-8')
        argv = [arg.replace(FINDINGS_FIELD, str(path)) for arg in filled(synthesis)]
        return merge_outputs([merged, run(argv, root)], reviewed)


def landed_base(root: Path, base: str, head: str) -> str:
    """What *head*'s own change is measured from: integration for an unmerged head, else what it landed on.

    A merged PR's head is an ancestor of integration, so the merge base would read nothing: its change is measured
    from the first parent of the merge that landed it; a commit integration took directly, from its own parent.
    """
    landed = f'origin/{base}'
    code, _ = git(root, 'merge-base', '--is-ancestor', head, landed, ok=(0, 1))
    if code:
        return landed
    merges = git(root, 'log', '--first-parent', '--merges', '--format=%H %P', landed)[1]
    for row in merges.splitlines():
        merge, _first, *merged = row.split()
        if head in merged:
            return f'{merge}^1'
    return f'{head}^'
