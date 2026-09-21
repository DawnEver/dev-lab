---
name: four-bodies-the-kit-owed-its-consumers
description: A lane audited all seven famtests bodies as adopted by wdg-lab and optimi-lab, found the adoption itself correct and four places where a consumer still had to hand-write an assertion the kit publishes no body for, plus one count pin whose own message claimed to name its members. All five are closed here, and ONE of the closes is a breaking signature change that reds both consumer repos until they pass the new argument.
metadata:
  type: project
created: 2026-09-21
accessed: 2026-09-21
---

# The adoption was done; the kit still owed four bodies

Measured 2026-09-21 by an audit lane over `wdg-lab` and `optimi-lab`: every consumer file is a thin
body passing keyword arguments, no forks remain, `FLOOR-ON-EVERY-SCAN` and `PLANTED-CONTROL` are
intact everywhere. What the audit found instead is the shape one layer in -- **the kit never
published a body for the thing both consumers were writing by hand**, so the duplication that the
`famtests` package exists to remove had simply moved from seven bodies to four.

The rule underneath, and it is the one to carry forward: *a consumer that has to hand-write an
assertion because the kit publishes none is the gap.* Not a fork yet -- the two copies were
byte-identical when found -- but byte-identical in two repos is the state a fork starts from, and
this family has already paid for that once.

## What was closed

| gap | body published | consumer file it lets shrink |
|---|---|---|
| `untimedwaits` stated the exemption obligation and published no assertion for it, while its sibling `citedtests` published `assert_every_exemption_is_real` | `untimedwaits.assert_every_exemption_is_real(root, *, exempt)` + `VacuousExemption` | both labs' `test_every_blocking_wait_declares_a_ceiling.py`, 6 identical lines each |
| `assert_the_source_is_itself_clean()` resolved `Path(__file__)` INSIDE the kit, so the consumer file's own half was uncovered | the body now takes `*, also: Collection[Path]` -- **required, no default** | both labs' `test_no_cjk_in_tracked_source.py`, 2 lines each |
| `assert_widths_are_the_named_set` merely FLOORED `files_read`, and `WidthScan.undecodable` was declared and read by no assertion anywhere | `injectedwidth.assert_every_document_handed_in_was_read(scan, *, handed)` + `UnreadDocument` | optimi-lab's `test_the_scan_reads_every_doc_handed_to_it` |
| `len(BLAS_THREAD_VARS) >= 4` under the message *"by name rather than by count"* | `boundedremedy.assert_the_pool_vars_are_the_named_set()` | both labs' `test_a_bounded_wait_names_its_remedy.py`, 1 line each |

`countpins` explicitly permits a NUMBER as a THRESHOLD, so every other numeric assertion in those
two consumer files -- the floors, the headrooms, the escape-hatch ceilings -- was left alone. Only
the one whose own message claimed to name its members was a defect.

## The one breaking change, said plainly

`assert_the_source_is_itself_clean` gains a REQUIRED keyword argument. Both consumer repos call it
with no argument today, so both will raise `TypeError` at that line until their lanes pass
`also=(Path(__file__),)`. That is deliberate rather than careless: the whole gap was that the
consumer's own half was unwritten, and an optional argument is one a consumer can adopt the body
WITHOUT closing the gap -- which is the state this lane was dispatched to end. The family's rule is
that every repo-shaped fact arrives as a keyword argument with NO DEFAULT, and "which file is mine"
is the most repo-shaped fact there is.

The property also TIGHTENED: the kit module was checked against `cjk.find_cjk` (the shared ranges)
and is now checked with `.isascii()`, which is what both consumers were asserting about their own
files. Strictly stronger, and no live file in the kit carried a non-ASCII character, so the
tightening cost nothing. When a body's subject grows, say so where the body is -- a reader who
finds an argument they did not have yesterday deserves to know it also got stricter.

## A pin against the kit's own constant is still a pin

`assert_the_pool_vars_are_the_named_set` compares `BLAS_THREAD_VARS` to a declared frozenset of four
runtime names. The obvious objection is that this pins a constant against itself. It does not: the
four names are now written down twice -- once where the environment is built, once in the assertion
-- and neither may move without the other. Nothing in the tree DERIVES the set, because the runtimes
behind it are native libraries whose honouring of a variable name is not observable in-process, so
a derivation would have been an invention wearing a measurement's clothes. The equality buys exactly
the thing the count could not: a one-for-one swap of a real runtime for a name that does not exist
is an edit a `>= 4` assertion reads as UNCHANGED, and both plants are asserted in the kit's controls
rather than argued in a docstring.

## Environment trap, measured here

`make verify` from lab-commons with the ambient `python` runs
`D:\Documents\MingyangBao\motronics-studio\.venv\Scripts\python.exe` and imports
`motronics-studio\.venv\Lib\site-packages\lab_commons\` -- a FROZEN INSTALLED COPY, not the working
tree. `make adoption` done that way reported 5 passed against code that had not changed. Prefix the
invocation with lab-commons' own `.venv/Scripts` (or call
`.venv/Scripts/python.exe -m lab_commons.dev.verify` directly) or every verdict this repo produces
is about somebody else's tree.
