"""THE REVIEW A REPO DECLARES: ``[tool.dev_lab.review]``, the family's command, and where a PR's review reads it.

:mod:`dev_lab.dev.forgereview` runs the review; this module says WHAT runs -- the :class:`Review` a manifest
declares (:func:`review_from`), read from the integration branch the repository's default branch trusts
(:func:`trusted_integration`, :func:`review_at`), and the declared command with every placeholder filled for
this host (:func:`command_for`).

THE COMMAND IS THE FAMILY'S (:data:`FAMILY_COMMAND`): a repo declares only where it differs, every key optional::

    [tool.dev_lab.review]
    # command: only a genuinely different method; the family's, redeclared, is refused. Placeholders:
    # {range}: <base>..<head>; {paths}: the slice's paths (one argument each); {lens}: strict|standard|light;
    # {model}: `model`; {rules}: the registry's rule ids, comma-separated (ai-lab imports no registry);
    # {principles}: a JSON file of dev_lab.dev.principles (written per run; ai-lab holds no copy);
    # {summary}: --pr-body <file> on the one summarizing call, --no-summary on the rest;
    # {disposed}: a JSON file of findings disposed earlier (a one-shot review hands an empty one);
    # {runtimes.<name>.<key>}: THIS host's machine-file [runtimes.<name>] value (repo says WHAT, host WHERE)
    model = "<id>"             # the default is FAMILY_MODEL
    synthesis = []             # optional: run once over {findings} (the merged slices) and {range}
    max_diff_bytes = 400000    # one slice: what one reviewer reads
    max_total_bytes = 800000   # one review: slices past it are listed, not read (strictest lens first)
    derived = []               # globs of generated files beyond the family's (famfiles.GENERATED)
    strict = [...]             # globs read under the strict lens; light = [...] under the light one
    code = [...]               # globs of what executes (reviewcode.CODE): nothing else is read or capped
    not_code = [...]           # globs never code whatever their extension (reviewcode.NOT_CODE)
    claim_stale = "1 h"        # the default: a claim older than this may be taken over
    quiet = "10 min"           # the default (DEFAULT_QUIET): the serve reviews a head only once it is this old
    reviewers = []             # forge logins the review producers post as (serve hosts, jobs): their reviews are read
    where = "serve"            # WHO reviews: "serve" (a checkout runs `command`) or "judge" (an isolated host runs
                               # `bundle` over a verified review bundle, posting a PR review) -- ONE per repo
    bundle = [...]             # the judge's command over {bundle} (FAMILY_BUNDLE): declared only to differ
    judge_login = "<login>"    # with where = "judge" on Gitea: the forge login whose PR review gates the merge
    judge_app = 0              # with where = "judge" on GitHub, INSTEAD of judge_login: the App id whose
                               # `review/judge` check run gates the merge (forgeapp); exactly one of the two
    preparers = []             # logins (never the Actions bot) whose review/bundle pointer the judge reads
    batch = true               # FAMILY_BATCH: model calls via the vendor batch endpoint ({batch}); false: at once
    on_expiry = "sync"         # a request the batch let expire (24 h): answered at once ("sync") or failed ("fail")
    batch_wait = "20 min"      # DEFAULT_BATCH_WAIT: one review waits this long on its batches, then pending
    month = { provider = "<ai-lab provider>", amount = <USD>, currency = "USD" }
                               # the review's month on a host with NO machine file (a GitHub runner), its spend
                               # charged to the forge's shared ledger (reviewledger); undeclared: that host skips

Retired keys (:data:`RETIRED_KEYS`: ``max_tokens``, ``rules``, ``max_rounds``, ``judge``) are refused by name.
"""

from __future__ import annotations

import dataclasses
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from lab_commons.units import Q_

from dev_lab.dev import forgereview_batch as batching_
from dev_lab.dev import forgereview_scope, reviewcode
from dev_lab.dev._forgebackends import ACTIONS_BOT
from dev_lab.dev.family import declared_table
from dev_lab.dev.forgereview_command import ReviewUnsupported
from dev_lab.dev.forgereview_runtimes import DERIVED_RUNTIMES, HOST_FIELD, RUNTIMES_TABLE, retired_field, runtime_names
from dev_lab.dev.forgereview_scope import Budget
from dev_lab.dev.lanepolicy import policy_from
from dev_lab.dev.reviewbudget import Month
from dev_lab.dev.reviewgate import DeclarationUnread, manifest_at
from dev_lab.dev.rules import RULES

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = [
    'BUNDLE_FIELD',
    'DEFAULT_CLAIM_STALE',
    'DEFAULT_QUIET',
    'EMPTY_COMMAND_FIX',
    'FAMILY_BUNDLE',
    'FAMILY_COMMAND',
    'FAMILY_MODEL',
    'FAMILY_RUNTIMES',
    'JUDGE',
    'LENS_FIELD',
    'LIGHT',
    'MODEL_FIELD',
    'PATHS_FIELD',
    'RANGE_FIELD',
    'RETIRED_KEYS',
    'RULES_FIELD',
    'SERVE',
    'STRICT',
    'WHERE',
    'Review',
    'base_manifest',
    'command_for',
    'forge_integration',
    'forge_review',
    'load_review',
    'operator_integration',
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
    '--disposed', forgereview_scope.DISPOSED_FIELD, batching_.BATCH_FIELD,
)  # fmt: skip

