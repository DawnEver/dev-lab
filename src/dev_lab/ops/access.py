"""THE OPS ACCESS ACCOUNT: an agent troubleshoots a host with its ssh key AND the user's TOTP code, sudo narrowed.

PAM_OATH, NOT libpam-google-authenticator: google-authenticator keeps the secret in ``~/.google_authenticator``,
a file the logged-in account itself owns -- so the agent the code is meant to gate could read the secret once and
never need the user again. pam_oath reads a ROOT-ONLY users file (``oath``), the same rule as the consent issuer's
secret (:mod:`dev_lab.ops.totp`): the secret lives on the host and in the user's Authenticator, nowhere else.

Rendered by :mod:`dev_lab.ops.install` from ``[ops.access]``: an sshd ``Match User`` block requiring
``publickey,keyboard-interactive`` with every forwarding off -- save local forwarding to the declared ``permit_open``
targets, which a host reached by jumping through this one needs -- a PAM include that asks pam_oath for THIS account
only (every other account skips it), and a sudoers line naming exactly the declared commands. :func:`ensure_include`
puts that include above ``@include common-auth`` in the sshd PAM stack, refusing a stack of any other shape.

ONE TOTP SECRET PER HOST (user ruling 2026-11-04): the code the user types comes from ONE Authenticator entry per host,
so pam_oath's users file is DERIVED from the host's one secret (:func:`secret_file`: ``[ops.access] totp``, else the
consent issuer's) -- by install, and by :func:`enrol` (first-ever enrolment only) or :func:`adopt` (a secret the
user's phone already holds, placed on another host) -- never generated independently.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from dev_lab.ops.config import Access, OpsConfig
from dev_lab.ops.totp import DIGITS, STEP, TotpRefused, uri, write_private
from dev_lab.ops.totp import adopt as adopt_secret
from dev_lab.ops.totp import enrol as enrol_secret

__all__ = [
    'KEYS_DIR',
    'PAM_INCLUDE',
    'PAM_SSHD',
    'Prepared',
    'adopt',
    'enrol',
    'ensure_include',
    'files',
    'keys_file',
    'oath_users',
    'prepare',
    'secret_file',
]

#: The PAM file the sshd stack includes first (:func:`ensure_include` puts the ``@include`` there).
PAM_INCLUDE: Final = 'dev-lab-ops-access'
#: The sshd PAM stack, and the line the include must precede.
PAM_SSHD: Final = '/etc/pam.d/sshd'
_COMMON_AUTH: Final = '@include common-auth'
#: Where every role's ssh keys live: root's, 0755, so sshd's StrictModes accepts it.
KEYS_DIR: Final = '/etc/dev-lab/ops'
#: One ``PermitOpen`` target: a host (name, IPv4, or bracketed IPv6) and a port.
_HOST_PORT: Final = re.compile(r'(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9._-]+):([0-9]{1,5})')
#: The highest TCP port (0 is no port).
_MAX_PORT: Final = 65535
#: Characters a sudoers command list cannot carry unescaped.
_SUDOERS_UNSAFE: Final = frozenset(',:=\\\n')


def _is_host_port(target: str) -> bool:
    found = _HOST_PORT.fullmatch(target)
    return found is not None and 1 <= int(found.group(2)) <= _MAX_PORT


@dataclass(frozen=True)
class Prepared:
    """What access adds to an install under a root.

    ``public`` files (0644), ``private`` ones (root 600, they carry a secret), and whether the host's one TOTP secret
    is still missing there (its next step is enrol or adopt).
    """

    public: dict[str, str]
    private: dict[str, str]
    needs_secret: bool


def prepare(config: OpsConfig, root: Path) -> Prepared:
    """The sshd PAM stack with the include, and the users file derived from the secret -- both read UNDER *root*.

    Raises:
        ValueError: the PAM stack is absent or of an unexpected shape (:func:`ensure_include`), or two secrets.

    """
    role = _role(config)
    stack = _under(root, PAM_SSHD)
    if not stack.is_file():
        msg = f'{PAM_SSHD} is absent under {root}; [ops.access] needs the sshd PAM stack to include its file'
        raise ValueError(msg)
    text = stack.read_text(encoding='utf-8')
    public = {_relative(root, stack): ensure_include(text) or text}
    held = _under(root, secret_file(config))
    secret = held.read_text(encoding='utf-8').strip() if held.is_file() else ''
    private = {_relative(root, _under(root, role.oath)): oath_users(role, secret)} if secret else {}
    return Prepared(public, private, needs_secret=not secret)


def _under(root: Path, path: str) -> Path:
    return root / Path(path).relative_to(Path(path).anchor)


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def keys_file(account: str) -> str:
    """The absolute path of *account*'s ssh keys, under :data:`KEYS_DIR`."""
    return f'{KEYS_DIR}/{account}.keys'


