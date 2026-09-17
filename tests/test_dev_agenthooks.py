"""The shipped ENGINE, DRIVEN -- real command strings in, the real deny decision out.

NOTHING HERE IS MOCKED, and that is the whole design of this file. The engine is the one artefact in
this family whose correctness cannot be argued from Python: it decides what a shell line will
EXECUTE, and every defect it has had was a disagreement between that decision and a reader's belief
about it. So each arm builds a real ``deny-rules.json`` out of the shared registry, feeds a real hook
payload to ``node``, and asserts the verdict that comes back.

THE FOUR ARMS THAT ARE INCIDENTS RATHER THAN EXAMPLES:

* the WRAPPER case. ``timeout 900 pytest`` invokes two commands and anchoring at the first alone
  misses the second; six shapes slipped through when that was measured (2026-09-01).
* the HEREDOC EVASION, measured 2026-08-22: an agent ran pytest through ``python - <<EOF ...
  pytest.main([...]) ... EOF`` and disclosed it. A CLOSED incident, pinned here so it stays closed.
* the other side of the same coin -- a heredoc consumed by a SINK is DATA. ``cat > notes.md <<EOF``
  writing the words ``uv sync`` is documentation, and refusing it fired twice in one session while
  the author was recording why the rule is right.
* the FALSE POSITIVE, repaid 2026-09-17: a command that merely CONTAINS a denied word in a string
  (``grep -rn "pytest" src``) runs grep, and a guard that refuses the sentence describing it is not
  strict, it is imprecise.

THE FLOOR IS THE ROWS' OWN PROOF. Every registry row carries ``refuses``/``permits`` controls, and
:func:`test_every_registry_row_behaves_through_the_real_engine` drives all of them through ``node``
with a count floor -- so an empty registry, an engine that denied nothing, or one that denied
everything all red instead of reading as green.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lab_commons.dev import agenthooks
from lab_commons.dev.hook_adoption import HookAdoption, render
from lab_commons.dev.hooks import DENY_RULES, Remedy

# ASSERTED AT MODULE SCOPE RATHER THAN SKIPPED, for the reason `NoNode` gives: the hook entry starts
# with `node`, so a box without one runs NO guard -- in every repo on it. That is the finding.
NODE = agenthooks.node_executable()

#: An adoption that remedies EVERY rule needing a repo artefact, so the rendered file carries the
#: whole registry. The commands are this repo's own real ones where they exist; what matters to the
#: engine is the reason text, and what matters here is that no row is silently dropped.
ADOPTION = HookAdoption(
    app_name='lab-commons (suite)',
    remedies={
        'BARE-TEST-INVOCATION': Remedy('verdict-entry-point', '.venv/Scripts/python.exe -m lab_commons.dev.verify'),
        'PUSH-NO-VERIFY': Remedy('verdict-entry-point', '.venv/Scripts/python.exe -m lab_commons.dev.verify'),
        'GIT-NETWORK-VERB': Remedy('retry-wrapper', 'sh {root}/scripts/hooks/with-retry.sh push'),
        'RAW-PROCESS-KILL': Remedy('process-tree-killer', '.venv/Scripts/python.exe -m lab_commons.dev.stop --pid N'),
    },
)

#: The floor on the registry-wide scan below: rows times their own controls. MEASURED 2026-09-17 --
#: 7 rows carrying 24 ``refuses`` and 20 ``permits``. Set under the measurement on purpose: a floor
#: refuses an UNREAD registry, it is not a second pin on the count.
CONTROL_FLOOR = 30


@pytest.fixture(scope='module')
def rules(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real ``deny-rules.json``, rendered from the shared registry exactly as a repo ships it."""
    path = tmp_path_factory.mktemp('rules') / 'deny-rules.json'
    path.write_text(render(ADOPTION), encoding='utf-8')
    return path


def test_the_package_ships_an_engine_and_it_carries_its_stamp() -> None:
    """The payload half: an engine that ships without its stamp cannot be told from a stranger's."""
    assert agenthooks.ENGINES, 'no engine ships in this package -- the registry would have nothing to run'
    for name in agenthooks.ENGINES:
        text = agenthooks.engine_path(name).read_text(encoding='utf-8')
        assert agenthooks.STAMP in text, f'{name} ships unstamped; agent_guard could not recognise an installed copy'


