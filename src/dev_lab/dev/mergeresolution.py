"""MERGE-RESOLUTION-DECLARED: a conflicted merge says, per conflicted file, how it was resolved and why.

THE DEFECT. A conflict resolution is the one edit in a merge nobody reviews: the diff against either parent
shows the other side's work, not the choice made between them. ``.claude/rules/rem/integration.md``
(consumer-a, 2026-09-04/05) records the result -- every conflicted file resolved by reinstating the lane's
OLDER shape, invisible until a later pin red. MERGE-DEVIATIONS-NAMED (:mod:`dev_lab.dev.mergeaudit`) sees the
TESTS such a resolution drops; this rule makes the resolution of every conflicted FILE a stated choice.

THE RULE. A merge commit whose parents conflict lists every conflicted file ONCE, one line each::

    src/pkg/table.py: newer-structure -- the lane's rows re-expressed in the derived table
    tests/test_pins.py: both-needed -- upstream's split file plus the lane's new pin

with the class one of :data:`CLASSES` and EVERY class with its why: a resolution is derived from what the code
must do now (first principles), and the why is that derivation.

THE CLASSES ARE THE RESOLUTION PRINCIPLES (user rulings 2026-10-25). Take the newer structure only where it is
also the simpler one; keep the simpler correct side even when it is older; collapse two copies of one fact into
one; delete obsolete structure, compat layers, aliases and upgrade-on-read paths (no backward compatibility);
rename to what a thing is. Layered decoupling is not a class: a resolution never adds an upward import, and each
repo's layering tests refuse one. The conflicted set is RECOMPUTED from
the parents' trees (``git merge-tree --write-tree --name-only``), never read from the message, so a line naming
a file the parents do not conflict on is refused too. A clean merge needs no line.

STRATEGY-BLIND ON PURPOSE. ``-s ours`` and ``-X ours|theirs`` stop on no conflict, yet the recomputation still
finds the parents' one: a strategy that picks a side silently IS the unreviewed resolution this rule names, so
it is declared like any other. The index cannot answer instead -- every stage is resolved by commit-msg time.

WHERE IT IS ENFORCED: on the FORGE, which no client can skip -- a PR into integration is not merged while a merge
commit its head adds over integration leaves a conflicted file undeclared (:func:`unresolved`, asked by
:func:`dev_lab.dev.forgemerge.decide`), so a web-UI or forge-made merge meets it too. A merge message cannot be
amended, so the remedy is to redo that merge with the declaration. The ``commit-msg`` hook beside ``merge-audit``
(the family base's ``merge-resolution`` row) is the same :func:`judge` on the one merge being committed (HEAD
plus ``MERGE_HEAD``), telling the author early; any other commit costs one file check.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.mergeaudit import MergeAuditError, pending_parents

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ['CLASSES', 'conflicted', 'judge', 'main', 'pending', 'undeclared', 'unresolved']

#: How a conflicted file may be resolved -- one class per resolution principle:
#: ``newer-structure`` the newer structure, the other side's content re-expressed inside it;
#: ``simpler-side`` the simpler correct side kept, older or not (Occam);
#: ``one-source`` two copies of one fact made one, the rest derived from it;
#: ``deleted-as-baggage`` obsolete structure, a compat layer, an alias or an upgrade path deleted;
#: ``renamed-to-reality`` a name changed to what the thing is;
#: ``both-needed`` both sides' content is live.
CLASSES: Final = frozenset(
    {'newer-structure', 'simpler-side', 'one-source', 'deleted-as-baggage', 'renamed-to-reality', 'both-needed'}
)

_LINE: Final = re.compile(
    r'^(?P<path>[^\s:][^:\n]*?):[ \t]+(?P<cls>\S+)(?:[ \t]+--[ \t]*(?P<why>\S.*?))?[ \t]*$', re.MULTILINE
)
_GIT: Final = shutil.which('git') or 'git'
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
        elif not m['why']:
            problems.append(f'{m["path"]}: {m["cls"]} needs its why -- `{m["path"]}: {m["cls"]} -- <why>`')
    return tuple(problems)


def judge(root: Path, parents: Sequence[str], message: str) -> tuple[str, ...]:
    """What *message* fails to declare about a merge of *parents*; empty for a non-merge.

    An octopus is :mod:`dev_lab.dev.mergeaudit`'s refusal, not repeated here.
    """
    if len(parents) != _PARENTS:
        return ()
    return undeclared(conflicted(root, parents), message)


def pending(root: Path, message: str) -> tuple[str, ...]:
    """What *message* fails to declare about the merge being committed in *root*; empty for a non-merge."""
    return judge(root, pending_parents(root) or (), message)


def unresolved(root: Path, base: str, head: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Each merge commit *head* adds over *base* paired with what its message fails to declare, oldest first."""
    argv = [_GIT, '-C', str(root), 'log', '--merges', '--reverse', '-z', '--format=%H %P%n%B', f'{base}..{head}']
    done = _door.run(argv, capture_output=True, check=False, timeout=_GIT_TIMEOUT_S)
    if done.returncode:
        msg = f'git log failed: {done.stderr.decode("utf-8", "replace").strip()}'
        raise MergeAuditError(msg)
    found = []
    for record in filter(None, done.stdout.decode('utf-8', 'surrogateescape').split('\0')):
        line, _, message = record.partition('\n')
        sha, *parents = line.split()
        if problems := judge(root, parents, message):
            found.append((sha, problems))
    return tuple(found)


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m dev_lab.dev.mergeresolution <commit-msg-file>`` -- the commit-msg hook; ``1`` refuses."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        emit('merge-resolution: pass exactly the commit message file (git hands it to commit-msg)', err=True)
        return 1
    try:
        problems = pending(_toplevel(), Path(args[0]).read_text(encoding='utf-8', errors='replace'))
    except (MergeAuditError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        emit(f'merge-resolution: commit REFUSED -- could not compute the conflicted set: {error}', err=True)
        return 1
    if not problems:
        return 0
    lines = [
        'merge-resolution: commit REFUSED -- a conflicted file is not declared with how it was resolved.',
        *(f'merge-resolution:   {line}' for line in problems),
        'merge-resolution: Remedy: one line per conflicted file, `<path>: <class> -- <why>`, then commit again.',
    ]
    emit('\n'.join(lines), err=True)
    return 1


def _toplevel() -> Path:
    argv = [_GIT, 'rev-parse', '--show-toplevel']
    done = _door.run(argv, capture_output=True, text=True, encoding='utf-8', check=True, timeout=_GIT_TIMEOUT_S)
    return Path(done.stdout.strip())


if __name__ == '__main__':
    raise SystemExit(main())
