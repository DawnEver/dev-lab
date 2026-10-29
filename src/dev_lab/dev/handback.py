"""AN AGENT RUNS WHAT IT CAN RUN: the ``Stop``/``SubagentStop`` hook refusing a turn that hands the user a command.

THE INCIDENT, 2026-10-26. A session ended its turn with "Here is the same command with an absolute path:
``! /d/.../.venv/Scripts/python.exe -m dev_lab.dev.stoprun --pid 39240``" -- an executable, non-interactive
command the agent could have run through its own shell tool, handed to the user instead. The user ruled
that such work is the agent's, and that the hooks feed it back. ``! <cmd>`` is for what an agent truly
cannot do: an interactive login, a passphrase prompt, a GUI action.

So the final assistant message is read at ``Stop`` and a handed command blocks the stop with a reason the
agent reads: run it yourself; if a guard refused it, follow the refusal's remedy; only an interactive login
goes to the user. :data:`INTERACTIVE_ONLY` is the one place the exceptions are declared. A turn is blocked
once: with ``stop_hook_active`` the agent already saw the reason, and a loop would hold the session.

The same ``Stop`` also ends a session's ROUND, so it asks :mod:`dev_lab.dev.roundgate` (ROUND-ENDS-GREEN) whether
every head the session pushed is green or watched while pending. A ``SubagentStop`` does not: a subagent hands
back to its session, which owns the round.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Final, TextIO

from lab_commons.log import emit

from dev_lab.dev.roundgate import for_session

__all__ = ['INTERACTIVE_ONLY', 'handed_commands', 'last_assistant_text', 'main', 'refusal', 'round_refusal']

#: THE ALLOW-SET, ONE PLACE: command prefixes that need a human at a prompt or a browser. Nothing else may
#: be handed to the user, because everything else the agent can run itself.
INTERACTIVE_ONLY: Final[tuple[str, ...]] = (
    'gh auth login',
    'gh auth refresh',
    'gcloud auth login',
    'gcloud auth application-default login',
    'az login',
    'aws sso login',
    'npm login',
    'docker login',
    'ssh-add',
    'ssh-keygen',
    'gpg --full-generate-key',
    'claude login',
    'codex login',
    '/login',
)

#: An imperative to the reader, in either language the family speaks.
_ASKS: Final = re.compile(
    r'(?:\b(?:please|you\s+can|you\s+could|you\s+may|you\s+need\s+to|you\'ll\s+need\s+to)\s+(?:re-?)?run\b'
    r'|\brun\s+(?:this|the\s+following|it\s+yourself)\b|^\s*run\s*:'
    r'|\u5728\u7ec8\u7aef(?:\u4e2d)?\u8fd0\u884c|\u8bf7(?:\u5728\u7ec8\u7aef)?(?:\u6267\u884c|\u8fd0\u884c))',
    re.IGNORECASE | re.MULTILINE,
)
_BANG: Final = re.compile(r'^\s*(?:[-*>]\s*)?`?!\s*([^`\n]+?)`?\s*$|`!\s*([^`\n]+)`', re.MULTILINE)
_FENCE: Final = re.compile(r'```[^\n]*\n(.*?)```', re.DOTALL)
_INLINE: Final = re.compile(r'`([^`\n]+)`')
#: How far past an imperative its command may sit (the "Please run:\n\n```" shape).
_REACH: Final = 400


def _looks_runnable(code: str) -> bool:
    """A code span that is a command line, not an identifier: it has a space or a path separator."""
    return bool(code) and (' ' in code or '/' in code or '\\' in code)


def handed_commands(text: str) -> tuple[str, ...]:
    """Every command *text* hands the reader to run: ``! <cmd>`` lines, and code after an imperative."""
    found = [(m.group(1) or m.group(2)).strip() for m in _BANG.finditer(text)]
    for ask in _ASKS.finditer(text):
        tail = text[ask.end() : ask.end() + _REACH]
        fence = _FENCE.search(tail)
        inline = _INLINE.search(tail)
        first = min((m for m in (fence, inline) if m), key=lambda m: m.start(), default=None)
        if first is None:
            continue
        if first is fence:
            found += [line.strip() for line in first.group(1).splitlines() if line.strip()]
        elif _looks_runnable(first.group(1).strip()):
            found.append(first.group(1).strip().lstrip('!').strip())
    return tuple(dict.fromkeys(c for c in found if c))


def _interactive(command: str) -> bool:
    return command.lower().startswith(INTERACTIVE_ONLY)


def refusal(text: str) -> str | None:
    """The block reason when *text* hands the user a command that is not interactive-only, else ``None``."""
    runnable = [c for c in handed_commands(text) if not _interactive(c)]
    if not runnable:
        return None
    listed = '; '.join(f'`{c}`' for c in runnable)
    return (
        f'AGENT-RUNS-ITS-OWN-COMMANDS: this turn hands the user a command to run ({listed}). Run it yourself '
        'through your shell tool, with absolute paths, and report the result. If a guard refused it, follow '
        "the refusal's remedy -- it names the door an agent uses. Only an interactive login, passphrase or GUI "
        f'step may go to the user (`! <cmd>`), and only these: {", ".join(INTERACTIVE_ONLY)}.'
    )


def _text_of(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ''
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get('type') == 'text':
            parts.append(str(block.get('text', '')))
        elif block.get('type') == 'tool_use' and isinstance(block.get('input'), dict):
            # A subagent's final report travels as a hand-back tool's ``message``.
            parts.append(str(block['input'].get('message', '')))
    return '\n'.join(p for p in parts if p)


def last_assistant_text(transcript: Path) -> str:
    """The text of the LAST assistant entry of a transcript JSONL; empty when there is none."""
    last = ''
    for line in transcript.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        message = row.get('message') if isinstance(row, dict) else None
        if isinstance(message, dict) and message.get('role') == 'assistant':
            text = _text_of(message.get('content'))
            if text:
                last = text
    return last


def _final_text(payload: dict) -> str:
    given = payload.get('last_assistant_message')
    if isinstance(given, str) and given:
        return given
    for key in ('agent_transcript_path', 'transcript_path'):
        path = payload.get(key)
        if isinstance(path, str) and path and Path(path).is_file():
            return last_assistant_text(Path(path))
    return ''


def round_refusal(cwd: str) -> str | None:
    """Why the session working in *cwd* may not end its round (:func:`dev_lab.dev.roundgate.for_session`)."""
    return for_session(Path(cwd))


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """The hook: read the payload, block a handed command once, else stay silent. Never exits nonzero."""
    del argv
    try:
        payload = json.load(stdin or sys.stdin)
    except ValueError:
        return 0
    if not isinstance(payload, dict) or payload.get('stop_hook_active'):
        return 0
    try:
        reason = refusal(_final_text(payload))
    except OSError:
        reason = None
    if reason is None and payload.get('hook_event_name', 'Stop') == 'Stop':
        reason = round_refusal(str(payload.get('cwd') or Path.cwd()))
    if reason is not None:
        emit(json.dumps({'decision': 'block', 'reason': reason}))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