def test_a_plainly_denied_command_is_denied_with_its_remedy(rules: Path) -> None:
    """The base case, and the reason text must carry the EXIT -- a sealed road gets routed around."""
    reason = agenthooks.decide('pytest tests/', rules)
    assert reason is not None, 'a bare pytest line was allowed; the guard refuses nothing'
    assert 'lab_commons.dev.verify' in reason, f'denied with no exit to take: {reason!r}'


def test_an_ordinary_command_is_allowed(rules: Path) -> None:
    """The other side of the ratchet: a guard that denies everything is not a guard."""
    assert agenthooks.decide('git status --short', rules) is None


def test_a_denied_verb_behind_an_allowed_wrapper_is_still_denied(rules: Path) -> None:
    """THE WRAPPER CASE. A segment has as many command positions as it has wrappers."""
    for command in ('timeout 900 pytest tests/', 'nohup git push origin HEAD', 'env sudo pytest -q'):
        assert agenthooks.decide(command, rules) is not None, f'the wrapper hid the command: {command!r}'


def test_the_heredoc_evasion_stays_closed(rules: Path) -> None:
    """THE 2026-08-22 INCIDENT. The denied command sits in a NON-FIRST position inside the body."""
    command = 'python - <<EOF\nimport os\nprint(os.getcwd())\npytest.main(["-q", "tests"])\nEOF'
    reason = agenthooks.decide(command, rules)
    assert reason is not None, 'pytest ran through a heredoc body and the guard did not see it -- the evasion reopened'


def test_a_heredoc_consumed_by_a_sink_is_data_and_is_not_denied(rules: Path) -> None:
    """The other direction: a body a SINK consumes is documentation, and refusing it is imprecision."""
    command = 'cat > notes.md <<EOF\nWhy the rule exists: pytest tests/ has no verdict.\nEOF'
    assert agenthooks.decide(command, rules) is None, 'writing prose ABOUT a denied command was refused'


def test_a_command_that_merely_contains_a_denied_word_is_not_denied(rules: Path) -> None:
    """THE MEASURED FALSE POSITIVE. These run grep, git-log and git-commit -- not the named verb."""
    for command in (
        'grep -rn "pytest" src',
        'git log --oneline -- tests/test_dev_verify.py',
        'git commit -m "mention a push in prose"',
        'echo "git push origin main"',
    ):
        assert agenthooks.decide(command, rules) is None, f'a string containing a denied word was refused: {command!r}'


def test_every_registry_row_behaves_through_the_real_engine(rules: Path) -> None:
    """THE SCAN, WITH ITS FLOOR: every row's own controls, driven through ``node``."""
    checked = 0
    wrong: list[str] = []
    shipped = {row['name'] for row in json.loads(rules.read_text(encoding='utf-8'))}
    for rule in DENY_RULES:
        if rule.id not in shipped:
            continue
        for command in rule.refuses:
            checked += 1
            if agenthooks.decide(command, rules) is None:
                wrong.append(f'{rule.id}: the engine ALLOWED a command the row says it refuses: {command!r}')
        for command in rule.permits:
            checked += 1
            if agenthooks.decide(command, rules) is not None:
                wrong.append(f'{rule.id}: the engine DENIED a near-miss the row permits: {command!r}')
    assert checked >= CONTROL_FLOOR, (
        f'only {checked} controls reached the engine, below the {CONTROL_FLOOR} floor. Finding nothing wrong '
        f'in an unread registry is not a green result. Fix the corpus, do not lower the floor.'
    )
    assert wrong == [], '\n'.join(wrong)


def test_the_engine_fails_open_on_an_unreadable_rules_file(tmp_path: Path) -> None:
    """FAIL-OPEN BY CONSTRUCTION: a typo in the data file must not lock a session.

    Pinned because it is a property a reader would otherwise assume the opposite of, and because the
    honest report for it is ``None`` -- nothing was refused -- rather than an exception here.
    """
    broken = tmp_path / 'deny-rules.json'
    broken.write_text('[ {"name": "x", ', encoding='utf-8')
    assert agenthooks.decide('pytest tests/', broken) is None
