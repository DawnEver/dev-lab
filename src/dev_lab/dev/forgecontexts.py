"""THE STATUS CONTEXTS under ``tests/``: every part's prefix, and the contexts that are never a part.

A part is ``tests/<need-set>`` (:mod:`dev_lab.dev.platformparts`). The review, its hold and the security check
post under the same prefix so they read beside the parts on the forge, and :data:`NOT_PARTS` is the one list
:func:`dev_lab.dev.platformparts.parts_of` skips. Re-exported by :mod:`dev_lab.dev.platformparts`.
"""

from __future__ import annotations

from typing import Final

__all__ = ['CONTEXT_PREFIX', 'HOLD_CONTEXT', 'MERGE_READY_CONTEXT', 'NOT_PARTS', 'REVIEW_CONTEXT', 'SECURITY_CONTEXT']

#: Every part's status context starts with this; the rest is the part's name (its need-set).
CONTEXT_PREFIX: Final = 'tests/'

#: The review's context (:mod:`dev_lab.dev.forgereview`): under the prefix so it reads beside the parts, and never a
#: part -- :data:`NOT_PARTS` holds it, so no promotion waits on it; every merge requires it ``success``
#: (:func:`dev_lab.dev.reviewgate.review_missing`).
REVIEW_CONTEXT: Final = f'{CONTEXT_PREFIX}review'

#: The review HOLD's context: posted ``pending`` on a head whose review could not run, released by a ``success`` a
#: session posts once it reviewed the head. Never a part; the merge reads it together with :data:`REVIEW_CONTEXT`
#: (:func:`dev_lab.dev.reviewgate.review_missing`), so an unreviewable head is never skipped into an auto-merge.
HOLD_CONTEXT: Final = f'{CONTEXT_PREFIX}review-hold'

#: The SECURITY check's context (:mod:`dev_lab.dev.forgesecurity`): one status per head posted by a serve step,
#: never a part -- :data:`NOT_PARTS` holds it; the merge waits on it through
#: :func:`dev_lab.dev.forgesecurity.security_wait`.
SECURITY_CONTEXT: Final = f'{CONTEXT_PREFIX}security'

#: The MERGE DECISION's context (:func:`dev_lab.dev.forgemerge.ready`): ONE status per head, ``success`` when the PR
#: may merge, else ``failure`` naming what is missing. A workflow job posts it on GitHub, where native auto-merge waits
#: on it as a required check; never a part.
MERGE_READY_CONTEXT: Final = f'{CONTEXT_PREFIX}merge-ready'

#: The contexts under the prefix that are never a part.
NOT_PARTS: Final = frozenset({REVIEW_CONTEXT, HOLD_CONTEXT, SECURITY_CONTEXT, MERGE_READY_CONTEXT})
