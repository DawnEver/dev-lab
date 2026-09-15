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

A RULE WITH NO RESOLVABLE MECHANISM IS A REFUSAL, IN TWO PLACES, and they are different refusals:

* :class:`Rule` refuses AT CONSTRUCTION to hold a row with no mechanism at all. A rule carried as a
  comment is prose masquerading as a guarantee, and no amount of careful writing fixes that -- the
  row cannot exist, so it cannot drift.
* :func:`assert_enforceable` refuses AT CHECK TIME when a row's mechanism is not live in the tree
  being checked: a test path that is not tracked, or a lint code that is not selected. Deleting the
  mechanism reds, which is the whole point -- that check is what the prose never had.

THE MECHANISM IS A PATH OR A LINT CODE, exactly as the registry this is modelled on states:
``'tests/...py'`` for a test that refuses the hazard, or ``('ruff', 'PLC0415')`` for a lint rule that
must be selected and not globally ignored. The data half writes them that way; :func:`_mechanism`
turns them into the two types. Paths are REPO-RELATIVE and are resolved against the adopting repo's
:class:`~lab_commons.dev.profile.RepoProfile`. A SECOND ADOPTER therefore inherits the statements and
must supply the mechanism for its own tree; until it does, this module's refusal is the honest
report, not a hole. That is deliberate: the alternative -- a shared rule that silently degrades to a
comment in a repo that never built the mechanism -- is the exact defect named above.

WHAT IS NOT HERE. The per-repo row (the dependency arrow, the case conventions, the launcher's
flags), the domain row (which vendor arbitrates which quantity), and the incident evidence that
explains why a rule exists -- that evidence stays in the repo that lived it, as a note attached to
the ID. Reasoning lives in `.claude/memory/`; this module is DATA.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lab_commons.dev._rule_rows import ROWS
from lab_commons.dev.profile import RepoProfile
from lab_commons.file_io import read_toml

__all__ = [
    'RULES',
    'LintRule',
    'Mechanism',
    'Rule',
    'TestPath',
    'UnenforceableRule',
    'assert_enforceable',
    'guard',
    'lint',
    'tracked_files',
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
