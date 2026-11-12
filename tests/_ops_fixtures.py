"""Shared fixtures of the ``dev_lab.ops`` tests: a host config in a temp dir, and an origin declaring its branches."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from dev_lab.ops.config import OpsConfig, load
from dev_lab.ops.consent.credential import public_text
from dev_lab.ops.consent.issuer import keygen
from dev_lab.ops.totp import STEP, code_at

#: A fixed base32 secret (RFC 6238's test key, ``12345678901234567890``).
RFC_KEY = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'
NOW = 1_800_000_000.0
_GIT = shutil.which('git') or 'git'


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        [_GIT, *args], cwd=cwd, check=True, capture_output=True, text=True, encoding='utf-8', timeout=60
    )
    return done.stdout.strip()


def origin(tmp: Path, name: str = 'alpha') -> tuple[str, str]:
    """A bare origin *name* whose default branch ``main`` declares ``integrate/main``; its URL and integration tip."""
    work = tmp / f'{name}-work'
    work.mkdir()
    git(work, 'init', '-q', '-b', 'main')
    git(work, 'config', 'user.email', 't@t')
    git(work, 'config', 'user.name', 't')
    (work / 'pyproject.toml').write_text(
        '[tool.dev_lab.integrator]\nintegration = "integrate/main"\n', encoding='utf-8'
    )
    git(work, 'add', '.')
    git(work, 'commit', '-qm', 'init')
    git(work, 'checkout', '-qb', 'integrate/main')
    (work / 'x').write_text('x', encoding='utf-8')
    git(work, 'add', '.')
    git(work, 'commit', '-qm', 'next')
    bare = tmp / 'forge' / 'owner' / f'{name}.git'
    git(tmp, 'clone', '-q', '--bare', str(work), str(bare))
    return bare.as_uri(), git(work, 'rev-parse', 'HEAD')


#: The repos break-glass serves in :func:`config`: ONE NAME on two forges (a mirror), each forge's token named once.
GLASS = ('https://gitea.example/owner/alpha.git', 'https://github.com/owner/alpha.git')
#: Their identities, as a request names them.
ALPHA, MIRROR = 'gitea.example/owner/alpha', 'github.com/owner/alpha'


def config(tmp: Path, repos: list[str], *, extra: str = '', glass: tuple[str, ...] = GLASS) -> OpsConfig:
    """An ``[ops]`` config under *tmp* with promote, break-glass and the consent issuer, its secret and key made.

    Break-glass serves *glass*: one token file per Gitea host they name (``<tmp>/token-<host>``), and on GitHub the
    ops App (``<tmp>/app-github.com.pem``) -- GitHub refuses a standing token.
    """
    hosts = sorted({url.split('/')[2] for url in glass})
    tokens = ''.join(f'"{host}" = "{(tmp / f"token-{host}").as_posix()}"\n' for host in hosts if host != 'github.com')
    apps = ''.join(
        f'"{host}" = {{app_id = 4242, key_file = "{(tmp / f"app-{host}.pem").as_posix()}"}}\n'
        for host in hosts
        if host == 'github.com'
    )
    served = ', '.join(f'"{url}"' for url in glass)
    (tmp / 'totp').write_text(RFC_KEY + '\n', encoding='utf-8')
    published = public_text(keygen(tmp / 'consent.key', force=True).public_key())
    home = (tmp / 'home').as_posix()
    listed = ', '.join(f'"{url}"' for url in repos)
    text = f"""
[ops]
home = "{home}"
python = "/opt/ops/bin/python"
repos = [{listed}]
[ops.promote]
user = "promote"
schedule = "*-*-* 04:30:00 Europe/London"
credentials = "{(tmp / 'creds').as_posix()}"
[ops.breakglass]
account = "breakglass"
keys = ["ssh-ed25519 AAAA agent"]
repos = [{served}]
state = "{(tmp / 'state').as_posix()}"
log = "{(tmp / 'audit.log').as_posix()}"
{extra}
[ops.breakglass.tokens]
{tokens}
[ops.breakglass.apps]
{apps}
[ops.consent]
account = "consent"
totp = "{(tmp / 'totp').as_posix()}"
key = "{(tmp / 'consent.key').as_posix()}"
state = "{(tmp / 'consent-state').as_posix()}"
[ops.consent_client]
endpoint = "consent@localhost"
public_key = "{published}"
"""
    path = tmp / 'supervise.toml'
    path.write_text(text, encoding='utf-8')
    return load(path, environ={})


def code(offset: int = 0) -> str:
    """The valid code at :data:`NOW` shifted by *offset* steps."""
    return code_at(RFC_KEY, int(NOW // STEP) + offset)
