"""THE GITIGNORED FILES A WORKTREE IS GATED WITH, declared as data and copied in by ``dep --bootstrap``.

``git worktree add`` materialises TRACKED files and nothing else, so a new worktree lands without the
untracked inputs its main checkout runs with -- an untracked resolution lock (a ``Cargo.lock`` that,
absent, re-resolves against today's index and silently changes the crate set) is the measured case.
A gate reporting that absence as a failure measures its own harness, not the tree.

A repo declares the paths, repo-relative, and NOTHING else::

    [tool.dev_lab.worktree]
    seeds = ["rust/Cargo.lock"]

:func:`seed` copies each declared path from the main checkout into a linked worktree when the worktree
lacks it. A seed the main checkout itself lacks is REPORTED, never fatal: every seed is gitignored, so
"required" can never be a property of the repository, only of a box. A file already present is never
overwritten -- the worktree's own copy is the one its history chose.
"""

from __future__ import annotations

import shutil
import tomllib
from typing import TYPE_CHECKING

from dev_lab.dev.familyroot import main_checkout

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['declared_seeds', 'seed']


def declared_seeds(root: Path) -> tuple[str, ...]:
    """``[tool.dev_lab.worktree] seeds`` of *root*'s pyproject; ``()`` when undeclared.

    Raises:
        ValueError: a seed is not a repo-relative path inside the checkout.

    """
    manifest = root / 'pyproject.toml'
    table = tomllib.loads(manifest.read_text(encoding='utf-8')) if manifest.is_file() else {}
    seeds = tuple(table.get('tool', {}).get('dev_lab', {}).get('worktree', {}).get('seeds', ()))
    for rel in seeds:
        if rel.startswith(('/', '\\')) or '..' in rel.replace('\\', '/').split('/') or ':' in rel:
            where = f'[tool.dev_lab.worktree] seeds in {manifest}'
            msg = f'{where}: {rel!r} is not a repo-relative path inside the checkout'
            raise ValueError(msg)
    return seeds


def seed(root: Path, *, main: Path | None = None) -> list[str]:
    """Copy each declared seed from the main checkout into *root* where absent; one line per seed acted on."""
    seeds = declared_seeds(root)
    if not seeds:
        return []
    source = main_checkout(root) if main is None else main
    if source.resolve() == root.resolve():
        return []
    lines = []
    for rel in seeds:
        target, origin = root / rel, source / rel
        if target.exists():
            continue
        if not origin.is_file():
            lines.append(f'seed {rel}: absent from the main checkout {source} too -- not copied')
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target)
        lines.append(f'seed {rel}: copied from {source}')
    return lines
