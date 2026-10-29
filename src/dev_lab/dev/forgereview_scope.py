"""REVIEW-SCOPE: what one PR review reads, cut into slices a reviewer can hold, and how the slices merge.

The branch's own change, minus generated files, since the last reviewed head; each slice under the lens its
paths earn.

THE CAP USED TO DECIDE WHETHER A HEAD WAS REVIEWED AT ALL, and a byte count of the whole diff answered the
wrong question: most of a large downstream diff was a lock file, a rendered allow block or a merge of
``integrate/main``, and the heads that most needed a review were the ones that got none. The budget is the
reviewer's, so it bounds a SLICE (``max_diff_bytes``); the head is held for a session only past the TOTAL
(``max_total_bytes``), or when one file alone outgrows a slice.

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
* A LENS per slice: ``strict`` for the paths that refuse or declare (``strict`` globs), ``light`` for prose
  (``light`` globs), ``standard`` for the rest. A slice holds one lens, so the command is told which.
"""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
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
    'CODE', 'FINDINGS_FIELD', 'LENSES', 'NOT_CODE', 'ONLY_GENERATED', 'OVER_CAP_TAKEOVER', 'PRINCIPLES_FIELD', 'Budget',
    'Scope', 'Slice',
    'gather', 'is_code', 'lens_of', 'own_base', 'plan', 'reviewable', 'reviewed_heads',
]  # fmt: skip

#: The review description of a held head (its :data:`~dev_lab.dev.platformparts.HOLD_CONTEXT` says the same): a
#: TAKEOVER, like a review whose reviewers were all exhausted. The integrator session reviews it through the same
#: method over every slice -- a session is never metered, so the cap that bounds a program review does not bind it
#: -- and its door posts the findings and releases the hold (:mod:`dev_lab.dev.forgetakeover`).
OVER_CAP_TAKEOVER: Final = 'over the cap: integrator takeover -- forge review takeover <sha> reviews it and releases'

#: What a head whose change is only generated files is posted as (``success``): nothing a reviewer reads.
ONLY_GENERATED: Final = 'nothing to review: every changed file is generated or not code'

#: What executes, by glob: a changed file is reviewed only if it matches one and no :data:`NOT_CODE` glob.
CODE: Final = (
    '**/*.py', '**/*.pyi', '**/*.rs', '**/*.js', '**/*.mjs', '**/*.cjs', '**/*.ts', '**/*.tsx', '**/*.sh',
    '**/*.ps1', '**/*.bat', '**/*.cmd', '**/*.c', '**/*.h', '**/*.cpp', '**/*.hpp', '**/*.toml', '**/*.yml',
    '**/*.yaml', '**/*.cfg', '**/*.ini', '**/Makefile', '**/Dockerfile', '**/justfile',
)  # fmt: skip

#: Never code whatever its extension: agent memory and rules, archived code, rendered docs, logs, lock files, and
#: golden reference data (a motronics golden is a TOML of measured values, 15 MB each).
NOT_CODE: Final = ('**/.claude/**', 'attic/**', 'docs-src/**', '**/logs/**', '**/*.lock', '**/*.log', '**/golden*')

#: In the ``synthesis`` command: replaced by the merged slice findings' path.
FINDINGS_FIELD: Final = '{findings}'

#: Replaced by the path of a JSON file holding :func:`dev_lab.dev.principles.payload`, written under the run's
#: scratch: the method judges against the family's principles and owns no copy of them.
PRINCIPLES_FIELD: Final = '{principles}'

#: The lenses, strictest first: a slice is reviewed under exactly one.
LENSES: Final = ('strict', 'standard', 'light')

_GIT_TIMEOUT_S: Final = 120


@dataclass(frozen=True)
class Slice:
    """One reviewer's share: paths under one lens, and their diff size in bytes."""

    lens: str
    paths: tuple[str, ...]
    size: int


@dataclass(frozen=True)
class Scope:
    """What a head's review reads: the range, its slices, and -- when it cannot be read -- why it is held."""

    range: str
    slices: tuple[Slice, ...] = ()
    held: str | None = None
    outside: int = 0  # changed files that are not code: counted, never read


def _git(root: Path, *args: str, ok: Iterable[int] = (0,)) -> tuple[int, str]:
    done = _door.run(
        ['git', *args], cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=_GIT_TIMEOUT_S, check=False,
    )  # fmt: skip
    if done.returncode not in tuple(ok):
        msg = f'git {" ".join(args)} failed: {done.stderr.strip()[:300]}'
        raise OSError(msg)
    return done.returncode, done.stdout


def _ancestor(root: Path, older: str, newer: str) -> bool:
    return _git(root, 'merge-base', '--is-ancestor', older, newer, ok=(0, 1))[0] == 0


def own_base(root: Path, target: str, head: str, reviewed: Sequence[str]) -> str:
    """Where *head*'s review starts: the newest *reviewed* head it descends from with no later integration merge.

    *reviewed* is oldest first. Without such a head, the merge base with *target*.
    """
    base = _git(root, 'merge-base', target, head)[1].strip()
    for earlier in reversed(reviewed):
        if earlier != head and _ancestor(root, base, earlier) and _ancestor(root, earlier, head):
            return earlier
    return base


