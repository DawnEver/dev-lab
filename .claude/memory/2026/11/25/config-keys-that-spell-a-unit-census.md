---
name: config-keys-that-spell-a-unit-census
description: Family census (2026-11-25) of TOML config keys that spell a size, duration or percentage unit, their readers, and the quantity-string key each became
created: 2026-11-25
---

# Census: config keys that spell a unit (2026-11-25)

User ruling 2026-11-25 (translated): "1: do all of it, GiB; 2: keep only `test = "10 min"`". A key that spells a
size, duration or percentage unit (`_gb`, `_mb`, `_bytes`, `_s`, `_ms`, `_min`, `_minutes`, `_hours`, `_days`,
`_pct`, `_percent`, or an unambiguous unit word in any segment) becomes a unit-free key whose value is a quantity
string parsed once by `lab_commons.quantity.parse`; the old key is refused by name with its new line
(`lab_commons.quantity.refuse_renamed`). Rule: `CONFIG-VALUES-CARRY-UNITS` (`dev_lab.dev.configkeys`).

Method (read-only): every tracked `*.toml` at each repo's integration head (the host-config repo: its `main`),
walked at every depth incl. arrays of tables; readers by `git grep` of `.get('<key>')`, subscripts, schema constants
and table dataclasses. `.claude/memory/` and `attic/` excluded; the frozen consumer skipped; private repos are named consumer-p1..p4 here (this repo is public). Host and account files
are named by role here, never by name (this repo is public).

## 1. Stored keys (tracked TOML)

