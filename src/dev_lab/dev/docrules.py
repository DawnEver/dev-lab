"""BEFORE A DOCUMENT IS EDITED, PUT THE DOCUMENT RULES BACK IN FRONT OF THE WRITER: ``python -m dev_lab.dev.docrules``.

The rules are read at session start and the doc edit happens an hour later, so what fails is RECALL, not the rules:
one session restated a constraint in two files, quoted an unmeasured number as a requirement, and wrote mechanism
into a constraints-only page. A ``PreToolUse`` row on the write tools re-injects them at the one moment they bind.

IT QUOTES; IT DOES NOT RESTATE. This module holds only the IDS of the rules a document is held to
(:data:`DOC_RULES`, :data:`DOC_PRINCIPLES`); each statement is read from its one home -- :data:`dev_lab.dev.rules.RULES`
and :data:`dev_lab.dev.principles.PRINCIPLES` -- so a hook carrying its own copy cannot become a third place for the
rules to drift. An id with no home raises at import, so a retired rule cannot be quoted as live.

SCOPE: prose -- any ``*.md``, anything under ``docs-src/`` or ``.claude/rules/``, and ``AGENTS.md`` / ``README.md`` /
``CLAUDE.md``. A source file is not a doc: firing on every edit would make the hook noise, and noise is how a guard
stops being read. It never blocks; an unreadable payload answers nothing.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev.principles import PRINCIPLES
from dev_lab.dev.rules import RULES

if TYPE_CHECKING:
    from typing import TextIO

__all__ = ['DOC_PRINCIPLES', 'DOC_RULES', 'is_doc', 'main', 'render']

#: The family rules a document is held to, by id.
DOC_RULES: Final[tuple[str, ...]] = ('DOCS-SPLIT', 'NAMED-SETS-NOT-COUNTS', 'RETIRED-NAMES-REGISTERED')

#: The principles a document is held to, by id.
DOC_PRINCIPLES: Final[tuple[str, ...]] = ('single-source-of-truth', 'progressive-disclosure', 'names-match-behaviour')

_DOC_PREFIXES: Final = ('.claude/rules/', 'docs-src/')
_DOC_NAMES: Final = frozenset({'AGENTS.md', 'README.md', 'CLAUDE.md'})
_WRITING: Final = frozenset({'Write', 'Edit', 'MultiEdit', 'NotebookEdit'})


def _statements() -> tuple[tuple[str, str], ...]:
    rules = {rule.id: rule.statement for rule in RULES}
    principles = {one.id: one.statement for one in PRINCIPLES}
    missing = [rid for rid in DOC_RULES if rid not in rules] + [pid for pid in DOC_PRINCIPLES if pid not in principles]
    if missing:
        msg = f'docrules quotes ids with no home in dev_lab.dev.rules / principles: {", ".join(missing)}'
        raise LookupError(msg)
    return tuple((rid, rules[rid]) for rid in DOC_RULES) + tuple((pid, principles[pid]) for pid in DOC_PRINCIPLES)


_QUOTED: Final = _statements()


def is_doc(file_path: str) -> bool:
    """Whether *file_path* is a document held to the prose rules."""
    if not file_path:
        return False
    normalised = '/' + file_path.replace('\\', '/')
    name = normalised.rsplit('/', 1)[-1]
    return any(f'/{prefix}' in normalised for prefix in _DOC_PREFIXES) or name in _DOC_NAMES or name.endswith('.md')


def render() -> str:
    """The quoted rules, one ``- ID: statement`` line each, under a one-line lead."""
    lines = [f'- {rid}: {statement}' for rid, statement in _QUOTED]
    return 'You are about to edit a DOCUMENT. The family rules for one, quoted from dev_lab.dev.rules:\n' + '\n'.join(
        lines
    )


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """The ``PreToolUse`` hook on the write tools: re-inject :func:`render` before a doc edit; never blocks."""
    del argv
    try:
        payload = json.load(stdin or sys.stdin)
    except ValueError:
        return 0
    if not isinstance(payload, dict) or payload.get('tool_name') not in _WRITING:
        return 0
    tool_input = payload.get('tool_input')
    target = (
        str(tool_input.get('file_path') or tool_input.get('notebook_path') or '')
        if isinstance(tool_input, dict)
        else ''
    )
    if is_doc(target):
        emit(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'additionalContext': render()}}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
