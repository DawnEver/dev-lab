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
    # ORIGINAL: split out of `hpcaccount.fleet` inside the kit (2026-11-10); the judge's machine file reads it too.
    'machinehome',
    # ORIGINAL: user ruling 2026-11-07, the two remote doors over one ssh transport; no consumer held either.
    'opsserver',
    'remote',
    # ORIGINAL: hpcaccount's forget verb (2026-11-10), one learned row off a cluster account; no consumer held it.
    'forget',
    # ORIGINAL: user ruling 2026-11-12, an agent places a minted forge token on a key-only account.
    'credential',
    # ORIGINAL: 2026-11-12, its stage-verify-replace core shared with a workstation's own placement door.
    'credstore',
    'devcredential',
)
