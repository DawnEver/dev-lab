---
name: push-message-validation-never-puts-the-message-on-argv
description: Windows argv-limit reproduction, file-backed Commitizen transport, exact exemptions, focused proof and downstream adoption requirements.
metadata:
  type: project
created: 2026-11-05
accessed: 2026-11-05
---

> Redacted 2026-11-09: site markers removed (public repo).

# Push message validation never puts the message on argv

## Cause and decision

Consumer `the private consumer repo` uses exact historical SHA exemptions. Its first migration push reached two valid, very large historical bodies after approximately 1800 checks and Windows refused Python's argument list. This is not a commit-format failure or an exemption failure. Fix the owner hook, not the consumer, shared environment, exemptions or history.

The canonical source is `https://github.com/DawnEver/dev-lab.git`; remote HEAD was `integrate/main` at `0fde02a30609fd854e3719d0bae06aa020278f12` when cloned. Work is isolated on the local branch `pr/cz-large-messages`, matching the intended remote ref.

The rare per-commit path now writes git's complete message to one private `mktemp` file and uses Commitizen's public `check --commit-msg-file` input. The file is overwritten for each judged commit and removed by the EXIT trap on both successful and refused validation. Message size is never argv size; no shell evaluation of message content occurs. Memory/file resources do not accumulate one body or file per commit.

Exact full-SHA/reason validation, exclusion of commits the declared base already holds, push-increment/fallback/deleted-ref/empty-range semantics, aggregate refusal and the ordinary range fast path are unchanged. This intentionally does not introduce a new parser, guessed prefix exemption, guessed commit-message ceiling, history rewrite or shelved pushgate work. Per-commit process count is unchanged; this change claims correctness, not a speedup.

## Lightweight evidence

`tests/test_dev_githook_scripts.py` adds two >32k Unicode/quoted-message controls beside an exact exemption, including an invalid ordinary commit. The judging child independently plants Windows' 32767-character argv limit on every platform. Both test success and refusal require the same single temporary file to be reused and subsequently absent. Test commit creation itself uses `git commit -F` rather than reproducing the argv bug in the fixture.

Before the hook change, both new controls failed on actual Windows `Argument list too long`. After the change, the owner measure door passed the full focused module: **28 passed in 89.36 s**, plus lint/format and hooks-installed checks; `verify: pass`, tree `sha256:1cfe9715d36839c6`, log `sha256:bbc0879d220628c747e9e7968cd4d9c0f8efa59ff2cbc097355b9b40d0e78242@17`. Command: `.venv/Scripts/python.exe -m dev_lab.dev.verify -- tests/test_dev_githook_scripts.py` in this isolated checkout. No full suite, gate, solver, SDK or shared-environment mutation.

## Publication and downstream adoption owed

The original implementation was published by the coordinator as PR #113 (`https://github.com/DawnEver/dev-lab/pull/113`). Its Linux full run at `91a0fcb7` reported 6337 passed and one failure: its memory lacked the owner's required `name`/`description` frontmatter. Memory is immutable even for a frontmatter repair, so the coordinator approved a clean replacement branch `pr/cz-large-messages-declared` from the exact same integration base. This branch adds the record correctly on its first commit; the original published ref/history and staged repair are preserved. No guard exception, bypass or history rewrite is introduced. The review's nonblocking LOW is also addressed: the judging fixture explicitly refuses even short `--message` arguments and its docstring describes the file/range inputs.

Replacement lightweight measurement: **31 passed in 63.24 s**, with lint/format and installed hooks passing, selection `tests/test_dev_githook_scripts.py tests/test_arch_memory_lives_in_a_dated_directory.py`; `verify: pass`, tree `sha256:9251e747985e52af`, log `sha256:080e66ae5b54179bdbb570911e8a7c380b9ab9c7dd3688cd8f4e53ccffab4b4f@17`. Its own environment was bootstrapped through `dev_lab.dev.dep`; no shared consumer environment moved.

Subagent does not push or open PRs. Coordinator publishes this exact local `pr/` ref through `dev_lab.dev.netverb`, then reads forge review/status and uses the canonical integration process. No remote ref or review status is claimed before that publication.

Consumer still pins `82ea2a01f952598fa7751765919faf3e767cc463`. Preserve the single bare canonical requirement and lock-only pin: once the fix is available through canonical integration HEAD, use the network door to run `uv lock --upgrade-package dev-lab --refresh-package dev-lab`, verify the resulting lock SHA actually contains this fix, then commit the consumer lock. Do not adopt the currently unfixed canonical tip or a nonexistent remote commit. Do not synchronize the consumer's shared `.venv` until its coordinator confirms no imports/hooks are running; the separate dependency door owns that synchronization.
