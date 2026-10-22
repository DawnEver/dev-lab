"""ONE-BRANCH-PER-SESSION at PUSH TIME: refuse a push that would put an UNDECLARED branch on origin.

WHY THIS EXISTS, AND WHY THE TESTS WERE NOT ENOUGH. The declared branch set has been read, censused
and asserted since 2026-10-04 -- and every one of those readings happens AFTER the push. MEASURED
2026-10-05/06: a session pushed SEVEN `work/*` lane branches to origin, and the guard that names
exactly that hazard was green the whole time because it had not run yet. A verdict that arrives after
the operation it judges is a report, not a guard, so this module runs where the decision is still
open: the ``pre-push`` hook, before git has sent anything.

THE REFSPEC ARRIVES ON STDIN, git's own ``pre-push`` protocol: ``<local ref> <local sha> <remote ref>
<remote sha>``, one line per ref (the family runner, :mod:`dev_lab.dev.githooks.runner`, pipes it
to every pre-push hook). A deletion is recognisable -- git writes the all-zero object name as the
local sha -- and is ALLOWED: cleaning up an undeclared branch is the remedy this guard`s own message
asks for. Only ``refs/heads/**`` lines are judged; a tag names a commit judged when its branch was
pushed. No line at all judges nothing and passes nothing silently: there is then nothing to push.

THERE IS NO BYPASS. No flag, no environment variable, no ``--force`` spelling relaxes the check.
The one documented way to push a new long-lived branch is to DECLARE it -- which is a reviewed edit
to ``pyproject.toml``, in the repo that argues for the branch, which is the whole point.

THE DECLARATION IS THE PUSHED COMMIT'S: each ref is judged by ``<sha>:pyproject.toml`` of the sha being
pushed to it, never by the pushing checkout's working tree (see :func:`refusal`).

Exit codes: ``0`` allowed, ``1`` REFUSED, ``2`` the guard could not judge (no readable branch set
at the pushed commit).
A ``2`` blocks the push exactly as a ``1`` does, because "I could not tell" is not "it is fine" --
the defect this module exists for was a guard that was not consulted, and a silent pass would rebuild
it one layer down.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lab_commons.log import emit

from dev_lab.dev.branchset import (
    BranchSet,
    BranchSetKeyRetired,
    BranchSetNotDeclared,
    KitOlderThanCheckout,
    branchset_at,
)

__all__ = [
    'ALLOWED',
    'COULD_NOT_JUDGE',
    'REFUSED',
    'PushedRef',
    'main',
    'pushed_refs',
    'refusal',
    'undeclared',
]

#: The verdicts, as exit codes. Named so a test asserts a WORD rather than a bare integer.
ALLOWED: Final = 0
REFUSED: Final = 1
COULD_NOT_JUDGE: Final = 2

#: The object name git writes for the LOCAL side of a ref that is being deleted.
_DELETED_SHA: Final = '0' * 40

#: How many fields git's pre-push protocol puts on a refspec line: local ref, local sha, remote ref,
#: remote sha. Named rather than written as a literal so a malformed line is skipped by STATEMENT.
_REFSPEC_FIELDS: Final = 4

#: The one ref namespace this guard judges. Everything else -- tags, ``refs/ci/**`` and the machine
#: refs -- names no branch and passes.
_BRANCHES: Final = 'refs/heads/'


@dataclass(frozen=True)
class PushedRef:
    """One ref a push would update, as the hook was told about it."""

    remote_ref: str
    deleted: bool = False
    #: The commit the push would put on *remote_ref* (the all-zero name for a deletion).
    local_sha: str = ''
    #: Whether the push CREATES *remote_ref* (the remote holds no commit for it yet).
    created: bool = False

    @property
    def branch(self) -> str | None:
        """The branch name when this ref is a branch, else ``None`` -- tags and machine refs pass."""
        return self.remote_ref[len(_BRANCHES) :] if self.remote_ref.startswith(_BRANCHES) else None


def _from_stdin(lines: Iterable[str]) -> Iterator[PushedRef]:
    """One :class:`PushedRef` per refspec line -- git's own pre-push protocol, four fields per line."""
    for line in lines:
        fields = line.split()
        if len(fields) != _REFSPEC_FIELDS:
            continue
        _local_ref, local_sha, remote_ref, remote_sha = fields
        yield PushedRef(
            remote_ref, deleted=local_sha == _DELETED_SHA, local_sha=local_sha, created=remote_sha == _DELETED_SHA
        )


def pushed_refs(lines: Iterable[str] = ()) -> tuple[PushedRef, ...]:
    """What this push would move: one entry per refspec line git wrote on stdin."""
    return tuple(_from_stdin(lines))


