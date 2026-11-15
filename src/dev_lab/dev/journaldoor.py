"""TRACKED-CITES-NO-EPHEMERAL AT THE DOOR: a task-journal append citing an ignored path is refused before it is written.

THE INCIDENT, dev-lab#419 (2026-11-11). An agent appended a progress line through rem's door (``task.js log``)
citing a git-ignored path. The commit-time check (:mod:`dev_lab.dev.ephemeralrefs`) then refused the journal,
rem's task guard refused every repair (the journal is append-only), the escape ceiling only goes down, and the
hand-back hook refused the ``! sed`` the agent proposed. Four guards, each right, and no remedy any of them allowed.

THE CAUSE is the order: the check ran at COMMIT time on a line written at APPEND time through a door with no undo.
So this ``PreToolUse`` hook runs the SAME predicate (:func:`dev_lab.dev.ephemeralrefs.cited_in_text`) on the text a
``task.js log|decide|open-item|close-item|handoff`` command is about to append, and denies the call naming a
rephrase every other guard allows: a memory name or a ``<placeholder>`` shape. Only the appended words are
judged -- a chained ``&& cat output/x`` is not the journal's text. A command the lexer cannot split is judged
whole from the verb on, so a heredoc-built line is refused rather than missed.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

import lab_commons.launch as _door

from dev_lab.dev import walls
from dev_lab.dev.agent_wiring import SHELL_TOOLS
from dev_lab.dev.ephemeralrefs import RULE, cited_in_text

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ['JOURNAL_VERBS', 'RULE', 'appended_texts', 'main', 'refusal']

#: rem's journal verbs: the ones whose words ``task.js`` appends to ``JOURNAL.md`` (rem ``scripts/task.js``).
JOURNAL_VERBS: Final = frozenset({'log', 'decide', 'open-item', 'close-item', 'handoff'})
#: ``task.js`` flags that take a value; the value is routing, not journal text.
_VALUED: Final = frozenset({'--task', '--scope', '--owner'})
_DOOR: Final = 'task.js'
_REMEDY: Final = (
    'rephrase the text before it is appended: cite a memory entry by name or the path as a <placeholder> shape '
    '(output/logs/<yy>/<mm>/<dd>/<kind>/) -- a written journal line is append-only, so this is the last point '
    'the agent can still change it'
)


def _words_after(words: list[str], start: int) -> list[str]:
    out: list[str] = []
    skip = False
    for word in words[start:]:
        if word and set(word) <= set(';&|'):
            break
        if skip:
            skip = False
        elif word.startswith('--'):
            skip = word in _VALUED
        else:
            out.append(word)
    return out


def appended_texts(command: str) -> list[str]:
    """The text each journal-verb ``task.js`` call in *command* would append; ``[]`` when there is none."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.escape = ''
    try:
        words = list(lexer)
    except ValueError:
        _, found, rest = command.partition(_DOOR)
        verb = rest.strip('\'" ').split(maxsplit=1)
        return [rest] if found and verb and verb[0] in JOURNAL_VERBS else []
    texts: list[str] = []
    for i, word in enumerate(words[:-1]):
        if Path(word.replace('\\', '/')).name == _DOOR and words[i + 1] in JOURNAL_VERBS:
            texts.append(' '.join(_words_after(words, i + 2)))
    return texts


def _toplevel(cwd: str) -> Path | None:
    answer = _door.run(
        ['git', 'rev-parse', '--show-toplevel'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        cwd=cwd,
        check=False,
        timeout=60,
    )
    return Path(answer.stdout.strip()) if answer.returncode == 0 and answer.stdout.strip() else None


def refusal(payload: Mapping[str, object]) -> str | None:
    """The deny reason for a shell call appending an ephemeral cite to a task journal, else ``None``."""
    tool_input = payload.get('tool_input')
    if payload.get('tool_name') not in SHELL_TOOLS or not isinstance(tool_input, dict):
        return None
    texts = appended_texts(str(tool_input.get('command', '')))
    # task.js writes under CLAUDE_PROJECT_DIR, else its cwd: judge in the same repo.
    where = os.environ.get('CLAUDE_PROJECT_DIR') or str(payload.get('cwd') or Path.cwd())
    root = _toplevel(where) if texts else None
    if root is None:
        return None
    refused = {token: why for text in texts for token, why in cited_in_text(root, text).items()}
    if not refused:
        return None
    cites = '; '.join(f'cites {why} {token!r}' for token, why in sorted(refused.items()))
    return f'[{RULE}] the task journal line {cites}.\nRemedy: {_REMEDY}.'


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    """The hook: deny the call with a reason, or stay silent. Never exits nonzero; an unreadable payload is silent."""
    del argv
    try:
        payload = json.load(stdin or sys.stdin)
    except ValueError:
        return 0
    try:
        reason = refusal(payload) if isinstance(payload, dict) else None
    except (OSError, RuntimeError):
        return 0
    if reason is not None:
        walls.refused_text(
            Path(payload.get('cwd') or Path.cwd()), reason, reason='pre-tool', rule=RULE,
            session=str(payload.get('session_id') or ''),
        )  # fmt: skip
        decision = {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny', 'permissionDecisionReason': reason}
        (stdout or sys.stdout).write(json.dumps({'hookSpecificOutput': decision}) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
