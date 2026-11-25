"""A failure FINGERPRINT: a test id plus the set of concrete SUBJECTS its failure names (finding D13, 2026-11-16).

WHY. A merge judged a PR's reds against its base by test id alone, so a test already red on the base hid every
NEW subject inside it: a new oversized module inside the already-red module-size alarm went unseen until the base
turned green. A ratchet's red is a SET of subjects (module paths, ``file:line`` sites, suppression tuples); the
fingerprint compares those sets, so a subject the base does not carry is a new red even under an inherited id.

ONE SOURCE. A test names its subjects in its failure text with :func:`subject_lines` -- one
``failure-subject: <subject>`` line each, stable and machine-readable -- and :func:`subjects_of` reads them back
from whatever text the run record carries. No per-ratchet message parser exists to drift from its message.

THE JUDGMENT. :func:`new_subjects` keeps, per ``(part, node)`` red on BOTH sides, the subjects the head names and
the base does not. A node red only on the head is pass-to-fail, judged where it always was; a subject that
disappeared is a repair, never a refusal. :func:`refusal` says the new ones and the door.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Final

# lab-commons owns the prefix: the run record it writes keeps every such line of a failure, untruncated.
from lab_commons.hpc.pytest_item import SUBJECT_PREFIX

__all__ = ['SUBJECT_PREFIX', 'Fingerprints', 'new_subjects', 'refusal', 'subject_lines', 'subjects_of']

_LINE: Final = re.compile(rf'^\s*(?:E\s+)?{re.escape(SUBJECT_PREFIX.strip())}\s*(?P<subject>.+?)\s*$', re.MULTILINE)

#: ``{part: {node id: the subjects its failure names}}`` -- one commit's not-ok tests, as its records say.
Fingerprints = Mapping[str, Mapping[str, frozenset[str]]]


def subject_lines(subjects: Iterable[object]) -> str:
    """One ``failure-subject: <subject>`` line per subject, sorted -- what a failing test appends to its message."""
    return '\n'.join(f'{SUBJECT_PREFIX}{subject}' for subject in sorted({str(one) for one in subjects}))


def subjects_of(text: str) -> frozenset[str]:
    """The subjects *text* names on its ``failure-subject:`` lines (pytest's ``E`` gutter tolerated)."""
    return frozenset(found.group('subject') for found in _LINE.finditer(text))


def new_subjects(head: Fingerprints, base: Fingerprints) -> dict[tuple[str, str], frozenset[str]]:
    """``{(part, node): subjects}`` the head's failures name that the base's failures of that node do not."""
    found: dict[tuple[str, str], frozenset[str]] = {}
    for part, nodes in head.items():
        known = base.get(part, {})
        for node, subjects in nodes.items():
            if node in known and (added := subjects - known[node]):
                found[part, node] = added
    return dict(sorted(found.items()))


def refusal(new: Mapping[tuple[str, str], frozenset[str]]) -> str | None:
    """Why a PR with *new* subjects inside inherited reds is refused, naming each one and the door; else ``None``."""
    if not new:
        return None
    said = '; '.join(f'{part} {node}: {", ".join(sorted(subjects))}' for (part, node), subjects in new.items())
    return (
        f'new failure subjects inside reds the base already carries ({said}) -- an inherited test id hides no new '
        f'subject: fix each one (only an open break-glass wave admits them, on record: user ruling D18)'
    )
