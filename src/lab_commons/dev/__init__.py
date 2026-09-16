"""``lab_commons.dev`` — dev-time guarantees, OPT-IN and never imported by the top level.

Tier 3, and the tier boundary is a real one. ``lab_commons``'s own pyproject states its tier-1
posture in its own words -- "*Tier 1 core deps only … a consumer that wants only logging installs
nothing heavier than this*" -- so a runtime consumer must not acquire a development system by
importing the package it already had. ``lab_commons/__init__.py`` does not import this subpackage,
in the same way and for the same reason that it does not import ``lab_commons.em``: importing
``lab_commons`` never pulls this in, and a consumer opts in explicitly::

    from lab_commons.dev.verdict import Verdict

THE OPT-IN IS GATED BY THE ``dev`` EXTRA, which already exists and is the right one: it names
``pytest`` and ``ruff``, and those two ARE this subpackage's dependencies -- as executables rather
than as imports. Nothing here needs a new install, because the layer is stdlib plus tier 1:
:mod:`lab_commons.resources` (the box lock), :mod:`lab_commons.paths` (the repo root), and
``hashlib``/``importlib.metadata``. That is a measurement, not an aspiration -- ``pip install
lab-commons`` pulls nothing new, and a consumer that wants only logging still installs nothing
heavier than it did yesterday.

WHAT IS HERE, and the order is the order of dependency rather than of importance:

* :mod:`lab_commons.dev.content` — a CONTENT address over the measured paths, the half of a verdict
  that a ``HEAD``-shaped stamp cannot supply.
* :mod:`lab_commons.dev.envkey` — a key over the resolved dependency set, the other half.
* :mod:`lab_commons.dev.logref` — the log a verdict carries, and the reader that re-derives it.
* :mod:`lab_commons.dev.verdict` — the algebra: ``(tree, env, selector, result, log)``.
* :mod:`lab_commons.dev.reports` — what a verify step REPORTED, read out of the text it printed:
  pure functions over a string and an exit code, including the two-sided skip ratchet a project
  declares in its own ``[tool.lab_commons.verify] allowed_skips``.
* :mod:`lab_commons.dev.verify` — the family's ONE entry point that PRODUCES one:
  ``python -m lab_commons.dev.verify`` runs ruff, ruff format and pytest, tees them into a log
  under ``.verify/``, and prints a stamped verdict. It is the portable half of motronics-studio's
  1770-line gate runner -- the half that needs no case library, no solver and no vendor engine --
  so the three repos that had no verdict-producing invocation at all now have the same one. It is
  the ONE module here NOT re-exported below, and that is deliberate rather than an omission: it is
  run as ``__main__``, and a package that imports its own entry point makes ``runpy`` warn that the
  module was already in ``sys.modules`` before it executed. Import it by its own path.
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
  does not exist in the adopting repo is not shipped to it at all -- a refusal with no exit gets
  routed around rather than obeyed, which is the measured lesson these two modules encode.
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
