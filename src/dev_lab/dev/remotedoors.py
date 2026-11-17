"""REMOTE DOORS: the agent-policy rows that act on a cluster account or a declared server.

Split out of :mod:`dev_lab.dev.agentpolicy` by responsibility at the module-size band (2026-11-16, when the
drift and CI-cron rows arrived): those doors reach another machine, and their rules (consent codes, the grant's
own login hosts, the user-only cron verbs) are one concern. They are NOT a second table:
:data:`dev_lab.dev.agentpolicy.POLICY` splices :data:`REMOTE_DOORS` in, and every renderer reads only POLICY.
"""

from __future__ import annotations

from typing import Final

from dev_lab.dev._policy_door import MAIN, SUBAGENT, USER, Door, module_argv

__all__ = ['REMOTE_DOORS']

#: The remote rows, in the order :data:`dev_lab.dev.agentpolicy.POLICY` lists them.
REMOTE_DOORS: Final[tuple[Door, ...]] = (
    Door(
        module_argv('hpcaccount', 'deploy-fleet'),
        MAIN,
        'Deploying or restarting the forge serve hosts of the trusted fleet: each trusted cluster account on its '
        'own declared login host, over ssh, detached, one log per account.',
        deny='HPC-THROUGH-THE-DOOR',
    ),
    Door(
        module_argv('hpcaccount', 'forget'),
        MAIN,
        "Forgetting one stale row of each trusted cluster account's learned memory table, backed up beside itself, "
        "through the grant's own login hosts; a dry run only reads what each account holds.",
        deny='HPC-THROUGH-THE-DOOR',
    ),
    Door(
        module_argv('hpcaccount', 'retention'),
        MAIN,
        "Reading each trusted cluster account's quota (files and blocks) and whether its serve ticks, and running "
        "that account's own in-flight-aware storage retention through the grant's own login hosts; a dry run "
        'unless asked to apply.',
        deny='HPC-THROUGH-THE-DOOR',
    ),
    Door(
        module_argv('hpcaccount', 'credential'),
        MAIN,
        'Placing one minted forge token of a declared login on a trusted cluster account, the token on standard '
        "input and replacing only that forge's stored line, through the grant's own login hosts, then confirming "
        'the forge answers as that login (user ruling 2026-11-12).',
        deny='HPC-THROUGH-THE-DOOR',
    ),
    Door(
        module_argv('opsserver'),
        MAIN,
        "Running one of the ops account's fixed verbs on a declared server the integrator deploys: install, a "
        "unit's status, restart, reload or logs, or a daemon reload, with the user's one-time code at the login.",
        deny='REMOTE-WRITE-THROUGH-A-DOOR',
    ),
    Door(
        (),
        MAIN,
        'The first hand deploy of a trusted fleet account the fleet deploy refuses for want of a declared host: on '
        "that account's own login host, through the family deploy verb, detached, its log kept on the account.",
    ),
    Door(
        (),
        MAIN,
        'Maintenance of a declared server or cluster account the integrator owns: read-only disk and process '
        'census, and cleanup of regenerable caches only (journal, package and archive caches, finished run '
        'scratch); never repository data, attachments, backups or anything the census marks not owned.',
    ),
    Door(
        module_argv('hpcaccount', 'drift-fleet'),
        SUBAGENT,
        'Reading, read-only, what each selected cluster account holds that its config source cannot render; it '
        'writes no file and touches no crontab (user ruling 2026-11-16).',
    ),
    Door(
        module_argv('hpcaccount', 'drift'),
        SUBAGENT,
        'Reading, read-only and on the account itself, what that account holds that its config source cannot '
        'render (user ruling 2026-11-16).',
    ),
    *(
        Door(
            module_argv('hpcaccount', verb),
            USER,
            f"{what} a verification account's forge CI cron around cluster maintenance: the user runs it, or "
            'grants a consent plan for the cluster and its account list (user ruling 2026-11-16).',
            deny='CI-CRON-NEEDS-CONSENT',
        )
        for verb, what in (
            ('ci-pause-fleet', 'Pausing, across the selected accounts,'),
            ('ci-resume-fleet', 'Resuming, across the selected accounts,'),
            ('ci-pause', 'Pausing, on the account itself,'),
            ('ci-resume', 'Resuming, on the account itself,'),
        )
    ),
    Door(
        module_argv('hpcaccount', 'deploy'),
        USER,
        "Making a cluster account's login host a forge serve host: run by the user on that account.",
        deny='HPC-THROUGH-THE-DOOR',
    ),
)
