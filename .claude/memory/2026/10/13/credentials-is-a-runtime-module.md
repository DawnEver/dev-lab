---
name: credentials-is-a-runtime-module
description: git-credential read/store promoted from dev/forgecred to runtime lab_commons.credentials so ai_lab can read API keys from it; never prompts
created: 2026-10-13
---
# lab_commons.credentials is runtime

- Promoted `credential_for` / `store_credential` / `NoCredential` out of `dev/forgecred.py` (stdlib only,
  cwd optional) so a runtime package (ai_lab) reads API keys from the same store as the forge token.
- Never prompts: GIT_TERMINAL_PROMPT=0, GCM_INTERACTIVE=never AND empty GIT_ASKPASS -- measured: VS Code's
  askpass returned a real github.com credential with the test store empty.
- Branch `feat/credentials-runtime` 5028352, unpushed.
