# Translations — a second language without breaking the CJK guard

- How a document is offered in a second language without breaking `NO-CJK-IN-TRACKED-SOURCE`. The rule statement is the registry row in `lab_commons.dev.rules`; this page is how the mechanism behind it works.

## The rule (user directive 2026-09-23)

- Every tracked file is refused a CJK character. The exemptions are `.claude/memory/` and `attic/` at any depth, `archived/` at the **repo root only**, and one NAME: a translation.
- A translation is a file named `<stem>.zh.md`. It is exempt **only while its English source `<stem>.md` is tracked beside it**, in the same directory. The English page is the source of truth; the translation is a rendering of it.
- An **orphaned** translation — a `<stem>.zh.md` with no `<stem>.md` — is not exempt. The CJK scan reads it like any other file, and the `TRANSLATION-HAS-ITS-SOURCE` refusal names it, telling you which English page to add (or restore). A translation with no source is simply non-English documentation under a different suffix.

## Where it is implemented

- `lab_commons.dev.cjk`: `TRANSLATION_SUFFIXES`, `translation_source`, `translation_exempted`, `orphaned_translations`. `scan_files` treats the paths it is handed as the corpus, so a translation is exempted only when its source is among them.
- `lab_commons.dev.famtests.trackedcjk.assert_every_translation_has_its_source`: the verdict. Each adopting repo calls it from its own architecture suite over its own tracked corpus.

## How to add or update a translation

1. Write or change the English page first.
2. Put the translation beside it as `<stem>.zh.md`. Link it from the index as a secondary page and say the English page is authoritative.
3. When the English page changes, update the translation in the same commit or mark it stale at its top; the guard checks that the source EXISTS, not that the two still agree — a guard cannot read prose.
4. Never put CJK anywhere else: code, comments, docstrings, TOML and ordinary docs are English. A CJK value a program must send or compare verbatim (a vendor's UI name, a quoted string a test asserts) is written as `\uXXXX` escapes, so the source is ASCII while the runtime value stays byte-identical.

## The final goal: no non-ASCII at all

- `lab_commons.dev.cjk.scan_non_ascii` applies the same exemptions to EVERY non-ASCII character, and `non_ascii_distance` reports the distance: total characters, file count, the breakdown by character class, and the top offending files. `famtests.trackedcjk.assert_no_tracked_non_ascii` is the verdict a repo wires as its goal test, failing on purpose until the distance is zero.
