r"""ONE repo's ``permissions.allow`` block, DERIVED from the remedies it already supplies.

THE DEFECT, MEASURED 2026-09-18 AND FROM BOTH SIDES ON THE SAME DAY. Every deny row in
:mod:`lab_commons.dev._deny_rows` NAMES the road an agent is supposed to take -- that is the
registry's whole design, and its docstring says so. Nothing put that road into
``.claude/settings.json``. The two files are hand-written, in different repos, by different people,
and :mod:`lab_commons.dev.famtests.allowguard` exists precisely because they disagree: it CHECKS the
agreement and nothing PRODUCED it.

* An agent was refused permission to run ``scripts/gate/stop_sweep.py`` on its OWN superseded runs.
  ``RAW-PROCESS-KILL`` carries ``stop_sweep\.py`` as its opening and its remedy names the exact
  command. The deny engine was permitting it; a different layer refused it. The two layers did not
  disagree about policy -- nothing had ever connected them.
* Three of the four repos had no allow row the guard could probe, so ``allowguard`` scanned ZERO
  rows and reported the strongest possible agreement between two files, one of which was never read.

DERIVED VERSUS DECLARED, and the boundary is MEASURED rather than chosen. Of the nine allow rows
live in the three consuming repos on 2026-09-18, THREE are a remedy this package already holds and
SIX are that repo's own road:

    wdg-lab      Bash(./.venv/Scripts/python.exe -m lab_commons.dev.verify *)   <- DERIVED
    optimi-lab   Bash(./.venv/Scripts/python.exe -m lab_commons.dev.verify *)   <- DERIVED
    motronics    Bash(*scripts/gate/stop_sweep.py *)                            <- DERIVED, by hand
    wdg-lab      uv run python -m wdg_lab / uv sync --extra * / *yarn preview* /
                 python *kill-server.py* / *yarn test* / node **/scripts/post-review.js*

The first two were hand-written in two repos by two hands and were CHARACTER-IDENTICAL to what
:func:`glob_for` rendered from ``Remedy.command`` on the day this module landed. That agreement is
the evidence the derivation rule is read off the data rather than imposed on it.

THEY ARE NO LONGER CHARACTER-IDENTICAL, AND THE REASON IS THE ONE CORRECTION THIS MODULE HAS TAKEN.
Both hand-written rows spell ``.venv/Scripts/python.exe``, which is a file macOS does not have, so
on half the fleet those rows permit NOTHING -- silently, because an allow list that matches no
command is indistinguishable from one that was never consulted. ``settings.json`` is TRACKED IN GIT:
it is authored on one machine and read on another, so no concrete spelling can be right in it.
:func:`glob_for` now renders ``Bash(./.venv/*/python* -m lab_commons.dev.verify *)`` via
:func:`lab_commons.dev.venvpath.portable`, and BOTH concrete spellings derive that same single row --
which is what keeps the evidence above intact rather than discarding it: the two hands still agree
with the derivation, they agree with it after a platform-blind spelling is normalised away.

WHAT MAKES A ROW DERIVABLE IS A PROPERTY OF THE REGISTRY, not a judgement. A rule with ``needs``
names a repo artefact and the repo answers it with a :class:`lab_commons.dev.hooks.Remedy`, whose
``command`` is MACHINE-READABLE by contract -- it is the text shown verbatim to the refused agent. A
rule with ``needs=None`` has no ``Remedy`` at all; its exit is ENGLISH PROSE ("Do not rewrite a
shared ref: land the change FORWARD as a new commit..."), and a glob extracted from prose would be a
guess. So the derived population is exactly the supplied remedies, and nothing else is derivable
even in principle.

THE ``needs`` RULE HOLDS ON THIS SIDE TOO. :func:`lab_commons.dev.hook_adoption.deny_rules` does not
ship a rule to a repo that supplies no such file; the same logic says this module does not render an
allow row for a remedy this repo cannot perform. A row is rendered for a remedy and for nothing
else, so a repo that declared a rule absent gets no row promising its exit -- and a
:class:`DeclaredAllow` naming a repo file is checked against the TRACKED set by :func:`allow_gaps`,
for the reason ``remedy_gaps`` gives one file over. A row permitting a path that does not exist is a
declaration that lies.

AN ALLOW LIST IS NOT A PLACE TO PRE-PAY FOR ROADS NOBODY HAS NEEDED YET, so a declared row costs an
argument: :class:`DeclaredAllow` refuses an empty ``because`` at construction, and
:func:`assert_allow_is_adoptable` binds the block's size on BOTH sides through
:mod:`lab_commons.dev.floors` -- a block that silently emptied reads exactly like agreement, and a
floor the block has outgrown is a waiver nothing uses. This is also why a derived glob is the
CANONICAL spelling and not a widened one: ``stop_sweep.py --pid <root-pid>`` renders
``Bash(... --pid *)``, and the ``--all`` variant the remedy mentions in a parenthetical is a
DECLARED row somebody argues for, not a free rider on the derivation.

THE ONE SANCTIONED WIDENING IS THE VENV INTERPRETER, and it is named here rather than left as an
exception a reader has to discover. ``.venv/*/python*`` admits more strings than the remedy spells,
which the paragraph above otherwise forbids. It is admitted because the alternative is not a
narrower row but a row that is FALSE on one of the two platforms this family runs on, and because
every string it admits is still an interpreter inside this project's own venv -- the widening stays
inside the road's meaning. It is bounded as DATA in :data:`lab_commons.dev.venvpath.VENV_LAYOUTS`,
so a third layout is a row in that table and cannot arrive as a looser pattern in one repo's
settings file.

WHY THIS IS NOT :mod:`lab_commons.dev.famconfig`, which is the mechanism a reader will reach for
first. ``famconfig`` is a WHOLE-FILE, LINE-ORIENTED renderer keyed by artefact filename, and it
opens every file it writes with a comment STAMP. ``.claude/settings.json`` is JSON: it has no
comment syntax, so the stamp alone is fatal; and its two blocks have two owners --
:func:`lab_commons.dev.agent_guard.wire_settings` writes ``hooks``, this module writes
``permissions`` -- so a whole-file base would have to own both or clobber one. The section-scoped
``Base`` that the config plan names as its missing mechanism is a TOML-TABLE mechanism for
``[tool.ruff]`` and would not have served a JSON object either. The mechanism a JSON section needs
already exists in this family and is proven: a dict-level merge that preserves every key it is not
about, which is what ``wire_settings`` does for the other block and what :func:`permissions_block`
does for this one.

THIS MODULE IS THE DERIVATION HALF. Reading a permission row, and merging a section into an
arbitrary JSON document, are a different subject with different failure modes and live in
:mod:`lab_commons.dev._allow_settings` -- the same write-half/survey-half seam ``famconfig`` and
``_famconfig_survey`` already draw, and the import runs one way. The surface a consumer imports is
still one name: every body there is re-exported or wrapped here.

WHAT THIS DOES NOT PROVE, and it is deliberately :mod:`lab_commons.dev.famtests.allowguard`'s: that
no rendered row names a command the repo's REAL engine refuses. :func:`self_refused` answers the
much smaller question this module owns, in pure Python through :func:`lab_commons.dev.hooks.denies`
-- does the repo's own shipped rule set name this command? -- and it is a construction-time check,
not a substitute. The guard drives ``node`` over the committed files, and nothing here reads either
of them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from lab_commons.dev._allow_settings import BASH, ROW, block_problems, live_bash_rows, merged_permissions
from lab_commons.dev._allow_settings import promised_command as _promised
from lab_commons.dev.floors import assert_floor, assert_floor_still_binds
from lab_commons.dev.hook_adoption import HookAdoption
from lab_commons.dev.hooks import DENY_RULES, DenyRule, denies
from lab_commons.dev.venvpath import portable

__all__ = [
    'BASH',
    'AllowAdoption',
    'DeclaredAllow',
    'UnarguedAllow',
    'allow_entries',
    'allow_gaps',
    'assert_allow_is_adoptable',
    'derived_entries',
    'glob_for',
    'live_bash_rows',
    'permissions_block',
    'provenance',
    'self_refused',
    'settings_problems',
]

#: What a remedy command spells for a value the agent supplies: an angle-bracket metavariable, or
#: the engine's own ``{root}`` token. Both become ``*`` in a glob -- the metavariable because its
#: value is by definition not known here, ``{root}`` because the agent client expands no such token
#: and a literal one would promise a path no box has.
_METAVAR: Final = re.compile(r'<[^<>\s][^<>]*>|\{root\}')

#: Runs of ``*`` separated by whitespace, collapsed: two adjacent metavariables stand for one opaque
#: tail, and ``* *`` would otherwise instantiate to two words where one may be typed.
_RUNS: Final = re.compile(r'\*(?:\s*\*)+')


class UnarguedAllow(ValueError):
    """A declared allow row arrives with no argument for itself, or names something unrenderable.

    Its own class rather than a bare ``ValueError`` because the caller it is aimed at is an
    adopting repo's suite, and the fix is to STATE WHY THE ROAD IS NEEDED -- or to drop the row --
    never to correct an argument. An allow list whose rows carry no reason is where a permission
    nobody can defend outlives the task that wanted it.
    """


def glob_for(command: str) -> str:
    """The ``Bash(...)`` row one remedy *command* promises, as the CANONICAL spelling of that road.

    A trailing ``*`` is appended when the command does not already end in one, so the arguments the
    agent supplies are covered while the program and its named options are not widened. Nothing is
    prepended: ``Remedy.command`` is the text the refused agent is told to type VERBATIM, so a
    leading wildcard would permit invocation prefixes this package never sanctioned.

    THE VENV INTERPRETER IS MADE PORTABLE FIRST, via
    :func:`lab_commons.dev.venvpath.portable`, and that is the one place a row is deliberately
    WIDER than the remedy it derives from. The remedy is concrete because an agent has to type it;
    this row is written into ``.claude/settings.json``, which is TRACKED IN GIT and read on a
    machine that may not be the one that wrote it, so a row naming ``Scripts/python.exe`` permits
    nothing at all on macOS -- silently, which is the failure mode an allow list cannot report. See
    that module for why a glob beats two rows or a render-at-adoption-time value.

    KNOWN AND SCOPED: the glob puts a ``*`` INSIDE a path token, which is the first row in this
    family to do so, and :func:`lab_commons.dev._allow_settings.promised_command` instantiates an
    interior ``*`` as a separate word -- so the command this row is PROBED with reads
    ``./.venv/ ARG /python ARG -m ...``. That is not corrected here: the splitting is pinned
    deliberately, so that ``Bash(python *tool.py*)`` probes as ``python ARG tool.py`` and lands the
    program at a command position. ``self_refused`` is already declared A FLOOR ON THE CHECK rather
    than the whole of it, and no rule in the registry matches either reading of this row. The real
    engine is driven over the committed file by
    :mod:`lab_commons.dev.famtests.allowguard`, which is where a contradiction would surface.

    Raises:
        UnarguedAllow: *command* is blank, or collapses to nothing but wildcards -- a row reading
            ``Bash(*)`` promises every shell command there is and answers no rule in particular.

    """
    text = _RUNS.sub('*', _METAVAR.sub('*', portable(' '.join(command.split()))))
    if not text.strip().strip('*').strip():
        msg = (
            f'the remedy command {command!r} renders the glob {text!r}, which promises every command there '
            f'is. A remedy that is all metavariable names no road, so no row can be derived from it.'
        )
        raise UnarguedAllow(msg)
    return f'{BASH}({text if text.endswith("*") else text + " *"})'


@dataclass(frozen=True, slots=True)
class DeclaredAllow:
    """ONE road that answers no deny rule: this repo's own, with the argument that admits it.

    *entry* is the permission row VERBATIM, in the agent client's own glob spelling. *because* is
    why this repo needs it, and it is non-optional for the reason the deny side's ``remedy`` is:
    the field is what stops the list growing by accretion. *needs* is the repo-relative file the
    road runs, when it is a file, so :func:`allow_gaps` can refuse a row permitting a path the tree
    does not track -- the same check :func:`lab_commons.dev.hook_adoption.remedy_gaps` makes on the
    other half, pointed the other way.
    """

    entry: str
    because: str
    needs: str | None = None

    def __post_init__(self) -> None:
        """Refuse a row with no argument, a row that is not a permission row, and a one-box path."""
        found = ROW.fullmatch(self.entry.strip())
        if found is None or not found.group(2).strip():
            msg = (
                f'{self.entry!r} is not a permission row: the agent client reads `Tool(<glob>)`, and anything '
                f'else is a line it ignores while a reader takes it for a permission.'
            )
            raise UnarguedAllow(msg)
        if not self.because.strip():
            msg = (
                f'{self.entry}: no reason. An allow list is not a place to pre-pay for roads nobody has '
                f'needed yet -- say what this one is for, or leave it out until something needs it.'
            )
            raise UnarguedAllow(msg)
        if self.needs is not None and (
            not self.needs.strip() or self.needs.startswith('/') or '\\' in self.needs or '..' in self.needs
        ):
            msg = f'{self.entry}: needs={self.needs!r} must be REPO-RELATIVE with POSIX separators.'
            raise UnarguedAllow(msg)


def derived_entries(
    adoption: HookAdoption,
    rules: Sequence[DenyRule] = DENY_RULES,
) -> dict[str, tuple[str, ...]]:
    """Every allow row *adoption*'s own remedies imply, mapped to the rule IDs it is the exit from.

    In registry order, and ONE row per distinct remedy command: a repo whose single verdict entry
    point answers both ``BARE-TEST-INVOCATION`` and ``PUSH-NO-VERIFY`` gets one row naming both,
    because two identical rows would be one road declared twice and a diff could not say which of
    them a later deletion removed.

    A rule the adoption declared absent, or never answered, contributes NOTHING -- that is the
    ``needs`` rule holding on this side, and it is why this reads the adoption rather than the
    registry: the registry knows the road exists, only the repo knows it can take it.
    """
    out: dict[str, list[str]] = {}
    for rule in rules:
        remedy = adoption.remedies.get(rule.id)
        if rule.needs is None or remedy is None:
            continue
        out.setdefault(glob_for(remedy.command), []).append(rule.id)
    return {entry: tuple(ids) for entry, ids in out.items()}


@dataclass(frozen=True, slots=True)
class AllowAdoption:
    """ONE repo's whole allow block: its deny-side adoption, plus the roads that answer no rule.

    The two populations are kept APART rather than merged into one list, because they are maintained
    by different acts: a derived row moves when the family registry or this repo's remedy moves, and
    a declared row moves when somebody argues for it. A merged list loses which is which, and the
    first hand that edits a derived row has forked the registry without saying so.

    Construction refuses a declared row that RE-STATES a derived one, for the reason
    :mod:`lab_commons.dev.famconfig` refuses a delta restating a base line: the restatement is where
    the two copies start to differ, and it reads as a decision rather than a duplicate.
    """

    app_name: str
    adoption: HookAdoption
    declared: tuple[DeclaredAllow, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Refuse an unnamed repo, a duplicated declared row, and a declared row already derived."""
        if not self.app_name.strip():
            msg = 'an allow adoption with no app_name cannot report WHICH repo over-declared a road.'
            raise ValueError(msg)
        entries = [row.entry.strip() for row in self.declared]
        repeated = sorted({entry for entry in entries if entries.count(entry) > 1})
        if repeated:
            msg = f'{self.app_name} declares {repeated} more than once; a deletion could not say which one went.'
            raise UnarguedAllow(msg)
        restated = sorted(set(entries) & set(derived_entries(self.adoption)))
        if restated:
            msg = (
                f'{self.app_name} declares {restated}, which its own remedies already derive. A declared copy '
                f'of a derived row is where the registry and the settings file start to disagree again.'
            )
            raise UnarguedAllow(msg)


