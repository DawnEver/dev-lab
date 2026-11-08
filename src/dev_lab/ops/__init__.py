"""FORGE HOST ROLES: the jobs a forge host runs unattended, and the one door that runs and installs them.

Every role is generic; a deployment is the ``[ops]`` table of the host's supervise configuration
(:mod:`dev_lab.ops.config`), whose ``[alerts]`` are the roles' alert channel too. The roles:

* :mod:`dev_lab.ops.promote` -- fast-forward each repo's trunk when ``integrate promote`` admits it;
* :mod:`dev_lab.ops.breakglass` -- merge PRs past the forge's protection inside a WAVE (:mod:`dev_lab.ops.wave`)
  opened by a ``breakglass.wave`` consent credential; its client is ``forge breakglass`` /
  ``forge pr breakglass`` (:mod:`dev_lab.dev.forgebreakglass`);
* :mod:`dev_lab.ops.consent` -- the consent ISSUER (TOTP seed, Ed25519 key, ledger) and its verifiers: the user
  grants a signed per-action credential (``python -m dev_lab.ops.consent grant``);
* :mod:`dev_lab.ops.probe` -- per declared repo on either forge, protection drift (``forge protect check``) and a
  failed scheduled or integration CI run, each alerted once;
* :mod:`dev_lab.ops.install` -- render the systemd units, sshd drop-in and sudoers line the config asks for.
* :mod:`dev_lab.ops.configdoor` -- ``config apply``: the ONE way the host's config changes; routine keys on the
  operator's word, the security boundary only with an ``ops.config`` consent credential for exactly that file.

The design and its follow-ups: ``.claude/memory/2026/11/03/PLAN-forge-host-roles-are-one-configured-mechanism.md``.
"""

__all__: list[str] = []
