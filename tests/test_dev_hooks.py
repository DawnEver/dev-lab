"""The shared deny registry, proved row by row -- and every refusal proved to be reachable.

WHAT A GUARD LIKE THIS CAN GET WRONG, and each one is checked below rather than read:

* A PATTERN THAT DOES NOT COMPILE. The engine fails OPEN on a bad regex, deliberately, so a typo
  there does not refuse -- it silently stops refusing while the row still reads as protection.
  motronics shipped exactly that: an ``allow`` of ``[/\\]``, an unterminated character class. Every
  pattern and every opening in the registry is compiled here, and the constructor compiles them too,
  so a bad one cannot reach a file at all.
* A PATTERN THAT MATCHES THE WRONG THING. Every row carries its own ``refuses`` and ``permits``
  examples, so the proof arrives WITH the row and a new rule cannot land without one. The floor
  below is over the EXAMPLES rather than over the rows: a row that carried no examples would
  otherwise pass by having nothing to check.
* A RULE WITH NO EXIT. The design's whole point. Checked twice -- the constructor refuses a remedy-
  less row, and every ``permits`` example is driven through the WHOLE registry, so a row whose exit
  is refused by a SIBLING rule fails here instead of in somebody's terminal.

THE ROWS' EXAMPLES ARE SEGMENTS, NOT SHELL LINES, and that is the honest scope: splitting a command
into what the shell will execute belongs to the JS engine and is not re-implemented in Python. What
is checked here is the anchoring a rule declares, which is the half a pattern can be wrong in.
"""

from __future__ import annotations

import re

import pytest

from lab_commons.dev.hooks import (
    DENY_RULES,
    MATCH_KINDS,
    PLACEHOLDER,
    DenyRule,
    Remedy,
    UnremediedRule,
    denies,
    fires,
    rules_by_id,
)

#: The floor on the row/example scan, MEASURED 2026-09-16 (7 rows, 25 refusing and 20 permitted
#: examples). Set below the measurement on purpose: a floor refuses an UNREAD registry, it is not a
#: second pin on the count -- pinning the exact number would red on every row added, which is how a
#: floor gets deleted.
ROW_FLOOR = 6
EXAMPLE_FLOOR = 30

#: A remedy of each kind the registry needs, so a row that ``needs`` one can be rendered here. These
#: are the TEST's remedies, not any repo's: what a real repo supplies is its own adoption's business.
_REMEDIES = {
    'verdict-entry-point': Remedy('verdict-entry-point', 'python -m lab_commons.dev.verify'),
    'retry-wrapper': Remedy('retry-wrapper', 'sh scripts/hooks/with-retry.sh push origin HEAD'),
    'process-tree-killer': Remedy('process-tree-killer', 'python scripts/gate/stop_sweep.py --pid <pid>'),
}


def _remedy_for(rule: DenyRule) -> Remedy | None:
    return _REMEDIES[rule.needs] if rule.needs is not None else None


def _examples() -> tuple[tuple[str, ...], tuple[str, ...]]:
    refused = tuple(text for rule in DENY_RULES for text in rule.refuses)
    permitted = tuple(text for rule in DENY_RULES for text in rule.permits)
    return refused, permitted


def test_the_registry_is_read_rather_than_assumed() -> None:
    """THE FLOOR. An empty registry and a clean one are the same result, and only one is green."""
    assert len(DENY_RULES) >= ROW_FLOOR, (
        f'the deny registry read {len(DENY_RULES)} rows, below the {ROW_FLOOR} floor: finding nothing wrong '
        f'in an unread table is vacuous rather than green.'
    )
    refused, permitted = _examples()
    assert len(refused) + len(permitted) >= EXAMPLE_FLOOR, (
        f'{len(refused) + len(permitted)} examples across the registry, below the {EXAMPLE_FLOOR} floor. A '
        f'row that carries no example is a pattern nothing exercises.'
    )
    assert len({rule.id for rule in DENY_RULES}) == len(DENY_RULES), 'two rows share an ID'


@pytest.mark.parametrize('rule', DENY_RULES, ids=lambda rule: rule.id)
def test_every_pattern_and_opening_compiles(rule: DenyRule) -> None:
    """The failure the ENGINE cannot report, because it fails open on it by construction."""
    re.compile(rule.pattern)
    if rule.allow is not None:
        re.compile(rule.allow)


@pytest.mark.parametrize('rule', DENY_RULES, ids=lambda rule: rule.id)
def test_every_row_fires_on_what_it_refuses(rule: DenyRule) -> None:
    """One half of the row's own proof: the shapes this rule exists to stop."""
    assert rule.refuses, f'{rule.id} names no command it refuses, so its pattern is exercised by nothing'
    missed = [text for text in rule.refuses if not fires(rule, text)]
    assert missed == [], f'{rule.id} does not fire on what it claims to refuse: {missed}'


@pytest.mark.parametrize('rule', DENY_RULES, ids=lambda rule: rule.id)
def test_every_row_lets_its_near_misses_through(rule: DenyRule) -> None:
    """The other half, and the one that matters more: a guard that refuses everything is routed around.

    Driven through the WHOLE registry rather than through the one rule, because a near-miss stopped
    by a SIBLING rule is just as refused from the terminal -- and a rule whose sanctioned spelling is
    denied elsewhere is the sealed road, reached by a different street.
    """
    assert rule.permits, f'{rule.id} names no near-miss, so nothing says its pattern is not simply always true'
    denied = {text: denies(DENY_RULES, text, _REMEDIES) for text in rule.permits}
    caught = {text: by for text, by in denied.items() if by is not None}
    assert caught == {}, f'{rule.id} declares these permitted and the registry refuses them: {caught}'


