# Adding a forge workstation

A Windows workstation is deployed in one command: its capabilities declared, its checkouts and venvs kept current.
It NEVER serves a merge's parts (user ruling 2026-11-16): only the executors the family binds (`ci` -- GitHub Actions -- and the HPC
accounts, `dev_lab.dev.roles`) produce, and nothing on a workstation ticks. This page is the runbook for a LIGHT
workstation: one that never runs heavy compute -- no JMAG, FEMM, MATLAB or SIMBA, even when the tool is installed (user ruling 2026-10-28, both heavy boxes). A JMAG box is the
same deploy with `--capabilities workstation,jmag:<N>` instead of a role ([the forge](forge.md#deploy-a-windows-workstation)).

## What the light role writes

The role is declared ONCE, `dev_lab.dev.workstationfile.ROLES`, and the deploy renders it into the machine file
(`~/.config/lab-commons/config.toml`). Print it for your repos with

```
.venv\Scripts\python.exe -m dev_lab.dev.workstation template --role light
```

which prints exactly this (a test pins this block to the command's output, so it cannot drift):

<!-- template: light -->
```toml
[capabilities.workstation]
```

- `[capabilities.workstation]`: the live-checkout-and-agent-kit resource (`node` and `codex` on `PATH`); the
  `workstation` parts need it.
- A heavy capability (`workstationfile.HEAVY`, every tool `lab_commons.compute.toolchecks.CHECKS` marks heavy)
  given to `--capabilities` with `--role light` is refused.

No `[serve]` is written, and the deploy removes one it finds: a workstation never serves a merge's parts (user
ruling 2026-11-16; `configcheck` refuses the table through `rolecheck.host_refusals`). Nothing else is
written: no `[reserve]`, no seats. Every other table, key and comment of the file is kept.

## Deploy, step by step

1. **Prerequisites**, logged on as the user who will work there: `git` (`winget install --id Git.Git -e`), `uv`
   (`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`), `node`
   (`winget install --id OpenJS.NodeJS.LTS -e`) and `codex` (`npm install -g @openai/codex`) on `PATH`. The
   deploy probes each and refuses all that are missing together, each with its remedy.
2. **The registry role.** This machine's entry in the synced `hosts.json` carries role `"forge"`, and the
   machine file names it: `[workstation] registry = "<path to hosts.json>"`. Without it the deploy refuses (the rule: [the forge](forge.md#deploy-a-windows-workstation)).
3. **The dev-lab kit checkout**, cloned where the deploy keeps it, and its venv:

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
       --repos dev-lab,lab-commons,consumer-a --dry-run
   ```

   Read every action and the machine-file diff, then run it again without `--dry-run`. It clones and bootstraps
   each repo, installs its hooks, merges the tables above, removes every RETIRED `[capabilities.<name>]` table
   (one retired into `[runtimes.<name>]` keeps its keys there; `ai_lab` is dropped, its runtime built from the
   lock -- [the reviewer](integration.md#the-pr-review-is-one-shot-advice)), and deletes the retired `lab-forge-serve`
   Task where an older deploy registered it. A second run changes nothing.

## Consent and break-glass need nothing more

Where the family declares an `https` URL in `[consent]` and `[breakglass]`, this workstation reaches the consent
issuer and the break-glass server over HTTPS from inside the forge allowlist: no ssh host key to distribute and no
client key to authorize. dev-lab and the user's code are all it needs
([topology](topology.md#reaching-the-issuer-and-break-glass-https-or-ssh)).

## Verify

Re-run the deploy: a second run changes nothing, and `[task] lab-forge-serve ... none installed` says nothing
ticks here. Where a sha stands is read from the forge, from any machine: `python -m dev_lab.dev.forge queue`.
`python -m dev_lab.dev.workstation serve` is refused by name with the producer ruling.

## Retiring a workstation

Remove `"forge"` from its `roles` in `hosts.json`; a deploy there is then refused. A card an older serving deploy
left is deleted with `python -m dev_lab.dev.forge hosts retire <host>`.
