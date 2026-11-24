"""THE FAMILY SECTION OF AGENTS.md (user ruling 2026-11-24): AGENTS.md is the ONE agent entry.

dev-lab renders a MANAGED section between :data:`BEGIN` and :data:`END` -- the principles from
:data:`dev_lab.dev.principles.PRINCIPLES` and the family workflow rules from the rules registry, cited by ID
with their first sentence -- and the repo writes everything outside the markers. A hand edit between the
markers is RED (:mod:`dev_lab.dev.famtests.agentsection`); `.claude/rules/` is retired with it.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING, Final

from dev_lab.dev.docwidth import WIDTH_CEILING
from dev_lab.dev.principles import bullet_lines
from dev_lab.dev.rules import RULES

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['AGENTS_REL', 'BEGIN', 'END', 'WORKFLOW_RULES', 'held_section', 'render_section', 'repo_text', 'splice']

AGENTS_REL: Final = 'AGENTS.md'
BEGIN: Final = '<!-- BEGIN dev-lab family section -->'
END: Final = '<!-- END dev-lab family section -->'

#: The family workflow an agent needs on every turn, by registry ID, in reading order. The statement is the
#: registry's (single source of truth); the section quotes its first sentence and cites the ID for the rest.
WORKFLOW_RULES: Final[tuple[str, ...]] = (
    'SHARED-CHECKOUT',
    'ONE-BRANCH-PER-SESSION',
    'PRS-TARGET-INTEGRATION',
    'DOWNSTREAM-SYNCS-INTEGRATION',
    'SUBAGENT-NO-PUSH',
    'VERDICTS-FROM-THE-FORGE',
    'TRUNK-MOVES-BY-FAST-FORWARD',
    'MERGE-OR-DELETE',
    'AGENT-GUARD',
    'NETWORK-RETRY-THEN-REPORT',
    'PRODUCTION-ENTRY-POINT',
)


def _first_sentence(statement: str) -> str:
    head, dot, _rest = statement.partition('. ')
    return head + ('.' if dot else '')


def _bullets(items: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for item in items:
        out += textwrap.wrap(item, width=WIDTH_CEILING, subsequent_indent='  ', break_on_hyphens=False)
    return out


def render_section() -> str:
    """The managed section, markers included, newline-terminated."""
    by_id = {rule.id: rule for rule in RULES}
    missing = [rule_id for rule_id in WORKFLOW_RULES if rule_id not in by_id]
    if missing:
        msg = f'WORKFLOW_RULES names {missing}, which the rules registry does not hold: a citation of nothing'
        raise KeyError(msg)
    lines = [
        BEGIN,
        '',
        '## Family principles',
        '',
        '_Rendered by `dev_lab.dev.agentsection` from `dev_lab.dev.principles`; a hand edit here is refused._',
        '',
        *bullet_lines(),
        '',
        '## Family workflow',
        '',
        '_Each rule is cited by ID; its full statement and refusing mechanism live in `dev_lab.dev.rules`._',
        '',
        *_bullets(tuple(f'- `{rid}`: {_first_sentence(by_id[rid].statement)}' for rid in WORKFLOW_RULES)),
        '',
        END,
    ]
    return '\n'.join(lines) + '\n'


def held_section(text: str) -> str | None:
    """The section *text* holds, markers included and newline-terminated, or ``None`` when it holds none.

    RAISES :class:`ValueError` when the markers are not exactly one ``BEGIN`` followed by one ``END``.
    """
    begins, ends = text.count(BEGIN), text.count(END)
    if begins == ends == 0:
        return None
    start, stop = text.find(BEGIN), text.find(END)
    if begins != 1 or ends != 1 or stop < start:
        msg = f'{AGENTS_REL} must hold exactly one {BEGIN} before one {END}; it holds {begins} and {ends}'
        raise ValueError(msg)
    return text[start : stop + len(END)] + '\n'


def repo_text(text: str) -> str:
    """*text* without its family section: the part the repo writes, which a restated-rule reading judges."""
    if held_section(text) is None:
        return text
    return text[: text.find(BEGIN)] + text[text.find(END) + len(END) :]


def splice(text: str) -> str:
    """*text* with its section replaced by :func:`render_section`, or the section appended when it has none."""
    section = render_section()
    held = held_section(text)
    if held is None:
        return (text.rstrip('\n') + '\n\n' if text.strip() else '') + section
    start = text.find(BEGIN)
    stop = text.find(END) + len(END)
    rest = text[stop:]
    return text[:start] + section.rstrip('\n') + (rest or '\n')


def render_into(root: Path, *, write: bool) -> str:
    """Re-render *root*'s AGENTS.md section; one status line. *write* false: the check mode."""
    path = root / AGENTS_REL
    held = path.read_text(encoding='utf-8') if path.is_file() else ''
    wanted = splice(held)
    if wanted == held:
        return f'{AGENTS_REL}: current'
    if not write:
        return f'{AGENTS_REL}: would render ({"absent" if not held else "drifted"})'
    path.write_text(wanted, encoding='utf-8', newline='\n')
    return f'{AGENTS_REL}: rendered'
