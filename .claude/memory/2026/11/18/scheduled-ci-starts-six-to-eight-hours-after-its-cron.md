---
name: Scheduled CI starts six to eight hours after its cron
description: Measured GitHub schedule delay of the family's nightly ci.yml against its 02:00 UTC cron, 2026-11-04..18; D63 accepts it and makes the cron per-repo.
metadata:
  type: project
---

User ruling D63 (2026-11-18): accept the nightly delay, measure it, and make the cron configurable rather than a dev-lab constant. This is the measurement.

Method: `gh run list --workflow ci.yml --event schedule -L 30 --json createdAt,databaseId,conclusion` per repo, taken 2026-11-18 ~09:40 UTC; delay = `createdAt` minus 02:00 UTC of the same day. Window: each repo's first scheduled run on or after 2026-11-04 through 2026-11-18. Conclusions do not affect the delay and are not tabulated.

| repo | n | first day | min | median | max | skipped days |
|---|---|---|---|---|---|---|
| dev-lab | 15 | 11-04 | 6h07 | 6h50 | 7h58 | none |
| lab-commons | 14 | 11-05 | 6h07 | 6h51 | 7h58 | none |
| numerics-lab | 13 | 11-05 | 6h15 | 6h54 | 8h04 | none (11-18 not yet created) |
| learn-lab | 10 | 11-08 | 6h31 | 7h00 | 8h06 | none (11-18 not yet created) |
| ai-lab | 13 | 11-05 | 6h21 | 6h59 | 8h14 | none (11-18 not yet created) |
| a private repo | 12 | 11-07 | 5h58 | 6h48 | 7h53 | none |
| document-lab | 12 | 11-06 | 6h28 | 7h03 | 8h19 | none (11-18 not yet created) |
| cc-market | 4 | 11-14 | 6h40 | 6h58 | 8h16 | none (11-18 not yet created) |
| agent-config repo | 4 | 11-14 | 6h41 | 6h59 | 8h17 | none (11-18 not yet created) |

Reading: every repo's scheduled run starts 6-8.3 h late (family median ~6h55); no day was dropped in the window. The delay is uniform across repos on a given day (e.g. all 11-14 runs at 08:17-08:42), so it is GitHub's schedule queue, not anything a repo does. On 11-18 five repos had no run yet at measurement time, consistent with the same delay rather than a skip.

Action: `ciworkflows.nightly_cron` -- a repo's `[tool.dev_lab.ci."ci.yml"] nightly = "<5-field cron>"` overrides the 02:00 UTC default (`NIGHTLY_CRON`); `docs-src/dev/project-files.md`.
