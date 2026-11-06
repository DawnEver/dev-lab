---
name: credential-preservation-keeps-the-current-network-budget-contract
description: Resolve the current integration import conflict without losing credential preservation or network deadline propagation.
metadata:
  type: project
---

# Credential preservation keeps the current network budget contract

PR 237 was actually pushed and opened ready. Its initial watch reported green
for the three posted checks, but the API still reported mergeable=false,
mergeable_state=dirty, merged=false. Those checks are not proof of a merge.
Fetch confirmed integration advanced from 432496c6 to 43f7019a.

Merge that actual integration into the repair branch, retaining both the
typed CredentialRefresh import and the new BudgetSpent propagation. This
was the only conflicted file. Do not drop either lower-level capability.

The first selection mistyped two architecture paths: zero collected and an
inconclusive result, not a pass. A correct six-file selection initially could
not fit the box allocation. No worker was restarted while live and no capacity
was fabricated. Retrying the official door with a 180-second wait budget ran
the actual six files: **153 passed in 27.49 s**. This includes preservation,
forge credential/client, public surface, one launch door, and network retries
and deadlines. Log sha256:ffecf806d94327f973a9155600cc30982bd3db99dff43d2bc977c81bbc8b7e28@19.
No real credential rejection, account change or restoration occurred.
