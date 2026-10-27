"""THE FAMILY'S ENGINEERING PRINCIPLES: one tuple, here, and everything else derived from it.

Family policy (user ruling 2026-10-27): every coding agent in every family repo reads them up front, and
every reviewer judges a change against them. ONE source, two derivations:

* :func:`render` -> ``.claude/rules/principles.md`` (:data:`PAGE_REL`), written into each repo by
  ``hook_install --install`` (:func:`write_page`) and pinned committed-equals-rendered by
  :mod:`dev_lab.dev.famtests.principlespage`;
* ``python -m dev_lab.dev.principles --json`` -> the payload the review command hands ai-lab
  (``--principles``, :data:`dev_lab.dev.forgereview.PRINCIPLES_FIELD`).

An id, once published, is never renamed: reviewer findings cite it. Extend by adding a row.
"""

from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path
from typing import Any, Final, NamedTuple

from lab_commons.log import emit

from dev_lab.dev.docwidth import WIDTH_CEILING

__all__ = ['PAGE_REL', 'PRINCIPLES', 'Principle', 'main', 'payload', 'render', 'write_page']


class Principle(NamedTuple):
    """One principle: a stable id, a short name, a one-sentence statement."""

    id: str
    name: str
    statement: str


PRINCIPLES: Final = (
    Principle(
        'first-principles',
        'First principles',
        'Derive from the actual system and current needs, not habit or precedent; state shaping assumptions.',
    ),
    Principle(
        'no-historical-baggage',
        'Discard historical baggage',
        'Remove obsolete structures and dead paths no current need uses.',
    ),
    Principle(
        'occams-razor', "Occam's razor", 'Simplest design that fully meets the need; nothing for hypothetical needs.'
    ),
    Principle(
        'single-source-of-truth',
        'Single source of truth',
        'Each fact lives in one place; everything else is derived from it.',
    ),
    Principle(
        'layered-decoupling',
        'Layered decoupling',
        'Depend one way through narrow interfaces; never into internals or upward.',
    ),
    Principle('names-match-behaviour', 'Names match what they do', 'A name says what the thing does now.'),
    Principle(
        'no-backward-compatibility',
        'No backward compatibility',
        'No shims, aliases or dual paths for old callers; callers move with the change.',
    ),
    Principle(
        'progressive-disclosure',
        'Progressive disclosure',
        'An entry point states what is needed first and points to detail; no duplication across levels.',
    ),
    Principle(
        'keep-valuable-options',
        'Keep every valuable parameter and option',
        'Generality is a requirement: keep every parameter and option a real case uses or plausibly needs; '
        'Occam and no-baggage remove dead paths, never capability.',
    ),
)

#: Where each family repo carries the rendered page (always loaded by the agent).
PAGE_REL: Final = '.claude/rules/principles.md'


def payload() -> dict[str, list[dict[str, Any]]]:
    """The JSON payload: ``{"principles": [{"id", "name", "statement"}, ...]}``."""
    return {'principles': [one._asdict() for one in PRINCIPLES]}


def render() -> str:
    """The rules page: a heading and one bullet per principle, wrapped (as one bullet) to the injected width."""
    lines = [
        '# Principles -- family policy, rendered from dev_lab.dev.principles; edit there',
        '',
    ]
    for one in PRINCIPLES:
        lines += textwrap.wrap(
            f'- **{one.name}** (`{one.id}`): {one.statement}',
            width=WIDTH_CEILING,
            subsequent_indent='  ',
            break_on_hyphens=False,
        )
    return '\n'.join(lines) + '\n'


def write_page(repo: Path) -> bool:
    """Write :data:`PAGE_REL` under *repo* when it differs from :func:`render`; whether it wrote."""
    page = repo / PAGE_REL
    text = render()
    if page.is_file() and page.read_text(encoding='utf-8') == text:
        return False
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(text, encoding='utf-8', newline='\n')
    return True


def main(argv: list[str] | None = None) -> int:
    """CLI: ``--json`` prints the payload; otherwise the rendered page."""
    parser = argparse.ArgumentParser(description='The family engineering principles.')
    parser.add_argument('--json', action='store_true', help='print {"principles": [...]} as JSON')
    args = parser.parse_args(argv)
    # ASCII-escaped JSON is valid UTF-8 whatever the console's encoding, so no stream can corrupt the payload.
    emit(json.dumps(payload(), indent=2) if args.json else render().rstrip('\n'), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
