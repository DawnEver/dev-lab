"""The shared rules registry -- one row per universal development rule, with its remedy.

THE DEFECT THIS EXISTS TO CLOSE, MEASURED. Every repo in this family carries its own copy of the
rules that are not about its subject: `wdg-lab`'s rules and `motronics-studio`'s share **zero
verbatim 4-gram runs** -- each was independently authored, with its own incident and its own dated
user quote -- and yet **5 of wdg-lab's 7 rules are the SAME RULE** as one motronics already states.
The copy in `wdg-lab` is unenforced prose; the copy in motronics has a ratchet. Sharing the rule
TEXT buys nothing (merging two wordings destroys the incident evidence each carries). Sharing rule
**IDENTITY plus the mechanism that refuses a violation** is the thing that works: one canonical
registry, adopted by ID, each repo supplying its own evidence and thresholds.

THE NOUN TEST decides what belongs here, and it is mechanical rather than a judgement call: **delete
every domain noun from the rule -- if it still constrains anything, it is universal.** "The reference
is a LADDER: one vendor first, a second vendor second" leaves nothing behind and stays home. "A
declaration that lies is the dominant defect" survives intact and belongs here.

A RULE WITH NO RESOLVABLE MECHANISM IS A REFUSAL, IN THREE PLACES, and they are different refusals:

* :class:`Rule` refuses AT CONSTRUCTION to hold a row with no mechanism at all. A rule carried as a
  comment is prose masquerading as a guarantee, and no amount of careful writing fixes that -- the
  row cannot exist, so it cannot drift.
* :class:`Adoption` refuses AT ADOPTION TIME to list a rule as enforced with an empty mechanism
  tuple, and refuses a rule that is both enforced and declared absent. Both are the same complaint as
  the first, one repo further out.
* :func:`assert_enforceable` and :func:`assert_adopted` refuse AT CHECK TIME when a mechanism is not
  live in the tree being checked -- a test path that is not tracked, or a lint code that is not
  selected -- and, for a shared rule, when a repo neither enforces it nor declares it absent.
  Deleting the mechanism reds, which is the whole point -- that check is what the prose never had.

THE MECHANISM IS A PATH OR A LINT CODE, exactly as the registry this is modelled on states:
``'tests/...py'`` for a test that refuses the hazard, or ``('ruff', 'PLC0415')`` for a lint rule that
must be selected and not globally ignored. The data half writes them that way; :func:`_mechanism`
turns them into the two types. Paths are REPO-RELATIVE.

THE TWO HALVES HAVE DIFFERENT OWNERS, and conflating them was this module's first defect. The
STATEMENT is universal and lives here; the MECHANISM is a file in a tree, and a tree belongs to one
repo. So a row's mechanisms are the EXISTENCE PROOF -- where the rule is enforced by whoever authored
it, which is what makes "a rule with no mechanism cannot exist" true -- and each adopter supplies its
own through :class:`Adoption`, checked by :func:`assert_adopted`. A shared row that silently degrades
to a comment in a repo that never built the mechanism is the exact defect named above, and so is a
shared row that grades every repo against one repo's paths.

WHAT IS NOT HERE. The per-repo row (the dependency arrow, the case conventions, the launcher's
flags), the domain row (which vendor arbitrates which quantity), and the incident evidence that
explains why a rule exists -- that evidence stays in the repo that lived it, as a note attached to
the ID. Reasoning lives in `.claude/memory/`; this module is DATA.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from lab_commons.dev._rule_rows import ROWS
from lab_commons.dev.profile import RepoProfile
from lab_commons.file_io import read_toml

__all__ = [
    'RULES',
    'Adoption',
    'LintRule',
    'Mechanism',
    'Rule',
    'TestPath',
    'UnenforceableRule',
    'assert_adopted',
    'assert_enforceable',
    'guard',
    'lint',
    'tracked_files',
    'unadopted',
    'unresolved',
]

#: A rule ID is a slug, never a number, and the reason is measured rather than aesthetic: an integer
#: cannot say WHICH row moved, so when a pin disagrees the honest-looking repair is to edit the digit
#: (`.claude/rules/rem/integration.md` records a pin that was lowered to a broken reading).
_ID: Final = re.compile(r'[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*')

#: The one lint-code spelling the data half may use, so `('ruff', ...)` cannot quietly become a
#: second, unchecked mechanism kind that no reader knows how to resolve.
_LINT_KIND: Final = 'ruff'


class UnenforceableRule(RuntimeError):
    """A rule is carried without a mechanism that can refuse a violation.

    Raised at construction (an empty mechanism tuple) and at check time (a mechanism that is not
    live in the adopting tree). Both are the same complaint: the row promises a refusal it cannot
    deliver. Its own class rather than a ``ValueError``, because the caller it is aimed at is an
    adopter's gate, and the fix is to build or restore the mechanism -- not to correct an argument.
    """


@dataclass(frozen=True, slots=True)
class TestPath:
    """A repo-relative test module that refuses the hazard, resolved against the adopting repo.

    A row usually names more than one -- the guard, its data half, its pins -- so the row's evidence
    is the whole set. A mechanism is never a single file when the guard is split on the data/checks
    seam, and naming only the checks half would let its table rot unnoticed.

    THE NAME IS ACCURATE AND THEREFORE NEEDS ONE LINE OF DEFENCE: a class whose name starts with
    ``Test`` is collected by pytest as a test class wherever it is imported, which turns a consumer's
    ``from lab_commons.dev.rules import TestPath`` into a collection error. ``__test__`` is pytest's
    own opt-out and is the honest fix -- renaming the class would trade an accurate name for a
    collector's convenience.
    """

    __test__ = False

    path: str

    def __post_init__(self) -> None:
        text = self.path.strip()
        if not text:
            msg = 'a mechanism with no path names nothing, and a rule pointing at nothing is the defect.'
            raise ValueError(msg)
        if text.startswith('/') or '\\' in text or '..' in Path(text).parts:
            msg = (
                f'mechanism path {self.path!r} must be REPO-RELATIVE with POSIX separators: a mechanism '
                f'is resolved against the adopting repo, so an absolute path would name one box.'
            )
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class LintRule:
    """A lint code that must be selected and not globally ignored by the adopting repo's config."""

    code: str

    def __post_init__(self) -> None:
        if not self.code.strip():
            msg = 'a lint mechanism with no code is indistinguishable from no mechanism at all.'
            raise ValueError(msg)


