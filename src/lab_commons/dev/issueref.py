"""The commit-msg check for issue references: WARN on a malformed one, never block (docs-src/dev/issues.md).

WHY A CHECK AT ALL. An issue's state is DERIVED (:mod:`lab_commons.dev.forgeissue`) from commit
messages that say ``Refs #N``, ``Closes #N`` or ``Fixes #N``. A reference the derivation cannot
parse -- ``Refs#12``, ``closes 12``, ``#12abc`` -- is not a failed commit, it is a link the issue
will never see: the lane reads ``todo`` while somebody works on it. The author is the only person
who can fix that cheaply, at the moment they type it, so the check speaks then.

WHY IT NEVER BLOCKS. A malformed reference is a typo in prose, and the family's commit gate is
commitizen's; a second gate on the free-text body would refuse commits for something that costs
nothing to repair with a follow-up ``Refs #N``. So :func:`main` returns 0 on every path, including
the ones where it cannot read the message -- and SAYS so, because a silent skip reads the same as a
clean message.

WHY IT RUNS IN PRE-COMMIT'S OWN ENVIRONMENT, unlike every other hook the family wires through
``lab-with-venv``. That launcher exits 1 when no venv provides the module, which is right for a
judging hook and wrong for this one: "never block" must hold on a fresh clone with no venv yet.
This module imports only the standard library and :mod:`lab_commons.log`, so the cached copy in
pre-commit's managed environment can run it; the price is that a change here reaches a consumer
when its pre-commit cache is rebuilt, which is acceptable for a pattern this small and stable.

The verbs are the derivation's, from one place: :data:`CLOSING_VERBS` and :data:`REF_VERBS` are
what :mod:`lab_commons.dev.forgeissue` matches, so the check cannot accept a spelling the derivation
ignores, or the reverse.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from lab_commons.log import emit

__all__ = ['CLOSING_VERBS', 'REF_VERBS', 'main', 'malformed']

#: Verbs that move an issue to done when their commit reaches the default branch.
CLOSING_VERBS: Final[tuple[str, ...]] = (
    'closes',
    'close',
    'closed',
    'fixes',
    'fix',
    'fixed',
    'resolves',
    'resolve',
    'resolved',
)

#: Every verb that links a commit to an issue: the closing ones, plus ``Refs``.
REF_VERBS: Final[tuple[str, ...]] = (*CLOSING_VERBS, 'refs')

_VERB: Final = '|'.join(REF_VERBS)
_SHAPES: Final[tuple[re.Pattern[str], ...]] = (
    # `Refs#12` -- the verb glued to the hash.
    re.compile(rf'\b(?:{_VERB})#\d+\b', re.IGNORECASE),
    # `closes 12` -- the number with no hash, so the derivation reads no reference at all. Only a
    # number that ENDS its clause: `fix 3 typos` is prose about a count, not a reference.
    re.compile(rf'\b(?:{_VERB})\s+\d+(?=\s*(?:[,.;:)]|$))', re.IGNORECASE),
    # `#12abc` -- a number glued to a word, which `#N\b` cannot match.
    re.compile(r'(?<![\w&])#\d+[A-Za-z_]\w*'),
)

#: git's scissors line: everything below it is discarded from the message (``--cleanup=scissors``).
_SCISSORS: Final = '# ------------------------ >8 ------------------------'

_HINT: Final = 'valid forms: `Refs #N`, `Closes #N`, `Fixes #N` (a space, then `#`, then the number alone)'


def _message_lines(message: str) -> list[str]:
    lines: list[str] = []
    for line in message.splitlines():
        if line.startswith(_SCISSORS):
            break
        if not line.startswith('#'):
            lines.append(line)
    return lines


def malformed(message: str) -> tuple[str, ...]:
    """Every malformed issue reference in *message*, in order; ``()`` when there is none.

    git comment lines (``#`` at column 0) and everything under the scissors line are not part of the
    message git records, so they are not read.
    """
    found: list[str] = []
    for line in _message_lines(message):
        hits = sorted((m.start(), m.group(0)) for shape in _SHAPES for m in shape.finditer(line))
        found.extend(token for _, token in hits)
    return tuple(found)


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m lab_commons.dev.issueref <commit-msg-file>`` -- warns on stderr, ALWAYS returns 0."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        emit('issue-ref: no commit message file was passed; nothing checked', err=True)
        return 0
    try:
        text = Path(args[0]).read_text(encoding='utf-8', errors='replace')
    except OSError as exc:
        emit(f'issue-ref: could not read the commit message ({exc}); nothing checked', err=True)
        return 0
    for token in malformed(text):
        emit(f'issue-ref: WARNING malformed issue reference {token!r} -- {_HINT}. Not blocking.', err=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
