"""AGENT-POLICY: one table of doors, and every rendering derived from it (user ruling 2026-11-07)."""

from __future__ import annotations

import importlib
import re

import pytest

from dev_lab.dev.agentpolicy import INTERPRETERS, MAIN, POLICY, SUBAGENT, USER, Door, exits_of, module_verbs
from dev_lab.dev.autodoors import claude_rows
from dev_lab.dev.automode import INTENTS, spelled_commands
from dev_lab.dev.hooks import DENY_RULES, rules_by_id

_RULES = rules_by_id(DENY_RULES)


def _spelled(door: Door) -> str:
    return f'{INTERPRETERS[0]} {" ".join(door.argv[1:])} 12 --why x'


def test_every_door_says_what_it_is_for_once_in_prose() -> None:
    intents = [door.intent for door in POLICY]
    assert len(intents) == len(set(intents)), 'one string per door: two doors sharing one are one door'
    assert spelled_commands(intents) == ()
    assert {door.actor for door in POLICY} == {MAIN, SUBAGENT, USER}


def test_every_python_door_names_a_module_that_exists() -> None:
    for door in POLICY:
        if door.argv[:2] == ('python', '-m'):
            importlib.import_module(door.argv[2])


def test_the_forge_write_remedy_names_every_door_it_is_the_exit_of() -> None:
    """The defect the table ends: the hand-copied remedy said `pr create|close`, omitting ready, draft (and close)."""
    exits = exits_of('FORGE-WRITE-VIA-CLI', 'dev_lab.dev.forge')
    assert exits == 'issue create|comment|close, pr create|ready|draft|close'
    assert exits in _RULES['FORGE-WRITE-VIA-CLI'].remedy


@pytest.mark.parametrize('door', [door for door in POLICY if door.actor == MAIN and door.argv[:1] == ('python',)])
def test_a_main_door_is_refused_to_a_subagent(door: Door) -> None:
    """SUBAGENT-NO-PUSH's door half is DERIVED from the MAIN rows: a door added there is refused to a subagent."""
    assert re.match(f'(?:{_RULES["SUBAGENT-NO-PUSH"].pattern})', _spelled(door)), door.argv


@pytest.mark.parametrize('door', [door for door in POLICY if door.actor == SUBAGENT and door.argv])
def test_a_subagent_door_is_not_refused_to_a_subagent(door: Door) -> None:
    """PLANTED CONTROL for the derivation: it refuses the main session's doors, not every door of a module."""
    assert not re.match(f'(?:{_RULES["SUBAGENT-NO-PUSH"].pattern})', _spelled(door)), door.argv


def test_a_user_door_renders_no_allow_row_and_no_intent() -> None:
    users = [door for door in POLICY if door.actor == USER]
    assert users, 'a floor: granting a consent credential is the user`s'
    assert ('dev_lab.ops.consent', 'grant') in {door.argv[2:] for door in users}
    rows = claude_rows()
    for door in users:
        assert door.allow_lines == ()
        assert door.intent not in INTENTS
        assert not any(row.endswith(f' {" ".join(door.argv[1:])} *)') for row in rows)


def test_each_granted_main_door_of_the_ruling_is_in_the_table() -> None:
    """User ruling 2026-11-07, item 2: the doors the main session is granted."""
    forge = module_verbs(MAIN)['dev_lab.dev.forge']
    for verb in (
        ('pr', 'create'),
        ('pr', 'ready'),
        ('pr', 'draft'),
        ('sync',),
        ('pr', 'breakglass'),
        ('breakglass', 'open'),
        ('review', 'takeover'),
        ('security', 'release'),
    ):
        assert verb in forge, verb
    assert ('promote',) in module_verbs(MAIN)['dev_lab.dev.integrate']
    granted = {door.argv[2:] for door in POLICY if door.actor != USER and door.argv[:2] == ('python', '-m')}
    assert {('dev_lab.dev.forge', 'queue'), ('dev_lab.dev.forge', 'status', 'list')} <= granted
    assert ('dev_lab.dev.hook_install', '--install') in granted


def test_a_door_row_is_one_literal_per_interpreter_layout() -> None:
    door = next(door for door in POLICY if door.argv[2:] == ('dev_lab.dev.integrate', 'promote'))
    assert door.allow_lines == tuple(f'Bash({head} -m dev_lab.dev.integrate promote *)' for head in INTERPRETERS)


def test_an_unknown_actor_or_runner_or_an_empty_intent_is_refused() -> None:
    with pytest.raises(ValueError, match='actor'):
        Door(('python', '-m', 'x'), 'anyone', 'x')
    with pytest.raises(ValueError, match='runner'):
        Door(('bash', 'x'), MAIN, 'x')
    with pytest.raises(ValueError, match='intent'):
        Door(('python', '-m', 'x'), MAIN, ' ')
