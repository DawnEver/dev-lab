---
name: the-user-gives-the-consent-code-and-the-agent-runs-it
description: "USER RULING 2026-11-08: the user supplies the consent/TOTP code, the agent runs the grant with it; CONSENT-CODE-NEVER-TYPED retired for CONSENT-CODE-FROM-THE-USER"
metadata:
  type: project
---

> Redacted 2026-11-09: site markers removed (public repo).

# The user gives the consent code; the agent runs the command with it

- USER RULING 2026-11-08: "注意 永远只能用户提供 TOTP code 你去执行！" then "请你机制性系统性清理全部误解！"
- The 2026-11-07 design read "an agent never types a code; the user runs `consent grant` in their own terminal".
  That was a misreading. Integrator sessions on 11-08 refused two user-given codes and kept asking the user to run
  commands, and the installed grant refused a third because it read only from a tty.
- Now: `consent grant <request.json> --code <code>` (or the code on stdin; a terminal still gets the no-echo
  prompt). The code is checked to be six digits before it is sent and is never echoed, logged or kept.
- The deny row is CONSENT-CODE-FROM-THE-USER (old id in `_deny_rows.RETIRED_IDS`). It refuses only a planted
  credential: a shell write under `~/.the private consumer/state/consent/`. The Write/Edit half is `consentguard.refuse_write`.
- The code's origin is the rule an agent keeps: only a code the user gave in this conversation, used at once.
