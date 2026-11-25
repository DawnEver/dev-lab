"""``forge pr close|edit``: the pull request writes that change one PR's state or body, on GitHub and Gitea alike.

Split from :mod:`dev_lab.dev.forgecli` at the module-size band (2026-11-25); the door parses, this writes.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from dev_lab.dev._forge_records import pull_of

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence

    from dev_lab.dev.forgework import Client, PullRequest

__all__ = ['edit_text', 'pr_close', 'pr_edit']


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
