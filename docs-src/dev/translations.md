# Translations

No tracked file may contain a CJK character (`NO-CJK-IN-TRACKED-SOURCE`), with one named exception: a
translation `<stem>.zh.md` beside its English `<stem>.md`. Write or change the English page first, then put the
translation beside it in the same commit. The English page is the source of truth.

## The rule

- Exempt everywhere: `.claude/memory/` and `attic/` at any depth, and `archived/` at the repo root only.
- A `<stem>.zh.md` is exempt **only while `<stem>.md` is tracked beside it**. An orphaned translation is scanned
  like any other file, and the `TRANSLATION-HAS-ITS-SOURCE` refusal names the English page to add.

## Where it is implemented

- `lab_commons.dev.cjk`: `TRANSLATION_SUFFIXES`, `translation_source`, `translation_exempted`,
  `orphaned_translations`. `scan_files` treats the paths it is handed as the corpus.
- `lab_commons.dev.famtests.trackedcjk.assert_every_translation_has_its_source`: each repo calls it from its own
  architecture suite over its tracked corpus.

## Adding or updating a translation

1. Write or change the English page.
2. Put the translation beside it as `<stem>.zh.md`; link it from the index as secondary.
3. When the English page changes, update the translation in the same commit or mark it stale at its top. The
   guard checks that the source exists, not that the two agree.
4. Never put CJK anywhere else. A CJK value a program must send or compare verbatim is written as `\uXXXX`
   escapes, so the source stays ASCII.

## The goal: no non-ASCII at all

- `lab_commons.dev.cjk.scan_non_ascii` applies the same exemptions to every non-ASCII character, and
  `non_ascii_distance` reports how far a repo is from zero. `famtests.trackedcjk.assert_no_tracked_non_ascii` is
  the goal test a repo wires, failing on purpose until the distance is zero.
