# Push message validation never puts the message on argv

## Cause and decision

Consumer `motronics-studio` uses exact historical SHA exemptions. Its first migration push reached two valid, very large historical bodies after approximately 1800 checks and Windows refused Python's argument list. This is not a commit-format failure or an exemption failure. Fix the owner hook, not the consumer, shared environment, exemptions or history.

The canonical source is `https://github.com/DawnEver/dev-lab.git`; remote HEAD was `integrate/main` at `0fde02a30609fd854e3719d0bae06aa020278f12` when cloned. Work is isolated on the local branch `pr/cz-large-messages`, matching the intended remote ref.

The rare per-commit path now writes git's complete message to one private `mktemp` file and uses Commitizen's public `check --commit-msg-file` input. The file is overwritten for each judged commit and removed by the EXIT trap on both successful and refused validation. Message size is never argv size; no shell evaluation of message content occurs. Memory/file resources do not accumulate one body or file per commit.

Exact full-SHA/reason validation, exclusion of commits the declared base already holds, push-increment/fallback/deleted-ref/empty-range semantics, aggregate refusal and the ordinary range fast path are unchanged. This intentionally does not introduce a new parser, guessed prefix exemption, guessed commit-message ceiling, history rewrite or shelved pushgate work. Per-commit process count is unchanged; this change claims correctness, not a speedup.

## Lightweight evidence

`tests/test_dev_githook_scripts.py` adds two >32k Unicode/quoted-message controls beside an exact exemption, including an invalid ordinary commit. The judging child independently plants Windows' 32767-character argv limit on every platform. Both test success and refusal require the same single temporary file to be reused and subsequently absent. Test commit creation itself uses `git commit -F` rather than reproducing the argv bug in the fixture.

Before the hook change, both new controls failed on actual Windows `Argument list too long`. After the change, the owner measure door passed the full focused module: **28 passed in 89.36 s**, plus lint/format and hooks-installed checks; `verify: pass`, tree `sha256:1cfe9715d36839c6`, log `sha256:bbc0879d220628c747e9e7968cd4d9c0f8efa59ff2cbc097355b9b40d0e78242@17`. Command: `.venv/Scripts/python.exe -m dev_lab.dev.verify -- tests/test_dev_githook_scripts.py` in this isolated checkout. No full suite, gate, solver, SDK or shared-environment mutation.

## Publication and downstream adoption owed

Subagent does not push or open PRs. Coordinator publishes this exact local `pr/` ref through `dev_lab.dev.netverb`, then reads forge review/status and uses the canonical integration process. No remote ref or review status is claimed before that publication.

Consumer still pins `82ea2a01f952598fa7751765919faf3e767cc463`. Preserve the single bare canonical requirement and lock-only pin: once the fix is available through canonical integration HEAD, use the network door to run `uv lock --upgrade-package dev-lab --refresh-package dev-lab`, verify the resulting lock SHA actually contains this fix, then commit the consumer lock. Do not adopt the currently unfixed canonical tip or a nonexistent remote commit. Do not synchronize the consumer's shared `.venv` until its coordinator confirms no imports/hooks are running; the separate dependency door owns that synchronization.
