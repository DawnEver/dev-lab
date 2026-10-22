"""A consumer's rule pages CITE a registry rule by ID and never restate its statement.

:class:`dev_lab.dev.rules.Rule` says it in its docstring: the statement is authored once, in the
registry, and a repo's rules page cites the ID -- two statements of one rule is the drift the registry
exists to remove. Nothing refused the copy, and an audit (2026-10-21) found consumer pages restating
seven registry rules beside their own IDs. This body is the refusal.

THE READING IS SHARED WORD n-GRAMS. Each text is lowercased and reduced to its words (backticks,
punctuation and line breaks are not words), and a page restates a rule when it shares more than
*max_shared* distinct word *n*-grams with that rule's statement. A citation -- the ID and the local
incident -- shares none; a paraphrase close enough to drift alongside the original shares many.

EVERY REPO-SHAPED FACT IS A KEYWORD WITH NO DEFAULT: the pages (the consumer's ``.claude/rules/**``,
tracked), *n*, *max_shared* and the *floor* on pages read, because a scan that read nothing is vacuous,
never clean.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final

from dev_lab.dev.rules import RULES, Rule

__all__ = ['RestatedRule', 'VacuousRestatementScan', 'assert_no_restated_rules', 'restated']

_WORD: Final = re.compile(r'[a-z0-9]+')


class RestatedRule(AssertionError):
    """A rules page restates a registry statement instead of citing its ID."""


class VacuousRestatementScan(AssertionError):
    """The scan read fewer pages than its floor, so finding nothing proves nothing."""


def _grams(text: str, n: int) -> frozenset[tuple[str, ...]]:
    words = _WORD.findall(text.lower())
    return frozenset(tuple(words[i : i + n]) for i in range(len(words) - n + 1))


def restated(text: str, *, n: int, max_shared: int, rules: Sequence[Rule] = RULES) -> dict[str, int]:
    """Rule id -> shared word *n*-grams, for every rule *text* shares more than *max_shared* with."""
    page = _grams(text, n)
    shared = {rule.id: len(page & _grams(rule.statement, n)) for rule in rules}
    return {rule: count for rule, count in shared.items() if count > max_shared}


def assert_no_restated_rules(
    *, pages: Iterable[Path], n: int, max_shared: int, floor: int, rules: Sequence[Rule] = RULES
) -> None:
    """Refuse every page in *pages* that restates a registry statement, naming the page and the rule.

    Raises:
        VacuousRestatementScan: fewer than *floor* pages were read.
        RestatedRule: a page shares more than *max_shared* word *n*-grams with a statement.

    """
    read = {path: path.read_text(encoding='utf-8') for path in pages}
    if len(read) < floor:
        msg = f'the restated-rules scan read {len(read)} page(s), below its floor of {floor}: nothing was judged'
        raise VacuousRestatementScan(msg)
    found = [
        f'{path}: restates {rule} ({count} shared {n}-word runs)'
        for path, text in read.items()
        for rule, count in restated(text, n=n, max_shared=max_shared, rules=rules).items()
    ]
    if found:
        msg = (
            'a rules page restates a registry statement -- cite the ID and keep only the local incident '
            '(dev_lab.dev.rules):\n  ' + '\n  '.join(found)
        )
        raise RestatedRule(msg)
