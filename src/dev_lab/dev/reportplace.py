"""REPORTS-LIVE-IN-MEMORY, the Write/Edit half: an agent may not write Markdown under ``output/``.

The shell half is the deny row in :mod:`dev_lab.dev._deny_report_row`; both speak its hazard and
remedy, so the two refusals cannot drift apart. Called by the ``codeplace`` ``PreToolUse`` hook on
``Write|Edit|MultiEdit``, which already parses the payload -- one hook, two placement questions.
"""

from __future__ import annotations

from pathlib import Path

from dev_lab.dev._deny_report_row import REPORTS_LIVE_IN_MEMORY

__all__ = ['refuse_report']


def refuse_report(path: Path) -> str | None:
    """The refusal for writing *path*, or ``None`` when it is not a Markdown file under ``output/``.

    ``output/`` is any path segment of that name below the nearest checkout (the nearest ancestor
    holding ``.git``, so a linked worktree is judged on its own); a path in no checkout is judged
    against its own segments.
    """
    target = Path(path).resolve()
    if target.suffix.lower() != '.md':
        return None
    root = next((c for c in target.parents if (c / '.git').exists()), None)
    parts = target.relative_to(root).parts[:-1] if root else target.parts[:-1]
    if 'output' not in parts:
        return None
    rel = target.relative_to(root).as_posix() if root else target.as_posix()
    row = REPORTS_LIVE_IN_MEMORY
    return f'{row["id"]}: {rel} -- {row["hazard"]} {row["remedy"]}'
