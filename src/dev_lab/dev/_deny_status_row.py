"""The agent deny registry, STATUS-VIA-DOORS row -- pure DATA.

USER RULING 2026-10-26: a head held over the review cap is the INTEGRATOR AGENT's to review, and the release
of ``tests/review-hold`` is the RECORD that a review happened. A raw ``forge status post`` on that context
releases with no review behind it, so it is refused; the door (:mod:`dev_lab.dev.forgetakeover`) reviews the
head over every slice, posts the findings, and refuses to release without them.

The same ruling made ``tests/review`` a merge condition: its ``failure`` is an open blocking finding, cleared only
by a later round or a disposition WITH ITS REASON (:mod:`dev_lab.dev.forgereview_dispose`). A raw post on
``tests/review`` would clear it with neither, so the pattern refuses both contexts.

``tests/security`` is a merge condition too: its ``success`` is posted by the serve step, or -- for a head whose
own new exemptions cover its findings -- by the release door, which RECORDS its host, reason and exemption delta
(:mod:`dev_lab.dev.forgesecurity`). A raw post would release with none, so the pattern refuses it as well.

It guards a security context as well as the review ones, so its name says STATUS alone; its earlier ids are
registered in ``RETIRED_IDS`` (:mod:`dev_lab.dev._deny_rows`).
"""

from __future__ import annotations

from dev_lab.dev._deny_forge_rows import VENV_PYTHONS

__all__ = ['STATUS_VIA_DOORS']

STATUS_VIA_DOORS: dict[str, object] = {
    'id': 'STATUS-VIA-DOORS',
    'pattern': r'\bdev_lab\.dev\.forge\s+status\s+post\b(?=[^\n]*\btests/(?:review(?:-hold)?|security)\b)',
    'matches': 'argument',
    'hazard': 'a raw post on tests/review-hold, tests/review or tests/security releases a head with no review or '
    'reason behind it.',
    'remedy': 'Use the door that records why: {python} -m dev_lab.dev.forge review takeover <sha>; '
    'forge review dispose <pr> <finding-id> --why "<reason>"; forge security release <pr> --why "<reason>".',
    'needs': None,
    'refuses': (
        'python -m dev_lab.dev.forge status post abc123 --context tests/review-hold --state success',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.forge status post abc123 --state success --context tests/review-hold',
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
