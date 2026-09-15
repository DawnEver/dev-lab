"""lab-commons' OWN tree obeys the units rule -- the first adopter, and the mechanism's home.

THE RULE. A name never carries a unit; the unit lives in the VALUE. `gap_mm = 12.5` teaches the
reader the unit and hands pint nothing, so every conversion downstream is a convention nobody
checks. `src/lab_commons/dev/units.py` is the scan that refuses it, and `quantity_parser` in
`lab_commons.units` is the other half -- where the unit goes instead.

WHY THIS FILE EXISTS SEPARATELY FROM THE SCANNER'S OWN TESTS. `tests/test_dev_units.py` proves the
scanner WORKS, over planted trees it builds itself. This one proves the tree it ships in is CLEAN,
which no planted fixture can say. A scanner with a green surface suite and no test over its own repo
would report a clean tree and nobody would know whether it had read one.

THE EXEMPTION SET IS THE MECHANISM'S OWN FILES, and it is two-sided on purpose. A scanner cannot
refuse a spelling while being forbidden to write it down -- the planted control in
`tests/test_dev_units.py` IS a violating name, and it has to be, or there is nothing to find. So
those files are exempt, and the exemption is CHECKED rather than trusted: an exempt file that
contains no violation is a stale exemption and the suite reds, because a waiver nothing uses is as
wrong as a missing one. That is the same instrument this family uses for suppressions and skips.
"""

from __future__ import annotations

from pathlib import Path

from lab_commons.dev.rules import tracked_files
from lab_commons.dev.units import SCANNED_SUFFIXES, scan_files

_ROOT = Path(__file__).resolve().parents[1]

#: The mechanism's own PLANTED CONTROLS: the one file that must write the forbidden spelling down,
#: because a scanner with nothing to find proves nothing. Each entry MUST contain at least one name
#: the rule forbids, which `test_every_exemption_is_used` asserts.
#:
#: `dev/units.py` and `dev/_unit_tokens.py` are deliberately NOT here, and the first draft of this
#: file listed them. They explain the rule in PROSE, and the scan reads signatures, not prose -- so
#: exempting them exempted nothing. `test_every_exemption_is_used` caught it on the first run, which
#: is the two-sided ratchet doing exactly what it exists for.
_EXEMPT = frozenset({'tests/test_dev_units.py'})

#: Non-vacuity floor, MEASURED 2026-09-15. A scan that read nothing reports no violations, and a
#: test asserting zero would be green over an empty list. The floor is a floor and not an exact
#: count -- files are added to this repo constantly and none of them should red this test.
_FLOOR_FILES = 30


def _scanned() -> tuple[str, ...]:
    """Every git-TRACKED file in the repo that the scan can read -- tracked, not merely present.

    A file that exists only in a working copy is not one the fleet has, so a verdict citing this
    scan has to be over files a second box can check out.
    """
    return tuple(
        sorted(name for name in tracked_files(_ROOT) if name.endswith(SCANNED_SUFFIXES) and name not in _EXEMPT)
    )


def test_lab_commons_names_no_unit() -> None:
    """THE RULE. Zero violations across the repo's own tracked and readable files."""
    names = _scanned()
    assert len(names) >= _FLOOR_FILES, (
        f'the scan read only {len(names)} files, below the {_FLOOR_FILES} floor. Zero violations over a '
        f'short list is not a clean repo, it is a scan that stopped reaching the tree.'
    )
    scan = scan_files([_ROOT / name for name in names], root=_ROOT)
    assert scan.files_read == len(names), (
        f'{len(names)} files were handed to the scan and it read {scan.files_read}: a file it could not '
        f'open is a file it did not check, and silently skipping one is how this goes green over a tree '
        f'it never looked at.'
    )
    assert not scan.violations, 'lab-commons names a unit; the unit belongs in the value:\n  ' + '\n  '.join(
        f'{v.path}:{v.line}: {v.name} (token {v.token!r})' for v in scan.violations
    )


def test_every_exemption_is_used() -> None:
    """The other side of the ratchet: an exemption that exempts nothing must be deleted.

    Without this, a rename that moves the planted controls elsewhere leaves the exemption behind,
    still reading as a considered decision, and the next violating name in that file goes unseen.
    """
    unused = sorted(name for name in _EXEMPT if not scan_files([_ROOT / name], root=_ROOT).violations)
    assert not unused, (
        f'these files are exempt from the units scan but contain nothing it forbids: {unused}. Delete the '
        f'exemption -- a waiver nothing uses is a hole that reads as a decision.'
    )
