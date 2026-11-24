"""LOSSLESS-DELETE's one judgement: whether deleting an origin branch at a given sha loses nothing.

Two callers ask it the same question. The door, ``branchprune delete`` (:func:`dev_lab.dev.branchdelete.delete`),
asks before it pushes a delete, of the tip its fresh fetch reads; the pre-push row ``lossless-delete``
(:mod:`dev_lab.dev.pushdelete`) asks of EVERY delete a push carries, of the sha git's own ref line names as the
remote's -- so a delete spelled any way (a ``$refs`` variable, ``xargs``, a script) meets the same judgement, and the
door's own push passes it with no exemption. Split from :mod:`dev_lab.dev.branchdelete` (2026-11-17), whose
docstring states the ruling: a branch goes only when every commit on it is on integration or on another live origin
branch or open PR head, or, by CONTENT, when no file its own commits wrote differs from integration, generated files
aside. A branch deleted in the same push holds nothing (*gone*), and a tag never holds anything (user ruling D22,
2026-11-17: "no tags -- merge or delete, never an archive tag").

A DERIVED branch (decision D23) is lossless whatever it carries: a machine branch whose whole content its producer
regenerates -- ``pr/components-bump``, one gitlink commit read off the integration tip and the component heads -- is
declared in ``[tool.dev_lab.integrator] derived`` with the producer that regenerates it
(:class:`~dev_lab.dev.lanepolicy.Derived`). Declared, never a branch name in code: an undeclared branch that merely
looks machine-made is judged like any other, and holds nothing for another branch either, since it may go any time.

A USER'S ORDER TO DROP A BRANCH is the one delete this judgement does not decide (2026-11-24: a branch carrying a
private pre-GitHub history -- a second root -- that no merge may publish). ``branchprune discard <branch> --approved
"<the user's words>"`` (:func:`dev_lab.dev.branchdelete.discard`) writes a :func:`grant` for that branch at that sha in
the clone's git dir, pushes, and spends it; the pre-push row passes a lossy delete only when a grant names exactly its
branch and sha (:func:`granted`). A verdict names the roots the branch's own commits carry (:attr:`Verdict.roots`), so
a refusal of a second root can name that door.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Collection, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from dev_lab.dev.checkout import git_out
from dev_lab.dev.famfiles import GENERATED
from dev_lab.dev.lanepolicy import Policy

__all__ = ['LOSSY', 'ORIGIN', 'PROTECTED', 'Verdict', 'grant', 'granted', 'judge', 'unlanded']

#: Where the fetched origin branches live.
ORIGIN: Final = 'refs/remotes/origin/'
#: Its refusals, each said once, here.
LOSSY: Final = '{branch}: refused -- {count} commit(s) exist on it alone ({commits}), with unlanded content in: {files}'
PROTECTED: Final = '{branch}: refused -- it is {why}, never deleted'
_UNFETCHED: Final = '{branch}: refused -- {sha} is not a commit this clone holds, so what it carries is unknown'
_FIRST: Final = 5


@dataclass(frozen=True)
class Verdict:
    """What LOSSLESS-DELETE judged of one branch: its tip, the container holding it, or why it is kept."""

    branch: str
    sha: str = ''
    container: str = ''
    lost: tuple[str, ...] = ()
    refused: str = ''
    roots: tuple[str, ...] = ()


def judge(
    root: Path, policy: Policy, branch: str, sha: str, *, open_heads: dict[str, int], gone: Collection[str] = ()
) -> Verdict:
    """Whether deleting origin's *branch* at *sha* loses nothing; read from the fetched remote-tracking refs.

    Lossless when *policy* declares *branch* derived; else when every commit on it is on integration, or on another
    live origin branch or open PR head -- never one of the branches *gone* with it, nor a derived one -- else, by
    content, when no file its own commits wrote differs from integration (:func:`unlanded`). FAILS CLOSED: a *sha*
    this clone does not hold is refused, never judged empty.
    """
    if why := _protected(policy, branch, open_heads):
        return Verdict(branch, refused=PROTECTED.format(branch=branch, why=why))
    producers = {row.branch: row.producer for row in policy.derived}
    if branch in producers:
        return Verdict(branch, sha, container=f'its producer {producers[branch]} (derived: regenerated, never lost)')
    if not sha or git_out(root, 'cat-file', '-e', f'{sha}^{{commit}}') is None:
        why = _UNFETCHED.format(branch=branch, sha=sha[:12]) if sha else f'{branch}: not on origin (gone already)'
        return Verdict(branch, sha, refused=why)
    listed = (git_out(root, 'for-each-ref', '--format=%(refname)', ORIGIN) or '').split()
    skipped = {branch, 'HEAD', *gone, *producers}
    others = [name for name in (ref.removeprefix(ORIGIN) for ref in listed) if name not in skipped]
    others.sort(key=lambda name: (name != policy.integration, name not in open_heads, name))
    for name in others:
        if git_out(root, 'merge-base', '--is-ancestor', sha, f'{ORIGIN}{name}') is not None:
            label = f'open PR #{open_heads[name]} ({name})' if name in open_heads else name
            return Verdict(branch, sha, container=label)
    lost = (git_out(root, 'rev-list', sha, '--not', *(f'{ORIGIN}{name}' for name in others)) or '').split()
    files = unlanded(root, sha, others, policy.integration, exempt=GENERATED) if lost else ()
    if not files:
        by_content = f'{policy.integration} (by content: no content {policy.integration} lacks)'
        return Verdict(branch, sha, container=by_content if lost else 'the union of the other origin branches')
    shown = ', '.join(one[:12] for one in lost[:_FIRST]) + (' ...' if len(lost) > _FIRST else '')
    refused = LOSSY.format(branch=branch, count=len(lost), commits=shown, files=', '.join(files))
    others_refs = (f'{ORIGIN}{name}' for name in others)
    roots = (git_out(root, 'rev-list', '--max-parents=0', sha, '--not', *others_refs) or '').split()
    return Verdict(branch, sha, lost=tuple(lost), refused=refused, roots=tuple(roots))


def _grant_path(root: Path, branch: str) -> Path:
    common = (git_out(root, 'rev-parse', '--path-format=absolute', '--git-common-dir') or '').strip()
    return Path(common) / 'dev_lab' / 'discard' / f'{urllib.parse.quote(branch, safe="")}.grant'


@contextmanager
def grant(root: Path, branch: str, sha: str) -> Iterator[None]:
    """While open, the pre-push row passes the delete of *branch* at *sha* (:func:`granted`); spent on exit."""
    path = _grant_path(root, branch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sha, encoding='utf-8')
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def granted(root: Path, branch: str, sha: str) -> bool:
    """An open :func:`grant` names exactly *branch* at *sha*."""
    path = _grant_path(root, branch)
    return bool(sha) and path.is_file() and path.read_text(encoding='utf-8').strip() == sha


def _protected(policy: Policy, branch: str, open_heads: dict[str, int]) -> str:
    """What makes *branch* never deleted -- the integration branch, the trunk, an open PR head -- else ``''``."""
    if branch in {policy.integration, policy.trunk}:
        return 'the integration branch or the trunk'
    return f'the head of open PR #{open_heads[branch]}' if branch in open_heads else ''


def unlanded(
    root: Path, sha: str, others: Sequence[str], integration: str, *, exempt: frozenset[str]
) -> tuple[str, ...]:
    """The files its own commits wrote whose tree entry at *sha* is not *integration*'s; FAILS CLOSED.

    The commits on *sha* alone name the files they wrote: a plain commit every file it changes, a merge only the
    files it resolved (``--cc``: differing from every parent), so a sync merge of integration names none. Of those,
    the *exempt* ones are set aside: LOSSLESS-DELETE passes the family's generated files
    (:data:`~dev_lab.dev.famfiles.GENERATED`), regenerated rather than lost; the landed sweep passes none. Any other
    whose ``(mode, blob)`` at the tip differs from integration's -- added (even empty), changed, re-moded or deleted
    -- is unlanded. A file integration changed after the branch landed it is refused too: a branch-side edit and
    integration moving ahead are not told apart, because a false refusal is safe and a false delete is not. Paths
    travel NUL-separated (``-z``), never quoted, and git failing to answer refuses every candidate.
    """
    tip_only = [sha, '--not', *(f'{ORIGIN}{name}' for name in others)]
    written = git_out(root, 'log', '-z', '--format=', '--name-only', '--cc', *tip_only)
    if written is None:
        return ("(git could not list the branch's files)",)
    candidates = sorted({path.strip('\n') for path in written.split('\0')} - {''} - exempt)
    if not candidates:
        return ()
    entries = [_entries(root, rev, candidates) for rev in (f'{ORIGIN}{integration}', sha)]
    if entries[0] is None or entries[1] is None:
        return tuple(candidates)
    return tuple(path for path in candidates if entries[0].get(path) != entries[1].get(path))


def _entries(root: Path, rev: str, paths: Sequence[str]) -> dict[str, str] | None:
    """``{path: 'mode blob'}`` for *paths* in *rev*'s tree (absent ones omitted); ``None`` when git could not answer."""
    listed = git_out(root, 'ls-tree', '-z', '--full-tree', rev, '--', *paths)
    if listed is None:
        return None
    found: dict[str, str] = {}
    for record in filter(None, listed.split('\0')):
        meta, path = record.split('\t', 1)
        mode, _, blob = meta.split()
        found[path] = f'{mode} {blob}'
    return found
