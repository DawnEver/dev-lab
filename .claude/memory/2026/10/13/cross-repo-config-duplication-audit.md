---
name: cross-repo-config-duplication-audit
description: Machine/user settings the family repos each read under their own key; owners named, lab-commons [user] table and the sharedsettings famtest added, adoption list per consumer
created: 2026-10-13
---

User ruling 2026-10-13: the machine file carried `text_editor_command = "start"` under both
`[motronics.utils]` and `[wdg_lab.utils]` -- "clean up this kind of cross-repo config duplication".

## Scope read (read-only)

lab-commons origin/integrate/main 37bd51d; motronics-studio origin/integrate/main (git show/grep only);
wdg-lab main 503e798b; optimi-lab and ai-lab cloned but read no machine file and define none of these
keys (no hits). Looked at: machine-file tables, config schemas, resources/defaults TOML, env vars,
repeated default literals.

## Audit

| setting | repos defining it | default in each | consumed? | owner |
|---|---|---|---|---|
| `text_editor_command` | motronics `core/utils/config_schema.py::Utils`; wdg-lab `utils/config.py::UtilsParameters`; machine file x2 | `'notepad.exe'` both | NO reader in either repo (dead field) | lab-commons `[user]`, `config.user()` |
| `log_file_format` | motronics `Utils`; wdg-lab `UtilsParameters` | identical literal | both, passed to lab-commons log handlers | lab-commons `[user]` |
| `log_console_format` | same two | `'%(message)s %(asctime)s'` both | both | lab-commons `[user]` |
| `log_date_format` | same two | `'%m/%d/%Y %H:%M:%S'` both | both | lab-commons `[user]` |
| `log_app_format` | same two | identical literal | NO reader in either (dead) | nobody: delete in both |
| `log_level` | motronics `Utils` (validated); wdg-lab hard-codes `logging.INFO` | `'INFO'` | motronics | lab-commons `[user]` (one validator) |
| `plot_backend` / `mpl_backend` / `wdg_backend` / `precision_digits` / `connection_dir` | wdg-lab only | -- | wdg-lab | stays wdg-lab (package-specific; lab-commons `viz.mpl` honours `MPLBACKEND` env, no config key) |
| `[motronics.reference]` archive/mirror roots, solver/mesh tables | motronics only | -- | motronics | stays motronics |
| `MOTRONICS_HOME` / `WDG_LAB_HOME` | one each | -- | -- | stay: each names its own package tree, not a shared fact |
| `JMAG_HOME`, `MPLBACKEND`, `DISPLAY` | read by motronics / lab-commons / wdg-lab | external | -- | vendor/OS env, owned by neither |
| `[hpc]`, `[capabilities.*]`, `[serve]`, `[deploy]` | lab-commons only | -- | lab-commons | already single-owner |

Finding: everything duplicated is the `Utils` block both consumers inherited from one ancestor; two of
its six fields are read by nobody.

## What landed (lane/one-user-config, not pushed)

- `lab_commons.config`: `[user]` table, `User` (one default each), `SHARED_KEYS`, `LOG_LEVELS`,
  `user()`; `section(<pkg>)` REFUSES a package table carrying a shared key at any depth, remedy
  "move it to [user] ... and delete it here". No fallback, no alias. 34b5a62.
- `lab_commons.dev.famtests.sharedsettings`: `assert_no_package_redefines_a_shared_setting(src, floor=,
  sanctioned=)` convicts a class field / dict or TOML key named a shared key, or a copy of a distinctive
  default; planted control `assert_a_planted_redefinition_is_convicted()`. 83f98a4.
- Not added to `hpc.declared.KNOWN_TABLES`: that set is `[tool.lab_commons.*]` pyproject tables;
  `[user]` is a machine-file table.

## Adoption (after promotion), file by file

The MACHINE FILE first, by the user, in the same step a consumer adopts (else `section()` refuses):
delete `[motronics.utils]` and `[wdg_lab.utils]` `text_editor_command`, add
`[user]\ntext_editor_command = "start"`.

motronics-studio:
1. `src/motronics/core/utils/config_schema.py`: delete from `Utils` the fields `log_level`,
   `log_file_format`, `log_console_format`, `log_app_format`, `log_date_format`,
   `text_editor_command` and the `_check_log_level` validator; delete `Utils` and `Config.utils` if
   nothing is left.
2. `src/motronics/core/utils/logger.py::add_handle`: take `lab_commons.config.User` (or call
   `user()`), `level = _log_level_from_str(u.log_level)`, formats from `u.*`.
3. Every caller of `add_handle(CONF.utils, ...)` / `CONF.utils.*` (grep `\.utils\.log_`): pass `user()`.
4. Any `resources/defaults` or rendered config template listing `[utils]` keys: drop those keys.
5. Tests asserting the `Utils` defaults: delete; add `tests/architecture/.../test_no_shared_setting_redefined.py`
   calling `assert_no_package_redefines_a_shared_setting(SRC, floor=<measured>)` and
   `assert_a_planted_redefinition_is_convicted()`.
6. `workflow/retired.py`: register `[motronics.utils].<key>` -> `[user].<key>` (RETIRED-NAMES-REGISTERED).

wdg-lab:
1. `src/wdg_lab/utils/config.py`: delete `UtilsParameters` and `Config.utils`; module docstring example
   drops `text_editor_command`.
2. `src/wdg_lab/utils/logger.py:~117`: formats from `lab_commons.config.user()`; level
   `_log_level_from_str(user().log_level)` instead of the hard-coded `logging.INFO`.
3. Tests on `UtilsParameters` / `CONF.utils`: delete; add the same famtest adoption test over `src`.
