"""``lab_commons.dev`` — dev-time guarantees, OPT-IN and never imported by the top level.

Tier 3, and the tier boundary is a real one. ``lab_commons``'s own pyproject states its tier-1
posture in its own words -- "*Tier 1 core deps only … a consumer that wants only logging installs
nothing heavier than this*" -- so a runtime consumer must not acquire a development system by
importing the package it already had. ``lab_commons/__init__.py`` does not import this subpackage,
in the same way and for the same reason that it does not import ``lab_commons.em``: importing
``lab_commons`` never pulls this in, and a consumer opts in explicitly, by the full path:
``from lab_commons.dev.verdict import Verdict``.

THE OPT-IN IS GATED BY THE ``dev`` EXTRA, which already exists and is the right one: it names ``pytest`` and
``ruff``, and those two ARE this subpackage's dependencies -- as executables rather than as imports. Nothing
here needs a new install, because the layer is stdlib plus tier 1: :mod:`lab_commons.resources` (the box
lock), :mod:`lab_commons.paths` (the repo root), and ``hashlib``/``importlib.metadata``. That is a
measurement, not an aspiration -- ``pip install lab-commons`` pulls nothing new, and a consumer that wants
only logging still installs nothing heavier than it did yesterday.

WHAT IS HERE, and the order is the order of dependency rather than of importance. A bullet reading
NOT RE-EXPORTED says one thing, stated once here instead of at each site: that module's own names
are too unqualified to survive being flattened into a namespace this wide.

* :mod:`lab_commons.dev.content` — a CONTENT address over the measured paths, the half of a verdict
  that a ``HEAD``-shaped stamp cannot supply.
* :mod:`lab_commons.dev.envkey` — a key over the resolved dependency set, the other half.
* :mod:`lab_commons.dev.logref` — the log a verdict carries, and the reader that re-derives it.
* :mod:`lab_commons.dev.verdict` — the algebra: ``(tree, env, selector, result, log)``.
* :mod:`lab_commons.dev.pytestout` — READING one test runner's stdout and nothing more: the escape
  strip, the anchored summary line, the collected count and the truncation vocabulary. Every reader
  answers ``None`` for a line never printed, never ``0``. NOT RE-EXPORTED.
* :mod:`lab_commons.dev.reports` — what those readings MEAN for a verify step: the exit-code table,
  the shortfalls, and the two-sided skip ratchet a project declares in ``allowed_skips``.
* :mod:`lab_commons.dev.verify` — the family's ONE entry point that PRODUCES one:
  ``python -m lab_commons.dev.verify`` runs ruff, ruff format and pytest, tees them into a log under
  ``.verify/``, and prints a stamped verdict -- the portable half of motronics-studio's 1770-line
  gate runner, the half needing no case library, no solver and no vendor engine, so the three repos
  with no verdict-producing invocation at all now have the same one. NOT RE-EXPORTED for its own
  reason: it runs as ``__main__``, and importing it here makes ``runpy`` warn it was already loaded.
* :mod:`lab_commons.dev.boxlock` — one CPU-saturating run at a time, ON the broker that already
  ships in this package rather than beside it.
* :mod:`lab_commons.dev.profile` — ``RepoProfile``, so attaching a repo is a substitution -- with
  one measured caveat recorded in its docstring: ``resolve_home``'s auto-detection anchors on its
  own file, so a profile carries an ``anchor`` for the checkout it describes.
* :mod:`lab_commons.dev.rules` — the shared registry: one row per UNIVERSAL rule, carrying its
  stable ID, its statement in the words the shared source owns, and the mechanism that refuses a
  violation. A rule with no resolvable mechanism is a REFUSAL in three places -- at construction, so
  prose cannot enter the registry; at adoption, so a repo cannot claim a rule it does not enforce;
  and at check time, so a deleted mechanism reds. ``Adoption`` is what makes the registry SHARED
  rather than merely central: a rule's statement is universal, its mechanism lives in one tree.
* :mod:`lab_commons.dev.hooks` and :mod:`lab_commons.dev.hook_adoption` — the same split one level
  down, for the machinery that REFUSES a command rather than a design: one row per universal denied
  shape, each NAMING ITS REMEDY, and a per-repo adoption that supplies the exit. A rule whose remedy
  does not exist in the adopting repo is not shipped there: a sealed road is routed around, not
  obeyed. :mod:`lab_commons.dev.allow_adoption` is that registry's ALLOW half and closes the seam
  that left those exits unreachable -- ``permissions.allow`` is DERIVED from the remedies a repo
  supplies (three of nine live rows, 2026-09-18), and only a road answering no rule is DECLARED.
* :mod:`lab_commons.dev.units` — the naming half of the units rule: a scan that refuses an
  identifier whose trailing segment spells a unit, because the unit belongs in the VALUE (see
  :func:`lab_commons.units.quantity_parser`). It reports the token set it searched for, so finding
  nothing is distinguishable from searching for nothing.
* :mod:`lab_commons.dev.cjk` — the family's ONE "no CJK in tracked source" guard (user directive,
  2026-09-16): the scan, the five CJK ranges, the ``.claude/memory/``/``attic/``/``archived/``
  exemptions and the floor are shared; each adopting repo supplies its own named-set declaration of
  files still carrying CJK, exactly the shape the suppression ratchet already uses, so a population
  too large for one commit can be migrated as a ratchet instead of a flat assertion. Re-exported
  below under ``CJK``-prefixed names because :class:`~lab_commons.dev.units.Scan` and
  :func:`~lab_commons.dev.units.scan_files` already own the unqualified spellings.
* :mod:`lab_commons.dev.docwidth` — the family's ONE per-line WIDTH ceiling for every document
  injected into an agent's context (user directive, 2026-09-16): a line-COUNT ratchet is blind to
  how long each line is, so this caps columns too, at 120 -- the ceiling every repo already uses for
  code. The injected-document corpus (``AGENTS.md``/``CLAUDE.md`` by basename, ``.claude/rules/**``,
  ``.claude/memory/`` excluded) is DATA a consumer may override, and the ratchet shape is the same
  named-set declaration as :mod:`lab_commons.dev.cjk`.
* :mod:`lab_commons.dev.hook_install` — HOOKS-ARE-WIRED, and the half a ``.pre-commit-config.yaml``
  cannot answer for itself: a configuration DECLARES hooks, ``pre-commit install`` is a separate act
  on a separate machine, and nothing links the two. Measured 2026-09-16: ``wdg-lab`` and
  ``optimi-lab`` each declared a full configuration and had ZERO hooks installed. It reports and
  never repairs itself -- a hooks directory is shared by every worktree of a checkout -- and its
  refusal names a remedy DERIVED from the configuration rather than restated beside it.
* :mod:`lab_commons.dev.bounded` — REFUSAL-NAMES-THE-REMEDY, all three halves of it: a wall that
  terminates the process TREE (``subprocess.run``'s timeout kills only the direct child and then
  reaps unbounded, which is a hang detector that hangs), the WIDTH a refusal must consult before it
  may call a run a tier boundary rather than a narrowed box, and the sentence itself -- three
  states, three DIFFERENT remedies, two of which are wrong in the other's case.
* :mod:`lab_commons.dev.netverb` - NETWORK-RETRY-THEN-REPORT, the family half of it: a BOUNDED
  retry around a network verb, a classification table saying which failures can clear on another
  attempt (a 401 cleared on a retry; a rejected ref, a 403 and a pre-push hook's refusal repeat
  identically), and a ``Report`` the caller BRANCHES on instead of a printed word "blocked". It
  composes with ``bounded`` for the wall rather than restating it. Reached BY NAME -- as an API,
  and as ``python -m lab_commons.dev.netverb -- git fetch origin`` for a shell caller -- so it is
  not re-exported below, exactly as ``verify`` is not: a package that imports its own entry point
  makes ``runpy`` warn the module was already in ``sys.modules``.
* :mod:`lab_commons.dev.checkout` — SHARED-CHECKOUT, which both siblings declared absent on the
  grounds that the push obligation "is a fact about origin, not about any file in this checkout".
  The premise is true and the conclusion was wrong: git answers "what is here that origin does not
  have" exactly and without a network call. Measured against the REMOTE and never a local pointer,
  and with ``git cherry`` rather than ancestry, because those are the two ways this audit has
  actually been observed to lie.
* :mod:`lab_commons.dev.githooks` -- the git hook SCRIPTS themselves, shipped as a package payload
  and reached by NAME (``python -m lab_commons.dev.githooks bump-version``). Five scripts as of R4,
  and they are not all hooks: ``with-venv`` and ``branch-push-only`` are WRAPPERS that take the
  command to run as arguments, and ``git-env-repair`` is a FRAGMENT that is SOURCED -- running one
  exits 0 having done nothing, which reads exactly like a hook that passed, so ``KINDS`` declares
  what each is and ``run_hook`` refuses the fragment. A repo fact a script cannot derive arrives as
  an environment variable with NO DEFAULT (``LAB_PUSH_PROTECTED_REF``, ``LAB_CZ_BASE_REF``), the
  shape :mod:`~lab_commons.dev.dep` already uses. Not re-exported below: it is run, not imported.
* :mod:`lab_commons.dev.agenthooks` -- the agent-guard ENGINE itself, shipped as a package payload
  the way ``githooks`` ships its scripts, and JavaScript because a ``PreToolUse`` hook is a command
  whose stdout is a JSON decision. It MOVES verbatim: two answers to "what will this shell line
  execute" is the fork these modules exist to remove. Unlike a git hook it is INSTALLED into the
  consumer, its command line in a committed ``.claude/settings.json``.
* :mod:`lab_commons.dev.agent_guard` -- AGENT-GUARD-IS-LIVE, the hook-install question one layer up:
  a rendered ``deny-rules.json`` is a DECLARATION, and installing the engine plus its ``PreToolUse``
  wiring is a separate act. MEASURED 2026-09-17: the registry and its wiring recipe existed while the
  engine lived in ONE repo of four, so rendering rules anywhere else would have produced an inert
  declaration that reads as a guard. Three parts reported BY NAME -- engine, rules, wiring -- because
  each fails differently, and installing is an EXPLICIT request that never clobbers an unrelated
  setting, matcher, or an engine lab-commons did not ship. Not re-exported below.
* :mod:`lab_commons.dev.docsite` -- the documentation-site driver: a TABLE of sub-sites, every
  subprocess checked and bounded, and a missing toolchain that SKIPS and SAYS SO on the portal page
  rather than failing the build or vanishing from it. Not re-exported below.
* :mod:`lab_commons.dev.quantity_values` -- the VALUE half of the units rule, and the reason it is a
  second module rather than a wider ``units``: a scan that refuses a unit-spelling NAME rewards the
  LOSSY repair -- deleting the suffix silences it and records the unit nowhere. This proves the unit
  reached the VALUE instead, and ``migration_conflicts`` refuses a key in both waiver and registry.
* :mod:`lab_commons.dev.boxwait` -- the adoption half of ``boxlock``: what a dev tier DOES when it
  finds the box held. Three answers are wrong (start anyway, refuse instantly, block forever) and
  this is the fourth -- queue on a DEADLINE, say who you are waiting for while you wait, and refuse
  NAMING the holder when the deadline passes. Separate from ``verify`` because verify is one adopter
  and not the only one.
* :mod:`lab_commons.dev.dep` -- the family's ONE door for mutating a Python environment, decided by
  STATE rather than by command TEXT: no verdict may cite an environment it did not run in, so a
  mutation DURING a run is PREVENTED against the box lock and a mutation BETWEEN runs RETIRES the
  stored anchors. It reads ``sys.prefix`` of the invoking interpreter, which is what makes the
  sibling-repo false positive structurally impossible rather than merely fixed.
* :mod:`lab_commons.dev.installdoor` -- the OTHER half of ``dep``'s invariant: ``dep`` decides WHEN
  an environment may move, this whether a path that moves one delivers the DECLARED build of a
  requirement carrying no ref -- MEASURED per tool, not read off a flag name, which is why the
  reverting door found here was a git hook and not a Makefile target.
* :mod:`lab_commons.dev.doorcensus` -- the question above it, which no per-repo guard can answer
  about itself: **was this repo's door set ever looked at, and is it still what was measured?** One
  row per repo per door by EQUALITY, not a floor; plus DECLINED rows, so a door left out is
  distinguishable from one nobody looked at, and SHARED rows, stored in one repo and RUN in others.
* :mod:`lab_commons.dev.syncscope` -- the OTHER half of what a sync does, which the two above are
  blind to by construction: they judge the BUILD one distribution arrives at, this the POPULATION
  left behind, after ``uv sync`` with no ``--extra`` took a box from 113 to 30 distributions while
  delivering the declared build. A tree with no pytest reads as BROKEN, not as UNEQUIPPED, and the
  answer is a JOIN never a property of the command: ``--extra all`` means whatever that repo's own
  manifest says, which in motronics is six extras and neither ``dev`` nor ``img-to-cad``.
* :mod:`lab_commons.dev.collectscope` -- the half ``syncscope`` names as UNMEASURABLE in its own
  docstring, which needs a second text to answer: the TEST TREE. A scope that scored COMPLETE still
  leaves a repo with NO VERDICT when a module-scope import is gone, because pytest IMPORTS what it
  collects and a collection error judges nothing. The join is IMPORT name to DISTRIBUTION name and
  they differ; reading that from installed metadata was measured and REFUSED, since an already-pruned
  environment answers that a distribution does not exist. A guard DEGRADES and a skip mark does not.
* :mod:`lab_commons.dev.synccensus` -- that reader pointed at the selections the family makes, which
  are mostly in a different repo from the command that syncs: one shared CI workflow builds its
  extras from each caller's ``extras:`` line. EQUALITY on scope and on the stranded set, plus a
  DERIVED scan refusing a pruning command no row accounts for. Not re-exported below.
* :mod:`lab_commons.dev.devdocs` -- the family's MECHANISM DOCS as DATA: one row per page under this
  repo's ``docs-src/dev/``, with the pointer table a consuming repo RENDERS instead of copying. The
  prose itself is deliberately NOT here -- ``tests/test_arch_rules_pages.py`` refuses markdown under
  ``src/`` -- so what ships is the table of contents, which is the half that rots when four repos
  hand-maintain it. Not re-exported below.
* :mod:`lab_commons.dev.shadow_build` -- measuring a rebuilt native extension WITHOUT installing it.
  The venv is SHARED, so ``maturin develop`` mutates the interpreter another lane's verdict is
  running in -- the :mod:`~lab_commons.dev.dep` hazard arriving through a build tool, which takes no
  lock and asks nobody. So it BUILDS a wheel, UNPACKS it (a wheel is a zip) and SHADOWS the
  installed copy via ``PYTHONPATH``, refusing any output path inside ``sys.prefix``; and it times
  the two arms A/B/A/B, because a block design charges a shared box's drift to whichever arm ran
  during it. It reports a KERNEL ratio and deliberately carries no end-to-end figure: the weight
  that would produce one is a property of the consuming repo's cases. Not re-exported below.
* :mod:`lab_commons.dev.ab_bench` -- the other half of that measurement: an IN-PROCESS seam, where
  its sibling times CHILD PROCESSES. The difference is the failure modes, not the scale. There may
  be more than two arms; an arm may legitimately REFUSE an input its rivals accept, which is an
  ANSWER and is recorded rather than aborted on; and an arm may pay a one-time setup, which is
  amortised over a recurrence count the CALLER measured, never over 1 and never over 0. A refused
  arm reports no median at all, because a candidate timed only on the inputs it accepted has
  selected its own sample. Whether a seam can be DISPATCHED on at all is asked rather than assumed,
  and the pairs that forbid it are named. NOT RE-EXPORTED.
* :mod:`lab_commons.dev.testfacts` -- what a test FILE declares about itself, and one assertion
  SHAPE (a test whose assertions are ALL ``is not None``, which cannot fail behaviourally), read from
  the AST and never by collecting: collection IMPORTS, and a census that collects starts MATLAB to
  find out whether a test starts MATLAB. Marks, ``timeout`` literals, ``test_``-prefixed functions
  and that shape are facts about PYTEST and are shared; which marks name a vendor, which paths a tier
  claims and what its wall is arrive as PREDICATES the consumer supplies. The partition is
  first-match-wins with a REQUIRED residual bucket, because the population that matched nothing -- in
  a slow tier for no reason any code can read -- is the reading the whole instrument exists for. Not
  re-exported below: ``collect`` and ``census`` say nothing about their subject once flattened.
* :mod:`lab_commons.dev.selfbuild` -- the one environment mutation that is NOT a dependency change:
  installing a wheel this workspace built from the checkout you are standing in. It composes with
  :mod:`~lab_commons.dev.dep` rather than repeating it -- that door decides WHEN an environment may
  move, this one decides WHOSE wheel may go through it in :attr:`~lab_commons.dev.dep.Mode.PINNED`.
  Without the ownership half, ``--no-index`` is a safety catch on a loaded gun: it stops an index
  being read and says nothing at all about ``pip install ./somebody-elses.whl``. The set of
  distributions a workspace builds is READ from the manifests the caller hands in, never spelled in a
  guard, and an empty set refuses everything rather than comparing vacuously. Not re-exported below.
* :mod:`lab_commons.dev.famconfig` -- the family's CONFIG artefacts as one BASE plus a named DELTA,
  rendered, with a guard that reds on a hand edit rather than letting it drift. A consumer therefore
  has two states and no third: it reads the family artefact, or it declares its delta. The measured
  counts, why a DROP is a mapping-to-its-reason and never a set, why an addition may be ANCHORED
  inside a rendered block, why ``REQUIRED`` exists beside ``RENDERED``, and why `[tool.ruff]` is
  deliberately absent are all in that module's own docstring. Not re-exported below.

R4 PHASE 1, THE ``scripts/gate/`` AND ``scripts/repo/`` MECHANISMS (2026-09-17) -- eight modules,
family half only, no consumer re-pointed, none re-exported. ONE LINE EACH AND THE BREVITY IS FORCED: this file entered
the tranche at 387 lines against a 400-line band, so the reasoning stays in each module's own
docstring rather than being copied here -- and the NEXT module to arrive must split this inventory.

* :mod:`lab_commons.dev.datedlog` -- one dated log layout; the base has NO DEFAULT (four repos, four answers).
* :mod:`lab_commons.dev.shards` -- a partition, the AND over a shard set, and a required population FLOOR.
* :mod:`lab_commons.dev.bypath` -- a by-path load as a CALL: one object per FILE, nothing to suppress.
* :mod:`lab_commons.dev.seams` -- rebinding for measurement WITH the undo; an unresolved seam is reported.
* :mod:`lab_commons.dev.gatebase` -- the NARROWEST admitted ancestor of HEAD; refs arrive with NO DEFAULT.
* :mod:`lab_commons.dev.treedirt` -- did the tree MOVE while judged; identity stays with ``content``.
* :mod:`lab_commons.dev.symcov` -- public symbols of one tree found in another; the floor is REQUIRED.
* :mod:`lab_commons.dev.forge` -- branch protection against a DECLARATION; INERT is its own standing.
* :mod:`lab_commons.dev.floors` -- a scan that read NOTHING is not a clean scan; both sides, no default.
* :mod:`lab_commons.dev.foreign` -- the leaf's own tier-1 rule, made refusable: which string
  constants here name a SIBLING or a path this checkout cannot resolve. Three kinds, because they
  are not equally wrong -- executable DATA, a consumer TREE PATH, and PROSE -- and the waiver is a
  NAMED SET of evicted-by-design rows rather than a count, so a deletion lands mechanically. NOT
  RE-EXPORTED -- ``scan`` and ``kinds`` say nothing once flattened.
* :mod:`lab_commons.dev.venvpath` -- the one place that spells a venv interpreter: concrete to run, globbed to track.
* :mod:`lab_commons.dev.durations` -- what every test COST, as a ledger the runner merges rather than
  overwrites, and the two readings a ``slow`` marker set is judged by. The wall's own kills arrive
  at ~0.0s, so they are filed at the WALL: a naive reading acquits exactly what the wall caught.
  NOT RE-EXPORTED -- ``read``, ``write`` and ``over`` say nothing once flattened.
* :mod:`lab_commons.dev.famtests` -- the shared test BODIES a consumer parametrizes; no fact has a default.
* :mod:`lab_commons.dev.supersede` -- has the family ALREADY expressed this roster row; overlap GRADES, never detects.

THE THREE ROWS THAT CLOSE A RULE ARE NOT RE-EXPORTED BELOW, and that is deliberate rather than an omission: each carries
short status constants whose meaning is local to its own question (``ABSENT``, ``PROTECTED``), and
flattening them into one namespace beside :data:`lab_commons.dev.content.ABSENT` would leave a
reader guessing which of two unrelated answers they are holding. Import them by module.

WHAT IS DELIBERATELY NOT HERE YET: the five architecture mechanisms (public-surface declaration,
suppression ratchet, module-size alarm, enforced-mechanism registry, duplication ratchet). They take
a ``RepoProfile`` and are the next layer. :mod:`lab_commons.dev.rules` is NOT that layer: it resolves
whether a named mechanism is still LIVE, and the five are the mechanisms an adopter would name.
"""

