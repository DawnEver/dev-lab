"""REVIEW-SCOPE: what one PR review reads, cut into slices a reviewer can hold, and how the slices merge.

The branch's own change since its merge base with integration, minus generated files; each slice under the lens
its paths earn.

A HEAD IS NEVER HELD, AND NEVER REVIEWED WITHOUT A DIFF (D123, user rulings 2026-10-31 and 2026-11-06). Every
slice names its paths, so every call is a diff review -- the one call mode the forge's headless run allows. The
budget bounds a SLICE (``max_diff_bytes``; one file over it is a slice of its own) and the TOTAL
(``max_total_bytes``): slices are taken strictest lens first (code that refuses or declares before the rest, prose
last), and what the total leaves out is LISTED (:attr:`Scope.unread`) in the review comment. There is no
whole-range "structure" review: its path-less slice was rendered by ai-lab as an ``agent`` call the headless run
mode refuses, so every reviewer reported ``unsupported`` and the head was never reviewed.

* THE RANGE is ``<base>..<head>``, *base* from ONE rule (:func:`review_base`): the merge base with the
  integration branch -- a merge of ``integrate/main`` moves the merge base with it, so the branch's own change is
  what is read -- unless the PR CONTINUES a landed one (LANDED-BRANCH-CONTINUES, :mod:`dev_lab.dev.branchreview`):
  then the LAST LANDED HEAD, when it is newer, so the continuation's review reads only the increment pushed after
  its predecessor merged, whatever the merge method (a squash leaves the landed head off integration). A change
  that touches previously reviewed code is in scope: scope is what the diff touches.
* GENERATED files are not read: the family's whole-file renders (:data:`dev_lab.dev.famfiles.GENERATED`) and
  the globs the repo declares (``derived``). Their generator is reviewed, not its output.
* CODE ONLY (user ruling 2026-10-29): a review reads what executes -- source, tests, scripts, and the build and
  workflow config that runs -- never prose or data. :func:`dev_lab.dev.reviewcode.is_code` is that one classification
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
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

from dev_lab.dev.blobfetch import fetch_blobs, git, is_partial
from dev_lab.dev.famfiles import GENERATED
from dev_lab.dev.forgereview_command import ReviewPending
from dev_lab.dev.forgereview_findings import merge_outputs
from dev_lab.dev.principles import payload
from dev_lab.dev.reviewcode import CODE, NOT_CODE, is_code, matches
from dev_lab.dev.writeroots import TEMP_PREFIX

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

__all__ = [
    'DISPOSED_FIELD',
    'FINDINGS_FIELD',
    'LENSES',
    'PRINCIPLES_FIELD',
    'SUMMARY_FIELD',
    'Budget',
    'Scope',
    'Slice',
    'code_bytes',
    'gather',
    'git',
    'landed_base',
    'lens_of',
    'plan',
    'prefetch',
    'review_base',
    'reviewable',
]  # fmt: skip

#: In the ``synthesis`` command: replaced by the merged slice findings' path.
FINDINGS_FIELD: Final = '{findings}'

#: Replaced by the path of a JSON file holding :func:`dev_lab.dev.principles.payload`, written under the run's
#: scratch: the method judges against the family's principles and owns no copy of them.
PRINCIPLES_FIELD: Final = '{principles}'

#: An argument exactly this expands, per call, into the engine's summary flags: ``--pr-body <file of the PR body>``
#: for the ONE designated call (the first slice), ``--no-summary`` for every other slice and the synthesis -- so the
#: summary is produced once per head (user ruling D83).
SUMMARY_FIELD: Final = '{summary}'

#: Replaced by the path of a JSON file ``{"disposed": [{"id", "reason"}]}``: findings the engine drops and lists
#: as disposed earlier: a continuation's carried findings already resolved or deferred, else an empty list.
DISPOSED_FIELD: Final = '{disposed}'

#: The lenses, strictest first: a slice is reviewed under exactly one.
LENSES: Final = ('strict', 'standard', 'light')

#: ``git diff -M``'s similarity threshold: a delete and an add this alike are one move, sized by its hunks. The
#: call passes ``-l0``: past git's default rename limit (1000) inexact detection is SKIPPED with a warning, and
#: a consumer repo's 33-branch merge (1504 adds) read 318 edited moves as deletes plus adds.
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
    """What a head's review reads: the range, its slices, and the code paths the total budget left unread."""

    range: str
    slices: tuple[Slice, ...] = ()
    unread: tuple[str, ...] = ()  # code paths past ``max_total_bytes``: listed in the comment, never read
    outside: int = 0  # changed files that are not code: counted, never read
    moved: tuple[str, ...] = ()  # pure moves (new paths): read for their path change, cost ~0


