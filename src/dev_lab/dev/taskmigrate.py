"""THE ONE-TIME MIGRATION of a checkout's retired task store into the machine's task ledger (FORMATS-MIGRATE-ONCE).

``python -m dev_lab.dev.task migrate <checkout> [--dry-run]`` (:func:`migrate`):

1. every task directory of ``<checkout>``'s retired store (:data:`~dev_lab.dev.taskledger.RETIRED_STORE`) -- a
   ``<slug>/`` and each ``archive/<date>/<slug>/`` -- is a UNIT, read from the working tree (tracked and untracked
   files alike; the retired ``.bindings`` and every dot entry skipped). A unit byte-identical in the ledger is
   skipped; one that DIFFERS refuses the WHOLE run, by name, before any write;
2. the rest are copied into :func:`~dev_lab.dev.taskledger.ledger` and committed there (local only);
3. the checkout's retired rem authority history (``~/.claude/rem/authority/<key>.jsonl``, keyed by the checkout's
   path or its store's) is folded into the one store (:func:`dev_lab.dev.taskauthority.fold`);
4. the retired per-session binding records, ``<machine home>/state/sessions/*.json``, are deleted.

It never deletes the checkout's tree: it prints the ``git rm`` its owner runs. ``--dry-run`` writes nothing and
lists everything it would do.
"""

from __future__ import annotations

import filecmp
import hashlib
import shutil
from pathlib import Path
from typing import Final

from lab_commons.home import part

from dev_lab.dev import taskauthority
from dev_lab.dev.taskledger import RETIRED_STORE, ledger

__all__ = ['RETIRED_AUTHORITY', 'migrate', 'units']

#: Where rem kept its authority history, below the user's home.
RETIRED_AUTHORITY: Final = ('.claude', 'rem', 'authority')
_SKIPPED: Final = '.bindings'


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


def _same(old: Path, new: Path) -> bool:
    a, b = _files(old), _files(new)
    return a.keys() == b.keys() and all(filecmp.cmp(a[k], b[k], shallow=False) for k in a)


def _history(checkout: Path, home: Path) -> list[Path]:
    keys = {
        hashlib.sha256(str(p).encode('utf-8')).hexdigest()[:16] for p in (checkout, checkout.joinpath(*RETIRED_STORE))
    }
    folder = home.joinpath(*RETIRED_AUTHORITY)
    return [folder / f'{k}.jsonl' for k in sorted(keys) if (folder / f'{k}.jsonl').is_file()]


def migrate(checkout: Path, *, dry_run: bool = False, user_home: Path | None = None) -> str:
    """Move *checkout*'s retired store into the ledger, once; the report (also the dry run's plan)."""
    from dev_lab.dev.task import TaskRefused, _commit  # noqa: PLC0415 -- task imports this module lazily

    checkout = Path(checkout).resolve()
    store, root = checkout.joinpath(*RETIRED_STORE), ledger()
    rel_store = '/'.join(RETIRED_STORE)
    if not store.is_dir():
        msg = f'{checkout.as_posix()} holds no retired task store ({rel_store}): nothing to migrate'
        raise TaskRefused(msg)
    todo = units(store)
    differ = [u for u in todo if (root / u).exists() and not _same(store / u, root / u)]
    if differ:
        msg = (
            f'{", ".join(differ)} already in the ledger {root.as_posix()} with different content: nothing migrated.\n'
            f'Door: reconcile each by hand in the ledger through python -m dev_lab.dev.task, then re-run the migration'
        )
        raise TaskRefused(msg)
    copy = [u for u in todo if not (root / u).exists()]
    skip = [u for u in todo if u not in copy]
    histories = _history(checkout, user_home or Path.home())
    sessions = sorted(part('state').joinpath('sessions').glob('*.json'))
    lines = [f'{"would copy" if dry_run else "copied"} {u}' for u in copy]
    lines += [f'skipped {u} (byte-identical in the ledger)' for u in skip]
    lines += [f'{"would fold" if dry_run else "folded"} authority history {h.as_posix()}' for h in histories]
    lines += [f'{"would delete" if dry_run else "deleted"} binding record {s.as_posix()}' for s in sessions]
    if not dry_run:
        for unit in copy:
            shutil.copytree(store / unit, root / unit)
        if copy:
            _commit(root, f'chore(tasks): migrate {len(copy)} task(s) from {checkout.name}', *copy)
        for history in histories:
            taskauthority.fold(root, history.read_text(encoding='utf-8').splitlines())
        for record in sessions:
            record.unlink()
    lines.append(f'the checkout owner removes the retired store: git -C {checkout.as_posix()} rm -r {rel_store}')
    if dry_run:
        lines.append('dry run: nothing was written')
    return '\n'.join(lines)
