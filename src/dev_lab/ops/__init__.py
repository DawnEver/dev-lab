"""FORGE HOST ROLES: the jobs a forge host runs unattended, and the one door that runs and installs them.

Every role is generic; a deployment is the ``[ops]`` table of the host's supervise configuration
(:mod:`dev_lab.ops.config`), whose ``[alerts]`` are the roles' alert channel too. The roles:

* :mod:`dev_lab.ops.promote` -- fast-forward each repo's trunk when ``integrate promote`` admits it;
* :mod:`dev_lab.ops.breakglass` -- merge PRs past the forge's protection inside a WAVE (:mod:`dev_lab.ops.wave`)
  the user opened with a TOTP code (:mod:`dev_lab.ops.totp`); its client is ``forge breakglass`` /
  ``forge pr breakglass`` (:mod:`dev_lab.dev.forgebreakglass`);
* :mod:`dev_lab.ops.install` -- render the systemd units, sshd drop-in and sudoers line the config asks for.

The design and its follow-ups: ``.claude/memory/2026/11/03/PLAN-forge-host-roles-are-one-configured-mechanism.md``.
"""

__all__: list[str] = []