def undeclared(refs: Iterable[PushedRef], branchset: BranchSet) -> tuple[str, ...]:
    """The branches *refs* would create or update that *branchset* does not name, sorted.

    THE WHOLE RULE, as one expression, so a planted control drives THIS function rather than a
    restatement of it that would agree with it by construction. Deletions are not violations: the
    remedy this guard prints is "merge it, then delete it", and a guard that refused the deletion
    would refuse its own remedy.
    """
    found = {
        ref.branch for ref in refs if not ref.deleted and ref.branch is not None and not branchset.admits(ref.branch)
    }
    return tuple(sorted(name for name in found if name is not None))


def _refusal(rows: Sequence[str], branchset: BranchSet) -> str:
    """The refusal text -- and it names the remedy, because a refusal that does not is a wall."""
    names = ', '.join(rows)
    declared = ', '.join([*sorted(branchset.declared), *branchset.ephemeral])
    return (
        f'[branchset-push] REFUSED -- this push carries {names} onto refs/heads, which the declared '
        f'branch set does not name.\n'
        f'[branchset-push]   declared: {declared}\n'
        f'[branchset-push]   REMEDY: merge it through a pull request -- push the change as a short-lived branch '
        f'in a declared ephemeral namespace '
        f'([tool.lab_commons.branchset] ephemeral, e.g. pr/<topic>) and open a pull request into the '
        f'integration branch; a new LONG-LIVED branch is a reviewed edit of sessions in pyproject.toml.\n'
        f'[branchset-push]   There is no switch to bypass this. A branch nobody declared is a branch '
        f'nobody owns, and the census that finds them afterwards runs too late to stop the push.\n'
    )


def _unjudgeable(sha: str, exc: Exception) -> str:
    """Why the declaration commit *sha* carries cannot judge it -- naming the remedy for each kind."""
    if isinstance(exc, KitOlderThanCheckout):
        remedy = 'rebuild this venv from the lock of the checkout, then push again; the declaration is not the problem'
    elif isinstance(exc, BranchSetKeyRetired):
        remedy = (
            'delete the retired key(s) from pyproject.toml (merge the integration branch, which already has), '
            'commit, then push again'
        )
    else:
        remedy = (
            'commit [tool.lab_commons.branchset] with a trunk and a sessions list to pyproject.toml on the branch '
            'you push.\n[branchset-push]   It is REFUSED rather than passed: a guard that cannot judge is not a '
            'guard, and passing here would rebuild -- one layer down -- exactly the defect this hook was written for'
        )
    what = 'declares no readable branch set: ' if type(exc) is BranchSetNotDeclared else 'cannot be judged: '
    return f'[branchset-push] REFUSED -- commit {sha} {what}{exc}\n[branchset-push]   REMEDY: {remedy}.\n'


def refusal(root: Path, *, lines: Iterable[str] = ()) -> tuple[int, str]:
    """The verdict for one push: an exit code and the text to print.

    EACH PUSHED REF IS JUDGED BY THE DECLARATION ITS OWN COMMIT CARRIES (``<sha>:pyproject.toml``), never by
    *root*'s working tree. MEASURED 2026-10-19: a checkout on ``main`` (``sessions = []``, not yet promoted)
    was refused pushing ``integrate/main`` whose commit declared it, while a worktree carrying the same
    declaration passed -- a pre-push verdict that depended on WHICH checkout pushed. The push carries its
    declaration; that declaration is the one reviewed with it. A commit with no readable declaration is
    :data:`COULD_NOT_JUDGE`, as a checkout without one used to be. Deletions carry no content and pass.

    Args:
        root: The repository being pushed; only its object store is read.
        lines: The refspec lines, as git would write them.

    Returns:
        ``(ALLOWED, '')``, ``(REFUSED, <the refusal>)``, or ``(COULD_NOT_JUDGE, <why>)``.

    """
    judged = [ref for ref in pushed_refs(lines) if not ref.deleted and ref.branch is not None]
    texts: list[str] = []
    could_not_judge = False
    for sha in sorted({ref.local_sha for ref in judged}):
        try:
            declared = branchset_at(root, sha)
        except BranchSetNotDeclared as exc:  # KitOlderThanCheckout and BranchSetKeyRetired included
            could_not_judge = True
            texts.append(_unjudgeable(sha, exc))
            continue
        if rows := undeclared([ref for ref in judged if ref.local_sha == sha], declared):
            texts.append(_refusal(rows, declared))
    if not texts:
        return ALLOWED, ''
    return (COULD_NOT_JUDGE if could_not_judge else REFUSED), ''.join(texts)


def _stdin_lines() -> tuple[str, ...]:
    """The refspec lines, or nothing when stdin is the terminal rather than git's pipe."""
    if sys.stdin.isatty():
        return ()
    return tuple(sys.stdin.read().splitlines())


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m dev_lab.dev.branchset_push [--root R]`` -- the pre-push entry point.

    Reads the refspec git writes on stdin and exits
    :data:`ALLOWED`, :data:`REFUSED` or :data:`COULD_NOT_JUDGE`. ``argv`` is accepted for a caller
    that wants a different checkout than the one git ran the hook in; the hook itself passes nothing.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else Path.cwd()
    code, text = refusal(root, lines=_stdin_lines())
    if text:
        emit(text, err=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
