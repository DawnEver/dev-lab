---
name: Required identities are proved outside the plugin
description: Tests-first exact catalog, collection proof and resource projection contract.
metadata:
  type: project
---

Actions `43738513049`, job `132886350173`, measured exact
`86f15de2d15dd85b7e5b07cc6973347ac22f1f0a`. Canonical MEASUREMENT failed
with exit 1, environment `d6d69fd6d2855cdf`; the complete jobparts owner
reported 2 failed, 62 passed in 5.18 seconds. Only the two existing disabled
plugin controls failed. The new real resource-ownership control passed:
the old implementation did not exhibit a resource-union defect in that case.
This is not qualification of a new four-owner combination.

Five additional tests-first cases now define the narrow shared execution API
in the existing `famtests.alwayson` owner:

- `required_ids(root)` must identify the exact actual required pytest items,
  checked against a real collection's `session.items` receipt, not copied IDs.
- `assert_required_collected(root, ids)` refuses each individually missing
  required identity and names both that identity and the plugin remedy.
- `resource_nodes(root, ids)` projects only exact catalog identities out of
  resource-marker membership. It preserves business ordering and duplicates,
  and leaves the complete input manifest unchanged.
- The outer proof does not advertise ordinary non-family git repositories or
  non-git directories as family pytest qualification.

The catalog is not a second layout scanner. Its checks call the separately
owned pure layout engine and the existing CJK owner. Complete manifests retain
required standing and base ownership; real runs still execute the checks.
No production API was stubbed to make these tests pass. Method references are
inside executed tests, so a missing implementation cannot crash collection.

Static Ruff and formatting checks passed; these five new cases have not run.
The next door is complete `tests/test_famtests_alwayson.py` through hosted
measurement. The pure body candidate and all execution seams remain pending
composed qualification. Issue #599 remains the sole umbrella.