from lab_commons.dev._unit_tokens import EXCLUDED_TOKENS, UNIT_TOKENS
from lab_commons.dev.boxlock import BOX_POOL, BoxLock
from lab_commons.dev.cjk import CJK_RANGES, EXEMPT_PREFIXES
from lab_commons.dev.cjk import Occurrence as CJKOccurrence
from lab_commons.dev.cjk import Scan as CJKScan
from lab_commons.dev.cjk import VacuousScan as VacuousCJKScan
from lab_commons.dev.cjk import assert_floor as assert_cjk_floor
from lab_commons.dev.cjk import ratchet as cjk_ratchet
from lab_commons.dev.cjk import scan_files as scan_cjk_files
from lab_commons.dev.content import ABSENT, DEFAULT_IGNORES, content_address, file_digest
from lab_commons.dev.docwidth import (
    INJECTED_BASENAMES,
    INJECTED_EXEMPT_PREFIXES,
    INJECTED_PREFIXES,
    WIDTH_CEILING,
    Overwidth,
    VacuousWidthScan,
    WidthScan,
    assert_width_floor,
    injected_docs,
    is_injected_doc,
    line_widths,
    scan_widths,
    width_ratchet,
    width_remedy,
)
from lab_commons.dev.envkey import UNREADABLE, env_key, env_manifest, interpreter_identity
from lab_commons.dev.hook_adoption import HookAdoption, assert_shippable, deny_rules, render, unremedied
from lab_commons.dev.hooks import DENY_RULES, DenyRule, Remedy, UnremediedRule, denies, fires
from lab_commons.dev.logref import MARKER, Citation, LogRef, UnverifiableLog, stamp_line, verify_log
from lab_commons.dev.profile import NotACheckout, RepoProfile
from lab_commons.dev.quantity_values import (
    DIMENSIONLESS,
    QuantitySite,
    ValueScan,
    assert_value_floor,
    carries_a_unit,
    migration_conflicts,
    parse_quantity,
    scan_toml_values,
    value_ratchet,
    value_remedy,
)
from lab_commons.dev.reports import (
    SKIP_CEILING,
    MalformedAllowance,
    StepReport,
    declared_skips,
    read_pytest,
    read_ruff,
)
from lab_commons.dev.rules import (
    RULES,
    Adoption,
    Rule,
    UnenforceableRule,
    assert_adopted,
    assert_enforceable,
    guard,
    lint,
    tracked_files,
    unadopted,
    waived,
)
from lab_commons.dev.units import (
    SCANNED_SUFFIXES,
    Scan,
    Violation,
    assert_registry_sane,
    scan_files,
    trailing_token,
)
from lab_commons.dev.verdict import IncompleteRun, Outcome, Proof, Result, Selector, Verdict

