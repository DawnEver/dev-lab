"""AGENT-GUARD-IS-LIVE, as assertions: the declared registry is the one a command actually meets.

WHY THE FILE MATTERS MORE THAN THE INSTALL. An installed guard with no test is one ``settings.json``
edit away from being absent again, and it goes absent SILENTLY -- nothing about a repo whose hook
stopped running looks different from a repo whose hook is passing everything. Both labs reached this
conclusion independently, one of them after measuring 19 declared pre-commit hooks with ZERO
installed one layer down.

WHAT IS ALREADY THE KIT'S, AND IS ONLY CALLED HERE. :func:`lab_commons.dev.agent_guard.guard_installation`
reports engine, rules and wiring by name; :func:`lab_commons.dev.hook_adoption.render` renders the
declaration; :func:`lab_commons.dev.hook_adoption.assert_shippable` refuses a rule a repo neither
remedies nor declares absent; :func:`lab_commons.dev.rules.tracked_files` answers what the fleet
actually has. None of that is re-implemented. What was forked is the six ARMS around them and the
hand-rolled engine runner each repo wrote for itself.

THE DENY ARM NAMES THE RULE IT EXPECTS, and this is the strongest thing in the module. A deny arm
that asks only *"was this refused"* cannot tell a working rule from one a NEIGHBOUR is covering for:
MEASURED in one lab, ``GIT-NETWORK-VERB`` shipped, sat ahead of ``PUSH-FORCE`` and ``PUSH-NO-VERIFY``
in registry order, and answered for every bare ``git push`` -- so both push rules could have stopped
firing altogether with the suite still green. That is the count-pin failure in a different spelling,
and the cure is the same: name the row. :func:`assert_refused_by` compares the refusal TEXT against
the reason the committed rules file carries for the rule that was meant to fire, and
:func:`reason_for` READS that text rather than restating it, so the arm cannot drift from the file.

THE INSTALLED ENGINE IS DRIVEN, NOT THE SHIPPED ONE, and the distinction is the question being asked.
:func:`lab_commons.dev.agenthooks.decide` runs the engine inside this interpreter's ``lab_commons``,
which answers *"does the engine we ship refuse this"*. That is a fact about the wheel. This module
asks *"does the guard installed IN THIS CHECKOUT refuse this"*, so it runs
``<root>/.claude/hooks/deny-commands.js`` against ``<root>/.claude/hooks/deny-rules.json`` -- the two
files the agent's tool will actually execute. :func:`assert_the_guard_is_live` is what makes that
pair trustworthy: it reads the provenance stamp, so a hand-copied engine in the same slot reports
FOREIGN rather than installed. Node resolution is still the kit's
(:func:`lab_commons.dev.agenthooks.node_executable`), because where ``node`` lives is not a repo fact.

THE FLOOR IS THE SHIPPED SET, PINNED BY NAME. A rules file that rendered EMPTY would satisfy "the
committed rules are the rendered rules" and every sanctioned row, and would refuse nothing. A count
cannot say WHICH rule came off, and the honest-looking repair when a count disagrees is to edit the
digit -- so :func:`assert_the_shipped_set_is_pinned` takes a set of names with NO DEFAULT.

EVERY REFUSAL IS A ``raise`` RATHER THAN AN ``assert``, for the reason
:mod:`lab_commons.dev.famtests.visibility` states: ``python -O`` erases the second, and a guard a
reader can switch off without editing it is the silent absence this module exists to detect.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

from lab_commons.dev.agent_guard import ENGINE_REL, GUARDED, RULES_REL, guard_installation
from lab_commons.dev.agenthooks import node_executable
from lab_commons.dev.hook_adoption import DENY_RULES, assert_shippable, render
from lab_commons.dev.rules import tracked_files

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from lab_commons.dev.hook_adoption import HookAdoption
    from lab_commons.dev.hooks import DenyRule

__all__ = [
    'GuardNotLive',
    'assert_committed_rules_are_rendered',
    'assert_every_rule_is_accounted_for',
    'assert_node_is_available',
    'assert_refused_by',
    'assert_sanctioned',
    'assert_the_guard_is_live',
    'assert_the_shipped_set_is_pinned',
    'decision_for',
    'reason_for',
    'shipped_rules',
]

#: The engine reads a payload and writes a decision; nothing here waits on a network or an editor.
_ENGINE_TIMEOUT_S = 60


class GuardNotLive(AssertionError):
    """The guard a repo declares is not the guard a command in that repo would meet."""


def _refuse(message: str) -> None:
    """Raise the one refusal this module makes, so every arm fails in one recognisable way."""
    raise GuardNotLive(message)


def assert_node_is_available() -> None:
    """NOT A SKIP, AND THAT IS THE POINT: no node means no guard, on this box, for every repo.

    The obvious spelling is ``skipif(shutil.which('node') is None)`` and it is the wrong one. The
    condition is not "this check does not apply here", it is "the thing under test cannot run at
    all", so a suite that goes quiet on it reports green for exactly the state it exists to detect.

    Raises:
        GuardNotLive: no ``node`` resolves, so nothing executes any repo's hook on this box.

    """
    try:
        node_executable()
    except RuntimeError as exc:
        _refuse(
            f"{exc} -- so nothing executes any repo's `.claude/hooks/deny-commands.js` and every "
            f'checkout on this box refuses nothing, whatever its files report. Install node, or say '
            f'somewhere a reader looks that this box is unguarded.'
        )


def decision_for(*, root: Path, command: str) -> str | None:
    """Run the guard INSTALLED IN *root* over one Bash command; the refusal text, or ``None``.

    The engine and the rules are the repo's own files rather than the ones in this wheel -- see the
    module docstring for why that is the question. The engine fails OPEN by construction, so an
    unparseable payload or a broken rule shows up as ``None``, which is the truthful answer: nothing
    was refused.

    Raises:
        GuardNotLive: the engine or the rules file is missing, so the command met no guard at all.

    """
    engine, rules = root / ENGINE_REL, root / RULES_REL
    for path in (engine, rules):
        if not path.is_file():
            _refuse(f'{path} is not there, so nothing in {root} judged {command!r}')
    payload = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': command}, 'cwd': str(root)})
    done = subprocess.run(
        [node_executable(), str(engine), str(rules)],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
        timeout=_ENGINE_TIMEOUT_S,
    )
    if not done.stdout.strip():
        return None
    hook = json.loads(done.stdout)['hookSpecificOutput']
    return hook['permissionDecisionReason'] if hook.get('permissionDecision') == 'deny' else None


def shipped_rules(*, root: Path) -> frozenset[str]:
    """The rule NAMES the committed rules file carries, read rather than derived from a declaration."""
    rows = json.loads((root / RULES_REL).read_text(encoding='utf-8'))
    return frozenset(row['name'] for row in rows)


def reason_for(*, root: Path, rule: str) -> str:
    """The refusal text the COMMITTED rules file carries for *rule*, read rather than restated.

    Raises:
        GuardNotLive: *rule* is not in the shipped set, so no command can be refused by it and an
            arm expecting it would be asserting about a rule that is not there.

    """
    rows = {row['name']: row['reason'] for row in json.loads((root / RULES_REL).read_text(encoding='utf-8'))}
    if rule not in rows:
        _refuse(f'{rule} is not in the set {root} ships, so no command can be refused by it')
    return rows[rule]


def assert_the_guard_is_live(*, root: Path) -> None:
    """Engine, rules and wiring are all installed -- and a red names the part that is not.

    Raises:
        GuardNotLive: any part is absent, stale or foreign.

    """
    report = guard_installation(root)
    if report.verdict != GUARDED:
        detail = '\n  '.join(f'{part.part}: {part.status} -- {part.detail}' for part in report.parts)
        _refuse(
            f'the agent guard in {root} is {report.verdict}, not {GUARDED}:\n  {detail}\n'
            f'Install it with `python -m lab_commons.dev.agent_guard --install --repo .`. A declared '
            f'guard that is not live refuses nothing while reading as protection.'
        )


def assert_committed_rules_are_rendered(
    *,
    root: Path,
    adoption: HookAdoption,
    rules: Sequence[DenyRule] = DENY_RULES,
) -> None:
    """The file the engine reads IS the repo's declaration, byte for byte.

    *rules* carries the family registry as its default because WHICH rules exist is the family's
    answer, not a repo's -- unlike *adoption*, which is the repo's and has none.

    Raises:
        GuardNotLive: the committed JSON has drifted from the rendered declaration.

    """
    committed = (root / RULES_REL).read_text(encoding='utf-8')
    if committed != render(adoption, rules):
        _refuse(
            f'{RULES_REL} in {root} has drifted from `render(ADOPTION)`. Re-render and commit the '
            f'result: the declaration is the half a reader trusts, and the JSON is the half the '
            f'engine obeys, and nothing else keeps them equal.'
        )


def assert_every_rule_is_accounted_for(
    *,
    root: Path,
    adoption: HookAdoption,
    rules: Sequence[DenyRule] = DENY_RULES,
) -> None:
    """No silently-dropped rule, no typo'd ID, and no exit naming a file this tree does not track.

    Raises:
        lab_commons.dev.hooks.UnremediedRule: delegated to
            :func:`lab_commons.dev.hook_adoption.assert_shippable`, which already refuses all three
            and names the repo while doing it.

    """
    assert_shippable(adoption, tracked_files(root), rules)


def assert_the_shipped_set_is_pinned(*, root: Path, declared: frozenset[str]) -> None:
    """THE FLOOR, BY NAME. An empty rules file would satisfy every other arm in this module.

    *declared* has NO DEFAULT: which rules a repo can honestly ship depends on the exits that repo
    offers, so there is no family answer to fall back on.

    Raises:
        GuardNotLive: the shipped set moved in either direction.

    """
    shipped = shipped_rules(root=root)
    if shipped != declared:
        _refuse(
            f'the shipped rule set in {root} moved: gained {sorted(shipped - declared)}, lost '
            f'{sorted(declared - shipped)}. Update the pin in the SAME edit that changes the '
            f'adoption, and say WHICH rule moved -- a count could not.'
        )


def assert_refused_by(*, root: Path, command: str, rule: str) -> None:
    """*command* is refused, BY *rule*, with a reason a reader can act on.

    Naming the rule is the point: see the module docstring for the measured shadowing that a
    "something refused it" arm could not see.

    Raises:
        GuardNotLive: the command passed, was refused with no reason, or was refused by a different
            rule -- which means the one named here could stop firing entirely and nothing would red.

    """
    reason = decision_for(root=root, command=command)
    if reason is None:
        _refuse(f'{command!r} passed the guard in {root}, and {rule} shipped for it says it must not')
    if not (reason or '').strip():
        _refuse(f'{command!r} was refused with no reason to act on; a refusal with no exit is a sealed road')
    expected = reason_for(root=root, rule=rule)
    if reason != expected:
        _refuse(
            f'{command!r} was denied, but NOT by {rule} -- the refusal it got was:\n'
            f'  {(reason or "")[:160]}\n'
            f'A rule earlier in registry order is answering for this shape, so {rule} could stop '
            f'firing altogether and this arm would still be green if it only asked whether SOMETHING '
            f'refused.'
        )


def assert_sanctioned(*, root: Path, command: str) -> None:
    """The other side of the ratchet: a guard that refused everything would pass every arm above.

    The rows that matter most are a repo's own EXITS -- the commands its own refusals tell an agent
    to type. One family rule's remedy line literally spells ``git push``, so the rule's pattern fires
    on the command it hands out, and only an ``allow`` opens it. Reading the regex is not the check;
    running it is.

    Raises:
        GuardNotLive: the command was refused, so the repo's own way out is sealed.

    """
    reason = decision_for(root=root, command=command)
    if reason is not None:
        _refuse(f'{command!r} is sanctioned in {root} and the guard refused it:\n  {reason[:160]}')