#: A mechanism is a test file or a lint code -- never a description of one.
Mechanism = TestPath | LintRule


def guard(path: str) -> TestPath:
    """``guard('tests/...py')`` -- the readable constructor, so a row reads as the mechanisms it names.

    Deliberately NOT named ``test``: a callable whose name starts with ``test`` is collected as a
    test FUNCTION by pytest wherever it is imported, so a consumer's one-line import would become a
    ``fixture 'path' not found`` error. The class keeps its accurate name behind ``__test__ = False``;
    a function has no equivalent that is worth relying on.
    """
    return TestPath(path)


def lint(code: str) -> LintRule:
    """``lint('PLC0415')`` -- the sibling constructor, for a rule a linter already refuses."""
    return LintRule(code)


@dataclass(frozen=True, slots=True)
class Rule:
    """One universal rule: its stable ID, its statement, and what refuses a violation of it.

    *id* is the handle every adopter cites, so it is stable by contract -- renaming one is a breaking
    change to every rules page that references it, which is stated here because the temptation is to
    improve a slug while editing the statement it names.

    *statement* is the constraint IN THE WORDS THE SHARED SOURCE OWNS. It is authored once, here, and
    a repo's rules page cites the ID rather than restating it -- two statements of one rule is
    exactly the drift this registry removes.

    *mechanisms* must be non-empty. See :class:`UnenforceableRule`.
    """

    id: str
    statement: str
    mechanisms: tuple[Mechanism, ...]

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.id):
            msg = (
                f'rule id {self.id!r} must be an UPPER-CASE slug (A-Z, 0-9, "-"): it is a handle in every '
                f"adopter's rules page, not a display name, and a handle that reads as a sentence gets "
                f'reworded by whoever edits the statement next.'
            )
            raise ValueError(msg)
        if not self.statement.strip():
            msg = f'rule {self.id!r} states nothing, so nothing can be refused under it.'
            raise ValueError(msg)
        if not self.mechanisms:
            msg = (
                f'rule {self.id!r} has no mechanism. A rule carried as a comment is prose masquerading '
                f'as a guarantee -- it reads as enforced and enforces nothing, which is the dominant '
                f'defect this registry exists to remove. Name the test that refuses it, or the lint code '
                f'that does, or leave the rule OUT until one exists.'
            )
            raise UnenforceableRule(msg)


