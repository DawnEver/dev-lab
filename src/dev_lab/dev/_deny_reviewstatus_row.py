"""The agent deny registry, REVIEW-STATUS-VIA-DOORS row -- pure DATA.

USER RULING 2026-10-26: a head held over the review cap is the INTEGRATOR AGENT's to review, and the release
of ``tests/review-hold`` is the RECORD that a review happened. A raw ``forge status post`` on that context
releases with no review behind it, so it is refused; the door (:mod:`dev_lab.dev.forgetakeover`) reviews the
head over every slice, posts the findings, and refuses to release without them.

The same ruling made ``tests/review`` a merge condition: its ``failure`` is an open blocking finding, cleared only
by a later round or a disposition WITH ITS REASON (:mod:`dev_lab.dev.forgereview_dispose`). A raw post on
``tests/review`` would clear it with neither, so the pattern refuses both contexts.

``tests/security`` is a merge condition too: its ``success`` is posted by the serve step, or -- for a head whose
own new exemptions cover its findings -- by the integrator's release WITH ITS REASON and the exemption delta
(:mod:`dev_lab.dev.forgesecurity`). A raw post would release with neither, so the pattern refuses it as well.
"""

from __future__ import annotations

__all__ = ['REVIEW_STATUS_VIA_DOORS']

REVIEW_STATUS_VIA_DOORS: dict[str, object] = {
    'id': 'REVIEW-STATUS-VIA-DOORS',
    'pattern': r'\bdev_lab\.dev\.forge\s+status\s+post\b(?=[^\n]*\btests/(?:review(?:-hold)?|security)\b)',
    'matches': 'argument',
    'hazard': 'a raw post on tests/review-hold, tests/review or tests/security releases a head with no review or '
    'reason behind it.',
    'remedy': 'Run the reviewed door, which posts the findings and only then releases: '
    '{python} -m dev_lab.dev.forge review takeover <sha> (list held heads: {python} -m dev_lab.dev.forge review '
    'held); for a blocking '
    'finding, {python} -m dev_lab.dev.forge review dispose <pr> <finding-id> --why "<reason>"; for a head clean '
    'only under its own new security exemptions, {python} -m dev_lab.dev.forge security release <pr> --why "<reason>".',
    'needs': None,
    'refuses': (
        'python -m dev_lab.dev.forge status post abc123 --context tests/review-hold --state success',
        '.venv/Scripts/python.exe -m dev_lab.dev.forge status post abc123 --state success --context tests/review-hold',
        'python -m dev_lab.dev.forge status post abc123 --context tests/review --state success',
        'python -m dev_lab.dev.forge status post abc123 --context tests/security --state success',
    ),
    'permits': (
        'python -m dev_lab.dev.forge review takeover abc123',
        'python -m dev_lab.dev.forge review dispose 7 F-0123456789ab --why "a false positive: the guard is upstream"',
        'python -m dev_lab.dev.forge security release 7 --why "seeded study samples, never a key"',
        'python -m dev_lab.dev.forge status list abc123',
        'python -m dev_lab.dev.forge status post abc123 --context tests/fast --state success',
        'git commit -m "the review-hold release goes through forge review takeover"',
    ),
}
