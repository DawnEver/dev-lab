"""LABELS BY NAME on both forges -- found, created, and put on an issue.

Gitea takes label IDS on an issue and silently drops a name it does not know (live: an issue created with
an unknown label returned 201 and never queued), so a name is resolved to its id first and a missing one
is refused by name (:class:`LabelMissing`) unless the caller creates it (:func:`ensure_labels`). GitHub
takes names; the same resolution still proves the label exists.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev._forgebackends import GITHUB

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = ['LABEL_COLOR', 'LabelMissing', 'add_label', 'ensure_labels', 'label_ids', 'relabel', 'remove_label']

#: The color a label this module creates gets (neutral grey).
LABEL_COLOR: Final = 'cccccc'
#: Labels read per page.
_PAGE: Final = 50


class LabelMissing(LookupError):
    """A label the repository does not have; the message names it."""


def _listed(client: Client) -> dict[str, Any]:
    found: dict[str, Any] = {}
    page = 1
    while True:
        query = f'{client.backend.page_param}={_PAGE}&page={page}'
        batch = client.call('GET', f'{client.repo}/labels?{query}') or []
        found |= {str(raw['name']): raw['id'] for raw in batch}
        if len(batch) < _PAGE:
            return found
        page += 1


def label_ids(client: Client, names: Iterable[str]) -> dict[str, Any]:
    """``name -> id`` of every label in *names*.

    Raises:
        LabelMissing: one is not a label of the repository; the message names every missing one.

    """
    wanted = list(names)
    found = _listed(client)
    missing = [name for name in wanted if name not in found]
    if missing:
        msg = f'{client.repo} has no label {", ".join(missing)}: create it (forge request does) before using it'
        raise LabelMissing(msg)
    return {name: found[name] for name in wanted}


def ensure_labels(client: Client, names: Iterable[str]) -> dict[str, Any]:
    """``name -> id`` of every label in *names*, each one missing created first; a list of what was created."""
    wanted = list(names)
    found = _listed(client)
    for name in wanted:
        if name not in found:
            made = client.call('POST', f'{client.repo}/labels', {'name': name, 'color': LABEL_COLOR})
            found[name] = made['id']
    return {name: found[name] for name in wanted}


def add_label(client: Client, number: int, name: str) -> None:
    """Put label *name* on issue *number*; a label the repository lacks raises :class:`LabelMissing`."""
    (ident,) = label_ids(client, [name]).values()
    client.call(
        'POST', f'{client.repo}/issues/{number}/labels', {'labels': [name if client.backend is GITHUB else ident]}
    )


def remove_label(client: Client, number: int, name: str) -> None:
    """Take label *name* off issue *number*; a label the repository lacks raises :class:`LabelMissing`."""
    (ident,) = label_ids(client, [name]).values()
    client.call('DELETE', f'{client.repo}/issues/{number}/labels/{name if client.backend is GITHUB else ident}')


def relabel(client: Client, number: int, *, add: Iterable[str], remove: Iterable[str]) -> None:
    """``forge issue label N --add A... --remove B...``: each *add* put on, then each *remove* taken off.

    A missing *add* label is created first; nothing to do is refused before any call.
    """
    adding, removing = list(dict.fromkeys(add)), list(dict.fromkeys(remove))
    if not adding and not removing:
        msg = f'issue label {number}: name a label with --add or --remove'
        raise ValueError(msg)
    if adding:
        ensure_labels(client, adding)
        for name in adding:
            add_label(client, number, name)
    for name in removing:
        remove_label(client, number, name)
