"""INJECTED-TEXT-IS-PROGRESSIVE: what the family injects into an agent is short and points at the rest.

The BUDGETS are declared data, one row per injected surface, and this module is their one source.
A refusal is three lines -- what was refused and why, the door, a ``details:`` pointer -- and the
history behind it lives in ``docs-src/dev/refusals.md``, one hop away. Reasoning:
``docs-src/dev/refusals.md#the-shape-of-a-refusal``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    'BUDGETS',
    'DETAILS_PREFIX',
    'REFUSALS_DOC',
    'Budget',
    'InjectedTextOverBudget',
    'anchors',
    'details_for',
    'pointer',
    'problems',
    'unresolved_pointers',
]


@dataclass(frozen=True, slots=True)
class Budget:
    """The most an injected text may carry: physical lines, characters per line, and a required pointer."""

    max_lines: int
    max_line_chars: int
    needs_details: bool


#: One row per injected surface. ``refusal`` is a deny reason as rendered; ``cross-repo-refusal`` is
#: the same with the engine's one header line naming the targeted repo.
BUDGETS: Final[dict[str, Budget]] = {
    'refusal': Budget(max_lines=3, max_line_chars=320, needs_details=True),
    'cross-repo-refusal': Budget(max_lines=4, max_line_chars=320, needs_details=False),
}

#: The page that holds every universal refusal's full text, relative to the lab-commons root.
REFUSALS_DOC: Final = 'docs-src/dev/refusals.md'
DETAILS_PREFIX: Final = 'details: '
_POINTER: Final = re.compile(r'^details: (?P<path>[\w./-]+\.md)#(?P<anchor>[a-z0-9-]+)(?: \(lab-commons\))?$')


class InjectedTextOverBudget(AssertionError):
    """An injected text is longer than its declared budget, or its details pointer is missing."""


def details_for(rule_id: str) -> str:
    """The ``details:`` line for a universal deny row: its section in :data:`REFUSALS_DOC`."""
    return f'{DETAILS_PREFIX}{REFUSALS_DOC}#{rule_id.lower()} (lab-commons)'


def pointer(text: str) -> tuple[str, str] | None:
    """The ``(path, anchor)`` the last line of *text* points at, or ``None`` when it points nowhere."""
    found = _POINTER.match(text.rstrip('\n').rsplit('\n', 1)[-1])
    return (found['path'], found['anchor']) if found else None


def problems(text: str, surface: str) -> list[str]:
    """Every way *text* breaks the budget declared for *surface*; empty when it fits."""
    budget = BUDGETS[surface]
    lines = text.rstrip('\n').split('\n')
    found = []
    if len(lines) > budget.max_lines:
        found.append(f'{len(lines)} lines > {budget.max_lines}')
    found.extend(
        f'line {n} is {len(line)} chars > {budget.max_line_chars}'
        for n, line in enumerate(lines, 1)
        if len(line) > budget.max_line_chars
    )
    if budget.needs_details and pointer(text) is None:
        found.append(f'no closing "{DETAILS_PREFIX}<page>.md#<anchor>" line')
    return found


def anchors(markdown: str) -> set[str]:
    """The heading anchors of *markdown*, slugged as the docs site and the forge both slug them."""
    slugs = set()
    for line in markdown.splitlines():
        heading = re.match(r'^#{1,6}\s+(.*?)\s*$', line)
        if heading:
            slug = re.sub(r'[^\w\- ]', '', heading[1].lower()).replace(' ', '-')
            slugs.add(slug)
    return slugs


def unresolved_pointers(texts: dict[str, str], root: Path) -> list[str]:
    """The keys of *texts* whose ``details:`` pointer names no file or no anchor under *root*."""
    bad = []
    for key, text in texts.items():
        target = pointer(text)
        page = root / target[0] if target else None
        readable = page is not None and page.is_file()
        if not readable or target[1] not in anchors(page.read_text(encoding='utf-8')):
            bad.append(key)
    return bad
