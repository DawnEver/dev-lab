"""HARD RULES AT SESSION START: a harness that does not load ``.claude/rules/`` itself is handed them as context.

Kept from the retired rem plugin (user ruling 2026-11-23), now dev-lab's: Claude Code auto-loads
``<root>/.claude/rules/**/*.md`` every session, another harness (Codex, Antigravity) does not, so this
``SessionStart`` row prints every rules page of the session's repo, sorted, each headed by its repo-relative path --
except under Claude Code (:func:`dev_lab.dev.native_session.primary_of`), where it would only say them twice, and on
a resumed or forked session, whose context still holds them. Only the repo ROOT's rules: scoped rules are retired.

``python -m dev_lab.dev.rulesinject`` reads the hook payload (``cwd``, ``source``) on stdin; it always exits 0.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev.native_session import primary_of

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = ['LOADS_RULES_ITSELF', 'main', 'rules_context']

#: The harness whose own loader reads ``.claude/rules/`` (its primary session key).
LOADS_RULES_ITSELF: Final = 'CLAUDE_CODE_SESSION_ID'
_KEPT_CONTEXT: Final = frozenset({'resume', 'fork'})


def rules_context(root: Path) -> str:
    """Every ``.claude/rules/**/*.md`` under *root*, sorted, as one text; ``''`` when there is none."""
    rules = root / '.claude' / 'rules'
    pages = sorted(rules.rglob('*.md')) if rules.is_dir() else []
    blocks = [
        f'Contents of {page.relative_to(root).as_posix()}:\n\n{page.read_text(encoding="utf-8").rstrip()}'
        for page in pages
    ]
    return '\n\n'.join(blocks)


def _wanted(payload: Mapping[str, object], env: Mapping[str, str]) -> bool:
    try:
        harness = primary_of(env)
    except ValueError:
        harness = ''
    return harness != LOADS_RULES_ITSELF and payload.get('source') not in _KEPT_CONTEXT


def main(argv: Sequence[str] | None = None) -> int:
    """The ``SessionStart`` hook: print the rules context where the harness needs it; always 0."""
    del argv
    try:
        payload = json.loads(sys.stdin.read() or '{}')
    except ValueError:
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    if not _wanted(payload, os.environ):
        return 0
    root = Path(os.environ.get('CLAUDE_PROJECT_DIR') or payload.get('cwd') or Path.cwd())
    if text := rules_context(root):
        emit(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