| repo | file | key | reader | new key = value |
|---|---|---|---|---|
| host config | 7 workstation host files | `[dev.resources] memory_gb = <n>` (32, 64, 63, 159.9) | dev-lab `devschema.RESOURCES` | `memory = "<n> GiB"` |
| host config | 2 HPC account files | `[hpc.paging] page_mem_gb = 20`, `movable_minutes = 30` | lab-commons `hpc.grants._paging` | `page_mem = "20 GiB"`, `movable = "30 min"` |
| host config | 2 HPC account files | `[schedule] tick_minutes = 15` | dev-lab `hpcaccount.spec`, `forgehosts`, `forgeserve`, `hostalarm` | `tick = "15 min"` |
| host config | the forge host file | `[[components.process_monitor.processes]] max_rss_mb = 500` | dev-lab `supervise.components.resources` | `max_rss = "500 MB"` |
| host config | family file | `slurm_accounts.<a>.budget.core_hours = 20000.0` | lab-commons `hpc.grants.Budget` | `core_time = "20000 h"` |
| host config | family file | `[dev] bridge.hpc.cadence_hours = 6` | dev-lab `devschema.BRIDGE_HPC`, `devprofile` | `cadence = "6 h"` |
| host config | family file | `[ssh.hold] max_hours = 24` | dev-lab `devschema.SSH_HOLD`, `sshhold` | see the applied table |
| host config | family file (comment) | `[storage] free_floor_gb = <GiB>` | lab-commons `storage` | `free_floor = "<n> GiB"` |
| host config | pyproject.toml | `[tool.dev_lab.branchset] max_idle_hours = 24` | dev-lab `branchset` | `max_idle = "24 h"` |
| host config | docs/topology.md | `memory_gb`, `free_floor_gb`, `wave_hours_max` (prose) | -- | follow the keys |
| dev-lab | pyproject.toml | `[tool.dev_lab.branchset] max_idle_hours = 12` | `branchset` | `max_idle = "12 h"` |
| dev-lab | layout.toml | `max_age_days = 3.0` | `codeplace` | `max_age = "3 d"` |
| dev-lab | src/dev_lab/dev/ci_base.toml | `timeout-minutes` | GitHub/Gitea Actions | the forge's vocabulary: exempt by name |
| lab-commons | pyproject.toml | `[tool.dev_lab.placement] max_age_days`, `[tool.dev_lab.branchset] max_idle_hours` | dev-lab | `max_age = "3 d"`, `max_idle = "12 h"` |
| consumer-p1 | pyproject.toml | `max_idle_hours = 12`, `max_age_days = 3.0` | dev-lab | `max_idle = "12 h"`, `max_age = "3 d"` |
| learn-lab | pyproject.toml | `[tool.dev_lab.verify] worker_mem_gb = 3.5`, `max_idle_hours = 24` | dev-lab `verifybox`, `branchset` | `worker_mem = "3.5 GiB"`, `max_idle = "24 h"` |
| consumer-p2 | pyproject.toml | `max_idle_hours = 12` | dev-lab `branchset` | `max_idle = "12 h"` |
| consumer-p2 | tests/fixtures/observation/*.observation.toml | `travel_min = 6.6` | consumer-p2 observation reader | `min` = MINIMUM, a domain value: left |
| consumer-p3 | pyproject.toml | `max_idle_hours = 12` | dev-lab `branchset` | `max_idle = "12 h"` |
| document-lab | pyproject.toml | `max_idle_hours = 24` | dev-lab `branchset` | `max_idle = "24 h"` |
| numerics-lab, ai-lab, claude-code-config (cc-market inside it) | -- | none | -- | -- |
| consumer-p4 (listed only; another session owns it) | layout.toml | `max_age_days = 3.0` | dev-lab `codeplace` | `max_age = "3 d"` |

## 2. Declared schemas and readers (keys a reader takes, written or not)

| repo | file | keys | table |
|---|---|---|---|
| lab-commons | storage.py | `free_floor_gb` | machine `[storage]` |
| lab-commons | home.py | `min_free_gb` | machine `[tools]` |
| lab-commons | hpc/grants.py | `page_mem_gb`, `movable_minutes`; budget `core_hours` | `[hpc.paging]`, `slurm_accounts.<a>.budget` |
| lab-commons | hpc/sshgate.py | `min_interval_s`, `window_s` | machine `[hpc.ssh]` |
| lab-commons | hpc/builds.py | `timeout_s`; item_wall `floor_s`, `unmeasured_s`, `ceiling_s` | `[tool.lab_commons.hpc]` |
| lab-commons | hpc/config.py | `[cost] mem_gb`, `seconds`; `[policy] shard_minutes_min/max`, `stall_minutes`, `poll_seconds` | the hpc job file |
| dev-lab | devschema.py | `memory_gb`, `allotted_memory_gb`; `cadence_hours`; `max_hours`, `idle_minutes` | host `[dev.resources]`, `[dev] bridge.hpc`, `[ssh.hold]` |
| dev-lab | sshhold.py | `check_hours`, `idle_s` (if config) | `[ssh.hold]` |
| dev-lab | forgehosts, forgeserve, hostalarm, hpcaccount/spec | `tick_minutes`, `tick_wall_minutes` | machine `[schedule]` |
| dev-lab | forgethreads `seconds()`, forgefeed, branchpolicy | `tick_s`, `prune_duty_s` | machine `[forgefeed]` |
| dev-lab | forgealarm | `repeat_hours` | alerts table |
| dev-lab | forgeschedule (Schedule in lab_commons.compute.model) | `starve_after_hours`, `daily_budget_core_h`, `prior_cost_h`, `request_unadmitted_hours` | `[tool.lab_commons.schedule]` |
| dev-lab | forgenotice.duration, forgereview_declared._duration | two duplicate duration parsers | -- (one parser) |
| dev-lab | retentionplan | `min_age_hours`, `abandon_days`, `log_max_mb`, `slurm_out_days` | machine `[retention]` |
| dev-lab | opsserver, ops/disk | `journal_max_mb` | ops `[[server]]` |
| dev-lab | ops/consentrole, consent/issuer, ops/httpsdoor | `lockout_minutes`, `https_window_minutes`, `https_lock_minutes` | `[ops.consent]` |
| dev-lab | ops/breakglass | `wave_hours_max` | `[ops.breakglass]` |
| dev-lab | ops/backuprole | `max_put_bytes`, `retention_days` | `[ops.backup]` |
| dev-lab | forgetidy | `request_max_age_days`, `work_max_idle_days` | `[tool.dev_lab.forge.issue_hygiene]` |
| dev-lab | supervise/pressure | `disk_free_floor_gb`, `psutil_window_s`, `interval_s`, `slope_span_s`, `*_percent_ceiling`, `days_to_full_floor` | supervise component config |
| dev-lab | supervise/daemon, process/systemd | `watchdog_seconds`, `ceiling_gb` | supervise config |
| dev-lab | supervise/components/resources | `max_rss_mb` | `[[components.process_monitor.processes]]` |
| dev-lab | branchset, codeplace | `max_idle_hours`, `max_age_days` | `[tool.dev_lab.branchset]`, `layout.toml` |
| dev-lab | verifybox | `wall_s`, `worker_mem_gb` | `[tool.dev_lab.verify]` |
| dev-lab | ciworkflows | `part_timeout_minutes` | `[tool.dev_lab.ci]` |
| dev-lab | forgereview_declared | `max_diff_bytes`, `max_total_bytes` | `[tool.dev_lab.review]` |
| dev-lab | forgerequest | `mem_gb`, `wall_h` | `[tool.dev_lab.requests.<name>]` |
| dev-lab | artifacts | `threshold_mb`, `retain_days`, `cap_gb`, `*_bytes` | `[tool.lab_commons.artefacts]` |
| dev-lab | testcost (lane tests-by-need-and-ledger) | `test_s`, `cores`, `memory_gb` | machine `[test_budget]` -> `test = "10 min"` only |
| consumer-p2 | its campaign spec module | `mem_gb`, `wall_seconds`, `margin_seconds`, `lane_mem_gb`, `spill_gib`, `epoch_seconds`, `poll_seconds` | `campaign.toml` |

## 3. Not config (listed, left)

- JSON/JSONL record fields -- the JSON half of `UNITS-GO-THROUGH-PINT`, not this rule: dev-lab box demand `mem_gb`,
  `peak_mb`/`peaks_mb`, `wall_s`, card `interval_s`/`max_mb`/`current_mb`, `system_ram_percent`, the HPC usage
  report's `core_hours`/`req_mem_mb`/`max_rss_mb`, `logical_bytes`, an artifact folder manifest's `bytes`;
  lab-commons records and plans (`mem_gb`, `peak_mb`, `mem_mb`, `top_minutes`, `heavy_bar_gb`); ai-lab ledger
  `latency_s`, `diff_bytes`, `read_bytes`; learn-lab bench `utilisation_pct`, `memory_used_mib`, `compile_s`;
  consumer-p2 timing records `*_seconds`, `cpu_hours`.
- CLI flags that spell a unit (`--campaign-wall-seconds`, `--campaign-spill-gib`): UNITS-GO-THROUGH-PINT's CLI arm.
- Keys with NO unit anywhere (`timeout = 10`, `max_age = 1800`, `warning = 80` in the forge host's components) are
  the opposite defect -- the unit is nowhere -- and outside this ruling.