def allow_entries(allow: AllowAdoption, rules: Sequence[DenyRule] = DENY_RULES) -> tuple[str, ...]:
    """The whole block: derived rows in registry order, then declared rows in declaration order."""
    return (*derived_entries(allow.adoption, rules), *(row.entry.strip() for row in allow.declared))


def provenance(allow: AllowAdoption, rules: Sequence[DenyRule] = DENY_RULES) -> dict[str, str]:
    """Each entry mapped to WHERE IT CAME FROM -- the named sets, so a count cannot hide a swap.

    Published rather than kept internal because it is what a reader of a red needs: "derived from
    RAW-PROCESS-KILL" and "declared: the docs preview server" are two different repairs, and an
    entry with no provenance is the hand edit this module exists to remove.
    """
    out = {entry: f'derived from {", ".join(ids)}' for entry, ids in derived_entries(allow.adoption, rules).items()}
    out.update({row.entry.strip(): f'declared: {row.because}' for row in allow.declared})
    return out


def self_refused(allow: AllowAdoption, rules: Sequence[DenyRule] = DENY_RULES) -> tuple[str, ...]:
    """Every rendered row whose own promise this repo's SHIPPED rules already name, with the rule.

    THE CONSTRUCTIVE HALF of the property :mod:`lab_commons.dev.famtests.allowguard` checks. A
    remedy whose command spells the very shape its rule matches -- ``netverb``'s exit contains
    ``git push`` -- must carry a ``Remedy.allow`` opening, and without one the registry would hand
    out a road it refuses. This answers that in pure Python via
    :func:`lab_commons.dev.hooks.denies`, applying the adoption's own openings, so the defect is
    caught where the block is BUILT rather than after it is committed.

    A FLOOR ON THE CHECK RATHER THAN THE WHOLE OF IT, and the scope travels with the result because
    a negative without its scope is not a result. :func:`lab_commons.dev.hooks.fires` anchors a
    ``matches: 'command'`` rule at the HEAD of a segment, so a remedy spelling the denied verb in
    its TAIL -- ``netverb``'s exit is exactly that -- is INVISIBLE here and is caught by the real
    engine, which splits nested command positions. An ``argument``-matched rule is searched anywhere
    and is fully reachable, which is the shape this module's own control is planted on. Deciding
    what a shell line executes belongs to ``deny-commands.js``, and the guard drives the real one.
    """
    out: list[str] = []
    for entry in allow_entries(allow, rules):
        command = _promised(entry)
        if not command:
            continue
        fired = denies(rules, command, allow.adoption.remedies)
        if fired is not None:
            out.append(f'{entry}  ->  promises {command!r}, which {fired} refuses')
    return tuple(out)


