"""The dispatcher's ONE ANSWER: every row's outcome merged into the hook's stdout and stderr.

Split from :mod:`dev_lab.dev.hookdispatch` (module-size band). The rules, stated there, are kept here:

* a refusal -- exit 2, ``decision: block``, ``permissionDecision: deny`` -- counts only from a ``may_block`` row; any
  other row's is a wiring fault, said on stderr and passed;
* refusals join into one ``deny`` (``PreToolUse``) or one ``decision: block``; additional context and system
  messages join; a row's plain stdout is context on ``UserPromptSubmit``/``SessionStart`` (the tool's own rule) and
  stderr elsewhere;
* a row that crashes or exits another nonzero code is one stderr line, never a block.

A BACKGROUND run (:func:`deferred_text`) answers nothing now: everything its rows said, a guard's refusal included,
becomes one text the session reads at its next context event.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dev_lab.dev.agent_wiring import Wire

__all__ = ['CONTEXT_EVENTS', 'Outcome', 'answer', 'deferred_text', 'parsed']

#: Events whose plain stdout the tool hands the model as context.
_TEXT_IS_CONTEXT: Final = frozenset({'UserPromptSubmit', 'SessionStart'})
#: Events whose JSON answer carries ``hookSpecificOutput.additionalContext``.
CONTEXT_EVENTS: Final = frozenset(
    {'PreToolUse', 'PostToolUse', 'PostToolUseFailure', 'UserPromptSubmit', 'SessionStart'}
)
#: A handler's refusing exit code (the tool's own convention).
_REFUSED: Final = 2


@dataclass(frozen=True, slots=True)
class Outcome:
    """What one row did: its exit code (``None``: outlived its bound), its stdout, its stderr and its wall time."""

    wire: Wire
    code: int | None
    out: str
    err: str
    ms: float = 0.0


def parsed(text: str) -> dict[str, Any] | None:
    """*text* as a JSON object, else ``None``."""
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


@dataclass(slots=True)
class _Merged:
    """The rows' answers, gathered: refusals, contexts, system messages and stderr notes."""

    event: str
    blocks: list[str] = field(default_factory=list)
    contexts: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def take(self, one: Outcome) -> None:
        name = one.wire.name
        if one.code == _REFUSED and one.wire.may_block:
            self.blocks.append(one.err.strip() or f'{name} refused')
            return
        if one.err:
            self.notes.append(one.err.rstrip('\n'))
        if one.code is None:
            self.notes.append(f'[hook] {name} outlived its {one.wire.background_bound:g}s bound; passed')
        elif one.code:
            self.notes.append(f'[hook] {name} exited {one.code}; not a refusal, so it passed')
        elif (said := parsed(one.out.strip())) is not None:
            self._said(name, said, may_block=one.wire.may_block)
        elif one.out.strip():
            (self.contexts if self.event in _TEXT_IS_CONTEXT else self.notes).append(one.out.strip())

    def _said(self, name: str, said: dict[str, Any], *, may_block: bool) -> None:
        specific = said.get('hookSpecificOutput') if isinstance(said.get('hookSpecificOutput'), dict) else {}
        refusal = said.get('reason') if said.get('decision') == 'block' else None
        if specific.get('permissionDecision') == 'deny':
            refusal = specific.get('permissionDecisionReason')
        if refusal is not None and not may_block:
            self.notes.append(f'[hook] {name} answered a refusal but is not wired may_block; passed: {refusal}')
        elif refusal is not None:
            self.blocks.append(str(refusal))
        if specific.get('additionalContext'):
            self.contexts.append(str(specific['additionalContext']))
        if said.get('systemMessage'):
            self.messages.append(str(said['systemMessage']))


def answer(
    event: str, outcomes: Sequence[Outcome], *, contexts: Sequence[str] = (), messages: Sequence[str] = ()
) -> tuple[str, str]:
    """``(stdout, stderr)`` of the dispatcher: the rows' answers, plus *contexts* and *messages*, merged into one."""
    merged = _Merged(event, contexts=list(contexts), messages=list(messages))
    for one in outcomes:
        merged.take(one)
    return _render(event, merged.blocks, merged.contexts, merged.messages), '\n'.join(merged.notes)


def deferred_text(event: str, outcomes: Sequence[Outcome]) -> str:
    """Everything *event*'s background rows said, as one text; a refusal is a note, never a block. ``''``: silence."""
    merged = _Merged(event)
    for one in outcomes:
        merged.take(one)
    said = [*(f'(refused after the hook returned) {one}' for one in merged.blocks), *merged.contexts]
    return '\n'.join([*said, *merged.messages, *merged.notes])


def _render(event: str, blocks: list[str], contexts: list[str], messages: list[str]) -> str:
    out: dict[str, Any] = {}
    if blocks and event == 'PreToolUse':
        reason = '\n'.join(blocks)
        out['hookSpecificOutput'] = {
            'hookEventName': event,
            'permissionDecision': 'deny',
            'permissionDecisionReason': reason,
        }
    elif blocks:
        out.update(decision='block', reason='\n'.join(blocks))
    if contexts and event in CONTEXT_EVENTS:
        out.setdefault('hookSpecificOutput', {'hookEventName': event})['additionalContext'] = '\n'.join(contexts)
    else:
        messages = [*contexts, *messages]
    if messages:
        out['systemMessage'] = '\n'.join(messages)
    return json.dumps(out) if out else ''