#: The placeholder the judge's bundle command carries (:data:`dev_lab.dev.reviewbundle.BUNDLE_FIELD`).
BUNDLE_FIELD: Final = '{bundle}'

#: The family's review over a REVIEW BUNDLE (:mod:`dev_lab.dev.reviewbundle`): ai-lab reads the bundle's plain
#: files, never git. Run by ``forge review judge`` when the base declares ``where = "judge"``.
FAMILY_BUNDLE: Final = (
    '{runtimes.ai_lab.python}', '-m', 'ai_lab.review', '--bundle', BUNDLE_FIELD, '--model', MODEL_FIELD,
    '--rules', RULES_FIELD, '--principles', forgereview_scope.PRINCIPLES_FIELD, forgereview_scope.SUMMARY_FIELD,
    '--disposed', forgereview_scope.DISPOSED_FIELD, batching_.BATCH_FIELD,
)  # fmt: skip

#: WHO reviews a repo's PRs (``where``): a serve host or the Actions job over a checkout, or the judge host over a
#: verified bundle. ONE per repo: the serve never reviews a ``judge`` repo, the judge never a ``serve`` one.
SERVE: Final = 'serve'
JUDGE: Final = 'judge'
WHERE: Final = (SERVE, JUDGE)

#: The runtimes the family's commands read from a host's ``[runtimes]``: the ONE set a deploy migrates. A derived
#: runtime (``ai_lab``, built from the lock) is not one: no host declares it.
FAMILY_RUNTIMES: Final = runtime_names((*FAMILY_COMMAND, *FAMILY_BUNDLE)) - DERIVED_RUNTIMES.keys()

#: The family's default lens globs: what refuses or declares is read strictly, prose lightly.
STRICT: Final = ('**/hooks/**', '**/rules/**', 'tests/architecture/**', '**/contracts/**')
LIGHT: Final = ('docs-src/**', '**/.claude/memory/**', '**/*.md')

#: How old a claim may grow before another host may take the head over (its claimant presumed dead): above the
#: command's own timeout, so a live review is never taken over.
DEFAULT_CLAIM_STALE: Final = '1 h'

#: DEBOUNCE (D52): how long a head must have been committed before the serve reviews it. A burst of pushes inside
#: it is ONE review, of its last head; a head older than it is reviewed on the first tick that sees it.
DEFAULT_QUIET: Final = '10 min'
#: How long a ready head may wait on ``tests/review`` before the backlog alarm pages (:mod:`dev_lab.dev.forgebacklog`).
DEFAULT_BACKLOG: Final = '6 h'