#: Blob modes a ``--raw`` line carries for file content (regular, executable, symlink); a gitlink is a commit.
_BLOB_MODES: Final = frozenset({'100644', '100755', '120000'})
_NO_OBJECT: Final = re.compile(r'0+')


def prefetch(root: Path, *ranges: str) -> int:
    """Fetch every blob *ranges* change into a partial clone, in one request per chunk; how many were asked for.

    The reviewer reads the range with git and holds no forge token (:mod:`dev_lab.dev.reviewgitauth`): in a
    blobless checkout -- the Gitea review job's -- its ``git diff`` would fetch each blob lazily and fail
    unauthenticated (a consumer repo, 2026-11-01). The door holds the header, so it asks first. ``--raw`` compares
    trees only and fetches nothing. A clone that is not partial (no ``remote.origin.promisor``) asks for nothing.
    """
    if not is_partial(root):
        return 0
    wanted: set[str] = set()
    for range_ in ranges:
        raw = git(root, 'diff', '--raw', '--no-renames', '--abbrev=40', '-z', '--end-of-options', range_)[1]
        for meta in raw.split('\0')[::2]:
            if not meta.startswith(':'):
                continue
            old_mode, new_mode, old, new, *_ = meta[1:].split()
            wanted |= {oid for mode, oid in ((old_mode, old), (new_mode, new))
                       if mode in _BLOB_MODES and not _NO_OBJECT.fullmatch(oid)}  # fmt: skip
    return fetch_blobs(root, wanted)


def reviewable(path: str, derived: Iterable[str]) -> bool:
    """Whether *path* is read: not a family render, not a declared *derived* glob."""
    return path not in GENERATED and not matches(path, derived)


def lens_of(path: str, strict: Iterable[str], light: Iterable[str]) -> str:
    """The lens *path* earns: ``strict`` first, then ``light``, else ``standard``."""
    if matches(path, strict):
        return 'strict'
    return 'light' if matches(path, light) else 'standard'


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


def _ancestor(root: Path, older: str, newer: str) -> bool:
    return not git(root, 'merge-base', '--is-ancestor', older, newer, ok=(0, 1))[0]


def review_base(root: Path, target: str, head: str, since: str = '') -> str:
    """What *head*'s review reads from: its merge base with *target*, else *since* (the module docstring).

    *since* -- a continuation's last landed head -- is taken when it is an ancestor of *head* and newer than the
    merge base; a landed head the branch no longer descends from (a rewritten branch) is not.
    """
    base = git(root, 'merge-base', target, head)[1].strip()
    if since and since != base and _ancestor(root, since, head) and _ancestor(root, base, since):
        return since
    return base


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
    *,
    sliceable: bool = True,
    since: str = '',
) -> Scope:
    """The :class:`Scope` of *head*'s review against *target*, cut by *budget* (the module docstring).

    A command that cannot be told a slice's paths (not *sliceable*) is run once, its slice naming every path.
    *since* is a continuation's last landed head (:func:`review_base`).
    """
    reviewed_range = f'{review_base(root, target, head, since)}..{head}'
    every, moves, pure = _diff(root, reviewed_range)
    sizes = _code(every, budget)
    outside = sum(reviewable(path, budget.derived) for path in every) - len(sizes)
    moved = tuple(path for path in pure if path in sizes)
    if not sliceable:
        whole = (Slice('standard', tuple(sorted(sizes)), sum(sizes.values())),) if sizes else ()
        return Scope(reviewed_range, whole, outside=outside, moved=moved)
    by_lens: dict[str, dict[str, int]] = {}
    for path, n in sizes.items():
        by_lens.setdefault(lens_of(path, budget.strict, budget.light), {})[path] = n
    slices = [
        one for lens in LENSES if lens in by_lens for one in _pack(lens, by_lens[lens], budget.slice_bytes, moves)
    ]
    kept: list[Slice] = []
    for one in slices:  # strictest lens first: the total leaves out the least risky code
        if kept and sum(s.size for s in kept) + one.size > budget.total_bytes:
            break
        kept.append(one)
    unread = tuple(path for one in slices[len(kept) :] for path in one.paths)
    return Scope(reviewed_range, tuple(kept), unread=unread, outside=outside, moved=moved)


