"""The agent deny registry, REVIEW-HOLD-VIA-TAKEOVER row -- pure DATA.

USER RULING 2026-10-26: a head held over the review cap is the INTEGRATOR AGENT's to review, and the release
of ``tests/review-hold`` is the RECORD that a review happened. A raw ``forge status post`` on that context
releases with no review behind it, so it is refused; the door (:mod:`dev_lab.dev.forgetakeover`) reviews the
head over every slice, posts the findings, and refuses to release without them.
"""

from __future__ import annotations

__all__ = ['REVIEW_HOLD_VIA_TAKEOVER']

REVIEW_HOLD_VIA_TAKEOVER: dict[str, object] = {
    'id': 'REVIEW-HOLD-VIA-TAKEOVER',
    'pattern': r'\bdev_lab\.dev\.forge\s+status\s+post\b(?=[^\n]*\btests/review-hold\b)',
    'matches': 'argument',
    'hazard': 'a raw post on tests/review-hold releases an over-cap head with no review behind it.',
    'remedy': 'Run the reviewed door, which posts the findings and only then releases: '
    'python -m dev_lab.dev.forge review takeover <sha> (list held heads: forge review held).',
    'needs': None,
    'refuses': (
        'python -m dev_lab.dev.forge status post abc123 --context tests/review-hold --state success',
        '.venv/Scripts/python.exe -m dev_lab.dev.forge status post abc123 --state success --context tests/review-hold',
    ),
    'permits': (
        'python -m dev_lab.dev.forge review takeover abc123',
        'python -m dev_lab.dev.forge status list abc123',
        'python -m dev_lab.dev.forge status post abc123 --context tests/fast --state success',
        'git commit -m "the review-hold release goes through forge review takeover"',
    ),
}
