"""THE ISSUE/PR DOOR'S ARGUMENTS: the ``issue`` and ``pr`` verb parser, and what a write verb refuses to publish.

Read by :func:`dev_lab.dev.forgecli.issue_and_pr` before any forge call.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from pathlib import Path

from lab_commons.log import emit

from dev_lab.dev import forgedraft, forgepr, privatemarkers
from dev_lab.dev.forge import Transport
from dev_lab.dev.issuekind import KINDS

__all__ = ['parser', 'refused']


def _verb(group: argparse._SubParsersAction, name: str) -> argparse.ArgumentParser:
    sub = group.add_parser(name)
    sub.add_argument('--json', action='store_true', help='print the normalized result as JSON')
    return sub


def parser() -> argparse.ArgumentParser:
    built = argparse.ArgumentParser(
        prog='dev_lab.dev.forge',
        description='issue and PR verbs on the forge',
        epilog=(
            'also: pr breakglass N --reason R, breakglass open|close|ack|status, pr close-landed [N...], '
            'pr close-superseded N... --by <M|sha|ref>, '
            'issue claim|status N, label create --name N --color C, status post|list SHA; token: auth login|status'
        ),
    )
    nouns = built.add_subparsers(dest='noun', required=True)
    issue = nouns.add_parser('issue').add_subparsers(dest='verb', required=True)
    listing = _verb(issue, 'list')
    listing.add_argument('--state', choices=('open', 'closed', 'all'), default='open')
    listing.add_argument('--limit', type=int, default=30)
    listing.add_argument('--label', action='append', default=[], help='only issues carrying it (repeatable)')
    for name in ('view', 'close'):
        _verb(issue, name).add_argument('number', type=int)
    create = _verb(issue, 'create')
    create.add_argument('--title', required=True)
    create.add_argument('--body', default='')
    create.add_argument('--kind', required=True, choices=KINDS, help='an issue is a need, defect or decision')
    create.add_argument('--label', action='append', default=[], help='also label it; a missing one is created')
    label = _verb(issue, 'label')
    label.add_argument('number', type=int)
    label.add_argument('--add', nargs='+', default=[], help='labels to put on it; a missing one is created first')
    label.add_argument('--remove', nargs='+', default=[], help='labels to take off it')
    comment = _verb(issue, 'comment')
    comment.add_argument('number', type=int)
    comment.add_argument('--body', required=True)
    pr = nouns.add_parser('pr').add_subparsers(dest='verb', required=True)
    _verb(pr, 'view').add_argument('number', type=int)
    closing = _verb(pr, 'close')
    closing.add_argument('number', type=int)
    closing.add_argument(
        '--reason', required=True, help='why; posted as a comment before the close (no branch deleted)'
    )
    editing = _verb(pr, 'edit')
    editing.add_argument('number', type=int)
    edits = editing.add_mutually_exclusive_group(required=True)
    edits.add_argument('--body-file', help='replace the body with this UTF-8 file')
    edits.add_argument(
        '--append-line', action='append', default=[], help='add this line after the current body (repeatable)'
    )
    opened = _verb(pr, 'create')
    opened.add_argument('--title', required=True)
    opened.add_argument('--body', default='')
    opened.add_argument('--head', required=True)
    opened.add_argument('--base', required=True)
    opened.add_argument(
        '--ready', action='store_true',
        help='open it ready for review; the default is a DRAFT, marked ready by `forge pr ready N` (D53)',
    )  # fmt: skip
    opened.add_argument(
        '--ready-when-current', action='store_true',
        help=f'open a DRAFT the serve marks ready once its head is current (`{forgedraft.READY_WHEN}` in the body)',
    )  # fmt: skip
    return built


def refused(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    root: Path,
    env: Mapping[str, str] | None,
    transport: Transport,
) -> str | None:
    """Why the verb is refused before any write: a reasonless close, a PUBLIC repo's text naming a private value.

    Every verb in :data:`_PUBLISHED_TEXT` publishes what a person typed; a private repository is where private
    names belong, and an unreadable visibility is scanned (fail closed).
    """
    if (args.noun, args.verb) == ('pr', 'close') and not args.reason.strip():
        parser.error('pr close: --reason must say why')
    if (args.noun, args.verb) == ('pr', 'create') and args.ready and args.ready_when_current:
        parser.error('pr create: --ready opens it ready; --ready-when-current opens a draft -- choose one')
    if (published := _PUBLISHED_TEXT.get((args.noun, args.verb))) is None:
        return None
    what, texts = published
    private, why = privatemarkers.repo_is_private(root, env=env, transport=transport)
    if private:
        return None
    if why:
        emit(f'[forge] scanning the {what} for private markers: {why}', err=True)
    public = privatemarkers.public_names(root, env=env, transport=transport)
    return privatemarkers.text_refusal('\n'.join(texts(args)), what, public=public)


#: Each write verb that publishes typed text: what a refusal calls it, and the argument fields that hold it.
_PUBLISHED_TEXT: dict[tuple[str, str], tuple[str, Callable[[argparse.Namespace], tuple[str, ...]]]] = {
    ('pr', 'create'): ('PR title or body', lambda a: (a.title, a.body)),
    ('pr', 'close'): ('close reason', lambda a: (a.reason,)),
    ('pr', 'edit'): ('PR body', lambda a: (forgepr.edit_text(a),)),
    ('issue', 'create'): ('issue title or body', lambda a: (a.title, a.body)),
    ('issue', 'comment'): ('comment body', lambda a: (a.body,)),
    ('issue', 'label'): ('label names', lambda a: (*a.add, *a.remove)),
}
