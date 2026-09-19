"""THE LIVE READING over this package: every foreign datum is either gone or NAMED.

This repo is the family's leaf. Its README's tier-1 rule -- "contains no concept from any single
project's domain" -- and `.claude/rules/statement-and-mechanism.md` -- "it never grades another
repo: an adopter supplies its own mechanisms through `Adoption`" -- were both being read on every
turn while the `dev` layer absorbed a consumer's rows and a consumer's tree paths as shipped source.
Prose did not hold the line. This does.

WHAT IT CAN AND CANNOT SAY. It refuses anything NEW, and it refuses a waiver that has outlived its
row. It does not refuse what is already here: the consumers cannot be edited from this pass and a
row a consumer still reads may not be deleted to make a scan green. Every such row is a handle in
`_foreign_rows.EVICTED` carrying the reason its deletion is elsewhere -- which is the eviction
ORDER, published as data, so the later deletion is mechanical.

The planted controls are in `test_dev_foreign.py`, where each refusal is driven through the real arm
against a real temporary tree. This file is only the reading.
"""

from __future__ import annotations

from _arch_corpus import ROOT

from lab_commons.dev._foreign_rows import EVICTED, PROSE_CEILING, SCAN_FLOOR, SELF, SIBLINGS, SYNTHETIC
from lab_commons.dev.foreign import (
    DATA,
    PATH,
    PROSE,
    assert_no_foreign_data,
    assert_prose_is_falling,
    kinds,
    modules_read,
    scan,
)

SOURCE = ROOT / 'src' / 'lab_commons'


def test_every_foreign_datum_is_gone_or_evicted_by_design() -> None:
    """THE CHECK, both sides: nothing unwaived arrives, and no waiver outlives its row."""
    findings = scan(SOURCE, repo_root=ROOT, siblings=SIBLINGS, exclude=SELF)
    judged = kinds(findings, DATA) + kinds(findings, PATH)
    assert_no_foreign_data(
        judged,
        evicted=EVICTED,
        synthetic=SYNTHETIC,
        read=modules_read(SOURCE, SELF, ROOT),
        floor=SCAN_FLOOR,
    )


def test_the_prose_half_may_only_fall() -> None:
    """A docstring naming where a finding came from is EVIDENCE, so it is ceilinged, not evicted."""
    findings = scan(SOURCE, repo_root=ROOT, siblings=SIBLINGS, exclude=SELF)
    assert_prose_is_falling(len(kinds(findings, PROSE)), ceiling=PROSE_CEILING)


def test_the_registry_that_names_the_siblings_is_the_only_module_excluded() -> None:
    """The exclusion is itself a claim, so it is pinned rather than left to a reader."""
    assert SELF == ('src/lab_commons/dev/_foreign_rows.py',)
