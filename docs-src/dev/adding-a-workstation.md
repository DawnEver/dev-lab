# Adding a forge workstation

A Windows workstation serves forge parts through one Scheduled Task, deployed in one command. This page is the
runbook for a LIGHT workstation: one that serves parts and requests but never heavy compute -- no JMAG, FEMM,
MATLAB or SIMBA run, even when the tool is installed (user ruling 2026-10-28, WS1 and WS2). A JMAG box is the
same deploy with `--capabilities workstation,jmag:<N>` instead of a role ([the forge](forge.md#deploy-a-windows-workstation)).

## What the light role writes

The role is declared ONCE, `dev_lab.dev.workstationfile.ROLES`, and the deploy renders it into the machine file
(`~/.config/lab-commons/config.toml`). Print it for your repos with

```
.venv\Scripts\python.exe -m dev_lab.dev.workstation template --role light --repos dev-lab,lab-commons,motronics-studio
```

which prints exactly this (a test pins this block to the command's output, so it cannot drift):

<!-- template: light dev-lab,lab-commons,motronics-studio -->
```toml
[capabilities.workstation]

[serve]
repos = ["dev-lab", "lab-commons", "motronics-studio"]
parts = "every"
withhold = ["femm", "jmag", "matlab", "simba"]
```

- `[capabilities.workstation]`: the live-checkout-and-agent-kit resource (`node` and `codex` on `PATH`); the
  `workstation` parts need it.
- `withhold` is every tool the presence probe knows (`workstationfile.HEAVY`, derived from
  `lab_commons.compute.toolchecks.CHECKS`). A probe finds an installed JMAG whether or not it is declared, so
  withholding is what keeps it off the forge: the host claims no part and no request needing one. A heavy
  capability given to `--capabilities` with `--role light` is refused.
- `parts = "every"`: it also produces `base`.

Nothing else is written: no `[reserve]`, no seats. Every other table, key and comment of the file is kept.

## Deploy, step by step

1. **Prerequisites**, logged on as the user who will serve: `git` (`winget install --id Git.Git -e`), `uv`
   (`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`), `node`
   (`winget install --id OpenJS.NodeJS.LTS -e`) and `codex` (`npm install -g @openai/codex`) on `PATH`. The
   deploy probes each and refuses all that are missing together, each with its remedy.
2. **The registry role.** This machine's entry in the synced `hosts.json` carries role `"forge"`, and the
   machine file names it: `[workstation] registry = "<path to hosts.json>"`. Without it the deploy and every
   serve tick refuse (the rule: [the forge](forge.md#deploy-a-windows-workstation)).
3. **The dev-lab serve checkout**, cloned where the deploy keeps it, and its venv:

   ```
   $D = "$env:LOCALAPPDATA\lab-forge\repos\dev-lab"
   git clone -b integrate/main <forge>/dev-lab.git $D
   cd $D
   uv sync --frozen
   ```

4. **The forge credential**, through the forge's own door: `.venv\Scripts\python.exe -m dev_lab.dev.forge auth
   login` (it prompts, input hidden), then `... forge auth status`. Use your OWN account; the deploy only runs
   `git ls-remote` with prompting off, so it never reads or prints a credential, and with none stored it refuses
   naming this step. No token belongs in this page, a file or a command line.
5. **Deploy, dry run first**:

   ```
   .venv\Scripts\python.exe -m dev_lab.dev.workstation deploy --role light --forge <forge> `
       --repos dev-lab,lab-commons,motronics-studio --dry-run
   ```

   Read every action and the machine-file diff, then run it again without `--dry-run`. It clones and bootstraps
   each repo, installs its hooks, merges the tables above, removes every RETIRED `[capabilities.<name>]` table
   (one retired into `[runtimes.<name>]` keeps its keys there), and writes the `lab-forge-serve` Task. A second
   run changes nothing.

## Verify

`python -m dev_lab.dev.forge queue`, from any machine. The host's card shows its OS, its supply, its last tick
and `serves ... none needing femm, jmag, matlab, simba`. A JMAG part waiting only on this host reads
`skipped here: ... which this host keeps for its own work`; one no live host supplies reads `no host provides
jmag`. The serve log is `%LOCALAPPDATA%\lab-forge\serve.log`.

## When a host goes stale, and how to retire one

A card older than three of its ticks is STALE: the queue lists its supply as `none (stale)`, it counts toward no
`no host provides` decision, and when every host providing a tool is stale the fleet alarm says so once. Its
claims are not released by anyone: each lapses with its lease (6 h, renewed only by its owner) and is then
retaken. To bring it back, read the serve log and fix the cause (logged off, Task disabled, credential refused).

To retire a host for good:

1. stop it serving: `schtasks /Change /TN lab-forge-serve /DISABLE`, then stop a serve still running with
   `python -m dev_lab.dev.stoprun --pid <pid>`, which releases its claims as `stopped`;
2. remove `"forge"` from its `roles` in `hosts.json`, so a re-enabled Task stands down instead of serving;
3. delete its card: `python -m dev_lab.dev.forge hosts retire <host>`. It rejoins only by ticking again.
