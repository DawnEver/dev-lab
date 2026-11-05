"""The family's conventional-commit message check: ``type(scope)!: subject``, owned here once.

It replaces ``commitizen check``, the one thing the family used commitizen for (user ruling 2026-11-05): the
commit-msg row (``githooks/base.toml``), the push-range script (``githooks/cz-push-range.sh``) and, through
that script, the forge's merge decision (:mod:`dev_lab.dev.forgemerge`). Dropping commitizen dropped six
packages from every consumer's resolution for a regex.

THE SHAPE is commitizen's ``cz_conventional_commits`` schema, unchanged: one of :data:`TYPES`, an optional
``(scope)`` with no whitespace, an optional ``!``, ``": "`` and a non-empty subject line; a body, if any, is
separated by a blank line. A message starting with one of :data:`DEFAULT_PREFIXES` (merges, reverts, fixups)
passes whatever follows, as commitizen's ``allowed_prefixes`` did; a repo EXTENDS that set with
``[tool.dev_lab.commit_msg] allowed_prefixes``.

THE EMPTY MESSAGE IS AN ABORT, NOT A REFUSAL (commitizen's ``--allow-abort``): git abandons an empty commit
itself, so a refusal would only be noise. Comment lines and everything under git's scissors line are not
part of the recorded message and are not read.

``python -m dev_lab.dev.commitmsg --commit-msg-file F | --message M | --rev-range A..B``: 0 when every
message passes, 1 otherwise, with the refusal as the LAST line said (the merge decision quotes it).
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.family import declared_table

__all__ = ['DEFAULT_PREFIXES', 'SHAPE', 'TYPES', 'declared_prefixes', 'main', 'refusal']

#: The commit types the family's ``cz_conventional_commits`` config accepted.
TYPES: Final[tuple[str, ...]] = (
    'build',
    'bump',
    'chore',
    'ci',
    'docs',
    'feat',
    'fix',
    'perf',
    'refactor',
    'revert',
    'style',
    'test',
)

#: The one regex: matched against the WHOLE message (comments and scissors already removed).
SHAPE: Final = re.compile(rf'(?s)(?:{"|".join(TYPES)})(?:\(\S+\))?!?: [^\n\r]+(?:\n\n.*|\s*)$')

#: Message starts that pass unjudged: git's own merge/revert/fixup subjects (commitizen's defaults).
DEFAULT_PREFIXES: Final[tuple[str, ...]] = ('Merge', 'Revert', 'Pull request', 'fixup!', 'squash!', 'amend!')

_SCISSORS: Final = '# ------------------------ >8 ------------------------'
_EXPECTED: Final = f'expected `type(scope)!: subject` with type one of {", ".join(TYPES)}'


def declared_prefixes(root: Path) -> tuple[str, ...]:
    """:data:`DEFAULT_PREFIXES` plus *root*'s ``[tool.dev_lab.commit_msg] allowed_prefixes``."""
    pyproject = root / 'pyproject.toml'
    data = tomllib.loads(pyproject.read_text(encoding='utf-8')) if pyproject.is_file() else {}
    extra = declared_table(data, 'commit_msg', {}).get('allowed_prefixes', [])
    return (*DEFAULT_PREFIXES, *(one for one in extra if one not in DEFAULT_PREFIXES))


def _recorded(text: str) -> str:
    """The message git records: comment lines and everything under the scissors line dropped."""
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith(_SCISSORS):
            break
        if not line.startswith('#'):
            lines.append(line)
    return '\n'.join(lines).strip('\n')


def refusal(message: str, prefixes: Sequence[str]) -> str | None:
    """Why *message* is off-format, or ``None`` when it passes."""
    if message.startswith(tuple(prefixes)) or SHAPE.match(message):
        return None
    subject = message.splitlines()[0] if message else ''
    return f'{subject!r} -- {_EXPECTED}'


def _range(spec: str) -> list[tuple[str, str]]:
    out = _door.run(
        ['git', 'log', '--reverse', '--format=%H%x00%B%x1e', spec],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=True,
    ).stdout
    pairs = (record.strip('\n').split('\0', 1) for record in out.split('\x1e') if record.strip())
    return [(sha, body.strip('\n')) for sha, body in pairs]


def main(argv: Sequence[str] | None = None) -> int:
    """Judge one message file, one message, or every commit of a range; 0 when all pass, else 1."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.commitmsg', description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--commit-msg-file', type=Path, help='the commit-msg hook argument')
    source.add_argument('--message', help='one message')
    source.add_argument('--rev-range', help='every commit of a git range, e.g. origin/main..HEAD')
    args = parser.parse_args(argv)
    prefixes = declared_prefixes(Path.cwd())
    if args.rev_range is not None:
        judged = _range(args.rev_range)
    else:
        text = args.message if args.message is not None else args.commit_msg_file.read_text(encoding='utf-8')
        judged = [('', _recorded(text))]
    if judged == [('', '')]:
        emit('[commit-msg] empty message -- an abort, nothing to judge')
        return 0
    refused = [(sha, why) for sha, body in judged if (why := refusal(body, prefixes)) is not None]
    emit(f'[commit-msg] {len(judged) - len(refused)}/{len(judged)} message(s) conventional')
    for sha, why in refused:
        emit(f'[commit-msg] refused {sha[:12] + " " if sha else ""}{why}')
    return 1 if refused else 0


if __name__ == '__main__':
    sys.exit(main())