def _matches(path: str, globs: Iterable[str]) -> bool:
    pure = PurePosixPath(path)
    return any(pure.full_match(glob) for glob in globs)


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


def _sizes(root: Path, reviewed: str) -> dict[str, int]:
    """``{path: bytes of its diff}`` over *reviewed*, renames read as a delete and an add."""
    names = [name for name in _git(root, 'diff', '--no-renames', '-z', '--name-only', reviewed)[1].split('\0') if name]
    text = _git(root, 'diff', '--no-renames', reviewed)[1]
    chunks = [chunk for chunk in text.split('\ndiff --git ') if chunk]
    if len(chunks) != len(names):
        return {name: len(text.encode()) // max(len(names), 1) for name in names}  # unsplittable: share it out
    return {name: len(chunk.encode()) for name, chunk in zip(names, chunks, strict=True)}


def _group(path: str) -> str:
    return '/'.join(PurePosixPath(path).parts[:-1][:2]) or '.'


def _moves(root: Path, reviewed: str) -> dict[str, str]:
    """``{old: new}`` for every rename git detects over *reviewed*."""
    fields = _git(root, 'diff', '-M', '-z', '--name-status', '--diff-filter=R', reviewed)[1].split('\0')
    return {fields[i + 1]: fields[i + 2] for i in range(0, len(fields) - 2, 3) if fields[i].startswith('R')}


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
    metered: bool = True,
) -> Scope:
    """The :class:`Scope` of *head*'s review against *target*, cut by *budget*.

    A command that cannot be told a slice's paths (not *sliceable*) reads the whole range: past one slice, held.
    Not *metered* (a session's takeover), the total cap and the one-file cap do not hold it: a file larger than a
    slice is a slice of its own, and the session reads every slice.
    """
    reviewed_range = f'{own_base(root, target, head, reviewed)}..{head}'
    read = {path: n for path, n in _sizes(root, reviewed_range).items() if reviewable(path, budget.derived)}
    sizes = {path: n for path, n in read.items() if is_code(path, budget.code, budget.not_code)}
    outside = len(read) - len(sizes)
    total = sum(sizes.values())
    if metered and total > budget.total_bytes:
        why = f'{total} reviewable code bytes > max_total_bytes={budget.total_bytes}'
        return Scope(reviewed_range, held=why, outside=outside)
    if metered and (huge := sorted(path for path, n in sizes.items() if n > budget.slice_bytes)):
        why = f'{huge[0]} alone is over max_diff_bytes={budget.slice_bytes}: derive it, or the integrator takes over'
        return Scope(reviewed_range, held=why, outside=outside)
    by_lens: dict[str, dict[str, int]] = {}
    for path, n in sizes.items():
        by_lens.setdefault(lens_of(path, budget.strict, budget.light), {})[path] = n
    moves = _moves(root, reviewed_range)
    slices = [
        one for lens in LENSES if lens in by_lens for one in _pack(lens, by_lens[lens], budget.slice_bytes, moves)
    ]
    if len(slices) > 1 and not sliceable:
        why = f'{len(slices)} slices, and the command takes no paths'
        return Scope(reviewed_range, held=why, outside=outside)
    return Scope(reviewed_range, tuple(slices), outside=outside)


_REVIEWED: Final = re.compile(re.escape(marker(Marker.REVIEW, 'SHA')).replace('SHA', '(?P<sha>[0-9a-f]{7,40})'))


def reviewed_heads(bodies: Iterable[str]) -> tuple[str, ...]:
    """The heads the PR comment *bodies* (oldest first) record a review of, oldest first."""
    return tuple(found['sha'] for body in bodies if (found := _REVIEWED.search(body)))


def gather(
    reviewed: str, argvs: Sequence[Sequence[str]], synthesis: Sequence[str], run: Callable[..., str], root: Path
) -> str:
    """The slices' outputs merged over *reviewed*; with several, the *synthesis* command's reading of them merged in.

    *synthesis* (empty: none) names the merged document's path as :data:`FINDINGS_FIELD`; every command names
    the principles file as :data:`PRINCIPLES_FIELD`.
    """
    with tempfile.TemporaryDirectory() as scratch:
        given = Path(scratch) / 'principles.json'
        given.write_text(json.dumps(payload()), encoding='utf-8')

        def filled(argv: Sequence[str]) -> list[str]:
            return [arg.replace(PRINCIPLES_FIELD, str(given)) for arg in argv]

        merged = merge_outputs([run(filled(argv), root) for argv in argvs], reviewed)
        if not synthesis or len(argvs) == 1:
            return merged
        path = Path(scratch) / 'findings.json'
        path.write_text(merged, encoding='utf-8')
        argv = [arg.replace(FINDINGS_FIELD, str(path)) for arg in filled(synthesis)]
        return merge_outputs([merged, run(argv, root)], reviewed)
