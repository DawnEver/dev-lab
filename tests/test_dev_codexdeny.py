"""The deny rows reach Codex: each prefix-expressible row is a ``forbidden`` rule, the rest a declared gap.

MEASURED 2026-11-16: Codex carried 0 of the registry's deny rows; every refusal Claude Code enforced ran
unjudged there. Codex execpolicy matches an argv PREFIX, so only a row whose refused shapes share one renders;
a row judged on a path, a host, a flag anywhere, or a live condition is a gap with its reason.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from dev_lab.dev import codexdeny
from dev_lab.dev.autodoors import doors
from dev_lab.dev.hooks import DENY_RULES, rules_by_id

ROOT = Path(__file__).resolve().parents[1]
_BY_ID = rules_by_id(DENY_RULES)


def _matches(prefix: tuple[str | tuple[str, ...], ...], argv: list[str]) -> bool:
    """Codex's prefix test: each position equals the token, or one of its alternatives."""
    return len(argv) >= len(prefix) and all(
        word in token if isinstance(token, tuple) else word == token for token, word in zip(prefix, argv, strict=False)
    )


def test_every_refusing_row_is_rendered_or_a_declared_gap_and_no_hint_is_forbidden() -> None:
    refusing = {rule.id for rule in DENY_RULES if rule.severity != 'hint'}
    assert set(codexdeny.FORBIDDEN) | set(codexdeny.GAPS) == refusing
    assert set(codexdeny.FORBIDDEN) & set(codexdeny.GAPS) == set()
    assert all(reason.strip() for reason in codexdeny.GAPS.values())


@pytest.mark.parametrize('rule_id', sorted(codexdeny.FORBIDDEN))
def test_each_prefix_names_a_shape_its_row_refuses(rule_id: str) -> None:
    """A prefix with no refused example behind it is a guess, not a rendering of the row."""
    refused = [shlex.split(text) for text in _BY_ID[rule_id].refuses]
    for prefix in codexdeny.FORBIDDEN[rule_id]:
        assert any(_matches(prefix, argv) for argv in refused), (rule_id, prefix)


def test_no_prefix_forbids_a_near_miss_or_a_door() -> None:
    """The other half: every row's permitted near-miss and every family door stays runnable under Codex.

    PLANTED CONTROL: the GIT-STASH prefix does forbid `git stash pop`, so the matcher can say yes.
    """
    permitted = [shlex.split(text) for rule in DENY_RULES for text in rule.permits if '<<' not in text]
    permitted += [list(argv) for argv in doors()]
    caught = [
        (rule_id, argv)
        for rule_id, prefixes in codexdeny.FORBIDDEN.items()
        for prefix in prefixes
        for argv in permitted
        if _matches(prefix, argv)
    ]
    assert caught == []
    assert any(_matches(prefix, ['git', 'stash', 'pop']) for prefix in codexdeny.FORBIDDEN['GIT-STASH'])


def test_the_rendered_file_is_forbidden_rules_naming_each_row_and_its_page() -> None:
    text = codexdeny.codex_deny_rules()
    assert text.count('decision = "forbidden"') == sum(len(p) for p in codexdeny.FORBIDDEN.values())
    assert 'decision = "allow"' not in text
    for rule_id in codexdeny.FORBIDDEN:
        assert f'{rule_id}: ' in text
        assert f'refusals.md#{rule_id.lower()}' in text
    for rule_id in codexdeny.GAPS:
        assert f'# {rule_id}: ' in text, f'{rule_id}: a gap is stated in the file, not only in the code'


def test_this_checkout_carries_the_current_rendering() -> None:
    assert (ROOT / codexdeny.CODEX_DENY_REL).read_text(encoding='utf-8') == codexdeny.codex_deny_rules()
