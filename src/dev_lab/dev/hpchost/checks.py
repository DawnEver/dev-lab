"""What a fresh account must have before a tick can run on it -- each read free of side effects, each refusal a fix.

Measured 2026-10-12 deploying three accounts on one cluster: every one of these passed the old deploy
(which only ran ``git ls-remote``) and then failed every tick.

* THE FORGE API. A token that reads repositories over git can still be refused by the API, and a tick
  lives on the API. That check is the forge's (``python -m dev_lab.dev.forge auth check``,
  :func:`dev_lab.dev.forgeauth.tick_refusal`); the deploy runs it as a subprocess, as a person runs it.
* THE CREDENTIAL STORE (:func:`store_problem`). A tick reads its token through git's credential helper;
  no helper means no token, and a ``store`` file another user can read is a leaked token.
* THE TOOLS (:func:`tool_plan`). ``uv`` always, plus every ``needs`` a served repo declares. Present is
  CAPABILITY, not lookup (:func:`runs`): ``<tool> --version`` exits 0 in the TICK'S environment (cron's
  PATH, then the grant setup) -- a rustup shim with no toolchain is on the PATH and is not a cargo.
  ``uv`` and the Rust toolchain come from their OFFICIAL installers into ``~/.local/bin`` and
  ``~/.cargo/bin`` -- user-space and removable; the installers edit no shell file, and ``cmake`` comes
  through ``uv tool``. Anything else is the cluster's to provide, so it is refused by name.
* ONE LOGIN ENVIRONMENT (:func:`login_files`, :func:`login_line`). The tick's PATH names those two
  directories; the account's login shell must too, or a tool runs for cron and not for its person (Ada
  2026-10-25: three accounts had cargo only for cron). The deploy writes one marked line into the files
  bash reads, once, backing each up first.
* THE SERVE'S GIT (:func:`merge_tree_refusal`). Every serve tick's trial merge runs
  ``git merge-tree --write-tree`` (git >= 2.38); cron's ``/usr/bin/git`` can be older (Ada 2026-10-17:
  2.31.1, every tick refused with merge-tree's usage). The floor is PROVEN on a toy repository, never read
  from ``--version`` -- a vendor build's version string is not the capability.
* THE GRANT (:func:`grant_of`). A tick on a cluster needs this account's own ``[[hpc.grant]]``
  (:mod:`lab_commons.hpc.grants`): the user from ``id -un``, the account and its CPU limit from
  ``sacctmgr``, this host, and the partitions the deployment declares (a partition list is a choice,
  not a fact Slurm can answer).
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door

from dev_lab.dev.hpchost.spec import Deployment, tick_dirs

__all__ = [
    'INSTALLERS',
    'LOGIN_MARK',
    'MERGE_TREE_GIT',
    'grant_of',
    'login_files',
    'login_line',
    'merge_tree_refusal',
    'runs',
    'store_problem',
    'tool_plan',
]

#: The git every serve tick needs: its trial merge (:mod:`dev_lab.dev.trialmerge`) and ``integrate``.
MERGE_TREE_GIT: Final = 'git >= 2.38 (`git merge-tree --write-tree`, the serve tick trial merge)'

_TREE: Final = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')
_PROBE_TIMEOUT_S: Final = 60

#: The official, user-space installer of each tool the deploy may install itself, in install order.
INSTALLERS: Final = {
    'uv': 'curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh',
    'cargo': "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path",
    'rustc': "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path",
    'cmake': 'uv tool install cmake',
}

_PRIVATE: Final = 0o077

#: The marker of the one line the deploy writes into a login file; its presence means the line is there.
LOGIN_MARK: Final = '# lab-commons-deploy:path'


def runs(sh: Sequence[str], environment: str, tool: str) -> bool:
    """Whether ``<tool> --version`` exits 0 under the shell prefix *environment*, run through the *sh* argv."""
    try:
        done = _door.run(
            [*sh, f'{environment}; {shlex.quote(tool)} --version'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=_PROBE_TIMEOUT_S,
            check=False,
        )
    except OSError:
        return False
    return done.returncode == 0


def login_files(home: Path) -> list[Path]:
    """The files bash reads: the first of its login files that exists (else ``.bash_profile``), and ``.bashrc``.

    Creating ``.bash_profile`` beside an existing ``.profile`` would shadow it, so an existing one is used.
    """
    login = ('.bash_profile', '.bash_login', '.profile')
    first = next((home / name for name in login if (home / name).exists()), home / login[0])
    return [first, home / '.bashrc']


def login_line(home: Path) -> str:
    """The marked line that puts the tick PATH's user-install directories first in a login shell."""
    return f'export PATH="{":".join(tick_dirs(home)[:2])}:$PATH" {LOGIN_MARK}'


