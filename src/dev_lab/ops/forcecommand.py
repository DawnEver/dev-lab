"""A RESTRICTED SSH ACCOUNT: every session is one ``sudo -n`` ForceCommand, and its keys authorize nothing else.

Break-glass and the consent issuer each take requests this way (:mod:`dev_lab.ops.install` renders both): an sshd
``Match User`` block with every forwarding and the TTY off, the account's authorized-keys file, and the one sudoers
line that lets it run the serve verb as root, keeping only :data:`dev_lab.ops.sshkey.ENV` (the authenticating key).
"""

from __future__ import annotations

from dev_lab.ops.access import keys_file
from dev_lab.ops.sshkey import ENV

__all__ = ['files', 'steps']


def files(unit: str, account: str, keys: tuple[str, ...], serve: str) -> dict[str, str]:
    """The sshd drop-in, keys file and sudoers line of *account*, whose sessions run *serve*; by root-relative path."""
    listed = keys_file(account)
    sshd = (
        f'Match User {account}\n    AuthorizedKeysFile {listed}\n'
        f'    ExposeAuthInfo yes\n    ForceCommand sudo -n {serve}\n'
        '    AllowTcpForwarding no\n    AllowAgentForwarding no\n    X11Forwarding no\n    PermitTTY no\n'
    )
    sudoers = f'Defaults:{account} env_keep += "{ENV}"\n{account} ALL=(root) NOPASSWD: {serve}\n'
    return {
        f'etc/ssh/sshd_config.d/60-{unit}-{account}.conf': sshd,
        listed.lstrip('/'): ''.join(f'{key}\n' for key in keys),
        f'etc/sudoers.d/{unit}-{account}': sudoers,
    }


def steps(unit: str, account: str) -> list[str]:
    """The live-host steps *account* needs: create it, check its sudoers line, test and reload sshd."""
    return [f'id {account} || useradd --create-home --shell /bin/sh {account}',
            f'visudo -cf /etc/sudoers.d/{unit}-{account}', 'sshd -t && systemctl reload ssh']  # fmt: skip
