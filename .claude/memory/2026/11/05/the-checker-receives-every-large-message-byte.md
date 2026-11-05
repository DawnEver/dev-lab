---
name: the-checker-receives-every-large-message-byte
description: PR 115 review follow-up proves exact raw git-message SHA256 and byte length at the checker boundary and removes a scaffold-only control.
metadata:
  type: project
created: 2026-11-05
corrects: 2026/11/05/push-message-validation-never-puts-the-message-on-argv.md
---

# The checker receives every large message byte

PR #115 (`https://github.com/DawnEver/dev-lab/pull/115`) passed Linux's 6339 tests, security and review at `5bb2818c`, while Windows remained running. Review identified a nonblocking MEDIUM evidence gap: large bodies were present, but the judging stub logged only the subject, so a future subject-only transport could pass the test. Its LOW also identified a redundant test of the stub itself. The coordinator chose correctness over avoiding a remote rerun.

The child checker now measures the actual private file's raw SHA256 and byte count before decoding. Both large Unicode/quoted/newline messages are compared, in validation order, with raw `git log -1 --format=%B <sha>` subprocess output, without text/newline/strip normalization. Both expected bodies are explicitly above Windows' 32767-character argv ceiling and retain all 2000 repeated Unicode/quote/newline payload lines. Exact exemption, invalid ordinary commit, one-file reuse and cleanup-on-success/refusal assertions remain.

Delete the scaffold-only short-argv test. The stub still refuses any `--message` argument in the actual hook tests; no old transport branch is restored. No production hook behavior, policy, shared environment or published history changes. The earlier immutable memory entry is preserved; this dated declared correction is appended.

Only the two parameterized large-message cases, serial through the owner's measure door, plus lint/format are selected for local verification. Full remote Windows/Linux and actual integration merge evidence still belong to the coordinator; no predicted merge SHA is an adoption claim.

Evidence: the two cases passed in 20.32 s with one worker and lint/format passing; `verify: pass`, tree `sha256:d9eec82686488373`, log `sha256:782efaca745b014a1fc6e3ae0c470c242f0623650a05090ac5e5bf1075b9c221@17`. Command: `.venv/Scripts/python.exe -m dev_lab.dev.verify -- tests/test_dev_githook_scripts.py::test_large_messages_use_bounded_argv_and_one_cleaned_file_beside_exact_exemptions`. The single selected file caps automatic width at one. An earlier explicit `-n 1` run also passed both cases but correctly stayed INCONCLUSIVE because the owner's census reader does not support that forwarded option; no verdict upgrade or unrelated scope-reader change was made.
