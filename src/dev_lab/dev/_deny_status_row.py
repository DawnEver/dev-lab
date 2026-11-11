"""The agent deny registry, STATUS-VIA-DOORS row -- pure DATA.

The release of ``tests/review-hold`` is the RECORD that the forge reviewed the head: only the forge's own round
releases it (D11). A raw ``forge status post`` on that context releases with no review behind it, so it is
refused -- and a session's post never counts anyway, since the gate reads the status's forge-recorded creator.

``tests/review`` is a merge condition too: its ``failure`` is an open security finding, cleared only by the forge's
review run again once it is fixed (``forge review again <pr>``). A raw post on ``tests/review`` would clear it with
no review behind it, so the pattern refuses both contexts.

``tests/security`` is a merge condition too: its ``success`` is posted by the serve step, or -- for a head whose
own new exemptions cover its findings -- by the release door, which RECORDS its host, reason and exemption delta
(:mod:`dev_lab.dev.forgesecurity`). A raw post would release with none, so the pattern refuses it as well.

It guards a security context as well as the review ones, so its name says STATUS alone; its earlier ids are
registered in the retired registry (:func:`dev_lab.dev._deny_rows.retired_row`).
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
    'remedy': "Use the door that records why: re-run the forge's review of the head, "
    '{python} -m dev_lab.dev.forge review again <pr>; or forge security release <pr> --why "<reason>".',
    'needs': None,
    'refuses': (
        'python -m dev_lab.dev.forge status post abc123 --context tests/review-hold --state success',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.forge status post abc123 --state success --context tests/review-hold',
        'python -m dev_lab.dev.forge status post abc123 --context tests/review --state success',
        'python -m dev_lab.dev.forge status post abc123 --context tests/security --state success',
    ),
    'permits': (
        'python -m dev_lab.dev.forge review takeover abc123',
        'python -m dev_lab.dev.forge review again 7',
        'python -m dev_lab.dev.forge security release 7 --why "seeded study samples, never a key"',
        'python -m dev_lab.dev.forge status list abc123',
        'python -m dev_lab.dev.forge status post abc123 --context tests/fast --state success',
        'git commit -m "the review-hold release goes through forge review takeover"',
    ),
}
