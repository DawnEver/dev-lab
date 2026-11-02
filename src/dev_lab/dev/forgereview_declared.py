"""THE REVIEW A REPO DECLARES: ``[tool.dev_lab.review]``, the family's command, and where a PR's review reads it.

:mod:`dev_lab.dev.forgereview` runs the round; this module says WHAT runs -- the :class:`Review` a manifest
declares (:func:`review_from`), read from the integration branch the repository's default branch trusts
(:func:`trusted_integration`, :func:`review_at`), and the declared command with every placeholder filled for
this host (:func:`command_for`, :func:`judge_for`).

THE COMMAND IS THE FAMILY'S (:data:`FAMILY_COMMAND`): a repo declares only where it differs, every key optional::

    [tool.dev_lab.review]
    # command: only a genuinely different method; the family's, redeclared, is refused. Placeholders:
    # {range}: <base>..<head>; {paths}: the slice's paths (one argument each); {lens}: strict|standard|light;
    # {model}: `model`; {rules}: the registry's rule ids, comma-separated (ai-lab imports no registry);
    # {principles}: a JSON file of dev_lab.dev.principles (written per run; ai-lab holds no copy);
    # {summary}: --pr-body <file> on the one summarizing call, --no-summary on the rest;
    # {disposed}: a JSON file of the findings disposed earlier (the forge's own dispositions only);
    # {runtimes.<name>.<key>}: THIS host's machine-file [runtimes.<name>] value (repo says WHAT, host WHERE)
    model = "<id>"             # the default is FAMILY_MODEL
    synthesis = []             # optional: run once over {findings} (the merged slices) and {range}
    max_rounds = 5             # full review rounds per PR (FAMILY_MAX_ROUNDS); past it, the head waits
    max_diff_bytes = 200000    # one slice: what one reviewer reads
    max_total_bytes = 4000000  # one head: past it, held for a session
    derived = []               # globs of generated files beyond the family's (famfiles.GENERATED)
    strict = [...]             # globs read under the strict lens; light = [...] under the light one
    code = [...]               # globs of what executes (forgereview_scope.CODE): nothing else is read or capped
    not_code = [...]           # globs never code whatever their extension (forgereview_scope.NOT_CODE)
    claim_stale = "1 h"        # the default: a claim older than this may be taken over
    quiet = "10 min"           # the default (DEFAULT_QUIET): the serve reviews a head only once it is this old

The keys of the retired in-process reviewer (``max_tokens``, ``rules``) are refused by name.
"""

from __future__ import annotations

import dataclasses
import re
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from lab_commons.units import Q_

from dev_lab.dev import forgereview_scope
from dev_lab.dev.family import declared_table
from dev_lab.dev.forgereview_command import ReviewUnsupported
from dev_lab.dev.forgereview_findings import Finding
from dev_lab.dev.forgereview_judge import Judge, Verdict, judge
from dev_lab.dev.forgereview_rounds import FAMILY_MAX_ROUNDS
from dev_lab.dev.forgereview_runtimes import HOST_FIELD, RUNTIMES_TABLE, retired_field, runtime_names
from dev_lab.dev.forgereview_scope import Budget
from dev_lab.dev.lanepolicy import policy_at
from dev_lab.dev.reviewgate import DeclarationUnread
from dev_lab.dev.rules import RULES

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = [
    'DEFAULT_CLAIM_STALE',
    'DEFAULT_QUIET',
    'EMPTY_COMMAND_FIX',
    'FAMILY_COMMAND',
    'FAMILY_JUDGE',
    'FAMILY_MODEL',
    'FAMILY_RUNTIMES',
    'LENS_FIELD',
    'LIGHT',
    'MODEL_FIELD',
    'PATHS_FIELD',
    'RANGE_FIELD',
    'RETIRED_KEYS',
    'RULES_FIELD',
    'STRICT',
    'Review',
    'command_for',
    'judge_for',
    'load_review',
    'review_at',
    'review_from',
    'stale_after',
    'trusted_integration',
]

#: The placeholder the declared command carries; the reviewed ``<base>..<head>`` range replaces it.
RANGE_FIELD: Final = '{range}'

#: An argument exactly this expands into the slice's paths, one argument each.
PATHS_FIELD: Final = '{paths}'

#: Replaced by the slice's lens (:data:`dev_lab.dev.forgereview_scope.LENSES`).
LENS_FIELD: Final = '{lens}'

