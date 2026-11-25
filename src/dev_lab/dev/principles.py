"""THE FAMILY'S ENGINEERING PRINCIPLES: one tuple, here, and everything else derived from it.

Family policy (user ruling 2026-10-27): every coding agent in every family repo reads them up front, and
every reviewer judges a change against them. ONE source, two derivations:

* :func:`bullet_lines` -> the principles in the family section of each repo's AGENTS.md
  (:mod:`dev_lab.dev.agentsection`, pinned by :mod:`dev_lab.dev.famtests.agentsection`);
* ``python -m dev_lab.dev.principles --json`` -> the payload the review command hands ai-lab
  (``--principles``, :data:`dev_lab.dev.forgereview_scope.PRINCIPLES_FIELD`).

An id, once published, is never renamed: reviewer findings cite it. Extend by adding a row.
"""

from __future__ import annotations

import argparse
import json
import textwrap
from typing import Any, Final, NamedTuple

from lab_commons.log import emit

from dev_lab.dev.docwidth import WIDTH_CEILING

__all__ = ['PRINCIPLES', 'Principle', 'bullet_lines', 'main', 'payload']


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
        'Remove obsolete structures, duplicates and dead paths no current need uses -- never a capability.',
    ),
    Principle(
        'occams-razor',
        "Occam's razor",
        'Simplest design meeting the need; nothing hypothetical; never a capability.',
    ),
    Principle(
        'single-source-of-truth',
        'Single source of truth',
        'Each fact lives in one place; all else derives from it.',
    ),
    Principle(
        'layered-decoupling',
        'Layered decoupling',
        'Depend one way through narrow interfaces; never into internals or upward.',
    ),
    Principle('names-match-behavior', 'Names match what they do', 'A name says what the thing does now.'),
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
        'Generality is a requirement: keep every parameter and option a real case uses or plausibly needs. A '
        'reference match ADDS a selectable option and never replaces or deletes the alternative; numerical '
        'method choices are options even with no current caller.',
    ),
    Principle(
        'every-wall-teaches',
        'Every wall teaches',
        'Every refusal or failure an agent hits names its cause and its door; one that does not is a mechanism '
        'gap, and closing it (a hook row, a remedy, a test) comes before the task. Never route around a wall or '
        'hand the user a command. The loop: docs-src/dev/feedback.md.',
    ),
    Principle(
        'no-barrier-fan-out',
        'Fan out without a barrier',
        'Parallel work is independent items, each landed the moment it is done; nothing waits for the slowest '
        'sibling -- no barrier-style orchestration (e.g. a dynamic workflow that joins all agents) unless a step '
        'truly needs every result. How: docs-src/dev/fanout.md.',
    ),
    Principle(
        'images-by-absolute-path',
        'Deliver an image by its absolute path',
        'An image handed to the user is named by its ABSOLUTE path, never a relative one (IMAGES-BY-ABSOLUTE-PATH).',
    ),
    Principle(
        'worktree-names-its-task',
        'A worktree is named for its task',
        "A worktree's name has a physical meaning tied to its task; a hash-like name (`agent-<hex>`, an appended "
        'hash) is forbidden (WORKTREE-NAMES-ITS-TASK).',
    ),
    Principle(
        'native-first',
        'Native first',
        'Python declares and orchestrates, Rust computes. A stage Rust owns is written in Rust from its first line; '
        'a Python version of it is only a scratch prototype, never a second implementation; acceptance is against '
        'references (analytic, the vendor ladder, the previous implementation during a migration), never against a '
        'Python twin.',
    ),
)


def payload() -> dict[str, list[dict[str, Any]]]:
    """The JSON payload: ``{"principles": [{"id", "name", "statement"}, ...]}``."""
    return {'principles': [one._asdict() for one in PRINCIPLES]}


def bullet_lines() -> tuple[str, ...]:
    """One Markdown bullet per principle, each wrapped (as one bullet) to the injected width."""
    lines: list[str] = []
    for one in PRINCIPLES:
        lines += textwrap.wrap(
            f'- **{one.name}** (`{one.id}`): {one.statement}',
            width=WIDTH_CEILING,
            subsequent_indent='  ',
            break_on_hyphens=False,
        )
    return tuple(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI: ``--json`` prints the payload; otherwise the bullets."""
    parser = argparse.ArgumentParser(description='The family engineering principles.')
    parser.add_argument('--json', action='store_true', help='print {"principles": [...]} as JSON')
    args = parser.parse_args(argv)
    # ASCII-escaped JSON is valid UTF-8 whatever the console's encoding, so no stream can corrupt the payload.
    emit(json.dumps(payload(), indent=2) if args.json else '\n'.join(bullet_lines()), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
