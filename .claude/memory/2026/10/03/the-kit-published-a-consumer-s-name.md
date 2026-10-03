---
name: the-kit-published-a-consumer-s-name
description: A commit carried a consumer's repository name and its process name into this published repo, past a guard that exists for exactly that. The same commit also shipped a stale module floor and undeclared suppressions, because the suite was never run before pushing.
metadata:
  type: project
created: 2026-10-03
accessed: 2026-10-03
---

# The kit published a consumer's name

This repo is published, and `tests/_private_markers.py` guards that on purpose: a tracked file may not
name a machine, a person, a home path, a chat id **or a private repository**. The denylist that names
the private values themselves is device-local and never committed, so the scan can refuse a value it
does not spell.

A commit adding the supervision subpackage carried **21 occurrences** of a consumer's repository name
and its process name, in docstring examples and in test fixtures. `git grep` at that commit's parent
returns nothing: the name had been removed before and was reintroduced here.

## The name was never needed

The examples wanted a generic deployed service. `webapp` says that. The consumer's name said it too,
and also published which private repository this kit is developed against — which is what the guard
is for, and which is why the fix was a substitution rather than a waiver.

## One CJK character, same shape

A docstring quoted a Chinese phrase from an earlier note instead of translating it.
`test_dev_cjk` refuses non-ASCII in tracked source and offers the two honest routes: translate
faithfully, or write the character as a `\uXXXX` escape when the value itself is what is being
tested. The phrase was prose, so it was translated.

## Worse than the leak: the commit was never verified

The same commit landed **twelve modules without re-taking `MODULE_FLOOR`** (the counted population
went to 149 against a ceiling of 140) and **without declaring five suppressions** the new package
carries. Both are guards this repo runs on every module. They failed, and were pushed anyway.

The reason is not interesting — the full suite was not run before pushing — but the shape is worth
recording, because it is the same shape as the leak: **three separate guards said no, and the commit
went out because nobody asked them.** A lane that has a 2,600-test suite and pushes without running it
has the suite for a reason it is not using.

Two lessons, and the second is the durable one:

1. Run the whole suite, not the tests for the directory that changed. Every one of these three
   failures was in a file this lane did not touch.
2. `source_modules()` walks **tracked** files. A guard cannot see an untracked package, so a new
   subpackage is invisible to every census until the moment it is committed — and it becomes visible
   **in the same commit that must also carry the re-measurement.** The reading and the thing it
   measures arrive together or not at all.

The repair moved the floor to 119 with the headroom unchanged at 45, declared the suppressions with
their reasons, and substituted a neutral example name. The published history still carries the name;
the decision on that was the repository owner's, and it was to keep the fix and leave the history.