#: Replaced by the family registry's rule ids, comma-separated: ai-lab (the method) is GIVEN them and imports no
#: registry of its runner's.
RULES_FIELD: Final = '{rules}'

#: Replaced by the review's ``model`` (:data:`FAMILY_MODEL` unless the repo overrides it).
MODEL_FIELD: Final = '{model}'

#: The model the family reviews with: ONE declared value; a repo overrides it with ``model = "<id>"``.
FAMILY_MODEL: Final = 'claude-sonnet-5-5'

#: The family's review command (REVIEW-COMMAND-IS-THE-FAMILY'S): ai-lab's review module on THIS host's ai-lab
#: interpreter, which packages the method, sliced (``{paths}``) under a lens. A repo declares ``command`` only
#: when its method genuinely differs; redeclaring this one is refused, so no stale copy can drift from it.
FAMILY_COMMAND: Final = (
    '{runtimes.ai_lab.python}', '-m', 'ai_lab.review', '--range', RANGE_FIELD, '--lens', LENS_FIELD,
    '--model', MODEL_FIELD, '--rules', RULES_FIELD, '--paths', PATHS_FIELD,
    '--principles', forgereview_scope.PRINCIPLES_FIELD, forgereview_scope.SUMMARY_FIELD,
    '--disposed', forgereview_scope.DISPOSED_FIELD,
)  # fmt: skip

#: The family's JUDGE (:mod:`dev_lab.dev.forgereview_judge`): ai-lab re-judges open findings and adjudicates
#: claims over ``{findings}`` (each with its claim) at the head of ``{range}``. Declared only to differ.
FAMILY_JUDGE: Final = (
    '{runtimes.ai_lab.python}', '-m', 'ai_lab.review.judge', '--range', RANGE_FIELD, '--model', MODEL_FIELD,
    '--rules', RULES_FIELD, '--principles', forgereview_scope.PRINCIPLES_FIELD,
    '--findings', forgereview_scope.FINDINGS_FIELD,
)  # fmt: skip

#: The runtimes the family's commands read from a host's ``[runtimes]``: the ONE set a deploy migrates.
FAMILY_RUNTIMES: Final = runtime_names((*FAMILY_COMMAND, *FAMILY_JUDGE))

#: The family's default lens globs: what refuses or declares is read strictly, prose lightly.
STRICT: Final = ('**/hooks/**', '**/rules/**', 'tests/architecture/**', '**/contracts/**')
LIGHT: Final = ('docs-src/**', '**/.claude/memory/**', '**/*.md')

#: How old a claim may grow before another host may take the head over (its claimant presumed dead): above the
#: command's own timeout, so a live review is never taken over.
DEFAULT_CLAIM_STALE: Final = '1 h'

#: DEBOUNCE (D52): how long a head must have been committed before the serve reviews it. A burst of pushes inside
#: it is ONE round, of its last head; a head older than it is reviewed on the first tick that sees it.
DEFAULT_QUIET: Final = '10 min'

#: The keys of the retired in-process reviewer, each refused naming where its concern lives now.
RETIRED_KEYS: Final = {
    'max_tokens': 'the review command bounds its own output',
    'rules': 'the review command reads the rules and profiles of the method it packages',
}

_TABLE: Final = 'review'

#: What an empty ``command`` is refused with (user ruling 2026-10-31, every PR is reviewed): no repo opts out, and
#: an omitted ``command`` is the family's, so the one fix is to delete the empty declaration.
EMPTY_COMMAND_FIX: Final = (
    'command = [] opts out of the review, and every PR is reviewed: delete it (the family command applies)'
)