#: The keys of the retired in-process reviewer, each refused naming where its concern lives now.
RETIRED_KEYS: Final = {
    'max_tokens': 'the review command bounds its own output',
    'rules': 'the review command reads the rules and profiles of the method it packages',
    'max_rounds': 'a PR is reviewed once (user ruling 2026-11-06): there are no rounds to cap',
    'judge': 'a one-shot review re-judges nothing and adjudicates no claim (user ruling 2026-11-06)',
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
    max_diff_bytes: int = 400_000  # one slice: every slice pays the fixed prompt again, so few and large
    max_total_bytes: int = 800_000  # one review: slices past it are listed, not read (spend 2026-11-03)
    derived: tuple[str, ...] = ()
    strict: tuple[str, ...] = STRICT
    light: tuple[str, ...] = LIGHT
    code: tuple[str, ...] = reviewcode.CODE
    not_code: tuple[str, ...] = reviewcode.NOT_CODE
    claim_stale: str = DEFAULT_CLAIM_STALE  # a duration: a claim older than this may be taken over
    quiet: str = DEFAULT_QUIET  # a duration: the serve reviews a head only once it is this old (D52)
    backlog: str = DEFAULT_BACKLOG  # a duration: a ready head unreviewed this long pages (forgebacklog)
    reviewers: tuple[str, ...] = ()  # the producer logins whose review records every host reads (never any writer)
    where: str = SERVE  # who reviews: SERVE or JUDGE, one per repo
    bundle: tuple[str, ...] = FAMILY_BUNDLE  # the judge's command over {bundle}
    judge_login: str = ''  # where = JUDGE (Gitea): the ONE login whose PR review gates the merge, never inferred
    judge_app: int = 0  # where = JUDGE (GitHub): the ONE App id whose JUDGE_CHECK run gates the merge
    preparers: tuple[str, ...] = ()  # where = JUDGE: logins (never the Actions bot) whose bundle pointer is read
    batch: bool = batching_.FAMILY_BATCH  # via the vendor batch endpoint; False: at once (forgereview_batch)
    on_expiry: str = batching_.FAMILY_ON_EXPIRY  # an expired batch request: one of batching_.ON_EXPIRY
    batch_wait: str = batching_.DEFAULT_BATCH_WAIT  # a duration: one review waits this long, then posts pending
    month: Month | None = None  # the review's month on a host with no machine file (reviewledger); None: it skips

    def __post_init__(self) -> None:
        """Refuse a ``where`` outside :data:`WHERE`, a judge with no login, a bad ``bundle`` or duration."""
        if self.where not in WHERE:
            msg = f'where = {self.where!r} is not one of {WHERE}'
            raise ValueError(msg)
        if isinstance(self.judge_app, bool) or not isinstance(self.judge_app, int) or self.judge_app < 0:
            msg = f'judge_app = {self.judge_app!r} is no GitHub App id (a positive integer)'
            raise ValueError(msg)
        if self.where == JUDGE and bool(self.judge_login) == bool(self.judge_app):
            said = 'both judge_login and judge_app' if self.judge_login else 'neither judge_login nor judge_app'
            msg = f'where = "{JUDGE}" declares {said}: exactly ONE identity gates the merge'
            raise ValueError(msg)
        if BUNDLE_FIELD not in self.bundle:
            msg = f'bundle = {list(self.bundle)} names no {BUNDLE_FIELD}: the judge would read no bundle'
            raise ValueError(msg)
        if forged := {ACTIONS_BOT, ''} & set(self.preparers):
            msg = f'preparers = {sorted(forged)}: an identity every Actions job posts as is no preparer'
            raise ValueError(msg)
        batching_.check_expiry(self.on_expiry)
        stale_after(self)
        batching_.wait_of(self)
        _duration('quiet', self.quiet)
        _duration('backlog', self.backlog)

    @property
    def quiet_for(self) -> timedelta:
        """``quiet`` as a :class:`~datetime.timedelta`."""
        return _duration('quiet', self.quiet)

    @property
    def backlog_for(self) -> timedelta:
        """``backlog`` as a :class:`~datetime.timedelta`."""
        return _duration('backlog', self.backlog)

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
    try:
        fields = {key: tuple(value) if isinstance(value, list) else value for key, value in declared.items()}
        if 'month' in fields:
            fields['month'] = Month.from_declared(fields['month'])
        review = Review(**fields)
    except ValueError as bad:
        msg = f'[tool.dev_lab.{_TABLE}] in {origin}: {bad}'
        raise ValueError(msg) from bad
    if 'command' in declared and not review.command:
        msg = f'[tool.dev_lab.{_TABLE}] in {origin}: {EMPTY_COMMAND_FIX}'
        raise ValueError(msg)
    if 'bundle' in declared and review.bundle == FAMILY_BUNDLE:
        msg = f'[tool.dev_lab.{_TABLE}] in {origin} redeclares the family bundle command: delete it'
        raise ValueError(msg)
    if 'command' in declared and review.command == FAMILY_COMMAND:
        msg = f'[tool.dev_lab.{_TABLE}] in {origin} redeclares the family command: delete it (override `model`)'
        raise ValueError(msg)
    if why := retired_field((*review.command, *review.synthesis, *review.bundle)):
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
    return _integration_of(root, _default_branch(client))


def forge_integration(client: Client) -> str:
    """:func:`trusted_integration` read from the FORGE alone, for a host holding no checkout (the review judge).

    The same chain -- the forge's ``default_branch`` -> its manifest's integration branch -- each file read through
    the forge's contents API (:func:`~dev_lab.dev.reviewgate.manifest_at`), never a working tree or a bundle.
    """
    default = _default_branch(client)
    try:
        return policy_from(manifest_at(client, default), f'{default}:pyproject.toml').integration
    except ValueError as failed:
        msg = f'{default}:pyproject.toml declares no readable integration branch: {failed}'
        raise DeclarationUnread(msg) from failed


def forge_review(client: Client, integration: str) -> Review:
    """The ``[tool.dev_lab.review]`` *integration* declares, read FRESH from the forge: the judge's review_at."""
    return review_from(manifest_at(client, integration), f'{integration}:pyproject.toml')


def _default_branch(client: Client) -> str:
    repo: Any = client.call('GET', client.repo)
    default = repo.get('default_branch') if isinstance(repo, dict) else None
    if not default:
        msg = 'the forge names no default branch: which integration branch a review trusts is undecided'
        raise DeclarationUnread(msg)
    return default


def operator_integration(root: Path) -> str:
    """:func:`trusted_integration` for the operator's own verbs (``plan``, ``takeover``, ``held``...), offline.

    The default branch is the operator clone's ``origin/HEAD`` -- set by the clone, never by a PR head -- so no
    ``GET /repos`` is spent (dev-lab #40). An unset ``origin/HEAD`` refuses, naming the fix.
    """
    code, out = forgereview_scope.git(root, 'symbolic-ref', '-q', '--short', 'refs/remotes/origin/HEAD', ok=(0, 1))
    default = out.strip().removeprefix('origin/') if code == 0 else ''
    if not default:
        msg = 'origin/HEAD is unset: `git remote set-head origin --auto` names the default branch'
        raise DeclarationUnread(msg)
    return _integration_of(root, default)


def _integration_of(root: Path, default: str) -> str:
    try:
        return policy_from(_manifest_at(root, f'origin/{default}'), f'origin/{default}:pyproject.toml').integration
    except (ValueError, OSError) as failed:
        msg = f'origin/{default}:pyproject.toml declares no readable integration branch: {failed}'
        raise DeclarationUnread(msg) from failed


def review_at(root: Path, base: str) -> Review:
    """The ``[tool.dev_lab.review]`` ``origin/<base>`` declares in *root* -- what a PR's review acts on.

    F-46e412ee799d, F-ef3a6c8b86b2 (dev-lab #38 round 2): the review job checks out the PR head, and the declared
    ``command`` runs beside the review key, so a head's own declaration would choose the code that runs -- under
    ``pull_request_target`` too, whose WORKFLOW alone is the base's. *base* is the integration branch
    :func:`trusted_integration` names (the job, a takeover) or the serve's own policy, read from
    the operator's checkout, never a PR head. A PR changing its review declaration is reviewed under the base's
    until it lands, like the Actions adoption (:mod:`dev_lab.dev.reviewgate`). Read from git (``git show``, never
    the working tree), so the serve's tick reads no forge before it knows its host can run the command. An
    unreadable base declaration refuses (:class:`~dev_lab.dev.reviewgate.DeclarationUnread`), never falls back.
    """
    return review_from(*base_manifest(root, base))


def base_manifest(root: Path, base: str) -> tuple[str, str]:
    """``origin/<base>``'s ``pyproject.toml`` in *root* and where it was read: what a PR's job may TRUST.

    Read from git, never the working tree (the PR head's); unreadable or empty refuses
    (:class:`~dev_lab.dev.reviewgate.DeclarationUnread`), never falls back.
    """
    where = f'origin/{base}:pyproject.toml'
    try:
        text = _manifest_at(root, f'origin/{base}')
    except OSError as failed:
        msg = f'{where} cannot be read: {failed}'
        raise DeclarationUnread(msg) from failed
    if not text.strip():
        msg = f'{where} is empty'
        raise DeclarationUnread(msg)
    return text, where


def _manifest_at(root: Path, rev: str) -> str:
    """*rev*'s ``pyproject.toml``, read by the door's git: its held credential fetches a blobless clone's blob.

    The review job's clone is ``--filter=blob:none``, so the read fetches the blob lazily; a plain ``git show``
    carries no credential and failed every review on a private forge (2026-11-02, exit 128). The header rides the
    door's git env alone (:func:`~dev_lab.dev.reviewgitauth.git_env`), never the reviewer's.
    """
    return forgereview_scope.git(root, 'show', f'{rev}:pyproject.toml')[1]


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
    paths: Sequence[str] = (), lens: str = 'standard', synthesis: bool = False,
    bundle: bool = False, batching: Sequence[str] = batching_.NO_BATCH,
) -> list[str]:  # fmt: skip
    """The declared command (or *synthesis*), every placeholder replaced: the range, the slice, this host's values.

    :data:`~dev_lab.dev.forgereview_batch.BATCH_FIELD` becomes *batching* (:func:`~dev_lab.dev.forgereview_batch.
    batch_args`); a caller that keeps no batch state leaves :data:`~dev_lab.dev.forgereview_batch.NO_BATCH`.

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
        if arg == batching_.BATCH_FIELD:
            return list(batching)
        return [
            HOST_FIELD.sub(host_value, arg)
            .replace(RANGE_FIELD, reviewed)
            .replace(LENS_FIELD, lens)
            .replace(MODEL_FIELD, review.model)
            .replace(RULES_FIELD, ','.join(rule.id for rule in RULES))
        ]

    declared = review.bundle if bundle else review.synthesis if synthesis else review.command
    return [one for arg in declared for one in filled(arg)]
