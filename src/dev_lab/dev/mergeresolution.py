"""MERGE-RESOLUTION-DECLARED: a conflicted merge says, per conflicted file, how it was resolved and why.

THE DEFECT. A conflict resolution is the one edit in a merge nobody reviews: the diff against either parent
shows the other side's work, not the choice made between them. ``.claude/rules/rem/integration.md``
(motronics, 2026-09-04/05) records the result -- every conflicted file resolved by reinstating the lane's
OLDER shape, invisible until a later pin red. MERGE-DEVIATIONS-NAMED (:mod:`dev_lab.dev.mergeaudit`) sees the
TESTS such a resolution drops; this rule makes the resolution of every conflicted FILE a stated choice.

THE RULE. A merge commit whose parents conflict lists every conflicted file ONCE, one line each::

    src/pkg/table.py: upstream-structure+lane-content -- the lane's rows re-expressed in the derived table
    tests/test_pins.py: both-needed -- upstream's split file plus the lane's new pin

with the class one of :data:`CLASSES`; ``both-needed`` requires its why. The conflicted set is RECOMPUTED from
the parents' trees (``git merge-tree --write-tree --name-only``), never read from the message, so a line naming
a file the parents do not conflict on is refused too. A clean merge needs no line.

WHEN IT RUNS: the ``commit-msg`` hook beside ``merge-audit`` (the family base's ``merge-resolution`` row), on the
merge being committed (HEAD plus ``MERGE_HEAD``); any other commit costs one file check.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.forge import _GIT
from dev_lab.dev.mergeaudit import MergeAuditError, pending_parents

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ['BOTH_NEEDED', 'CLASSES', 'conflicted', 'main', 'pending', 'undeclared']

#: Kept both sides' content; the one class that must say why both were needed.
BOTH_NEEDED: Final = 'both-needed'

#: How a conflicted file may be resolved (NEWER-STRUCTURE's vocabulary, ``.claude/rules/rem/integration.md``).
CLASSES: Final = frozenset({'upstream-structure+lane-content', 'lane-supersedes', 'deleted-as-baggage', BOTH_NEEDED})

_LINE: Final = re.compile(
    r'^(?P<path>[^\s:][^:\n]*?):[ \t]+(?P<cls>\S+)(?:[ \t]+--[ \t]*(?P<why>\S.*?))?[ \t]*$', re.MULTILINE
)
_GIT_TIMEOUT_S: Final = 120
_CONFLICTS_EXIT: Final = 1
_PARENTS: Final = 2


def conflicted(root: Path, parents: Sequence[str]) -> tuple[str, ...]:
    """The files the two *parents* conflict on, sorted, as git's own three-way merge computes them."""
    done = _door.run(
        [_GIT, '-C', str(root), 'merge-tree', '--write-tree', '--name-only', '--no-messages', '-z', *parents],
        capture_output=True,
        check=False,
        timeout=_GIT_TIMEOUT_S,
    )
    if done.returncode not in {0, _CONFLICTS_EXIT}:
        msg = f'git merge-tree failed: {done.stderr.decode("utf-8", "replace").strip()}'
        raise MergeAuditError(msg)
    if done.returncode == 0:
        return ()
    _tree, *names = done.stdout.decode('utf-8', 'surrogateescape').split('\0')
    return tuple(sorted({name for name in names if name}))


def undeclared(conflicts: Sequence[str], message: str) -> tuple[str, ...]:
    """What *message* fails to declare about the resolution of *conflicts*; empty when every line matches."""
    wanted = set(conflicts)
    lines = [m for m in _LINE.finditer(message) if m['path'] in wanted or m['cls'] in CLASSES]
    counts = Counter(m['path'] for m in lines)
    classes = ', '.join(sorted(CLASSES))
    problems = [
        f'{path}: not declared -- add `{path}: <class> -- <why>` (class one of {classes})'
        for path in sorted(wanted - set(counts))
    ]
    problems += [f'{path}: declared {n} times -- list each conflicted file once' for path, n in counts.items() if n > 1]
    for m in lines:
        if m['path'] not in wanted:
            problems.append(f'{m["path"]}: declared, but the parents do not conflict on it -- delete the line')
        elif m['cls'] not in CLASSES:
            problems.append(f'{m["path"]}: {m["cls"]!r} is not a resolution class -- use one of {classes}')
        elif m['cls'] == BOTH_NEEDED and not m['why']:
            problems.append(f'{m["path"]}: {BOTH_NEEDED} needs its why -- `{m["path"]}: {BOTH_NEEDED} -- <why>`')
    return tuple(problems)


def pending(root: Path, message: str) -> tuple[str, ...]:
    """What *message* fails to declare about the merge being committed in *root*; empty for a non-merge.

    An octopus is :mod:`dev_lab.dev.mergeaudit`'s refusal, not repeated here.
    """
    parents = pending_parents(root)
    if parents is None or len(parents) != _PARENTS:
        return ()
    return undeclared(conflicted(root, parents), message)


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m dev_lab.dev.mergeresolution <commit-msg-file>`` -- the commit-msg hook; ``1`` refuses."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        emit('merge-resolution: pass exactly the commit message file (git hands it to commit-msg)', err=True)
        return 1
    try:
        root = Path(_door.run([_GIT, 'rev-parse', '--show-toplevel'], capture_output=True, text=True,
                              check=True).stdout.strip())  # fmt: skip
        problems = pending(root, Path(args[0]).read_text(encoding='utf-8', errors='replace'))
    except (MergeAuditError, OSError, subprocess.CalledProcessError) as error:
        problems = (str(error),)
    if not problems:
        return 0
    lines = [
        'merge-resolution: commit REFUSED -- a conflicted file is not declared with how it was resolved.',
        *(f'merge-resolution:   {line}' for line in problems),
        'merge-resolution: Remedy: one line per conflicted file, `<path>: <class> -- <why>`, then commit again.',
    ]
    emit('\n'.join(lines), err=True)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
