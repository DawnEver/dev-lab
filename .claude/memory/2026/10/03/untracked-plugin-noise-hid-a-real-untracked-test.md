---
name: untracked-plugin-noise-hid-a-real-untracked-test
description: tests/test_supervise_transport.py shipped the transport fix without ever being added to git, and it sat in `git status` beside six pieces of rem-plugin bookkeeping that the generated index already declares device-local. The noise is what kept it invisible; the ignore patterns went in .git/info/exclude, not .gitignore, because the ignore list is a measured census.
created: 2026-10-03
accessed: 2026-10-03
---

# Untracked plugin noise hid a real untracked test (2026-10-03)

`src/lab_commons/supervise/transport.py` was written to fix the scheme defect and its test was
written beside it. The module was committed; **the test was not.** `tests/test_supervise_transport.py`
sat untracked — no round trip over a real server, no `split_url` refusal, no `https_only` refusal in
the published tree — while the fix it covers was in `src/`.

## Why nobody saw it

`git status` in this repo printed eight lines, and seven of them were the rem plugin's own
bookkeeping: `.claude/rules/MEMORY.md` (which declares itself gitignored in its own generated header
and was not), `.claude/meta/`, five `_meta.json` files, and `.claude/worktrees/`. A real source file
in that list reads exactly like the noise around it.

## Where the fix went

**Not `.gitignore`.** That file here is a MEASURED artefact: `test_the_kit_declines_the_gitignore_base`
ratchets its pattern count in both directions and quotes the number in its own docstring. Four more
lines would have to be re-measured into that census — and the quoted numbers would move — to say what
a per-checkout exclude file says for free.

They went into `.git/info/exclude`, which is device-local by construction and read by no census. The
comment there records why, because the next reader will otherwise "tidy" them into `.gitignore` and
break a guard about a file that has nothing to do with them.

**The general shape: an untracked file is not visible until the list it hides in is empty.**
