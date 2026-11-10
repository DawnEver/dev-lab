"""``forge label create``: one repository label, written through the family door.

The write goes through :meth:`~dev_lab.dev.forgework.Client.call`, so it is journaled, retried and attributed
like every other forge write. It is idempotent: a label already present under the same name (compared
case-insensitively, as both forges do) is reported and never re-posted. The colour is six hex digits; Gitea
spells it ``#rrggbb`` and GitHub ``rrggbb``, and the caller may give either.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from lab_commons.log import emit

from dev_lab.dev.forge import Transport, forge_transport
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgework import GITHUB, Client, client_for

__all__ = ['label_create', 'main']

_HEX = re.compile(r'#?([0-9a-fA-F]{6})')
#: Labels read per page; a repository with more than this many labels is not one the family keeps.
_PAGE = 100


def label_create(client: Client, name: str, color: str, description: str) -> str:
    """Create label *name* unless the repository already has it; the answer names which happened.

    RAISES :class:`ValueError` before any call when *color* is not six hex digits.
    """
    matched = _HEX.fullmatch(color.strip())
    if matched is None:
        said = f'label {name!r}: colour {color!r} is not six hex digits (rrggbb or #rrggbb)'
        raise ValueError(said)
    listed = client.call('GET', f'{client.repo}/labels?{client.backend.page_param}={_PAGE}')
    if any(str(label.get('name', '')).casefold() == name.casefold() for label in listed):
        return f'{name}: already present'
    digits = matched.group(1).lower()
    spelled = digits if client.backend is GITHUB else f'#{digits}'
    client.call('POST', f'{client.repo}/labels', {'name': name, 'color': spelled, 'description': description})
    return f'{name}: created'


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = forge_transport,
) -> int:
    """``python -m dev_lab.dev.forge label create --name N --color C [--description D]``; exit 1 on a refusal."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge label', description='repository labels on the forge')
    verbs = parser.add_subparsers(dest='verb', required=True)
    made = verbs.add_parser('create')
    made.add_argument('--name', required=True)
    made.add_argument('--color', required=True, help='six hex digits, rrggbb or #rrggbb')
    made.add_argument('--description', default='')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    client = client_for(Path.cwd() if cwd is None else cwd, env=env, transport=transport)
    try:
        emit(label_create(client, args.name, args.color, args.description))
    except (ForgeCallFailed, ValueError) as failed:
        emit(f'[forge] {failed}', err=True)
        return 1
    return 0
