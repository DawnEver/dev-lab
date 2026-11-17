"""The paths ``ops install`` prepares on a host: homes, credentials and secrets, owned and narrowed.

Split out of :mod:`dev_lab.ops.install` (2026-11-10, MODULE-SIZE-ALARM): that module renders and writes the
files; this one decides who owns the paths around them. It NEVER re-owns or widens a directory it did not create,
and what it cannot apply here is a next step.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dev_lab.ops.access import KEYS_DIR
from dev_lab.ops.accounts import account_of, may_enter
from dev_lab.ops.config import OpsConfig

__all__ = ['Chown', 'keys_dir', 'prepare_paths', 'under']

#: Change a path's owner and/or group (``shutil.chown``'s shape); ``LookupError`` when the account does not exist.
type Chown = Callable[[Path, str | None, str | None], None]


def under(root: Path, path: Path | str) -> Path:
    """*path* (absolute, as declared) re-rooted under *root*, the tree install writes into."""
    return root / Path(path).relative_to(Path(path).anchor)


def _may_enter(path: Path, user: str) -> bool:
    found = path.stat()
    return may_enter(found.st_mode, found.st_uid, found.st_gid, account_of(user))


def _own(chown: Chown | None, path: Path, user: str | None, group: str | None) -> bool:
    """Apply the ownership when it can be applied here; ``False`` leaves it to a next step."""
    if chown is None or not path.exists():
        return False
    try:
        chown(path, user, group)
    except LookupError:
        return False
    return True


def keys_dir(root: Path, chown: Chown | None, done: dict[str, str]) -> list[str]:
    """Create :data:`KEYS_DIR` (root's, 0755) when absent; an existing one is the host's, never re-owned."""
    keys = under(root, KEYS_DIR)
    if keys.is_dir():
        done[keys.relative_to(root).as_posix()] = 'unchanged'
        return []
    done[keys.relative_to(root).as_posix()] = 'created'
    keys.mkdir(parents=True)
    keys.chmod(0o755)
    return [] if _own(chown, keys, 'root', 'root') else [f'chown root:root {KEYS_DIR}']


def prepare_paths(config: OpsConfig, root: Path, chown: Chown | None) -> tuple[dict[str, str], list[str]]:
    """Create the clone home (only if absent), hand the promote user it and the credential, make the env file root's."""
    done: dict[str, str] = {}
    steps: list[str] = []
    if (role := config.promote) is not None:
        home = under(root, config.home)
        if home.is_dir():  # an existing directory is the host's; install never re-owns or widens it
            done[home.relative_to(root).as_posix()] = 'unchanged'
        else:
            done[home.relative_to(root).as_posix()] = 'created'
            home.mkdir(parents=True)
            home.chmod(0o750)
            if not _own(chown, home, role.user, role.user):
                steps.append(f'chown {role.user}:{role.user} {config.home.as_posix()}')
        credential = under(root, role.credentials)
        if credential.is_file():
            credential.chmod(0o600)
        if not _own(chown, credential, role.user, None):
            steps.append(f'chown {role.user} {role.credentials} && chmod 600 {role.credentials}')
        steps += _entered(root, role.credentials, role.user)
    if (judge := config.judge) is not None:
        for secret in judge.secrets:
            steps += _private(root, chown, secret, judge.user) + _entered(root, secret, judge.user)
    # every root-only host secret takes the one narrowing: the environment files and the judge's key bundle
    root_only = [config.environment_file, *((judge.environment_file, judge.keys_file) if judge is not None else ())]
    for environment in filter(None, root_only):
        steps += _private(root, chown, environment, 'root', 'root')
    return done, steps


def _entered(root: Path, declared: str, user: str) -> list[str]:
    """The remedy when *user* cannot enter the directory holding *declared*: install never opens one it did not make."""
    parent = under(root, declared).parent
    if not parent.is_dir() or _may_enter(parent, user):
        return []
    where = Path(declared).parent.as_posix()
    return [f'{user} cannot enter {where}: chown root:{user} {where} && chmod 750 {where}, or move the file out of it']


def _private(root: Path, chown: Chown | None, declared: str, user: str, group: str | None = None) -> list[str]:
    """Narrow *declared* to 0600 and hand it to *user*; what could not be applied is a next step."""
    found = under(root, declared)
    if found.is_file():
        found.chmod(0o600)
    if _own(chown, found, user, group):
        return []
    return [f'chown {user}{f":{group}" if group else ""} {declared} && chmod 600 {declared}']