@dataclass(frozen=True)
class Review:
    """``[tool.dev_lab.review]``: the command that reviews, and what bounds and cuts what it reads."""

    command: tuple[str, ...] = FAMILY_COMMAND  # declare only a genuinely different method
    model: str = FAMILY_MODEL  # fills ``{model}``
    synthesis: tuple[str, ...] = ()  # undeclared: the slice outputs are merged, nothing reads across them
    judge: tuple[str, ...] = FAMILY_JUDGE  # re-judges open findings and adjudicates claims, every round
    max_rounds: int = FAMILY_MAX_ROUNDS  # full rounds per PR; past it, the head waits (reviewbudget)
    max_diff_bytes: int = 200_000  # one slice
    max_total_bytes: int = 4_000_000  # one head
    derived: tuple[str, ...] = ()
    strict: tuple[str, ...] = STRICT
    light: tuple[str, ...] = LIGHT
    code: tuple[str, ...] = forgereview_scope.CODE
    not_code: tuple[str, ...] = forgereview_scope.NOT_CODE
    claim_stale: str = DEFAULT_CLAIM_STALE  # a duration: a claim older than this may be taken over
    quiet: str = DEFAULT_QUIET  # a duration: the serve reviews a head only once it is this old (D52)

    def __post_init__(self) -> None:
        """Refuse a ``claim_stale`` or ``quiet`` that is not a duration, naming it."""
        stale_after(self)
        _duration('quiet', self.quiet)

    @property
    def quiet_for(self) -> timedelta:
        """``quiet`` as a :class:`~datetime.timedelta`."""
        return _duration('quiet', self.quiet)

    @property
    def stale(self) -> timedelta:
        """``claim_stale`` as a :class:`~datetime.timedelta`."""
        return stale_after(self)

    @property
    def budget(self) -> Budget:
        """The bounds and globs :func:`~dev_lab.dev.forgereview_scope.plan` cuts a head by."""
        return Budget(
            self.max_diff_bytes, self.max_total_bytes, self.derived, self.strict, self.light, self.code, self.not_code
        )


def review_from(text: str, origin: str) -> Review:
    """The :class:`Review` *text* declares, defaults for what it omits; a retired or unknown key is refused."""
    declared = declared_table(tomllib.loads(text), _TABLE, {})
    if retired := [f'{key} is retired: {RETIRED_KEYS[key]}' for key in declared if key in RETIRED_KEYS]:
        msg = f'[tool.dev_lab.{_TABLE}] in {origin}: ' + '; '.join(retired)
        raise ValueError(msg)
    known = {field.name for field in dataclasses.fields(Review)}
    if unknown := sorted(set(declared) - known):
        msg = f'[tool.dev_lab.{_TABLE}] in {origin} has unknown key(s) {unknown}; the keys are {sorted(known)}'
        raise ValueError(msg)
    review = Review(**{key: tuple(value) if isinstance(value, list) else value for key, value in declared.items()})
    if 'command' in declared and not review.command:
        msg = f'[tool.dev_lab.{_TABLE}] in {origin}: {EMPTY_COMMAND_FIX}'
        raise ValueError(msg)
    if 'command' in declared and review.command == FAMILY_COMMAND:
        msg = f'[tool.dev_lab.{_TABLE}] in {origin} redeclares the family command: delete it (override `model`)'
        raise ValueError(msg)
    if why := retired_field((*review.command, *review.synthesis)):
        msg = f'[tool.dev_lab.{_TABLE}] in {origin}: {why}'
        raise ValueError(msg)
    return review


def load_review(root: Path) -> Review:
    """*root*'s working-tree ``[tool.dev_lab.review]``; defaults when it has no manifest.

    A LOCAL check of a checkout's own declaration (the family test, the policy page, merge-ready's config line);
    never what a PR's review acts on -- that is the base's, :func:`review_at`.
    """
    manifest = root / 'pyproject.toml'
    return review_from(manifest.read_text(encoding='utf-8'), str(manifest)) if manifest.is_file() else Review()


def trusted_integration(root: Path, client: Client) -> str:
    """The integration branch a PR review trusts: the one the repository's DEFAULT branch declares.

    THE TRUST CHAIN (dev-lab #38 rounds 2-4): the forge's ``default_branch`` (main, which moves only by
    ``integrate promote``) -> its ``[tool.dev_lab.integrator] integration`` (``git show origin/<default>``) -> that
    branch's review declaration (:func:`review_at`) -> the command that runs beside the review key. The PR head
    enters only as the DIFF, read as data. F-169e99e6c68c: a name read from the working tree -- the head's --
    let a PR opened against a branch it controls name that branch the integration, and its declaration ran.
    A default branch the forge does not name, or whose manifest cannot be read, refuses
    (:class:`~dev_lab.dev.reviewgate.DeclarationUnread`), never falls back to the head.
    """
    repo: Any = client.call('GET', client.repo)
    default = repo.get('default_branch') if isinstance(repo, dict) else None
    if not default:
        msg = 'the forge names no default branch: which integration branch a review trusts is undecided'
        raise DeclarationUnread(msg)
    try:
        return policy_at(root, f'origin/{default}').integration
    except (ValueError, OSError) as failed:
        msg = f'origin/{default}:pyproject.toml declares no readable integration branch: {failed}'
        raise DeclarationUnread(msg) from failed


