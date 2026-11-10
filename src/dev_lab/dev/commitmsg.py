"""The family's conventional-commit message check: ``type(scope)!: subject``, owned here once.

It replaces ``commitizen check``, the one thing the family used commitizen for (user ruling 2026-11-05): the
commit-msg row (``githooks/base.toml``), the push-range script (``githooks/cz-push-range.sh``) and, through
that script, the forge's merge decision (:mod:`dev_lab.dev.forgemerge`). Dropping commitizen dropped six
packages from every consumer's resolution for a regex.

THE SHAPE is commitizen's ``cz_conventional_commits`` schema, unchanged: one of :data:`TYPES`, an optional
``(scope)`` with no whitespace, an optional ``!``, ``": "`` and a non-empty subject line; a body, if any, is
separated by a blank line. A message starting with one of :data:`DEFAULT_PREFIXES` passes whatever follows:
those are the subjects GIT ITSELF writes (merges, reverts, fixups), and nothing else. NO REPO CAN ADD A PREFIX
(user ruling 2026-11-05): a ``rem(``/``data(``-style message is a violation, never an exemption.

HISTORY IS NOT RE-JUDGED (user ruling 2026-11-05: EXISTING ``rem(``/``data(`` commits stand, new ones are
refused). ``--published REV`` (repeatable) drops every commit reachable from *REV* -- ``git log <range> --not
REV...``, so git's own ``--remotes`` (every remote-tracking ref) is a valid *REV*. A commit is judged once, when
it is first published; one already published is history. That -- not a name or sha list -- is what keeps an
off-format commit published long ago from blocking every later push that merges it.

ONE NAMED LANE'S HISTORY, the one exception (user ruling 2026-11-10): a repo may declare
``[tool.dev_lab.commitmsg] history = [{ head = "pr/<lane>", through = "<sha>" }]`` for a lane that predates
the 11-05 rule and was never published. Every commit reachable from *through* counts as published, in both
modes of ``cz-push-range`` (this module reads it, so neither caller can forget it); a commit after it is
judged. :data:`HISTORY_CEILING` is ONE entry and only goes down (ESCAPE-HATCH-CEILING); an entry the base
already holds is said to be removable.

THE EMPTY MESSAGE IS AN ABORT, NOT A REFUSAL (commitizen's ``--allow-abort``): git abandons an empty commit
itself, so a refusal would only be noise. Comment lines and everything under git's scissors line are not
part of the recorded message and are not read.

``python -m dev_lab.dev.commitmsg --commit-msg-file F | --message M | --rev-range A..B [--published REV]...``:
0 when every message passes, 1 otherwise, with the refusal as the LAST line said (the merge decision quotes it).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.log import emit

__all__ = ['DEFAULT_PREFIXES', 'HISTORY_CEILING', 'SHAPE', 'TYPES', 'main', 'refusal']

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

#: Message starts that pass unjudged: ONLY the subjects git itself writes (merge, revert, fixup/squash/amend).
#: No ``Pull request`` (a web-UI merge subject; the forge merges as ``chore(merge): ...``) and no repo extension.
DEFAULT_PREFIXES: Final[tuple[str, ...]] = ('Merge', 'Revert', 'fixup!', 'squash!', 'amend!')

#: How many lanes may declare their history published; it only goes down (ESCAPE-HATCH-CEILING).
HISTORY_CEILING: Final = 1

_SCISSORS: Final = '# ------------------------ >8 ------------------------'
_EXPECTED: Final = f'expected `type(scope)!: subject` with type one of {", ".join(TYPES)}'


def _recorded(text: str) -> str:
    """The message git records: comment lines and everything under the scissors line dropped."""
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith(_SCISSORS):
            break
        if not line.startswith('#'):
            lines.append(line)
    return '\n'.join(lines).strip('\n')


def refusal(message: str) -> str | None:
    """Why *message* is off-format, or ``None`` when it passes."""
    if message.startswith(DEFAULT_PREFIXES) or SHAPE.match(message):
        return None
    subject = message.splitlines()[0] if message else ''
    return f'{subject!r} -- {_EXPECTED}'


def _range(spec: str, published: Sequence[str]) -> list[tuple[str, str]]:
    history = ['--not', *published] if published else []
    out = _door.run(
        ['git', 'log', '--reverse', '--format=%H%x00%B%x1e', spec, *history],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=True,
    ).stdout
    pairs = (record.strip('\n').split('\0', 1) for record in out.split('\x1e') if record.strip())
    return [(sha, body.strip('\n')) for sha, body in pairs]


def _git(*argv: str) -> subprocess.CompletedProcess[str]:
    return _door.run(['git', *argv], capture_output=True, text=True, encoding='utf-8', errors='replace', check=False)


def _declared_history() -> list[dict[str, str]]:
    """The repo's ``[tool.dev_lab.commitmsg] history`` entries; ``[]`` outside a repo or when undeclared."""
    top = _git('rev-parse', '--show-toplevel')
    pyproject = Path(top.stdout.strip()) / 'pyproject.toml'
    if top.returncode or not pyproject.is_file():
        return []
    table = tomllib.loads(pyproject.read_text(encoding='utf-8')).get('tool', {}).get('dev_lab', {})
    return list(table.get('commitmsg', {}).get('history', []))


def _held_by(sha: str, refs: Sequence[str]) -> bool:
    """Whether any of *refs* already holds *sha* (so the entry naming it is removable)."""
    return any(_git('merge-base', '--is-ancestor', sha, ref).returncode == 0 for ref in refs if ref != '--remotes')


def main(argv: Sequence[str] | None = None) -> int:
    """Judge one message file, one message, or every commit of a range; 0 when all pass, else 1."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.commitmsg', description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--commit-msg-file', type=Path, help='the commit-msg hook argument')
    source.add_argument('--message', help='one message')
    source.add_argument('--rev-range', help='every commit of a git range, e.g. origin/main..HEAD')
    parser.add_argument(
        '--published',
        metavar='REV',
        action='append',
        default=[],
        help='with --rev-range: skip commits REV already holds (repeatable; --published=--remotes for every remote)',
    )
    args = parser.parse_args(argv)
    if args.published and args.rev_range is None:
        parser.error('--published narrows a --rev-range and means nothing without one')
    if args.rev_range is not None:
        history = _declared_history()
        if len(history) > HISTORY_CEILING:
            emit(
                f'[commit-msg] refused: {len(history)} [tool.dev_lab.commitmsg] history entries, the ceiling is '
                f'{HISTORY_CEILING} -- remove the entries whose lane has merged'
            )
            return 1
        for entry in history:
            if _held_by(entry['through'], args.published):
                emit(f'[commit-msg] history entry {entry["head"]} is removable: the base holds {entry["through"][:12]}')
        published = [*args.published, *(entry['through'] for entry in history)]
        judged = _range(args.rev_range, published)
    else:
        text = args.message if args.message is not None else args.commit_msg_file.read_text(encoding='utf-8')
        judged = [('', _recorded(text))]
    if judged == [('', '')]:
        emit('[commit-msg] empty message -- an abort, nothing to judge')
        return 0
    refused = [(sha, why) for sha, body in judged if (why := refusal(body)) is not None]
    emit(f'[commit-msg] {len(judged) - len(refused)}/{len(judged)} message(s) conventional')
    for sha, why in refused:
        emit(f'[commit-msg] refused {sha[:12] + " " if sha else ""}{why}')
    return 1 if refused else 0


if __name__ == '__main__':
    sys.exit(main())
