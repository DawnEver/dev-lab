"""THE OPS ACCESS ACCOUNT: an agent troubleshoots a host with its ssh key AND the user's TOTP code, sudo narrowed.

PAM_OATH, NOT libpam-google-authenticator: google-authenticator keeps the secret in ``~/.google_authenticator``,
a file the logged-in account itself owns -- so the agent the code is meant to gate could read the secret once and
never need the user again. pam_oath reads a ROOT-ONLY users file (``oath``), the same rule as the break-glass secret
(:mod:`dev_lab.ops.totp`): the secret lives on the host and in the user's Authenticator, nowhere else.

Rendered by :mod:`dev_lab.ops.install` from ``[ops.access]``: an sshd ``Match User`` block requiring
``publickey,keyboard-interactive`` with every forwarding off, a PAM include that asks pam_oath for THIS account only
(every other account skips it), and a sudoers line naming exactly the declared commands. :func:`enrol` writes the
users file and returns the URI the user scans on the host's own terminal.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Final

from dev_lab.ops.config import Access
from dev_lab.ops.totp import DIGITS, STEP, uri
from dev_lab.ops.totp import enrol as enrol_secret

__all__ = ['PAM_INCLUDE', 'enrol', 'files']

#: The PAM file the sshd stack includes first (``@include`` is the operator's one-line step).
PAM_INCLUDE: Final = 'dev-lab-ops-access'
#: Characters a sudoers command list cannot carry unescaped.
_SUDOERS_UNSAFE: Final = frozenset(',:=\\\n')


def _keys_file(role: Access) -> str:
    return f'/etc/dev-lab/ops/{role.account}.keys'


def files(role: Access) -> dict[str, str]:
    """The sshd drop-in, the account's keys, the PAM include and the sudoers line, by path under the root.

    Raises:
        ValueError: a declared command carries a character sudoers would read as syntax.

    """
    if bad := [command for command in role.commands if _SUDOERS_UNSAFE & set(command)]:
        msg = f'[ops.access] commands carry sudoers syntax (, : = \\ newline): {bad}'
        raise ValueError(msg)
    sshd = (
        f'Match User {role.account}\n    AuthorizedKeysFile {_keys_file(role)}\n'
        '    AuthenticationMethods publickey,keyboard-interactive\n    KbdInteractiveAuthentication yes\n'
        '    AllowTcpForwarding no\n    AllowAgentForwarding no\n    AllowStreamLocalForwarding no\n'
        '    X11Forwarding no\n    PermitTunnel no\n'
    )
    pam = (
        f'# dev_lab.ops access: {role.account} needs its TOTP code; every other account skips the next line\n'
        f'auth [success=ignore default=1] pam_succeed_if.so quiet user = {role.account}\n'
        f'auth [success=done default=die] pam_oath.so usersfile={role.oath} window=1 digits={DIGITS}\n'
    )
    sudoers = f'{role.account} ALL=(root) NOPASSWD: {", ".join(role.commands)}\n' if role.commands else ''
    rendered = {
        f'etc/ssh/sshd_config.d/61-dev-lab-ops-{role.account}.conf': sshd,
        _keys_file(role).lstrip('/'): ''.join(f'{key}\n' for key in role.keys),
        f'etc/pam.d/{PAM_INCLUDE}': pam,
    }
    return rendered | ({f'etc/sudoers.d/dev-lab-ops-{role.account}': sudoers} if sudoers else {})


def enrol(role: Access, *, force: bool = False) -> str:
    """Write the account's pam_oath line (mode 600) and return the ``otpauth://`` URI to scan once."""
    secret = enrol_secret(Path(role.oath), force=force)
    hexed = base64.b32decode(secret + '=' * (-len(secret) % 8)).hex()
    Path(role.oath).write_text(f'HOTP/T{STEP}/{DIGITS} {role.account} - {hexed}\n', encoding='utf-8')
    return uri(secret, issuer=role.issuer, account=role.account)