@dataclass(frozen=True, slots=True)
class Adoption:
    """ONE repo's mechanisms for the rules it cites -- the half a shared registry cannot hold.

    A rule's STATEMENT is universal and is authored once, above. Its MECHANISM is a test file or a
    lint code that lives in a tree, and a tree belongs to one repo: ``tests/architecture/...``
    resolves in exactly one checkout on earth. So the two halves have different owners, and this is
    the second one.

    THE DEFECT THIS EXISTS TO CLOSE, MEASURED 2026-09-15 -- by the repo that AUTHORED the registry.
    Before this class existed, a row carried one mechanism tuple that every adopter was checked
    against, and all 70 mechanisms named motronics paths. Driven against its own tree, lab-commons
    refused its own registry with **70 failures** -- the module docstring promised "a second adopter
    inherits the statements and must supply the mechanism for its own tree", and there was no way to
    supply one. A promise the code does not honour is exactly the defect the registry exists to
    remove, so it was removed.

    *declared_absent* is the honest migration state, and it is three-sided on purpose. A rule that is
    neither enforced nor declared absent is a RED, because citing a rule and saying nothing about it
    is how a citation becomes decoration. A rule that is BOTH is a RED, because the contradiction is
    the thing that would let a stale entry sit there looking enforced. And a declared-absent rule is
    not a red but is RENDERED by :func:`unadopted`, so the gap is visible instead of silent.

    THAT THIRD SIDE NEEDS ITS OWN CEILING, and it does not live here: an escape hatch that no one
    must justify is how a check reaches zero without anything being fixed. The adopting repo pins
    this set as a NAMED SET in its own ratchet, which may only shrink -- the same instrument this
    family already uses for suppressions, skips and module size.
    """

    app_name: str
    mechanisms: Mapping[str, tuple[Mechanism, ...]] = field(default_factory=dict)
    declared_absent: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.app_name.strip():
            msg = 'an adoption with no app_name cannot report WHICH repo is missing a mechanism.'
            raise ValueError(msg)
        both = sorted(set(self.mechanisms) & self.declared_absent)
        if both:
            msg = (
                f'{self.app_name} both enforces and declares absent: {both}. One of the two is stale, and '
                f'a row that reads as enforced while being waived is the failure this registry cannot see.'
            )
            raise ValueError(msg)
        for name, mechs in self.mechanisms.items():
            if not _ID.fullmatch(name):
                msg = f'{self.app_name} adopts {name!r}, which is not a rule ID (UPPER-CASE slug).'
                raise ValueError(msg)
            if not mechs:
                msg = (
                    f'{self.app_name} lists {name!r} with no mechanism. Declaring a rule enforced with '
                    f"nothing refusing it is prose wearing a guarantee's clothes; declare it ABSENT instead."
                )
                raise UnenforceableRule(msg)


def _mechanism(raw: str | tuple[str, str]) -> Mechanism:
    """One data-half mechanism as its type: a path string, or the ``('ruff', CODE)`` pair."""
    if isinstance(raw, str):
        return TestPath(raw)
    kind, value = raw
    if kind != _LINT_KIND:
        msg = (
            f'mechanism kind {kind!r} is not resolvable. The data half may name a lint code only as '
            f"('{_LINT_KIND}', CODE); anything else is a mechanism this module would have to guess at, "
            f'and a guessed mechanism is the same as none.'
        )
        raise UnenforceableRule(msg)
    return LintRule(value)


def _build(rows: Iterable[tuple[str, str, tuple[str | tuple[str, str], ...]]]) -> tuple[Rule, ...]:
    """The data half as :class:`Rule` objects -- where a mechanism-less row refuses, at import."""
    return tuple(
        Rule(id=name, statement=text, mechanisms=tuple(_mechanism(m) for m in mechs)) for name, text, mechs in rows
    )


