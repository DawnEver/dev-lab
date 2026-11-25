"""THE ONE-TIME MIGRATION of checkouts' retired task stores into the machine's task ledger (FORMATS-MIGRATE-ONCE).

``python -m dev_lab.dev.task migrate <checkout>... [--dry-run]`` (:func:`migrate`):

1. every task directory of each ``<checkout>``'s retired store (:data:`~dev_lab.dev.taskledger.RETIRED_STORE`) -- a
   ``<slug>/`` and each ``archive/<date>/<slug>/`` -- is a UNIT, read from the working tree (tracked and untracked
   files alike; the retired ``.bindings`` and every dot entry skipped). The checkouts are planned in order against
   the ledger AS IT WILL BE: a file it lacks is added; a ``JOURNAL.md`` that differs is UNION-merged (the ledger's
   ``.gitattributes`` ``merge=union``: its lines, then each line it lacks); any other differing file refuses the
   WHOLE run, by name, before any write. A unit with nothing new is skipped;
2. the planned files are written into :func:`~dev_lab.dev.taskledger.ledger` and committed there (local only);
3. each checkout's retired rem authority history (``~/.claude/rem/authority/<key>.jsonl``, keyed by the checkout's
   path or its store's) is folded into the one store (:func:`dev_lab.dev.taskauthority.fold`);
4. the retired per-session binding records, ``<machine home>/state/sessions/*.json``, are deleted -- except a record
   whose ``ledger.path`` names a retired store still holding a task (:func:`_live`): a session bound under the
   retired gate still reads it, and only the user's prompt can bind it again, so it is kept, and named, while that
   store is live;
5. each OPEN task of the run whose ledger TASK.md names no ``issue`` gets its identity (user ruling 2026-11-25, R9):
   the forge issue labeled ``task:<slug>`` is opened -- or the open one already labeled so is reused
   (:class:`~dev_lab.dev._task_io.ForgeIssues`), so a re-run after a failure opens no duplicate -- and
   ``issue: <url>`` is added as the last frontmatter line and committed. That one line is the ledger's own: a
   retired TASK.md that differs from the ledger's only by it is byte-identical for step 1. An archived task is
   closed and gets none.

It never deletes a checkout's tree: it prints the ``git rm`` its owner runs. ``--dry-run`` writes nothing and
lists everything it would do.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Final

from lab_commons.home import part

from dev_lab.dev import taskauthority, taskjournal
from dev_lab.dev._task_io import Forge, ForgeIssues, TaskRefused, commit
from dev_lab.dev.taskledger import RETIRED_STORE, ledger

__all__ = ['RETIRED_AUTHORITY', 'migrate', 'units']

#: Where rem kept its authority history, below the user's home.
RETIRED_AUTHORITY: Final = ('.claude', 'rem', 'authority')
_SKIPPED: Final = '.bindings'
_JOURNAL: Final = 'JOURNAL.md'
_TASK: Final = 'TASK.md'
_ISSUE: Final = 'issue: '


def _files(folder: Path) -> dict[str, Path]:
    return {p.relative_to(folder).as_posix(): p for p in sorted(folder.rglob('*')) if p.is_file()}


def units(store: Path) -> list[str]:
    """The task directories of a retired *store*, as ledger-relative paths: ``<slug>`` and ``archive/<d>/<slug>``."""
    found: list[str] = []
    for entry in sorted(store.iterdir()):
        if not entry.is_dir() or entry.name.startswith('.') or entry.name == _SKIPPED:
            continue
        if entry.name == 'archive':
            found += [f'archive/{d.name}/{t.name}' for d in sorted(entry.iterdir()) if d.is_dir()
                      for t in sorted(d.iterdir()) if t.is_dir()]  # fmt: skip
        else:
            found.append(entry.name)
    return found


def _union(held: str, incoming: str) -> str:
    """*held*, then each line of *incoming* it lacks -- git's ``merge=union`` for a journal."""
    have = set(held.splitlines())
    added = [line for line in incoming.splitlines() if line not in have]
    base = held if not held or held.endswith('\n') else held + '\n'
    return base + ''.join(f'{line}\n' for line in added)