@pytest.mark.parametrize('rule', DENY_RULES, ids=lambda rule: rule.id)
def test_every_row_names_an_exit_and_renders_it(rule: DenyRule) -> None:
    """The design's whole point: the reason an agent reads must say what to do INSTEAD."""
    row = rule.rendered(_remedy_for(rule))
    assert row['name'] == rule.id
    assert row['matches'] in MATCH_KINDS
    assert PLACEHOLDER not in row['reason'], f'{rule.id} shipped the raw {PLACEHOLDER} token to a reader'
    assert rule.hazard in row['reason'], f'{rule.id} renders a reason that no longer states the hazard'
    remedy = _remedy_for(rule)
    if remedy is not None:
        assert remedy.command in row['reason'], f'{rule.id} renders a reason that does not name its exit'


def test_a_rule_that_needs_a_remedy_refuses_to_render_without_one() -> None:
    """A reason whose exit went missing reads exactly like one whose exit is a plain command."""
    needy = [rule for rule in DENY_RULES if rule.needs is not None]
    assert needy, 'no row needs a repo artefact, so this control is checking nothing'
    with pytest.raises(UnremediedRule, match='no exit to name'):
        needy[0].reason()
    with pytest.raises(UnremediedRule, match='answers a different question'):
        needy[0].reason(Remedy('something-else', 'do a different thing'))


def test_a_planted_remedyless_rule_is_refused() -> None:
    """THE PLANTED CONTROL, through the REAL constructor, for the rule this module exists to enforce."""
    with pytest.raises(UnremediedRule, match='seals a road with no exit'):
        DenyRule(id='PLANTED', pattern=r'\bplanted\b', hazard='it is planted', remedy='   ')
    with pytest.raises(UnremediedRule, match='leaves no'):
        DenyRule(id='PLANTED', pattern=r'x', hazard='h', remedy='do this instead', needs='a-tool')
    with pytest.raises(UnremediedRule, match='with no `needs` to fill it'):
        DenyRule(id='PLANTED', pattern=r'x', hazard='h', remedy=f'run {PLACEHOLDER}')
    clean = DenyRule(id='PLANTED', pattern=r'x', hazard='h', remedy=f'run {PLACEHOLDER}', needs='a-tool')
    assert clean.reason(Remedy('a-tool', 'the-tool --go')) == 'h run the-tool --go'


def test_a_planted_uncompilable_pattern_is_refused() -> None:
    """The `[/\\]` incident, as a control: an unterminated class must never reach a shipped file."""
    with pytest.raises(ValueError, match='does not compile'):
        DenyRule(id='PLANTED', pattern=r'[/\\', hazard='h', remedy='do this')
    with pytest.raises(ValueError, match='does not compile'):
        DenyRule(id='PLANTED', pattern=r'x', hazard='h', remedy='do this', allow=r'(unclosed')
    with pytest.raises(ValueError, match='does not compile'):
        Remedy('a-tool', 'the-tool', allow=r'[/\\')


def test_a_planted_bad_declaration_is_refused() -> None:
    """The ID and the anchoring are a closed vocabulary, so a typo cannot quietly widen a rule."""
    with pytest.raises(ValueError, match='UPPER-CASE slug'):
        DenyRule(id='planted', pattern='x', hazard='h', remedy='do this')
    with pytest.raises(ValueError, match='is not one of'):
        DenyRule(id='PLANTED', pattern='x', hazard='h', remedy='do this', matches='anywhere')
    with pytest.raises(ValueError, match='REPO-RELATIVE'):
        Remedy('a-tool', 'the-tool', path='C:/abs/tool.sh')


def test_the_anchoring_a_row_declares_is_the_anchoring_it_gets() -> None:
    """A 'command' rule names the command; an 'argument' rule names an option wherever it appears."""
    command = DenyRule(id='PLANTED', pattern=r'\bstash\b', hazard='h', remedy='do this')
    argument = DenyRule(id='PLANTED', pattern=r'--force\b', hazard='h', remedy='do this', matches='argument')
    assert fires(command, 'stash something')
    assert not fires(command, 'echo "stash something"'), 'a command rule must not fire on a mention'
    assert fires(argument, 'some-tool --force'), 'an argument rule is searched anywhere in the segment'


def test_an_opening_is_what_turns_a_hit_into_a_pass() -> None:
    """`denies` is the reachability question, and an `allow` is the only thing that answers it yes."""
    rule = DenyRule(id='PLANTED', pattern=r'\btool\b', hazard='h', remedy=f'use {PLACEHOLDER}', needs='a-tool')
    assert denies((rule,), 'tool --go') == 'PLANTED'
    opened = {'PLANTED': Remedy('a-tool', 'tool --sanctioned', allow=r'--sanctioned\b')}
    assert denies((rule,), 'tool --sanctioned', opened) is None
    assert denies((rule,), 'tool --go', opened) == 'PLANTED', 'the opening must not open the rule generally'


def test_the_lookup_is_the_registry_itself() -> None:
    """The keyed view an adoption resolves against really covers every row."""
    assert set(rules_by_id(DENY_RULES)) == {rule.id for rule in DENY_RULES}
