"""CI-CRON-NEEDS-CONSENT through the REAL engine: drift is every agent's, a CI cron change is refused with its door.

User ruling 2026-11-16: ``hpcaccount drift`` and ``drift-fleet`` are read-only and free; ``ci-pause``,
``ci-pause-fleet``, ``ci-resume`` and ``ci-resume-fleet`` rewrite a crontab, so an agent is refused them every time
and the refusal names the door -- the user runs it, or grants a consent plan for the cluster plus its accounts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev import agenthooks
from dev_lab.dev._deny_cicron_row import RULE_ID, refused_verbs
from dev_lab.dev.agentpolicy import POLICY, SUBAGENT, USER
from dev_lab.dev.autodoors import claude_rows
from dev_lab.dev.codexdeny import codex_deny_rules
from dev_lab.dev.doorrows import INTERPRETERS
from dev_lab.dev.hook_adoption import HookAdoption, render

_PY = INTERPRETERS[0]
_MODULE = 'dev_lab.dev.hpcaccount'


@pytest.fixture(scope='module')
def rules(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The registry rendered exactly as a repo ships it."""
    path = tmp_path_factory.mktemp('rules') / 'deny-rules.json'
    path.write_text(render(HookAdoption(app_name='suite', remedies={})), encoding='utf-8')
    return path


def test_the_refused_verbs_are_the_rulings_four() -> None:
    assert set(refused_verbs()) == {'ci-pause', 'ci-pause-fleet', 'ci-resume', 'ci-resume-fleet'}


@pytest.mark.parametrize('verb', ['ci-pause-fleet', 'ci-pause', 'ci-resume-fleet', 'ci-resume'])
def test_a_ci_cron_verb_is_refused_and_names_its_door(rules: Path, verb: str) -> None:
    reason = agenthooks.decide(f'{_PY} -m {_MODULE} {verb} --cluster c1 --dry-run', rules)
    assert reason is not None, f'{verb} was admitted'
    assert RULE_ID in reason
    assert 'consent plan' in reason
    assert 'cluster plus its account list' in reason
    assert 'consent grant' in reason
    assert 'the user' in reason


@pytest.mark.parametrize(
    'command',
    [
        f'{_PY} -m {_MODULE} drift-fleet --cluster c1',
        f'{_PY} -m {_MODULE} drift --from /srv/clone --host h',
        f'{_PY} -m {_MODULE} --help',
        f'{_PY} -m {_MODULE} ci-pause-fleetx',
        'git log --grep ci-pause-fleet',
    ],
)
def test_drift_and_near_misses_are_admitted(rules: Path, command: str) -> None:
    """PLANTED CONTROL: the row refuses the crontab verbs only, not the module."""
    assert agenthooks.decide(command, rules) is None, command


def test_drift_is_every_agents_door_and_the_cron_verbs_are_the_users() -> None:
    doors = {door.argv[3]: door for door in POLICY if door.argv[2:3] == (_MODULE,) and len(door.argv) > 3}
    assert doors['drift'].actor == SUBAGENT
    assert doors['drift-fleet'].actor == SUBAGENT
    rows = claude_rows()
    assert f'Bash({_PY} -m {_MODULE} drift-fleet *)' in rows
    for verb in refused_verbs():
        assert doors[verb].actor == USER
        assert doors[verb].deny == RULE_ID
        assert not any(f'{_MODULE} {verb} ' in row for row in rows), verb


def test_codex_forbids_the_same_verbs() -> None:
    text = codex_deny_rules()
    assert f'"{_MODULE}", [{", ".join(f"{chr(34)}{verb}{chr(34)}" for verb in refused_verbs())}]' in text
    assert f'{RULE_ID}:' in text


@pytest.mark.parametrize('verb', ['ci-pause-fleet', 'ci-pause', 'ci-resume-fleet', 'ci-resume'])
def test_a_verb_carrying_its_credential_is_admitted_for_the_verb_to_check(rules: Path, verb: str) -> None:
    """The guard admits ``--credential``; the verb redeems it against its subject (test_dev_hpcaccount_cicron)."""
    assert agenthooks.decide(f'{_PY} -m {_MODULE} {verb} --cluster c1 --credential 0123abcd-ef', rules) is None
    assert agenthooks.decide(f'{_PY} -m {_MODULE} {verb} --cluster c1 --credential=0123abcd-ef', rules) is None


def test_a_credential_in_a_chained_command_admits_nothing(rules: Path) -> None:
    """PLANTED CONTROL: ``--credential`` must ride the verb's own invocation, not a neighbor's."""
    reason = agenthooks.decide(f'{_PY} -m {_MODULE} ci-pause-fleet --cluster c1; echo --credential x', rules)
    assert reason is not None
    assert RULE_ID in reason