def store_problem(helper: str, store: Path, *, mode: int | None) -> str:
    """Why git's credential helper cannot hand a tick its token; ``''`` when it can. *mode* is *store*'s, if any."""
    if not helper:
        return (
            'git has no credential helper, so a tick has no token: '
            '`git config --global credential.helper store`, then `python -m dev_lab.dev.forge auth login`'
        )
    if helper.split(maxsplit=1)[0] != 'store':
        return ''  # another helper keeps its secret elsewhere
    if mode is None:
        return f'{store} is missing: `python -m dev_lab.dev.forge auth login` stores the token there'
    if mode & _PRIVATE:
        return f'{store} is readable by others (mode {mode:o}): `chmod 600 {store}`'
    return ''


def merge_tree_refusal(git: Sequence[str], scratch: Path) -> str:
    """``''`` when *git* writes a merge tree of a toy repository made under *scratch*; else why not, as evidence."""
    toy = str(scratch / 'merge-tree-probe')
    who = ('-c', 'user.name=probe', '-c', 'user.email=probe@invalid')
    steps = {
        'init': ('init', '-q', toy),
        'commit': ('-C', toy, *who, 'commit', '-q', '--allow-empty', '-m', 'probe'),
        'merge-tree --write-tree': ('-C', toy, 'merge-tree', '--write-tree', 'HEAD', 'HEAD'),
    }
    name = ' '.join(git)
    done = None
    for label, args in steps.items():
        try:
            done = _door.run(
                [*git, *args],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=_PROBE_TIMEOUT_S,
                check=False,
            )
        except OSError as why:
            return f'{name} does not run: {why}'
        if done.returncode:
            said = (done.stderr.strip() or done.stdout.strip()).splitlines()
            return f'{name} {label} exited {done.returncode}: {said[0] if said else ""}'
    first = done.stdout.strip().splitlines()[:1] if done else []
    return '' if first and _TREE.fullmatch(first[0]) else f'{name} merge-tree --write-tree wrote no tree: {first}'


def tool_plan(needs: Iterable[str], *, found: Callable[[str], bool]) -> tuple[list[tuple[str, str]], list[str]]:
    """``(installs, refused)``: ``uv`` and each of *needs* not *found*, as ``(tool, installer)`` or refused by name."""
    installs: list[tuple[str, str]] = []
    refused: list[str] = []
    for tool in dict.fromkeys(['uv', *needs]):
        if found(tool):
            continue
        script = INSTALLERS.get(tool)
        if script is None:
            refused.append(tool)
        elif script not in {s for _t, s in installs}:
            installs.append((tool, script))
    return installs, refused


def grant_of(user: str, sacct: str, *, spec: Deployment, host: str) -> dict[str, Any] | str:
    """The account's ``[[hpc.grant]]`` from ``sacctmgr -nP show assoc ... format=account,grptres``; else why not."""
    if not spec.partitions:
        return (
            'declare the partitions its grant may use: --partition <name> (repeatable; partitions = [...] in [deploy])'
        )
    limits: dict[str, str] = {}
    for line in sacct.splitlines():
        account, _, tres = line.strip().partition('|')
        if account:
            limits.setdefault(account, tres)
    if not limits:
        return f'no Slurm association for {user} (sacctmgr show assoc): the cluster has given this account none'
    if spec.slurm_account:
        if spec.slurm_account not in limits:
            return f"[deploy] slurm_account {spec.slurm_account!r} is not one of {user}'s: {', '.join(limits)}"
        account = spec.slurm_account
    elif len(limits) > 1:
        return f'{user} has several Slurm accounts ({", ".join(limits)}): declare one with --slurm-account <account>'
    else:
        (account,) = limits
    return {
        'user': user,
        'hosts': [host],
        'slurm_account': account,
        'partitions': list(spec.partitions),
    }
