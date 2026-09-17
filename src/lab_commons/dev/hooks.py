"""The shared agent-guard registry: one denied command shape per row, each NAMING ITS REMEDY.

THE DEFECT THIS EXISTS TO CLOSE, MEASURED 2026-09-16. The family's goal doc asks that "a hand-written
pytest line or a bare ``git push`` is refused identically everywhere". Only one repo of four has any
of the machinery -- motronics-studio carries `.claude/hooks/deny-rules.json` and a 228-line engine;
`lab-commons`, `optimi-lab` and `wdg-lab` carry none. So a rule this family states in prose four
times is refused once, and the three quiet repos are where an agent's habit actually forms.

THE SEAM, and it is the one :mod:`lab_commons.dev.rules` already chose rather than a second scheme.
A rule has two halves with two different owners:

* the STATEMENT -- the pattern, the hazard, the shape of the remedy -- is universal and is authored
  once: the rows in :mod:`lab_commons.dev._deny_rows`, read by THIS module;
* the REMEDY -- the file you are supposed to run INSTEAD -- lives in one tree.
  ``scripts/hooks/with-retry.sh`` resolves in exactly one checkout on earth, and a shared row naming
  it would be FALSE in three repos. That half is :mod:`lab_commons.dev.hook_adoption`, and the split
  between the two modules IS the split the design turns on.

EVERY RULE NAMES ITS REMEDY. This is the hardest-won lesson in the family this week -- a rule that
seals a road with no exit gets ROUTED AROUND rather than obeyed, and motronics' ``uv`` rule had no
exit for months and cost a full day before its reason was made to name ``dep_sync.py``. So
:class:`DenyRule` refuses AT CONSTRUCTION a row with an empty remedy, and refuses a row that
declares ``needs`` without leaving the ``{remedy}`` placeholder for it, or the reverse. The other
two refusals -- not SHIPPING a rule whose remedy the repo lacks, and not accepting a remedy whose
file the tree does not track -- are the adoption half's, because only a repo can answer them.

WHAT THIS MODULE IS NOT. It is not the ENGINE. The engine is JavaScript, because the tool that runs
a ``PreToolUse`` hook executes a command from the repo tree, and it does the hard part: deciding what
a shell line will actually EXECUTE (segments, wrappers, heredoc bodies classified by their CONSUMER).
That decision is deliberately NOT re-implemented here -- two implementations of "what will the shell
run" is exactly the fork this family removes elsewhere. :func:`fires` answers the much smaller
question this module owns: given ONE already-split command segment, does this rule NAME it? That is
the half the rows' own ``refuses``/``permits`` proof exercises, and the half a pattern can be wrong in.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from lab_commons.dev._deny_rows import DENY_ROWS

__all__ = [
    'DENY_RULES',
    'MATCH_KINDS',
    'PLACEHOLDER',
    'DenyRule',
    'Remedy',
    'UnremediedRule',
    'denies',
    'fires',
    'rules_by_id',
]

#: The token a row leaves for the consuming repo's own command. Substituted by REPLACEMENT rather
#: than by ``str.format``, because a reason may also carry the engine's ``{root}`` token and a
#: format call would raise on it -- an unrelated placeholder is not an error to be handled here.
PLACEHOLDER: Final = '{remedy}'

#: A rule ID is a slug, never a number, for the reason `lab_commons.dev.rules` states: an integer
#: cannot say WHICH row moved, so the honest-looking repair when a pin disagrees is to edit the digit.
_ID: Final = re.compile(r'[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*')

#: What a pattern NAMES, in the engine's own vocabulary. A closed set, so a typo cannot become a
#: third matching mode that the engine silently reads as its default.
MATCH_KINDS: Final = frozenset({'command', 'argument'})


class UnremediedRule(RuntimeError):
    """A deny rule is carried, or shipped, without an exit the reader can actually take.

    Raised at construction (an empty remedy, or a ``needs`` with no placeholder to fill), at render
    time (a remedy of the wrong kind, an ID that is not a rule), and at check time (a remedy naming
    a file the adopting tree does not track). Its own class rather than ``ValueError`` because the
    caller it is aimed at is an adopter's suite, and the fix is to BUILD the remedy -- or to declare
    the rule absent -- not to correct an argument.
    """


@dataclass(frozen=True, slots=True)
class Remedy:
    r"""ONE repo's exit for one shared rule: the command to type instead, and what it opens.

    *kind* must equal the rule's ``needs``, so a remedy cannot be attached to a rule it does not
    answer -- a retry wrapper offered as the exit from a bare test line reads as an exit and is not.

    *command* is shown VERBATIM to the agent that was refused. The engine expands ``{root}`` in it,
    so a repo-absolute spelling is available without this module knowing any box's paths.

    *allow* is the regex that OPENS the rule for this command. Optional, because most remedies do
    not resemble the shape they replace and so are never matched by the pattern in the first place.
    It is compiled HERE, at construction, and that is not defensive tidiness: motronics once shipped
    ``[/\\]`` as an ``allow`` -- an unterminated character class -- and the engine, which fails open
    by construction, skipped the rule in silence.

    *path* is the repo-relative file the remedy runs, when it is a file. It is what the adoption
    half resolves against the adopting tree, so "the remedy exists" is a claim somebody checked.
    """

    kind: str
    command: str
    allow: str | None = None
    path: str | None = None

    def __post_init__(self) -> None:
        """Refuse a remedy with no kind, which could not be matched to the rule it answers."""
        if not self.kind.strip():
            msg = 'a remedy with no kind cannot be matched to the rule it answers.'
            raise ValueError(msg)
        if not self.command.strip():
            msg = (
                f'the {self.kind!r} remedy names no command. A remedy that does not say what to type is the '
                f'sealed road this registry exists to keep open.'
            )
            raise UnremediedRule(msg)
        _compiled(self.allow, f'remedy {self.kind!r} allow')
        if self.path is not None:
            _repo_relative(self.path, f'remedy {self.kind!r} path')


@dataclass(frozen=True, slots=True)
class DenyRule:
    """One universal denied command shape: what it matches, why, and the shape of the way out.

    *id* is the handle every adopter cites and is stable by contract: renaming one silently
    un-adopts it in every repo that supplied a remedy under the old spelling.

    *needs* names the KIND of repo artefact the remedy requires, or is ``None`` when the exit is a
    plain command every checkout already has. The two cases are checked against the ``{remedy}``
    placeholder in BOTH directions: a rule that needs an artefact and leaves nowhere to put it would
    ship a reason describing an exit it never names, and a rule that leaves the placeholder with
    nothing to fill it would ship the literal token to a reader.
    """

    id: str
    pattern: str
    hazard: str
    remedy: str
    matches: str = 'command'
    needs: str | None = None
    allow: str | None = None
    refuses: tuple[str, ...] = ()
    permits: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Refuse an id that is not an UPPER-CASE slug, at construction."""
        if not _ID.fullmatch(self.id):
            msg = f'deny rule id {self.id!r} must be an UPPER-CASE slug (A-Z, 0-9, "-"): it is a handle, not a title.'
            raise ValueError(msg)
        if self.matches not in MATCH_KINDS:
            msg = (
                f'{self.id}: matches={self.matches!r} is not one of {sorted(MATCH_KINDS)}. The engine reads '
                f'anything else as the default anchoring, so a typo would quietly widen or narrow the rule.'
            )
            raise ValueError(msg)
        _compiled(self.pattern, f'{self.id} pattern')
        _compiled(self.allow, f'{self.id} allow')
        if not self.hazard.strip():
            msg = f'{self.id}: a rule that does not say what the hazard IS cannot be argued with, only obeyed.'
            raise ValueError(msg)
        if not self.remedy.strip():
            msg = (
                f'{self.id}: no remedy. A rule that seals a road with no exit gets routed around rather than '
                f'obeyed -- name what to do INSTEAD, or leave the rule out until the alternative exists.'
            )
            raise UnremediedRule(msg)
        self._check_slot()

    def _check_slot(self) -> None:
        """The ``needs``/``{remedy}`` biconditional, refused in both directions."""
        has_slot = PLACEHOLDER in self.remedy
        if self.needs is not None and not has_slot:
            msg = (
                f'{self.id}: needs={self.needs!r} but the remedy leaves no {PLACEHOLDER} for it, so the repo '
                f'that supplies one would have nowhere to put it and the reader would never see it.'
            )
            raise UnremediedRule(msg)
        if self.needs is None and has_slot:
            msg = f'{self.id}: the remedy carries {PLACEHOLDER} with no `needs` to fill it, so the token ships raw.'
            raise UnremediedRule(msg)

    def reason(self, remedy: Remedy | None = None) -> str:
        """The full text the refused agent reads: the hazard, then the exit, with *remedy* filled in.

        Raises:
            UnremediedRule: the rule needs an artefact and *remedy* is absent or answers a different
                kind. Refused rather than rendered with a gap, because a reason whose exit went
                missing reads exactly like one whose exit is a plain command.

        """
        if self.needs is None:
            return f'{self.hazard} {self.remedy}'
        if remedy is None:
            msg = f'{self.id} needs a {self.needs!r} remedy and none was supplied, so it has no exit to name.'
            raise UnremediedRule(msg)
        if remedy.kind != self.needs:
            msg = (
                f'{self.id} needs a {self.needs!r} remedy and was given a {remedy.kind!r} one. A remedy that '
                f'answers a different question reads as an exit and is not one.'
            )
            raise UnremediedRule(msg)
        return f'{self.hazard} {self.remedy.replace(PLACEHOLDER, remedy.command)}'

    def rendered(self, remedy: Remedy | None = None) -> dict[str, str]:
        """The rule as the engine's own row: ``name``, ``pattern``, ``matches``, ``allow``, ``reason``.

        The two openings -- the rule's own and the remedy's -- are combined by ALTERNATION rather
        than by picking one. They are different claims (a spelling sanctioned everywhere, and this
        repo's exit), and either alone would close a door the other means to leave open.
        """
        openings = [text for text in (self.allow, remedy.allow if remedy else None) if text]
        row = {'name': self.id, 'pattern': self.pattern, 'matches': self.matches, 'reason': self.reason(remedy)}
        if openings:
            row['allow'] = openings[0] if len(openings) == 1 else '|'.join(f'(?:{text})' for text in openings)
        return row


