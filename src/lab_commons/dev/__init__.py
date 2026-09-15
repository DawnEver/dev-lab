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
* :mod:`lab_commons.dev.boxlock` — one CPU-saturating run at a time, ON the broker that already
  ships in this package rather than beside it.
* :mod:`lab_commons.dev.profile` — ``RepoProfile``, so attaching a repo is a substitution -- with
  one measured caveat recorded in its docstring: ``resolve_home``'s auto-detection anchors on its
  own file, so a profile carries an ``anchor`` for the checkout it describes.

WHAT IS DELIBERATELY NOT HERE YET: the five architecture mechanisms (public-surface declaration,
suppression ratchet, module-size alarm, enforced-mechanism registry, duplication ratchet). They take
a ``RepoProfile`` and are the next layer; this one is the verdict, because nothing else in the
shared kit is VERIFIABLE until a run can be told from a run that proved nothing.
"""

from lab_commons.dev.boxlock import BOX_POOL, BoxLock
from lab_commons.dev.content import ABSENT, DEFAULT_IGNORES, content_address, file_digest
from lab_commons.dev.envkey import UNREADABLE, env_key, env_manifest, interpreter_identity
from lab_commons.dev.logref import MARKER, Citation, LogRef, UnverifiableLog, verify_log
from lab_commons.dev.profile import NotACheckout, RepoProfile
from lab_commons.dev.verdict import IncompleteRun, Outcome, Proof, Result, Selector, Verdict

__all__ = [
    'ABSENT',
    'BOX_POOL',
    'DEFAULT_IGNORES',
    'MARKER',
    'UNREADABLE',
    'BoxLock',
    'Citation',
    'IncompleteRun',
    'LogRef',
    'NotACheckout',
    'Outcome',
    'Proof',
    'RepoProfile',
    'Result',
    'Selector',
    'UnverifiableLog',
    'Verdict',
    'content_address',
    'env_key',
    'env_manifest',
    'file_digest',
    'interpreter_identity',
    'verify_log',
]
