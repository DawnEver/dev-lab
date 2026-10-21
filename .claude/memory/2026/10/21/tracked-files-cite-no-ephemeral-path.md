---
created: 2026-10-21
---
# Tracked files cite no ephemeral path, judged by git's own ignore rules

User ruling 2026-10-21: content from the output tree, temp dirs and similar never enters tracked
files, and no tracked file references them. Rule `TRACKED-CITES-NO-EPHEMERAL`
(`lab_commons.dev._rule_rows_c`), scanner `lab_commons.dev.ephemeralrefs`, full-tree body
`lab_commons.dev.famtests.ephemeralrefs`, staged check the base pre-commit row `ephemeral-refs`.

- The criterion is DERIVED: `git check-ignore --no-index --stdin -z -v`. Measured quirk: a bare `dir/`
  on stdin is answered wrongly (matched a blank ignore line), so a directory is probed as a file in it.
- A directory token whose parent holds tracked files is the ignored root itself (`output/`,
  `.claude/worktrees/`) and passes; a `<placeholder>` segment passes; `.venv/Scripts/python.exe` and
  `.venv/bin/python` are the interpreter door and pass.
- Code tier is Python only and judges only literals inside read-verb calls, not under `/` joins and
  not in a writing `open`. Docstrings are not scanned; comments are.
- Escapes: `[tool.lab_commons.ephemeral_refs]`, count == ceiling. This repo: 4 (forge.md defaults x3,
  the rendered ignore section's comment). 15 memory lines here were rewritten to shapes or
  "evidence no longer available"; measured before: 30 refusals over 766 files.