def files(role: Access) -> dict[str, str]:
    """The sshd drop-in, the account's keys, the PAM include and the sudoers line, by path under the root.

    Raises:
        ValueError: a declared command carries a character sudoers would read as syntax, or a ``permit_open``
            target is not one ``host:port``.

    """
    if wrong := [target for target in role.permit_open if not _is_host_port(target)]:
        msg = f'[ops.access] permit_open targets must each be host:port: {wrong}'
        raise ValueError(msg)
    if bad := [command for command in role.commands if _SUDOERS_UNSAFE & set(command)]:
        msg = f'[ops.access] commands carry sudoers syntax (, : = \\ newline): {bad}'
        raise ValueError(msg)
    forwarding = (
        f'    AllowTcpForwarding local\n    PermitOpen {" ".join(role.permit_open)}\n'
        if role.permit_open
        else '    AllowTcpForwarding no\n'
    )
    sshd = (
        f'Match User {role.account}\n    AuthorizedKeysFile {keys_file(role.account)}\n'
        '    AuthenticationMethods publickey,keyboard-interactive\n    KbdInteractiveAuthentication yes\n'
        f'{forwarding}    AllowAgentForwarding no\n    AllowStreamLocalForwarding no\n'
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
        keys_file(role.account).lstrip('/'): ''.join(f'{key}\n' for key in role.keys),
        f'etc/pam.d/{PAM_INCLUDE}': pam,
    }
    return rendered | ({f'etc/sudoers.d/dev-lab-ops-{role.account}': sudoers} if sudoers else {})


def secret_file(config: OpsConfig) -> str:
    """The host's ONE TOTP secret: ``[ops.access] totp``, else ``[ops.consent] totp``.

    Raises:
        ValueError: both are declared and name different files (two TOTP secrets on one host), or neither is.

    """
    role = config.access
    issuer = config.consent.totp if config.consent is not None else ''
    own = role.totp if role is not None else ''
    if own and issuer and Path(own) != Path(issuer):
        msg = f'two TOTP secrets on one host: [ops.access] totp = {own}, [ops.consent] totp = {issuer}; name one'
        raise ValueError(msg)
    if not (found := own or issuer):
        msg = "[ops.access] declares no totp and the host no [ops.consent] totp: name the host's one TOTP secret"
        raise ValueError(msg)
    return found


def oath_users(role: Access, secret: str) -> str:
    """The pam_oath users file DERIVED from the host's one base32 *secret* (never a second secret)."""
    hexed = base64.b32decode(secret.strip() + '=' * (-len(secret.strip()) % 8)).hex()
    return f'HOTP/T{STEP}/{DIGITS} {role.account} - {hexed}\n'


def _role(config: OpsConfig) -> Access:
    if config.access is None:
        msg = f'{config.path} enables no [ops.access]'
        raise ValueError(msg)
    return config.access


def enrol(config: OpsConfig, *, force: bool = False) -> str:
    """The FIRST-EVER enrolment: generate the host's one secret, derive the users file, return the URI to scan once.

    Raises:
        TotpRefused: the host already holds its secret (that enrolment is reused) and *force* is not given.

    """
    role, path = _role(config), Path(secret_file(config))
    if path.is_file() and path.read_text(encoding='utf-8').strip() and not force:
        msg = (
            f"{path} already holds the host's TOTP secret: the existing enrolment is reused (install derives "
            f'{role.oath} from it); --force replaces it for every role on this host'
        )
        raise TotpRefused(msg)
    secret = enrol_secret(path, force=force)
    write_private(Path(role.oath), oath_users(role, secret))
    return uri(secret, issuer=role.issuer, account=role.account)


def adopt(config: OpsConfig, secret: str) -> str:
    """Place an EXISTING secret (the user's Authenticator holds it) as the host's one secret; derive the users file.

    Returns what was done, never the secret.
    """
    role, path = _role(config), Path(secret_file(config))
    wrote = adopt_secret(path, secret)
    write_private(Path(role.oath), oath_users(role, path.read_text(encoding='utf-8')))
    return f'{"adopted" if wrote else "already held"}: {path} (600); {role.oath} derived from it (600)'


def ensure_include(stack: str) -> str | None:
    """*stack* (an sshd PAM file) with ``@include`` :data:`PAM_INCLUDE` above its first auth line; ``None`` if it is.

    The first auth line must be ``@include common-auth`` -- the Debian shape the include was written against; a
    stack of any other shape is refused, never guessed at.

    Raises:
        ValueError: the stack's first auth line is not ``@include common-auth``.

    """
    lines = stack.splitlines(keepends=True)
    ours = f'@include {PAM_INCLUDE}'
    auth = [n for n, line in enumerate(lines) if line.split()[:1] == ['auth'] or line.strip() == _COMMON_AUTH]
    if not auth or lines[auth[0]].strip() != _COMMON_AUTH:
        msg = f'{PAM_SSHD}: the first auth line is not `{_COMMON_AUTH}`; put `{ours}` above its auth stack by hand'
        raise ValueError(msg)
    first = auth[0]
    if any(line.strip() == ours for line in lines[:first]):
        return None
    if any(line.strip() == ours for line in lines[first:]):
        msg = f'{PAM_SSHD}: `{ours}` sits below `{_COMMON_AUTH}`, where it gates nothing; move it above'
        raise ValueError(msg)
    return ''.join([*lines[:first], f'{ours}\n', *lines[first:]])
