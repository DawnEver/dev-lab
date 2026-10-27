"""The agent deny registry, REVIEW-STATUS-VIA-DOORS row -- pure DATA.

USER RULING 2026-10-26: a head held over the review cap is the INTEGRATOR AGENT's to review, and the release
of ``tests/review-hold`` is the RECORD that a review happened. A raw ``forge status post`` on that context
releases with no review behind it, so it is refused; the door (:mod:`dev_lab.dev.forgetakeover`) reviews the
head over every slice, posts the findings, and refuses to release without them.

The same ruling made ``tests/review`` a merge condition: its ``failure`` is an open blocking finding, cleared only
by a later round or a disposition WITH ITS REASON (:mod:`dev_lab.dev.forgereview_dispose`). A raw post on
``tests/review`` would clear it with neither, so the pattern refuses both contexts.
"""

from __future__ import annotations

from dev_lab.dev._deny_forge_rows import VENV_PYTHONS

__all__ = ['REVIEW_STATUS_VIA_DOORS']

REVIEW_STATUS_VIA_DOORS: dict[str, object] = {
    'id': 'REVIEW-STATUS-VIA-DOORS',
    'pattern': r'\bdev_lab\.dev\.forge\s+status\s+post\b(?=[^\n]*\btests/review(?:-hold)?\b)',
    'matches': 'argument',
    'hazard': 'a raw post on tests/review-hold or tests/review releases a head with no review or reason behind it.',
    'remedy': 'Release through the reviewed door: {python} -m dev_lab.dev.forge review takeover <sha> '
    '(held heads: `review held`); clear a blocking finding with `review dispose <pr> <finding-id> --why "<reason>"`.',
    'needs': None,
    'refuses': (
        'python -m dev_lab.dev.forge status post abc123 --context tests/review-hold --state success',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.forge status post abc123 --state success --context tests/review-hold',
        'python -m dev_lab.dev.forge status post abc123 --context tests/review --state success',
    ),
    'permits': (
        'python -m dev_lab.dev.forge review takeover abc123',
        'python -m dev_lab.dev.forge review dispose 7 F-0123456789ab --why "a false positive: the guard is upstream"',
        'python -m dev_lab.dev.forge status list abc123',
        'python -m dev_lab.dev.forge status post abc123 --context tests/fast --state success',
        'git commit -m "the review-hold release goes through forge review takeover"',
    ),
}