def permissions_block(
    settings: Mapping[str, Any],
    allow: AllowAdoption,
    rules: Sequence[DenyRule] = DENY_RULES,
) -> dict[str, Any]:
    """*settings* with its ``permissions.allow`` Bash rows replaced by this adoption's block.

    A SECTION MERGE, and every other key survives it -- see
    :func:`lab_commons.dev._allow_settings.merged_permissions` for why that is the mechanism a JSON
    section needs and a whole-file renderer is not.
    """
    return merged_permissions(settings, allow_entries(allow, rules))


def settings_problems(
    settings: Mapping[str, Any],
    allow: AllowAdoption,
    rules: Sequence[DenyRule] = DENY_RULES,
) -> tuple[str, ...]:
    """Both sides of the ratchet between what this adoption renders and what the document holds."""
    return block_problems(settings, allow_entries(allow, rules), provenance(allow, rules))


def allow_gaps(allow: AllowAdoption, tracked: Iterable[str]) -> tuple[str, ...]:
    """Every DECLARED row whose file the adopting tree does not track, named with its row.

    Derived rows are not checked here and that is not an omission:
    :func:`lab_commons.dev.hook_adoption.assert_shippable` already refuses a remedy whose file the
    tree lacks, and a second check over the same fact is a place for the two to disagree. Takes the
    tracked set as an argument for the reason ``remedy_gaps`` does -- so a control can drive THIS
    function against a planted tree.
    """
    have = frozenset(tracked)
    return tuple(
        f'{row.entry}: the declared road runs {row.needs}, which is not a tracked file'
        for row in allow.declared
        if row.needs is not None and row.needs not in have
    )


