"""THE ORIGINAL `dev_lab.dev` MODULES THAT REACH A REMOTE HOST -- DATA, one name per module.

The remote-door half of the `original` registry (`_original_rows.py` holds the rest; split by responsibility at
the module-size band, 2026-11-12). READ AS SOURCE by `dev_lab.dev._provenance.provenance_rows`, never imported.
"""

from __future__ import annotations

from typing import Final

__all__ = ['ORIGINAL_MODULES']

ORIGINAL_MODULES: Final[tuple[str, ...]] = (
    # ORIGINAL: one TOTP-authenticated ssh connection held for a work session (user ruling 2026-11-09).
    'sshhold',
    # ORIGINAL: sshhold's state file and audit split from its client (MODULE-SIZE-ALARM, 2026-11-11).
    'sshholdstate',
    # ORIGINAL: 2026-11-23, a remote command Git Bash rewrote is refused before sshhold sends it.
    'msyspath',
    # ORIGINAL: split out of `hpcaccount.fleet` inside the kit (2026-11-10); the judge's machine file reads it too.
    'machinehome',
    # ORIGINAL: user ruling 2026-11-07, the two remote doors over one ssh transport; no consumer held either.
    'opsserver',
    'remote',
    # ORIGINAL: hpcaccount's forget verb (2026-11-10), one learned row off a cluster account; no consumer held it.
    'forget',
    # ORIGINAL: 2026-11-14, an account's quota, tick lines and own retention read from the workstation.
    'storage',
    # ORIGINAL: user ruling 2026-11-12, an agent places a minted forge token on a key-only account.
    'credential',
    # ORIGINAL: user ruling 2026-11-22, an account's login keys derived from hosts-config [dev] client_keys and hpc.
    'keys',
    # ORIGINAL: 2026-11-12, its stage-verify-replace core shared with a workstation's own placement door.
    'credstore',
    'devcredential',
    # ORIGINAL: 2026-11-20, tokens never rotate (user ruling): the helper and store-line presence checked by drift.
    'forgecredential',
    # ORIGINAL: 2026-11-20, user (translated): 'you must be able to do it yourself' -- one code enrols a machine.
    'forgeenrol',
    # ORIGINAL: user ruling 2026-11-23, a declared key is admitted by one code from any machine the issuer admits.
    'devhostadmit',
    # ORIGINAL: 2026-11-20, the effective [dev] split from devhost at the module-size band for the credential doors.
    'devdeclared',
    # ORIGINAL: 2026-11-23, a forge token's declared shape per forge kind, checked at every intake before a store.
    'forgetoken',
    # The hpcaccount verbs, which deploy and run on a remote cluster account (moved here from `_original_rows.py`
    # at the module-size band, 2026-11-13). No consumer guard is superseded: these forge-launching verbs moved from
    # the lab-commons owner into dev-lab in 9ac2e681. "original" denotes no consumer fork, not newly written code.
    'account',
    'allocate',
    # ORIGINAL: 2026-11-16, the fleet launcher of drift, ci-pause and ci-resume (the retired backup verb's half).
    'accountset',
    # ORIGINAL: 2026-11-16, a verification account's CI cron paused and resumed around cluster maintenance.
    'cimark',
    'cipause',
    # ORIGINAL: 2026-11-17, the hpcaccount.ci-cron consent a CI cron verb redeems before any crontab change.
    'cicron',
    'checks',
    # ORIGINAL: 2026-11-16, what a deploy declares (flags, stored [deploy], first write), split at the size band.
    'declaration',
    'deploy',
    # ORIGINAL: 2026-11-15, deploy's host check split from it at the module-size band.
    'deployhost',
    # ORIGINAL: 2026-11-16, what an account holds that its config source cannot render (an account is a render).
    'drift',
    'division',  # ORIGINAL: the workstation's HPC division as data (user rulings 2026-11-09)
    'fleet',
    # ORIGINAL: 2026-11-21, deploy-fleet's run-wide refusals, split from fleet at the module-size band.
    'fleetguard',
    # ORIGINAL: 2026-11-21, the machine file's [hpc] slice (grants, login hosts), split from spec at the size band.
    'grantslice',
    'spec',
    'steps',
    'tick',
    # ORIGINAL: 2026-11-15, every remote hpcaccount step rides the dest's held session when live, else key-only ssh.
    'transport',
    # ORIGINAL: the integrator as a session role, verified offline from its consent credential (2026-11-12).
    'session',
)
