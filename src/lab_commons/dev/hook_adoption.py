"""ONE repo's half of the shared deny registry: the remedies IT offers, and what it may ship.

THE HALF A SHARED REGISTRY CANNOT HOLD. A deny rule's STATEMENT is universal and is authored once
in :mod:`lab_commons.dev.hooks`. Its REMEDY is a file in a tree, and a tree belongs to one repo:
``scripts/hooks/with-retry.sh`` resolves in exactly one checkout on earth. So the two halves have
different owners and live in different modules -- the same ID-plus-mechanism split
:class:`lab_commons.dev.rules.Adoption` already uses for rule statements, not a second scheme.

A RULE WHOSE REMEDY DOES NOT EXIST HERE IS NOT SHIPPED HERE. That is the design, and it is not a
convenience: a deny rule whose exit does not exist in the repo reading it leaves an agent with
disobey or stop, and the first is what actually happens. So :func:`deny_rules` DROPS such a rule
rather than softening its reason, :func:`unremedied` makes the resulting gap visible instead of
silent, and :func:`assert_shippable` refuses a remedy whose file the tree does not track.

THE CONSUMPTION RECIPE, for the three repos that have nothing today. The wiring is a separate change
and is deliberately not performed from here::

    # <repo>/scripts/repo/write_deny_rules.py
    from pathlib import Path
    from lab_commons.dev.hooks import Remedy
    from lab_commons.dev.hook_adoption import HookAdoption, render
    from lab_commons.dev.venvpath import current_os_name, venv_interpreter

    PYTHON = venv_interpreter(os_name=current_os_name())
    VERIFY = Remedy('verdict-entry-point', f'{PYTHON} -m lab_commons.dev.verify')
    ADOPTION = HookAdoption(
        app_name='wdg-lab',
        remedies={'BARE-TEST-INVOCATION': VERIFY, 'PUSH-NO-VERIFY': VERIFY},
        declared_absent=frozenset({'GIT-NETWORK-VERB', 'RAW-PROCESS-KILL'}),
    )
    Path('.claude/hooks/deny-rules.json').write_text(render(ADOPTION), encoding='utf-8')

THE INTERPRETER IS RESOLVED AND NEVER SPELLED, and that line is the reason this recipe was
rewritten on 2026-09-19. It used to read ``.venv/Scripts/python.exe`` literally, and it was copied
VERBATIM into ``scripts/deny_rules.py`` in two consuming repos, where it became live code naming a
file macOS does not have. A RECIPE IS NOT A DOCSTRING -- it is source somebody will paste, so a
platform-blind spelling in one is a platform-blind spelling in every repo that adopts the kit, and
prose is exactly where a retired spelling survives longest. A ``Remedy.command`` is shown VERBATIM
to a refused agent and so must stay CONCRETE for the box that is running; making the tracked
``permissions.allow`` row portable is a separate job and belongs to
:func:`lab_commons.dev.allow_adoption.glob_for`, which normalises it.

The repo then commits that JSON and points a ``PreToolUse`` Bash matcher in `.claude/settings.json`
at the engine with the file as ``argv[2]``. The rendered rows carry exactly the engine's own field
names -- ``name``, ``pattern``, ``matches``, ``allow``, ``reason`` -- so nothing translates between
the halves, and a suite in the consuming repo calls :func:`assert_shippable` plus a comparison of
the committed file against :func:`render` so the two cannot drift.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from lab_commons.dev.hooks import DENY_RULES, DenyRule, Remedy, UnremediedRule, rules_by_id

__all__ = [
    'HookAdoption',
    'assert_shippable',
    'deny_rules',
    'needing',
    'remedy_gaps',
    'render',
    'unremedied',
    'waived',
]


@dataclass(frozen=True, slots=True)
class HookAdoption:
    """ONE repo's remedies for the shared rules it ships, and the rules it declares it cannot.

    *remedies* maps a rule ID to the exit THIS repo offers. *declared_absent* is the honest other
    side: a rule this repo does not ship, ON RECORD, because it has no exit to offer yet. A rule in
    NEITHER set is the silent case, and :func:`unremedied` is what makes it visible -- a rule that is
    quietly not shipped is indistinguishable from one nobody has looked at.

    Construction refuses a rule listed in BOTH, for the reason
    :class:`lab_commons.dev.rules.Adoption` gives: the contradiction is what lets a stale entry sit
    there reading as shipped while being waived.
    """

    app_name: str
    remedies: Mapping[str, Remedy] = field(default_factory=dict)
    declared_absent: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        """Refuse an adoption that cannot name the repo it speaks for, at construction."""
        if not self.app_name.strip():
            msg = 'an adoption with no app_name cannot report WHICH repo is missing a remedy.'
            raise ValueError(msg)
        both = sorted(set(self.remedies) & self.declared_absent)
        if both:
            msg = (
                f'{self.app_name} both remedies and declares absent: {both}. One of the two is stale, and a '
                f'row that reads as shipped while being waived is the failure this registry cannot see.'
            )
            raise ValueError(msg)


def needing(rules: Sequence[DenyRule]) -> frozenset[str]:
    """The rules an adoption has to answer for: those whose exit is a file in a repo.

    A rule whose remedy is a plain git verb ships EVERYWHERE and is not accounted for, because there
    is nothing a repo could supply and nothing it could sensibly decline -- asking it to list one
    would be bookkeeping that only ever has one right answer, and a check with one right answer
    teaches a reader to type it without reading.
    """
    return frozenset(rule.id for rule in rules if rule.needs is not None)


def unremedied(rules: Sequence[DenyRule], adoption: HookAdoption) -> tuple[str, ...]:
    """Rule IDs *adoption* neither remedies nor declares absent -- the gap nobody looked at.

    IDs rather than a count, because the set is what an adopting repo pins: a repo that dropped one
    rule while picking up another would compare equal on a number.
    """
    return tuple(sorted(needing(rules) - set(adoption.remedies) - set(adoption.declared_absent)))


def waived(rules: Sequence[DenyRule], adoption: HookAdoption) -> tuple[str, ...]:
    """The rules *adoption* declares absent, sorted -- the visible gap, not a silent one."""
    return tuple(sorted(set(rules_by_id(rules)) & set(adoption.declared_absent)))


def deny_rules(adoption: HookAdoption, rules: Sequence[DenyRule] = DENY_RULES) -> tuple[dict[str, str], ...]:
    """The rows *adoption* can HONESTLY ship, in registry order.

    A rule needing an artefact this repo does not supply is DROPPED, not softened -- see this
    module's docstring for why that is the design rather than a shortcut.

    Raises:
        UnremediedRule: the adoption names an ID the registry does not define -- a typo remedies
            nothing and says so nowhere -- or supplies a remedy answering a different kind, which
            :meth:`lab_commons.dev.hooks.DenyRule.reason` refuses.

    """
    known = rules_by_id(rules)
    strangers = sorted((set(adoption.remedies) | set(adoption.declared_absent)) - set(known))
    if strangers:
        msg = (
            f'{adoption.app_name} names {strangers}, which the deny registry does not define. A typo in an ID '
            f'ships nothing and reports nothing, which is how a rule quietly stops being enforced.'
        )
        raise UnremediedRule(msg)
    unconditional = sorted(adoption.declared_absent - needing(rules))
    if unconditional:
        msg = (
            f'{adoption.app_name} declares {unconditional} absent, but those rules need nothing from a repo '
            f'and ship anyway. A waiver that does not waive anything reads as a decision and is not one.'
        )
        raise UnremediedRule(msg)
    out: list[dict[str, str]] = []
    for rule in rules:
        remedy = adoption.remedies.get(rule.id)
        if rule.needs is not None and remedy is None:
            continue
        out.append(rule.rendered(remedy))
    return tuple(out)


def render(adoption: HookAdoption, rules: Sequence[DenyRule] = DENY_RULES) -> str:
    """The shippable rows as the engine's JSON file, indented and newline-terminated.

    Indented because the file is COMMITTED in the consuming repo and read in diffs by people: a
    one-line blob would make every rule change look like the same change.
    """
    return json.dumps(deny_rules(adoption, rules), indent=2, ensure_ascii=False) + '\n'


def remedy_gaps(adoption: HookAdoption, tracked: Iterable[str]) -> tuple[str, ...]:
    """Every supplied remedy whose file is not TRACKED in the adopting tree, named with its rule.

    Takes the tracked set as an argument rather than fetching it, so a control can drive THIS
    function against a planted tree instead of re-implementing it and agreeing with itself. A remedy
    with no ``path`` contributes nothing: a plain git verb has no file to find.
    """
    have = frozenset(tracked)
    return tuple(
        f'{name}: the {remedy.kind} remedy runs {remedy.path}, which is not a tracked file'
        for name, remedy in sorted(adoption.remedies.items())
        if remedy.path is not None and remedy.path not in have
    )


def assert_shippable(adoption: HookAdoption, tracked: Iterable[str], rules: Sequence[DenyRule] = DENY_RULES) -> None:
    """Raise unless *adoption* accounts for every rule and every remedy it names really exists.

    THE ADOPTING REPO'S ENTRY POINT. Three refusals, each naming the repo:

    * a rule neither remedied nor declared absent -- silently not shipped;
    * an ID that is not a rule, a waiver of a rule that ships anyway, or a remedy answering a
      different kind -- delegated to :func:`deny_rules`, which already refuses all three;
    * a remedy naming a file the tree does not track. TRACKED rather than merely present, for the
      reason :func:`lab_commons.dev.rules.tracked_files` gives: a file in one working copy is not a
      file the fleet has, so an exit resting on it is an exit nobody else can take.

    Raises:
        UnremediedRule: any of the above.

    """
    silent = unremedied(rules, adoption)
    if silent:
        msg = (
            f'{adoption.app_name} neither remedies nor declares absent {len(silent)} deny rule(s):\n  '
            + '\n  '.join(silent)
            + '\nSupply the remedy this repo offers, or list it in declared_absent so the gap is on record. '
            'A rule that is quietly not shipped looks exactly like one nobody has read.'
        )
        raise UnremediedRule(msg)
    deny_rules(adoption, rules)
    gaps = remedy_gaps(adoption, tracked)
    if gaps:
        msg = (
            f'{adoption.app_name} offers {len(gaps)} remedy/remedies that do not exist in its tree:\n  '
            + '\n  '.join(gaps)
            + '\nBuild the remedy, or declare the rule absent. A refusal pointing at a missing file is the '
            'sealed road wearing a signpost.'
        )
        raise UnremediedRule(msg)
