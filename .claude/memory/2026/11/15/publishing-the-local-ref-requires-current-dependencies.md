---
name: Publishing the local ref requires current dependencies
description: Supported sync after refspec and dependency-currentness refusals, with tests-first semantics unchanged.
metadata:
  type: project
---

Publishing tests-first `1e17c00df2906349ca6e4aa1031e9ba3a970ed9a` was
refused by the normal pre-push hook. The local branch already existed and was
correct: `pr/family-layout-runs-in-every-part-1115`. The specific
PUBLISH-IS-THE-LOCAL-REF refusal concerned using a SHA refspec instead of that
local branch name; it was not evidence of a missing branch. A separate
currentness refusal found lab-commons 24 commits behind its allowed limit 20.
Nothing was published or dispatched from that failed attempt.

The supported remedy ran `dep --root . --sync --dry-run`, then normal
`forge sync`. Sync terminated successfully, normally merged the current
integration branch as `384d597a` and committed its official relock as
`1c2c6ec649c146c07519fc38346912084be9b18a`. Lab-commons moved from
`50a4034228fc19df80ea2640b6998d5addddb613` to
`b088c1c226c5739a2445fc2ff0b95aae0159ecb4`; environment identity moved
from `cc01d403bbc2929f` to `1c526dcde1d8988c`.

All four execution test owners are byte-identical to the 1e17 checkpoint.
No layout production implementation or engine stub was added. Earlier RED
receipts retain their historical source/environment identities; sync does not
qualify this new combination. The next door is normal publication by the actual
local branch name, followed by hosted measurement of the unchanged tests-first
controls. No skip, force, dependency override or hand-authored lock was used.