__all__ = [
    'ABSENT',
    'BOX_POOL',
    'CJK_RANGES',
    'DEFAULT_IGNORES',
    'DENY_RULES',
    'DIMENSIONLESS',
    'EXCLUDED_TOKENS',
    'EXEMPT_PREFIXES',
    'INJECTED_BASENAMES',
    'INJECTED_EXEMPT_PREFIXES',
    'INJECTED_PREFIXES',
    'MARKER',
    'RULES',
    'SCANNED_SUFFIXES',
    'SKIP_CEILING',
    'UNIT_TOKENS',
    'UNREADABLE',
    'WIDTH_CEILING',
    'Adoption',
    'BoxLock',
    'CJKOccurrence',
    'CJKScan',
    'Citation',
    'DenyRule',
    'HookAdoption',
    'IncompleteRun',
    'LogRef',
    'MalformedAllowance',
    'NotACheckout',
    'Outcome',
    'Overwidth',
    'Proof',
    'QuantitySite',
    'Remedy',
    'RepoProfile',
    'Result',
    'Rule',
    'Scan',
    'Selector',
    'StepReport',
    'UnenforceableRule',
    'UnremediedRule',
    'UnverifiableLog',
    'VacuousCJKScan',
    'VacuousWidthScan',
    'ValueScan',
    'Verdict',
    'Violation',
    'WidthScan',
    'assert_adopted',
    'assert_cjk_floor',
    'assert_enforceable',
    'assert_registry_sane',
    'assert_shippable',
    'assert_value_floor',
    'assert_width_floor',
    'carries_a_unit',
    'cjk_ratchet',
    'content_address',
    'declared_skips',
    'denies',
    'deny_rules',
    'env_key',
    'env_manifest',
    'file_digest',
    'fires',
    'guard',
    'injected_docs',
    'interpreter_identity',
    'is_injected_doc',
    'line_widths',
    'lint',
    'migration_conflicts',
    'parse_quantity',
    'read_pytest',
    'read_ruff',
    'render',
    'scan_cjk_files',
    'scan_files',
    'scan_toml_values',
    'scan_widths',
    'stamp_line',
    'tracked_files',
    'trailing_token',
    'unadopted',
    'unremedied',
    'value_ratchet',
    'value_remedy',
    'verify_log',
    'waived',
    'width_ratchet',
    'width_remedy',
]
