"""NO ``permissions.allow`` ENTRY MAY NAME A COMMAND THE DENY ENGINE REFUSES.

``.claude/settings.json`` and ``.claude/hooks/deny-rules.json`` are two hand-written files that speak
about the same thing -- which commands an agent may issue -- and nothing made them agree. The hook
wins at runtime, so a contradiction is never a functional hazard; it is A DECLARATION THAT LIES
instead, which this family calls its dominant defect. An ``allow`` row publicly promises a road the
engine refuses, in a file that is committed and read on every box, and the reader who believes it
spends its refusal budget finding out.

MEASURED 2026-09-17 across the three repos that ship this engine, by DRIVING it rather than comparing
patterns by eye: exactly one contradiction existed anywhere, ``Bash(pytest *)`` against
``BARE-TEST-INVOCATION``, installed the same day. One row is the whole point -- a one-time
reconciliation of two hand-written files drifts again by next week.

WHY THIS IS A SHARED BODY. The same guard existed three times: 96.9% identical CODE between two of
them with the difference being exactly TWO CONSTANTS, and 89.1% against the third, whose extra
divergence was not a repo fact at all but a hand-rolled engine call its own docstring dated to a
stale dependency pin. So the seam is two facts, and both arrive with NO DEFAULT:

* *root* -- the tree being asked about. A scan rooted at the working directory answers, plausibly,
  about somebody else's checkout.
* *sanctioned* -- the exit a red is redirected to. THE FIX FOR A RED IS REDIRECTION, NOT DELETION:
  ask what the row was trying to permit and permit THAT. An agent must always be left its own door,
  and sealing the road is the other way to make this guard green. A default here would name one
  repo's verdict command in another repo's failure message, sending a reader to a command that does
  not exist -- so the red would be repaired by deleting the row, which is the wrong repair.

THE FLOOR IS DELEGATED RATHER THAN RE-WALKED, and that is this body's one improvement on all three
copies. Each of them hand-walked ``hooks.PreToolUse`` for the rules filename, which cannot tell an
ABSENT wiring from a STALE one. :func:`lab_commons.dev.agent_guard.guard_installation` already tells
those apart by name, so the floor asks it: a repo whose engine is not wired has nothing for an allow
row to contradict, and reporting that as agreement is the exact failure this module is about.

A SCAN REPORTS WHAT IT SEARCHED FOR. :class:`Scan` carries *probed* beside *refused*, because zero
contradictions over zero probed rows is not agreement -- it is an unasked question, and
:func:`assert_no_allow_contradicts` refuses it rather than passing.

THE SUBJECT IS THE CONSUMER'S OWN ENGINE, and that had to be decided rather than inherited. Until
2026-09-17 this body drove the copy inside the installed wheel while its sibling
:mod:`lab_commons.dev.famtests.agentguard` drove ``<root>/.claude/hooks/deny-commands.js``; one
consumer adopted four of the five bodies and refused this one over that contradiction instead of
weakening its arm, which was the right call. :func:`contradictions` now takes the engine as a PATH --
the family's one spelling for *whose copy* -- defaulting to the one beside the rules it was handed,
and REFUSING rather than falling back when it is absent.

WHAT THIS DOES NOT PROVE. That the agent client honours ``permissions.allow`` at all; that is a fact
about a tool's configuration loading, not about any tree here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from lab_commons.dev.agent_guard import (
    ENGINE_REL,
    INSTALLED,
    RULES_REL,
    SETTINGS_REL,
    engine_beside,
    guard_installation,
)
from lab_commons.dev.agenthooks import run_engine

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    'GLOB_CASES',
    'Scan',
    'UnreadableSettings',
    'VacuousAllowScan',
    'allow_entries',
    'assert_no_allow_contradicts',
    'assert_the_scan_can_still_see',
    'contradictions',
    'probe_command',
]

#: What an interior ``*`` is instantiated as: ONE opaque word, which is what it stands for.
_ARGUMENT = 'ARG'

#: The permission rows this guard is about. Any other tool's rows promise nothing a shell engine
#: could refuse, so they are not probed -- reported as ``None`` rather than skipped silently.
_BASH_ROW = re.compile(r'Bash\((.*)\)', flags=re.DOTALL)

#: The instantiation, pinned by a consumer's parametrize. FAMILY rather than repo data: the
#: ``Bash(...)`` glob spelling belongs to the agent client, not to any repository, and the three
#: forked copies each pinned it with one repo-flavoured example that taught the next reader nothing.
GLOB_CASES: tuple[tuple[str, str | None], ...] = (
    ('Bash(pytest *)', 'pytest'),
    ('Bash(git push *)', 'git push'),
    ('Bash(python *tool.py*)', f'python {_ARGUMENT} tool.py'),
    ('Read(**)', None),
)


class UnreadableSettings(OSError):
    """The settings file is absent or is not JSON.

    RAISED RATHER THAN READ AS EMPTY. No rows means no contradictions means green, so an unreadable
    declaration would report as the strongest possible agreement between two files, one of which
    could not be opened.
    """


class VacuousAllowScan(AssertionError):
    """Nothing was probed, so nothing was measured.

    An ``AssertionError`` because it is a test-time finding rather than a programming error: the
    repo declares no command shape this engine could refuse, and that is a fact its author should
    state rather than a result this scan may report as agreement.
    """


@dataclass(frozen=True)
class Scan:
    """What was probed, and which of those the engine refused."""

    probed: tuple[str, ...]
    refused: dict[str, str]

    @property
    def vacuous(self) -> bool:
        """No row was probed at all, so the empty *refused* says nothing about the declaration."""
        return not self.probed


def probe_command(entry: str) -> str | None:
    """One ``permissions.allow`` row as the concrete command it promises, or ``None`` if not Bash.

    A row is a GLOB and the engine reads TEXT, so the glob is instantiated. LEADING AND TRAILING
    ``*`` ARE DROPPED rather than substituted -- the most permissive reading of the row, which puts
    the named program at a command POSITION where a ``matches: command`` rule can see it, with no
    trailing noise a rule might anchor against. An INTERIOR ``*`` becomes one opaque word.
    """
    found = _BASH_ROW.fullmatch(entry.strip())
    if found is None:
        return None
    instantiated = re.sub(r'\*+', f' {_ARGUMENT} ', found.group(1).strip().strip('*'))
    return ' '.join(instantiated.split())


def allow_entries(settings: Path) -> tuple[str, ...]:
    """Every ``permissions.allow`` row in *settings*, in file order.

    Raises:
        UnreadableSettings: when the file is absent or is not JSON. See that class for why.

    """
    if not settings.is_file():
        msg = f'{settings} does not exist, so the allow list this guard judges is not there to judge'
        raise UnreadableSettings(msg)
    try:
        doc = json.loads(settings.read_text(encoding='utf-8'))
    except json.JSONDecodeError as error:
        msg = f'{settings} is unreadable JSON ({error.msg}); the agent client reads no permissions out of it'
        raise UnreadableSettings(msg) from error
    rows = doc.get('permissions', {}).get('allow', []) or []
    return tuple(str(row) for row in rows)


def contradictions(settings: Path, rules: Path, *, cwd: Path, engine: Path | None = None) -> Scan:
    """Every allow row in *settings* whose own promise *rules* refuses, and what it was asked.

    The engine is DRIVEN through :func:`lab_commons.dev.agenthooks.run_engine` -- a real
    ``deny-commands.js`` under ``node``, on the real payload shape -- because comparing an allow glob
    against a deny regex by eye is the reasoning this measurement exists to replace.

    WHICH COPY IS THE SUBJECT, AND WHY THE DEFAULT IS THE CONSUMER'S. This body used to drive
    :func:`lab_commons.dev.agenthooks.decide`, which names a SHIPPED engine and therefore always
    judged the copy inside the installed wheel -- while :func:`lab_commons.dev.famtests.agentguard.decision_for`,
    one module over in the same package, drove ``<root>/.claude/hooks/deny-commands.js``. Two bodies,
    opposite answers to *which file is the subject*, and a consumer refused to adopt this one for
    exactly that reason rather than weakening its own arm. The consumer was right, and not as a
    preference: measured 2026-09-17, the installed engines in three repos had drifted far enough to
    ALLOW a shape the shipped engine had refused since 2026-08-22, so a body judging the wheel goes
    green on precisely the checkout whose own guard has stopped working.

    Args:
        settings: the ``settings.json`` whose ``permissions.allow`` rows are the declaration.
        rules: the ``deny-rules.json`` those rows are judged against.
        cwd: the tool call's working directory, which the engine expands into ``{root}``.
        engine: the ``deny-commands.js`` to run. Defaults to the one BESIDE *rules*
            (:func:`lab_commons.dev.agent_guard.engine_beside`) -- the copy that repo really runs.
            Pass :func:`lab_commons.dev.agenthooks.engine_path` to ask about the wheel's instead.

    Raises:
        UnreadableSettings: *settings* is absent or is not JSON.
        lab_commons.dev.agenthooks.EngineNotReadable: the engine or the rules file is not there.
            REFUSED RATHER THAN FALLEN BACK to the wheel: a silent substitution would re-create the
            defect above with extra steps, reporting the family's engine as this repo's verdict.

    """
    judge = engine_beside(rules) if engine is None else engine
    probed: list[str] = []
    refused: dict[str, str] = {}
    for entry in allow_entries(settings):
        command = probe_command(entry)
        if not command:
            continue
        probed.append(entry)
        reason = run_engine(judge, command, rules, cwd=cwd)
        if reason is not None:
            refused[entry] = reason
    return Scan(probed=tuple(probed), refused=refused)


def _assert_there_is_something_to_contradict(root: Path) -> None:
    """The floor: a repo whose guard is not live has nothing for an allow row to lie about."""
    rules = root / RULES_REL
    if not rules.is_file():
        msg = (
            f'{rules} does not exist, so there is no registry for an allow row to contradict and every '
            f'row is trivially honest. That is an unasked question, not agreement.'
        )
        raise AssertionError(msg)
    engine = root / ENGINE_REL
    if not engine.is_file():
        msg = (
            f'{engine} does not exist, so no engine in this checkout judges anything and every allow '
            f'row is trivially honest. Install one with `python -m lab_commons.dev.agent_guard '
            f'--install --repo .`; the wheel ships a copy but running THAT one here would answer '
            f'about the family rather than about this tree.'
        )
        raise AssertionError(msg)
    wiring = guard_installation(root).by_part['wiring']
    if wiring.status != INSTALLED:
        msg = (
            f'the agent guard wiring in {root / SETTINGS_REL} is {wiring.status}: {wiring.detail}. '
            f'Nothing in this repo runs the engine, so the permissions block is in tension with no '
            f'guard at all and a green here would be measuring an empty room.'
        )
        raise AssertionError(msg)


def assert_no_allow_contradicts(*, root: Path, sanctioned: str) -> None:
    """THE PROPERTY, for one repository. Both arguments are that repository's own answers.

    Args:
        root: the checkout being asked about.
        sanctioned: the command a red is redirected to -- this repo's verdict entry point.

    Raises:
        VacuousAllowScan: when no ``Bash(...)`` row exists to probe.
        AssertionError: when the guard is not live, or when a row promises a refused command.

    """
    _assert_there_is_something_to_contradict(root)
    scan = contradictions(root / SETTINGS_REL, root / RULES_REL, cwd=root)
    if scan.vacuous:
        msg = (
            f'no `Bash(...)` row in {root / SETTINGS_REL} -- this guard probed nothing, so its silence '
            f'is an unasked question rather than agreement between the two files.'
        )
        raise VacuousAllowScan(msg)
    if not scan.refused:
        return
    report = '\n'.join(
        f'  {entry}  ->  promises {probe_command(entry)!r}, engine says: {reason.splitlines()[0]}'
        for entry, reason in scan.refused.items()
    )
    msg = (
        f'{len(scan.refused)} of {len(scan.probed)} probed `permissions.allow` row(s) in '
        f'{root / SETTINGS_REL} name a command the deny engine refuses:\n{report}\n'
        f'The hook wins at runtime, so this is A DECLARATION THAT LIES rather than an open road. Fix '
        f'it by REDIRECTION: ask what the row was trying to permit and permit the sanctioned spelling '
        f'for that intent ({sanctioned}). Delete a row only when nothing sanctioned exists for it, and '
        f'say so where the deletion lands.'
    )
    raise AssertionError(msg)


def assert_the_scan_can_still_see(
    *,
    root: Path,
    denied_entry: str,
    harmless_entry: str,
    scratch: Path,
) -> None:
    """THE INSTRUMENT'S FLOOR: plant both directions against this repo's own rendered rules.

    Without this, the body above passes exactly as well against an engine that stopped matching --
    the state in which every real allow row reads as honest. Both rows are arguments with NO
    DEFAULT because WHICH shapes a repo refuses depends on the rules it could honestly ship:
    :func:`lab_commons.dev.hook_adoption.deny_rules` DROPS a rule whose remedy that repo lacks, so a
    row denied in one tree is permitted in another and a family default would assert the wrong thing.

    Args:
        root: the repository whose rendered rules do the judging.
        denied_entry: an allow row this repo's rules MUST refuse.
        harmless_entry: one they must NOT, so a matcher that refuses everything is caught.
        scratch: a directory to write the planted settings file into.

    """
    scratch.mkdir(parents=True, exist_ok=True)
    planted = scratch / 'settings.json'
    planted.write_text(
        json.dumps({'permissions': {'allow': [denied_entry, harmless_entry]}}),
        encoding='utf-8',
    )
    scan = contradictions(planted, root / RULES_REL, cwd=root)
    if denied_entry not in scan.refused:
        msg = (
            f'the planted row {denied_entry!r} went UNDETECTED against {root / RULES_REL}, so a green '
            f'from this guard proves nothing about the real settings file. The engine, the glob '
            f'instantiation, or the rule that refuses that shape has moved.'
        )
        raise AssertionError(msg)
    if harmless_entry in scan.refused:
        msg = (
            f'the harmless row {harmless_entry!r} was reported as a contradiction, which would push a '
            f'reader to rewrite or delete a row that promises nothing forbidden.'
        )
        raise AssertionError(msg)