def _compiled(pattern: str | None, what: str) -> re.Pattern[str] | None:
    """*pattern* compiled, or ``None``. A pattern that does not compile is refused HERE, loudly.

    The engine fails OPEN by construction -- a bad regex there is skipped, so that a typo cannot
    lock a session -- which makes the engine exactly the wrong place to learn a rule is broken. This
    is the right place, and it is why every pattern is compiled at import.
    """
    if pattern is None:
        return None
    try:
        return re.compile(pattern)
    except re.error as exc:
        msg = (
            f'{what} does not compile: {exc}. The engine fails OPEN on a bad regex, so a rule with one is a '
            f'rule that silently refuses nothing while reading as protection.'
        )
        raise ValueError(msg) from exc


#: A Windows drive-qualified path. Spelled out because ``Path('C:/x').is_absolute()`` is FALSE on
#: posix, so the obvious check would let a one-box path through on exactly the machines that do NOT
#: have that box -- which is every machine that would have to act on the refusal.
_DRIVE: Final = re.compile(r'^[A-Za-z]:[\\/]')


def _repo_relative(path: str, what: str) -> None:
    """Refuse a path that names one box rather than a place in every adopter's tree."""
    if not path.strip() or path.startswith('/') or _DRIVE.match(path) or '\\' in path or '..' in Path(path).parts:
        msg = f'{what} {path!r} must be REPO-RELATIVE with POSIX separators: an absolute path names one box.'
        raise ValueError(msg)


