"""A repo raises (or lowers) one family row's severity; it never copies the row.

MEASURED 2026-11-16 in one consumer: BARE-NETWORK-GIT was a local copy of NETWORK-VERB kept only to make the
hint a refusal there, so two rows judged one shape with two reasons and two doors. ``HookAdoption.severities``
replaces the copy: the family row ships, at the severity the repo declares.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev_lab.dev import agenthooks
from dev_lab.dev.hook_adoption import HookAdoption, render
from dev_lab.dev.hooks import DENY_RULES, Remedy, UnremediedRule
from dev_lab.dev.rules import RULES

_RETRY = Remedy('retry-wrapper', 'sh scripts/hooks/with-retry.sh <verb> <args>')


def _rows(adoption: HookAdoption) -> dict[str, dict[str, str]]:
    return {row['name']: row for row in json.loads(render(adoption))}


def test_a_declared_severity_is_the_shipped_rows_severity(tmp_path: Path) -> None:
    """The family row, its reason and door unchanged, refuses where the repo raised it. PLANTED CONTROL: unraised."""
    raised = HookAdoption('a', remedies={'NETWORK-VERB': _RETRY}, severities={'NETWORK-VERB': 'deny'})
    plain = HookAdoption('a', remedies={'NETWORK-VERB': _RETRY})
    assert _rows(raised)['NETWORK-VERB']['reason'] == _rows(plain)['NETWORK-VERB']['reason']
    assert _rows(raised)['NETWORK-VERB'].get('severity', 'deny') == 'deny'
    assert _rows(plain)['NETWORK-VERB']['severity'] == 'hint'
    for name, adoption, refused in (('raised', raised, True), ('plain', plain, False)):
        path = tmp_path / f'{name}.json'
        path.write_text(render(adoption), encoding='utf-8')
        assert (agenthooks.decide('git fetch origin', path) is not None) is refused, name


@pytest.mark.parametrize(
    ('severities', 'why'),
    [
        ({'NO-SUCH-ROW': 'deny'}, 'does not define'),
        ({'GIT-RESET': 'loud'}, 'not a severity'),
        ({'GIT-RESET': 'deny'}, 'already'),
    ],
)
def test_an_override_naming_no_row_no_severity_or_no_change_is_refused(severities: dict[str, str], why: str) -> None:
    """A typo raises nothing and says so nowhere; a no-op override reads as a decision and is none."""
    with pytest.raises(UnremediedRule, match=why):
        render(HookAdoption('a', severities=severities))


def test_agent_guard_says_the_network_verb_severity_the_family_ships(tmp_path: Path) -> None:
    """#1036: AGENT-GUARD said a bare network git verb is REFUSED while the family row ships as a hint.

    An agent read the statement, saw ``git fetch -q origin`` run, and filed a guard gap: the declaration lied, not
    the engine, which hints on the issue's lines alone and chained. PLANTED CONTROL: raised to ``deny``, it refuses.
    """
    row = next(rule for rule in DENY_RULES if rule.id == 'NETWORK-VERB')
    statement = next(rule.statement for rule in RULES if rule.id == 'AGENT-GUARD')
    assert row.severity == 'hint'
    assert 'network git verb and a stash are refused' not in statement, statement
    assert 'hinted' in statement, statement
    assert 'severities' in statement, statement
    assert 'git fetch -q origin' in row.refuses
    plain, raised = tmp_path / 'plain.json', tmp_path / 'raised.json'
    plain.write_text(render(HookAdoption('a', remedies={'NETWORK-VERB': _RETRY})), encoding='utf-8')
    raised.write_text(
        render(HookAdoption('a', remedies={'NETWORK-VERB': _RETRY}, severities={'NETWORK-VERB': 'deny'})),
        encoding='utf-8',
    )
    for line in ('git fetch -q origin', 'cd sub && git fetch -q origin'):
        assert agenthooks.decide(line, plain) is None, line
        hinted = agenthooks.decide(line, plain, hint=True)
        assert hinted is not None, line
        assert hinted.startswith('NETWORK-VERB:'), hinted
        assert agenthooks.decide(line, raised) is not None, line