def _history(checkout: Path, home: Path) -> list[Path]:
    keys = {
        hashlib.sha256(str(p).encode('utf-8')).hexdigest()[:16] for p in (checkout, checkout.joinpath(*RETIRED_STORE))
    }
    folder = home.joinpath(*RETIRED_AUTHORITY)
    return [folder / f'{k}.jsonl' for k in sorted(keys) if (folder / f'{k}.jsonl').is_file()]


def _end(lines: list[str]) -> int:
    """The index of the ``---`` line closing the frontmatter of a TASK.md split (ends kept) into *lines*."""
    bare = [ln.rstrip('\r\n') for ln in lines]
    return bare.index('---', 1) if bare[:1] == ['---'] and '---' in bare[1:] else 0


def _without_issue(text: str) -> str:
    """*text* (a TASK.md) without the ``issue:`` frontmatter line the ledger adds."""
    lines = text.splitlines(keepends=True)
    end = _end(lines)
    return ''.join(ln for i, ln in enumerate(lines) if not (0 < i < end and ln.startswith(_ISSUE)))


def _with_issue(text: str, url: str) -> str:
    """*text* (a TASK.md) with ``issue: <url>`` as its last frontmatter line, in the file's own line ending."""
    lines = text.splitlines(keepends=True)
    end = _end(lines)
    if not end:
        msg = f'a TASK.md without a frontmatter cannot name its issue {url}'
        raise TaskRefused(msg)
    newline = lines[end - 1][len(lines[end - 1].rstrip('\r\n')) :] or '\n'
    return ''.join([*lines[:end], f'{_ISSUE}{url}{newline}', *lines[end:]])


def _live(record: Path) -> bool:
    """Whether binding *record* names a retired store that still holds a task (a live session reads it)."""
    try:
        named = json.loads(record.read_text(encoding='utf-8'))['ledger']['path']
    except (OSError, ValueError, KeyError, TypeError):
        return False
    store = Path(str(named))
    return store.is_dir() and any(p.is_file() for p in store.rglob('*'))


def _read(path: Path) -> str | None:
    return path.read_bytes().decode('utf-8') if path.is_file() else None


class _Plan:
    """The ledger AS IT WILL BE: each file's planned text, the report lines, and the conflicts that refuse the run."""

    def __init__(self, root: Path, *, dry_run: bool) -> None:
        self.root, self.would = root, 'would ' if dry_run else ''
        self.files: dict[str, str] = {}  # ledger-relative file -> the text it will hold
        self.units: set[str] = set()
        self.lines: list[str] = []
        self.differ: list[str] = []

    def unit(self, store: Path, unit: str, origin: str) -> None:
        """Plan one *unit* of *store* (from the checkout *origin*) against everything planned so far."""
        new = unit not in self.units and not (self.root / unit).exists()
        changed = False
        for name, src in _files(store / unit).items():
            rel, text = f'{unit}/{name}', src.read_bytes().decode('utf-8')
            held = self.files.get(rel, _read(self.root / rel))
            if held == text or (name == _TASK and held is not None and _without_issue(held) == text):
                continue
            if held is None:
                self.files[rel], changed = text, True
                if not new:
                    self.lines.append(f'{self.would}add {rel}')
            elif name != _JOURNAL:
                self.differ.append(f'{rel} (from {origin})')
            elif (merged := _union(held, text)) != held:
                self.files[rel], changed = merged, True
                self.lines.append(f'{self.would}merge {rel} (+{merged.count(chr(10)) - held.count(chr(10))} line)')
        self.units.add(unit)
        if new:
            self.lines.append(f'{"would copy" if self.would else "copied"} {unit}')
        elif not changed:
            self.lines.append(f'skipped {unit} (byte-identical in the ledger)')


