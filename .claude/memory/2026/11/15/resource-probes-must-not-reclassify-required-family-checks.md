---
name: Resource probes must not reclassify required family checks
description: Actual 5fe RED receipt and one further collection ownership control, before production implementation.
metadata:
  type: project
---

Downloaded Actions `43737554566`, job `132883399165`, produced the canonical
MEASUREMENT receipt for exact `5fe721b865e06a236faa86054c6580d767cc4e97`:
result fail, exit 1, environment `d6d69fd6d2855cdf`. All four complete owners
ran: 19 failed, 89 passed in 10.19 seconds. This includes the original three
execution failures and all sixteen added controls. The raw receipt and logs
are retained locally under `output/logs/26/11/15/integration/layout-execution-red-5fe`.
No conclusion is inferred merely from the Actions job's failure status.

Before production changes, one further real-subprocess control now tests the
resource projection seam in `tests/test_dev_jobparts.py`. Its real git repository
declares two resources, contains a base business test and a Windows-only test,
and collects through the actual family plugin. Required IDs are discovered from
that actual collection, not copied as string aliases. `localpart.owners` must
keep those required checks as base ownership, not combine every resource marker
whose probe necessarily executes the checks. The business tests retain their
actual independent resource assignments. This control has not yet executed;
whether the old implementation already preserves this distinction is unknown.

The contract requires one catalog for required IDs, outer collection proof and
resource-probe projection. A complete manifest must retain explicit required
check standing, rather than silently dropping those checks or creating aliases.
All actual runs still execute the required checks. No production scanner or
partition implementation was changed, and no engine stub was introduced while
the separately owned pure layout implementation is pending.