#: THE REGISTRY. The rows are DATA in their own module and this module is the machinery that reads
#: them -- the same seam `tests/architecture/docs/test_enforced_registry.py` uses, for the same
#: reason: a table edited through the module that checks it drifts away from what it describes.
#: Rows are the number -- nothing here states a count, because a count is blind to which row moved
#: and the honest repair when it disagrees is to edit the digit.
RULES: Final[tuple[Rule, ...]] = _build(ROWS)


def tracked_files(root: Path) -> frozenset[str]:
    """Every file git tracks under *root*, as POSIX relative paths.

    TRACKED rather than merely present, because a mechanism that exists only in a working copy is
    not a mechanism anybody else has: it cannot be run by the fleet, so a verdict citing it is a
    verdict nobody can reproduce. Raises rather than returning empty -- a version-control lookup
    that failed and a tree with nothing tracked are the same empty set, and only one of them means
    the registry is satisfied.
    """
    git = shutil.which('git')
    if git is None:
        msg = (
            'git is not on PATH, so whether a mechanism is TRACKED cannot be answered. A registry check '
            'that passes here would be a green over a tree it never read.'
        )
        raise UnenforceableRule(msg)
    done = subprocess.run([git, '-C', str(root), 'ls-files'], capture_output=True, text=True, timeout=120, check=False)
    if done.returncode != 0:
        msg = f'git ls-files failed in {root}: {done.stderr.strip() or done.returncode}'
        raise UnenforceableRule(msg)
    return frozenset(done.stdout.splitlines())


def lint_selection(config: Path) -> tuple[frozenset[str], frozenset[str]]:
    """``(selected, ignored)`` from a lint config, read wherever the repo keeps it.

    Both shapes this family uses: a ``ruff.toml``'s top-level ``[lint]`` and a ``pyproject.toml``'s
    ``[tool.ruff.lint]``. Read rather than assumed, because "the rule is selected" is a claim about
    a file this module has to actually open -- an assumption here is the declaration that lies.
    """
    if not config.is_file():
        msg = f'the lint config {config} does not exist, so no lint mechanism can be resolved against it.'
        raise UnenforceableRule(msg)
    table = read_toml(config)
    lint = table.get('lint') or (table.get('tool') or {}).get('ruff', {}).get('lint') or {}
    return frozenset(lint.get('select', ())), frozenset(lint.get('ignore', ()))


def unresolved(
    rules: Sequence[Rule],
    *,
    tracked: Iterable[str],
    selected: Iterable[str],
    ignored: Iterable[str],
) -> tuple[str, ...]:
    """Every rule whose mechanism is not live, named with the rule ID and the mechanism.

    Takes its three facts as arguments rather than fetching them, so a control can drive THIS
    function against a planted tree instead of re-implementing its logic and agreeing with itself.
    """
    have = frozenset(tracked)
    chosen, waived = frozenset(selected), frozenset(ignored)
    out: list[str] = []
    for rule in rules:
        for mech in rule.mechanisms:
            if not isinstance(mech, LintRule):
                if mech.path not in have:
                    out.append(f'{rule.id}: {mech.path} is not a tracked file')
            elif mech.code in waived:
                out.append(f'{rule.id}: lint rule {mech.code} is globally IGNORED, so it refuses nothing')
            elif not any(mech.code.startswith(prefix) for prefix in chosen):
                out.append(f'{rule.id}: lint rule {mech.code} is not SELECTED, so it refuses nothing')
    return tuple(out)


def assert_enforceable(profile: RepoProfile, rules: Sequence[Rule] = RULES) -> None:
    """Raise unless every rule's mechanism is live in *profile*'s tree -- naming each failure.

    The adopting repo calls this from its own suite. It is the check that makes the registry a
    guarantee rather than a document: without it, deleting the test a rule names would leave the
    rule in place, reading exactly as it did the day it was enforced.

    Raises:
        UnenforceableRule: at least one mechanism is gone, waived, or not selected; the message names
            the rule ID and the mechanism, because a refusal that does not say which row failed is a
            refusal nobody can act on.

    """
    selected, ignored = lint_selection(profile.lint_config_path)
    problems = unresolved(
        rules,
        tracked=tracked_files(profile.repo_root()),
        selected=selected,
        ignored=ignored,
    )
    if problems:
        msg = (
            f'{len(problems)} mechanism(s) named by the shared rules registry are not live in '
            f'{profile.app_name}:\n  ' + '\n  '.join(problems) + '\n'
            'Restore the mechanism or repoint the row at whatever refuses it now. Do not delete the row: '
            "a rule with no mechanism is prose wearing a guarantee's clothes, and that is the defect "
            'this registry exists to remove.'
        )
        raise UnenforceableRule(msg)