def _write(root: Path, planned: dict[str, str], message: str) -> None:
    """Write each planned file that differs from the ledger's, and commit them there."""
    written = sorted(rel for rel, text in planned.items() if _read(root / rel) != text)
    for rel in written:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(planned[rel].encode('utf-8'))
    if written:
        commit(root, message, *written)


def _unnamed(root: Path, plan: _Plan) -> list[tuple[str, str, str]]:
    """``(slug, goal, TASK.md text)`` of each open task of *plan* whose TASK.md (as it will be) names no issue."""
    found = []
    for unit in sorted(u for u in plan.units if '/' not in u):
        text = plan.files.get(f'{unit}/{_TASK}', _read(root / unit / _TASK))
        fields = taskjournal.frontmatter(text or '')
        if text is not None and (fields.get('status') or 'open') == 'open' and not fields.get('issue'):
            found.append((unit, fields.get('description', '').strip('"'), text))
    return found


def _identify(root: Path, unnamed: list[tuple[str, str, str]], forge: Forge) -> list[str]:
    """Open (or reuse) each unnamed task's issue and commit its ``issue:`` line, one task at a time."""
    said = []
    for slug, goal, text in unnamed:
        url = forge.open(slug, goal)
        (root / slug / _TASK).write_bytes(_with_issue(text, url).encode('utf-8'))
        commit(root, f'chore(tasks): {slug} names its task:{slug} issue', f'{slug}/{_TASK}')
        said.append(f'opened the task:{slug} issue {url}')
    return said


def migrate(*checkouts: Path, dry_run: bool = False, user_home: Path | None = None, forge: Forge | None = None) -> str:
    """Move each of *checkouts*' retired stores into the ledger, once; the report (also the dry run's plan).

    *forge* opens each migrated open task's issue (default :class:`~dev_lab.dev._task_io.ForgeIssues` on the
    ledger's origin, reached only when a task needs one and never on a dry run).
    """
    root, rel_store = ledger(), '/'.join(RETIRED_STORE)
    resolved = [Path(c).resolve() for c in checkouts]
    plan = _Plan(root, dry_run=dry_run)
    for checkout in resolved:
        store = checkout.joinpath(*RETIRED_STORE)
        if not store.is_dir():
            msg = f'{checkout.as_posix()} holds no retired task store ({rel_store}): nothing to migrate'
            raise TaskRefused(msg)
        for unit in units(store):
            plan.unit(store, unit, checkout.as_posix())
    lines, differ, planned = plan.lines, plan.differ, plan.files
    if differ:
        msg = (
            f'{", ".join(differ)} already in the ledger {root.as_posix()} with different content: nothing migrated.\n'
            f'Door: reconcile each by hand in the ledger through python -m dev_lab.dev.task, then re-run the migration'
        )
        raise TaskRefused(msg)
    home = user_home or Path.home()
    histories = [h for c in resolved for h in _history(c, home)]
    records = sorted(part('state').joinpath('sessions').glob('*.json'))
    kept = [r for r in records if _live(r)]
    sessions = [r for r in records if r not in kept]
    lines += [f'{"would fold" if dry_run else "folded"} authority history {h.as_posix()}' for h in histories]
    lines += [f'{"would delete" if dry_run else "deleted"} binding record {s.as_posix()}' for s in sessions]
    lines += [f'kept binding record {r.as_posix()}: the retired store it names still holds tasks' for r in kept]
    unnamed = _unnamed(root, plan)
    if not dry_run:
        _write(root, planned, f'chore(tasks): migrate the task stores of {", ".join(c.name for c in resolved)}')
        for history in histories:
            taskauthority.fold(root, history.read_text(encoding='utf-8').splitlines())
        for record in sessions:
            record.unlink()
        if unnamed:
            lines += _identify(root, unnamed, forge or ForgeIssues(root))
    else:
        lines += [f'would open the task:{slug} issue' for slug, _, _ in unnamed]
    lines += [f'the owner removes the retired store: git -C {c.as_posix()} rm -r {rel_store}' for c in resolved]
    if dry_run:
        lines.append('dry run: nothing was written')
    return '\n'.join(lines)