def _code(every: Mapping[str, int], budget: Budget) -> dict[str, int]:
    """``{path: diff bytes}`` of the reviewable code in *every*: what a review reads and what its budget counts."""
    return {
        path: n
        for path, n in every.items()
        if reviewable(path, budget.derived) and is_code(path, budget.code, budget.not_code)
    }


def code_bytes(root: Path, target: str, head: str, budget: Budget, since: str = '') -> int:
    """The reviewable code bytes of *head*'s own change from :func:`review_base`: what a PR's growth is measured in."""
    base = review_base(root, target, head, since)
    return sum(_code(_diff(root, f'{base}..{head}')[0], budget).values())


def gather(
    reviewed: str, argvs: Sequence[Sequence[str]], synthesis: Sequence[str], run: Callable[..., str], root: Path, *,
    pr_body: str, disposed: Sequence[tuple[str, str]] = (),
) -> str:  # fmt: skip
    """The slices' outputs merged over *reviewed*; with several, the *synthesis* command's reading of them merged in.

    *synthesis* (empty: none) names the merged document's path as :data:`FINDINGS_FIELD`; every command names
    the principles file as :data:`PRINCIPLES_FIELD` and the *disposed* ``(id, reason)`` pairs -- a continuation's
    carried findings already resolved or deferred, none otherwise -- as :data:`DISPOSED_FIELD`; the first
    slice alone is handed *pr_body* through :data:`SUMMARY_FIELD`, every other call ``--no-summary``. A slice whose
    batch is still running (:class:`~dev_lab.dev.forgereview_command.ReviewPending`) does not stop the slices after
    it: each submits its own, and the first pending is raised once all have run.
    """
    with tempfile.TemporaryDirectory(prefix=TEMP_PREFIX) as scratch:
        given = Path(scratch) / 'principles.json'
        given.write_text(json.dumps(payload()), encoding='utf-8')
        body = Path(scratch) / 'pr-body.md'
        body.write_text(pr_body, encoding='utf-8')
        gone = Path(scratch) / 'disposed.json'
        rows = [{'id': key, 'reason': why} for key, why in disposed]
        gone.write_text(json.dumps({'disposed': rows}), encoding='utf-8')

        def filled(argv: Sequence[str], *, summarizes: bool = False) -> list[str]:
            flags = ['--pr-body', str(body)] if summarizes else ['--no-summary']
            return [
                one
                for arg in argv
                for one in (flags if arg == SUMMARY_FIELD else [arg.replace(PRINCIPLES_FIELD, str(given))
                                                                .replace(DISPOSED_FIELD, str(gone))])
            ]  # fmt: skip

        outputs, waiting = [], None
        for at, argv in enumerate(argvs):
            try:
                outputs.append(run(filled(argv, summarizes=not at), root))
            except ReviewPending as pending:  # the slices after it still submit theirs: one wait settles all
                waiting = waiting or pending
        if waiting is not None:
            raise waiting
        merged = merge_outputs(outputs, reviewed)
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