def review_at(root: Path, base: str) -> Review:
    """The ``[tool.dev_lab.review]`` ``origin/<base>`` declares in *root* -- what a PR's review acts on.

    F-46e412ee799d, F-ef3a6c8b86b2 (dev-lab #38 round 2): the review job checks out the PR head, and the declared
    ``command`` runs beside the review key, so a head's own declaration would choose the code that runs -- under
    ``pull_request_target`` too, whose WORKFLOW alone is the base's. *base* is the integration branch
    :func:`trusted_integration` names (the job, a takeover, an adjudication) or the serve's own policy, read from
    the operator's checkout, never a PR head. A PR changing its review declaration is reviewed under the base's
    until it lands, like the Actions adoption (:mod:`dev_lab.dev.reviewgate`). Read from git (``git show``, never
    the working tree), so the serve's tick reads no forge before it knows its host can run the command. An
    unreadable base declaration refuses (:class:`~dev_lab.dev.reviewgate.DeclarationUnread`), never falls back.
    """
    where = f'origin/{base}:pyproject.toml'
    try:
        text = forgereview_scope.git(root, 'show', where)[1]
    except OSError as failed:
        msg = f'{where} cannot be read: {failed}'
        raise DeclarationUnread(msg) from failed
    if not text.strip():
        msg = f'{where} is empty'
        raise DeclarationUnread(msg)
    return review_from(text, where)


def stale_after(review: Review) -> timedelta:
    """*review*'s ``claim_stale``; a bare number or a non-duration is refused naming it."""
    return _duration('claim_stale', review.claim_stale)


def _duration(key: str, value: str) -> timedelta:
    """The declared *key*'s *value* as a :class:`~datetime.timedelta`; a bare number or a non-duration is refused."""
    try:
        quantity = Q_(value)
    except Exception as bad:
        msg = f'{key} {value!r} is not a duration; write one such as "1 h"'
        raise ValueError(msg) from bad
    if not isinstance(quantity, Q_) or not quantity.check('[time]'):
        msg = f'{key} {value!r} is not a duration (it needs a unit); write one such as "1 h"'
        raise ValueError(msg)
    return timedelta(seconds=float(quantity.m_as('s')))


def command_for(
    review: Review, reviewed: str, runtimes: Mapping[str, Mapping[str, Any]], *,
    paths: Sequence[str] = (), lens: str = 'standard', synthesis: bool = False, judge: bool = False,
) -> list[str]:  # fmt: skip
    """The declared command (or *synthesis*), every placeholder replaced: the range, the slice, this host's values.

    A host value *runtimes* (this host's ``[runtimes]``) does not declare is :class:`ReviewUnsupported`.
    """

    def host_value(field: re.Match[str]) -> str:
        value = runtimes.get(field['name'], {}).get(field['key'])
        if not isinstance(value, str) or not value:
            where = f'[{RUNTIMES_TABLE}.{field["name"]}] {field["key"]}'
            msg = f'unsupported: this host declares no {where} for the review command'
            raise ReviewUnsupported(msg)
        return str(Path(value).expanduser()) if value.startswith('~') else value

    def filled(arg: str) -> list[str]:
        if arg == PATHS_FIELD:
            return list(paths)
        return [
            HOST_FIELD.sub(host_value, arg)
            .replace(RANGE_FIELD, reviewed)
            .replace(LENS_FIELD, lens)
            .replace(MODEL_FIELD, review.model)
            .replace(RULES_FIELD, ','.join(rule.id for rule in RULES))
        ]

    declared = review.judge if judge else review.synthesis if synthesis else review.command
    return [one for arg in declared for one in filled(arg)]


def judge_for(
    root: Path, review: Review, reviewed: str, run: Callable[[Sequence[str], Path], str],
    runtimes: Mapping[str, Mapping[str, Any]],
) -> Judge:  # fmt: skip
    """The :data:`~dev_lab.dev.forgereview_judge.Judge` of *review*'s declared judge over *reviewed*, on this host.

    The command is filled only when there is something to judge: a first round has no open finding.
    """

    def judged(items: Sequence[tuple[Finding, str]]) -> Mapping[str, Verdict]:
        if not items:
            return {}
        argv = command_for(review, reviewed, runtimes, judge=True)
        return judge(argv, items, run, root, findings_field=forgereview_scope.FINDINGS_FIELD,
                     principles_field=forgereview_scope.PRINCIPLES_FIELD)  # fmt: skip

    return judged