def assert_allow_is_adoptable(
    allow: AllowAdoption,
    tracked: Iterable[str],
    *,
    floor: int,
    headroom: int,
    rules: Sequence[DenyRule] = DENY_RULES,
) -> None:
    """Raise unless the rendered block is honest, self-consistent and the size its repo argued for.

    Args:
        allow: the repo's own adoption.
        tracked: the files that repo's tree tracks.
        floor: the smallest block this repo can render and still be measuring something. NO
            DEFAULT: a repo whose remedies silently stopped deriving renders an empty block, which
            is what ``allowguard`` reported as agreement in three repos, and a family default would
            be one repo's number refusing another repo's tree.
        headroom: how far the block may grow past *floor* before the number is re-measured. The high
            side of :mod:`lab_commons.dev.floors`, and it is what makes each new road cost an
            argument twice -- once in ``because``, once in this number.
        rules: the deny registry the derivation reads.

    Raises:
        UnarguedAllow: a rendered row names a command this repo's own rules refuse, or a declared
            road runs a file the tree does not track.
        lab_commons.dev.floors.FloorUnmet: the block fell below *floor*.
        lab_commons.dev.floors.SlackFloor: the block outgrew *floor* past *headroom*.

    """
    entries = allow_entries(allow, rules)
    what = f'{allow.app_name} permissions.allow rows'
    assert_floor(len(entries), floor=floor, what=what)
    assert_floor_still_binds(len(entries), floor=floor, headroom=headroom, what=what)
    refused = self_refused(allow, rules)
    if refused:
        msg = (
            f'{allow.app_name} renders {len(refused)} allow row(s) naming a command its own deny rules '
            f'refuse:\n  ' + '\n  '.join(refused) + '\nThe rule needs an `allow` opening for the exit it '
            'hands out, or the remedy names the wrong road. A registry that refuses its own remedy is the '
            'sealed road wearing a signpost.'
        )
        raise UnarguedAllow(msg)
    gaps = allow_gaps(allow, tracked)
    if gaps:
        msg = (
            f'{allow.app_name} declares {len(gaps)} road(s) whose file its tree does not track:\n  '
            + '\n  '.join(gaps)
            + '\nA row permitting a path that does not exist is a declaration that lies.'
        )
        raise UnarguedAllow(msg)