def unadopted(rules: Sequence[Rule], adoption: Adoption) -> tuple[str, ...]:
    """The rule IDs *adoption* neither enforces nor declares absent -- the citation that says nothing.

    Returns IDs rather than a count because the set is what an adopting repo pins: a count is blind
    to WHICH rule moved, and a repo that dropped one rule while picking up another would compare
    equal, with the honest-looking repair being to edit the digit.
    """
    silent = set(rules_by_id(rules)) - set(adoption.mechanisms) - set(adoption.declared_absent)
    return tuple(sorted(silent))


def waived(rules: Sequence[Rule], adoption: Adoption) -> tuple[str, ...]:
    """The rules *adoption* declares absent, sorted -- the visible gap, not a silent one.

    Kept separate from :func:`unadopted` because they are different facts: one is a decision the repo
    made and on record, the other is a rule nobody has looked at yet.
    """
    return tuple(sorted(set(rules_by_id(rules)) & set(adoption.declared_absent)))


def rules_by_id(rules: Sequence[Rule]) -> dict[str, Rule]:
    """The rules keyed by ID -- the lookup an adoption resolves against."""
    return {rule.id: rule for rule in rules}


def _rebound(rules: Sequence[Rule], adoption: Adoption) -> tuple[Rule, ...]:
    """*rules* with each adopted row carrying THIS repo's mechanisms, and unadopted rows dropped.

    Dropping rather than passing through is the point: a row left holding its authoring repo's
    mechanisms is the motronics-path failure that made lab-commons refuse its own registry.
    """
    return tuple(
        Rule(id=rule.id, statement=rule.statement, mechanisms=adoption.mechanisms[rule.id])
        for rule in rules
        if rule.id in adoption.mechanisms
    )


def assert_adopted(profile: RepoProfile, adoption: Adoption, rules: Sequence[Rule] = RULES) -> None:
    """Raise unless *adoption* accounts for every rule and every mechanism it names is live.

    THE SHARED-REGISTRY ENTRY POINT -- what an adopting repo calls from its own suite. Four refusals,
    and each names the repo, because a refusal that does not say whose gap it is cannot be acted on:

    * a rule neither enforced nor declared absent: cited by nothing, so it is prose here;
    * a rule both enforced and declared absent: a stale half, which is how a row reads as enforced
      while being waived (refused earlier, at :class:`Adoption` construction);
    * an ID that is not a rule: a typo adopts nothing, silently;
    * a mechanism that is not tracked, not selected, or globally ignored -- delegated to
      :func:`assert_enforceable`, which already refuses those.

    The authoring repo's own mechanisms are NOT consulted here. That is the whole correction: they
    are the existence proof that a rule is enforceable at all, and they are a path in one checkout.

    Raises:
        UnenforceableRule: any of the above.

    """
    known = rules_by_id(rules)
    strangers = sorted((set(adoption.mechanisms) | set(adoption.declared_absent)) - set(known))
    if strangers:
        msg = (
            f'{adoption.app_name} adopts {strangers}, which the registry does not define. A typo in an ID '
            f'adopts nothing and says so nowhere, which is how a rule quietly stops being checked.'
        )
        raise UnenforceableRule(msg)
    silent = unadopted(rules, adoption)
    if silent:
        msg = (
            f'{adoption.app_name} neither enforces nor declares absent {len(silent)} rule(s):\n  '
            + '\n  '.join(silent)
            + '\nName the mechanism that refuses each one, or list it in declared_absent so the gap is on '
            'record. A cited rule with no answer to either is decoration, and it is what this registry '
            'exists to remove.'
        )
        raise UnenforceableRule(msg)
    assert_enforceable(profile, _rebound(rules, adoption))