def _build(rows: Iterable[Mapping[str, Any]]) -> tuple[DenyRule, ...]:
    """The data half as :class:`DenyRule` objects -- where a remedy-less row refuses, at import.

    ``Any`` rather than ``object`` plus a suppression: a row is heterogeneous by nature (strings, a
    nullable string, tuples of strings), and the thing that actually checks it is
    :meth:`DenyRule.__post_init__`, one line later. A type ignore here would declare a narrowness
    the data does not have and would be checked by nobody.
    """
    return tuple(DenyRule(**row) for row in rows)


#: THE REGISTRY. Rows are the number: nothing here states a count, because a count is blind to which
#: row moved and the honest-looking repair when it disagrees is to edit the digit.
DENY_RULES: Final[tuple[DenyRule, ...]] = _build(DENY_ROWS)


def rules_by_id(rules: Sequence[DenyRule]) -> dict[str, DenyRule]:
    """The deny rules keyed by ID -- the lookup an adoption resolves against."""
    return {rule.id: rule for rule in rules}


def fires(rule: DenyRule, segment: str) -> bool:
    """Does *rule* NAME the command in one already-split shell *segment*?

    THE SMALL QUESTION, DELIBERATELY. Deciding what a shell line will execute belongs to the engine,
    and a second implementation of it here would be two answers to one question. What this owns is
    the anchoring the rule itself declares: a ``'command'`` pattern must match at the START of a
    segment (``echo "git push"`` runs echo), while an ``'argument'`` pattern is searched anywhere in
    it, because the command an option qualifies varies.
    """
    anchored = rule.pattern if rule.matches == 'argument' else f'^(?:{rule.pattern})'
    return re.search(anchored, segment) is not None


def denies(rules: Sequence[DenyRule], segment: str, remedies: Mapping[str, Remedy] | None = None) -> str | None:
    """The ID of the first rule that REFUSES *segment*, or ``None`` -- openings applied.

    An opening is tested against the whole text, as the engine tests it against the whole command:
    an ``allow`` is a statement about the invocation, not about the token the pattern landed on.
    """
    supplied = remedies or {}
    for rule in rules:
        if not fires(rule, segment):
            continue
        offered = supplied.get(rule.id)
        openings = [text for text in (rule.allow, offered.allow if offered else None) if text]
        if any(re.search(text, segment) for text in openings):
            continue
        return rule.id
    return None
