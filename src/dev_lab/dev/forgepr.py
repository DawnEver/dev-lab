"""``forge pr close|edit|retarget``: the pull request writes that change one PR's state, body or base, on both forges.

Split from :mod:`dev_lab.dev.forgecli` at the module-size band (2026-11-25); the door parses, this writes.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from dev_lab.dev._forge_records import pull_of
from dev_lab.dev.branchset import declared_branchset
from dev_lab.dev.forgepulls import pr_list
from dev_lab.dev.lanepolicy import load_policy

if TYPE_CHECKING:
    import argparse
    from collections.abc import Collection, Sequence

    from dev_lab.dev.forgework import Client, PullRequest

__all__ = ['declared_bases', 'edit_text', 'pr_close', 'pr_edit', 'pr_retarget', 'retarget_children', 'retarget_refusal']


def pr_close(client: Client, number: int, reason: str) -> PullRequest:
    """Close pull request *number*, commenting *reason* first so the record says why; its branch stays.

    An empty *reason* is refused before any call: a close nobody can explain is not a record.
    """
    if not reason.strip():
        said = f'pr close {number}: a reason is required (--reason "<why>")'
        raise ValueError(said)
    client.issue_comment(number, f'closed: {reason.strip()}')
    return pull_of(client.call('PATCH', f'{client.repo}/pulls/{number}', {'state': 'closed'}))


def pr_edit(client: Client, number: int, *, body: str | None = None, append: Sequence[str] = ()) -> PullRequest:
    """Set pull request *number*'s body to *body*, or add the *append* lines after the body the forge holds.

    The body is READ before an append, so another writer's text stays; asking for neither is refused before any call.
    """
    if (body is None) == (not append):
        said = f'pr edit {number}: give exactly one of a body (--body-file F) or lines to add (--append-line L)'
        raise ValueError(said)
    if body is None:
        held = client.pr_view(number).body.rstrip('\n')
        body = '\n'.join([*([held] if held else []), *append]) + '\n'
    return pull_of(client.call('PATCH', f'{client.repo}/pulls/{number}', {'body': body}))


def edit_text(args: argparse.Namespace) -> str:
    """The text ``pr edit`` publishes: the body file's, or the lines it adds."""
    return Path(args.body_file).read_text(encoding='utf-8') if args.body_file else '\n'.join(args.append_line)


def pr_retarget(client: Client, number: int, base: str, *, allowed: Collection[str], reason: str) -> PullRequest:
    """Move pull request *number* onto *base*, commenting *reason* first so the record says why.

    PRS-TARGET-INTEGRATION: *base* must be one of *allowed* -- the integration branch or a declared long-lived
    branch (:attr:`~dev_lab.dev.branchset.BranchSet.declared`); any other base is refused before any call.
    """
    if said := retarget_refusal(number, base, allowed):
        raise ValueError(said)
    client.issue_comment(number, f'retargeted onto `{base}`: {reason.strip()}')
    return pull_of(client.call('PATCH', f'{client.repo}/pulls/{number}', {'base': base}))


def retarget_refusal(number: int, base: str, allowed: Collection[str]) -> str:
    """Why PR *number* may not move onto *base* (not one of *allowed*), or ``''`` when it may."""
    if base in allowed:
        return ''
    return (
        f'pr retarget {number}: {base!r} is not a declared base -- a PR targets the integration branch or a '
        f'declared branch ({", ".join(sorted(allowed))}); PRS-TARGET-INTEGRATION'
    )


def declared_bases(root: Path) -> frozenset[str]:
    """The bases *root* lets a PR target: its integration branch and its declared long-lived branches."""
    return frozenset({load_policy(root).integration}) | declared_branchset(root).declared


def retarget_children(client: Client, branch: str, *, onto: str, landed: int) -> tuple[PullRequest, ...]:
    """Retarget every open PR whose base is *branch* onto *onto*, before *branch* is deleted by landing #*landed*.

    GitHub CLOSES a PR whose base branch is deleted, and one whose base is gone cannot be reopened (dev-lab #1003):
    the landing moves the stacked children first, each with one comment saying why. *onto* is the landed PR's own
    base, where *branch*'s commits now live; the children are what was moved.
    """
    children = tuple(pull for pull in pr_list(client) if pull.base == branch)
    why = f'its base `{branch}` landed in #{landed} and is deleted; PRS-TARGET-INTEGRATION'
    return tuple(pr_retarget(client, pull.number, onto, allowed=(onto,), reason=why) for pull in children)
