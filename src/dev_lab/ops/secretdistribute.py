"""``secretplace distribute --remote R``: a secret entered ONCE on this workstation, to every declaring account.

THE ONE SOURCE OF EACH FACT. The remote itself (endpoint, region, bucket) is the family's ``[storage.remotes.<R>]``;
WHICH machine reaches it is that machine's own ``[storage.reach.<R>] credentials_file`` (its host file, or an HPC
account's account file ``hosts/<cluster>-<user>.toml``); the secret's bytes are the file the person placed here with
``secretplace enter --remote R``. Nothing restates any of them: this door reads the config-source clone the machine
file names and the local credentials file, and writes only where an account DECLARES it reaches *R*.

* Accounts this machine reaches (:func:`dev_lab.dev.hpcaccount.division.reached_machine`) whose account file declares
  the reach get the same bytes over their own door (:func:`dev_lab.dev.hpcaccount.transport.grant_runner`: a held
  session or key-only ssh), mode 0600, the written file's sha256 compared with ours, then ``storage check R`` in the
  account's kit. An account that declares no reach is never written.
* Other machines that declare the reach (workstations) have no push channel: each is listed with its one door,
  ``secretplace enter --remote R`` run there by the person.
* One consent code covers the whole plan: the subject binds every (account, path) and the content's sha256, never the
  value; the value never reaches an argv, a log or the output (a sha256 prefix only).
"""

from __future__ import annotations

import hashlib
import json
import shlex
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lab_commons import config
from lab_commons.hpc.cluster import Runner
from lab_commons.hpc.grants import Grant

from dev_lab.dev.hpcaccount.division import reached_machine
from dev_lab.dev.hpcaccount.fleet import account_host, config_source_of, declared_target
from dev_lab.dev.hpcaccount.target import in_checkout
from dev_lab.dev.hpcaccount.transport import grant_runner
from dev_lab.ops.consent.client import grant, verify_held

__all__ = ['ACTION', 'Plan', 'Target', 'distribute', 'plan', 'run', 'subject']

#: The issuer already knows this action; the plan's subject (every target and the sha) is what makes it one grant.
ACTION: Final = 'ops.secret.place'


@dataclass(frozen=True)
class Target:
    """One account that declares it reaches the remote: its grant and its declared credentials file."""

    grant: Grant
    path: str


@dataclass(frozen=True)
class Plan:
    """Where the secret goes (accounts), and the machines that must run ``enter`` themselves."""

    remote: str
    accounts: tuple[Target, ...]
    by_hand: tuple[str, ...]
    unreached: tuple[str, ...] = ()


def _file(table: object) -> str:
    return str(table.get('credentials_file', '')) if isinstance(table, Mapping) else ''


def _reach(host_file: Path, remote: str, everyone: str) -> str:
    """The ``credentials_file`` *host_file*'s machine uses for *remote*: its own, else the family's *everyone*."""
    if not host_file.is_file():
        return ''
    reach = tomllib.loads(host_file.read_text(encoding='utf-8')).get('storage', {}).get('reach', {})
    return _file(reach.get(remote)) or everyone


def _everyone(clone: Path, remote: str) -> str:
    """The file every machine keeps *remote*'s key in when the family reaches it for all (``remotes.<r>.reach``)."""
    family = (
        tomllib.loads((clone / 'family.toml').read_text(encoding='utf-8')) if (clone / 'family.toml').is_file() else {}
    )
    return _file(family.get('storage', {}).get('remotes', {}).get(remote, {}).get('reach'))


def plan(remote: str, *, clone: Path, grants: Sequence[Grant], this_host: str) -> Plan:
    """Every machine reaching *remote* in the config-source *clone* (its own reach, or the family's for all)."""
    accounts, names, everyone = [], set(), _everyone(clone, remote)
    for reached in grants:
        name = account_host(reached)
        names.add(name)
        if path := _reach(clone / 'hosts' / f'{name}.toml', remote, everyone):
            accounts.append(Target(reached, path))
    rest = [file for file in sorted((clone / 'hosts').glob('*.toml')) if file.stem not in names | {this_host}]
    reaching = [file for file in rest if _reach(file, remote, everyone)]
    kinds = {file.stem: tomllib.loads(file.read_text(encoding='utf-8')) for file in reaching}
    by_hand = tuple(name for name, table in kinds.items() if 'dev' in table and 'deploy' not in table)
    unreached = tuple(name for name, table in kinds.items() if 'deploy' in table)
    return Plan(remote, tuple(accounts), by_hand, unreached)


def subject(work: Plan, content: bytes) -> str:
    """The consent subject of *work*: every (account, path) and the content's sha256 -- never the value."""
    rows = sorted(f'{t.grant.user}:{t.path}' for t in work.accounts)
    text = '\n'.join([ACTION, work.remote, *rows, f'sha256={hashlib.sha256(content).hexdigest()}'])
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _write_command(path: str) -> str:
    """The POSIX line that writes stdin at *path* (``~`` = the account's home), 0600, atomically; prints its sha."""
    remote = '"$HOME"/' + shlex.quote(path[2:]) if path.startswith('~/') else shlex.quote(path)
    return (
        f'set -e; umask 077; p={remote}; mkdir -p "$(dirname "$p")"; cat > "$p.placing"; '
        'chmod 600 "$p.placing"; mv -f "$p.placing" "$p"; sha256sum "$p" | cut -c1-64'
    )


def distribute(
    work: Plan, content: bytes, *, connect: Callable[[Grant], Runner], say: Callable[[str], None],
) -> int:  # fmt: skip
    """Place *content* on every planned account and check it there; 0 when every account agrees, else 2."""
    digest = hashlib.sha256(content).hexdigest()
    failed = 0
    for target in work.accounts:
        user = target.grant.user
        try:
            shell = connect(target.grant)
            written = shell(_write_command(target.path), content.decode('utf-8')).strip().split()[-1:]
        except (RuntimeError, OSError, ValueError) as refused:
            say(f'{user}: refused -- {refused}')
            failed += 1
            continue
        if written != [digest]:
            say(f'{user}: refused -- the written {target.path} does not hash to the entered secret')
            failed += 1
            continue
        said = _check(shell, target.grant, work.remote)
        say(f'{user}: placed {target.path} (sha256 {digest[:12]}, 0600); {said}')
    for host in work.by_hand:
        say(f'{host}: a workstation, no push channel -- its person runs there: '
            f'python -m dev_lab.ops.secretplace enter --remote {work.remote}')  # fmt: skip
    for account in work.unreached:
        say(f'{account}: an account this session does not reach (its role: hpcaccount.session status) -- run '
            f'distribute again from a session that reaches it')  # fmt: skip
    return 2 if failed else 0


def _check(shell: Runner, grant: Grant, remote: str) -> str:
    """``storage check`` in the account's kit; its answer, or why it could not run (never fatal to the placement)."""
    target = declared_target(grant, shell)
    if isinstance(target, str):
        return f'check skipped: {target}'
    try:
        return shell(in_checkout(target, ['-m', 'dev_lab.dev.storage', 'check', remote]), None).strip().splitlines()[-1]
    except (RuntimeError, OSError, IndexError) as failed:
        return f'check refused: {failed} (the account kit needs dev_lab.dev.storage check: redeploy it)'


def run(remote: str, content: bytes, *, requests: Path, say: Callable[[str], None]) -> int:
    """The verb: plan from this machine's declarations, show it, one consent code, distribute, report per account."""
    live = config.machine()
    work = plan(remote, clone=config_source_of(live).clone, grants=reached_machine().grants,
                this_host=str(live.get('devhost', {}).get('host', '')))  # fmt: skip
    for target in work.accounts:
        say(f'[ops secret] plan: {target.grant.user} <- {target.path}')
    wanted = subject(work, content)
    asked = requests / f'secret-{remote}-distribute.request.json'
    asked.parent.mkdir(parents=True, exist_ok=True)
    asked.write_text(json.dumps({'action': ACTION, 'subject': wanted}), encoding='utf-8')
    say(f'[ops secret] {remote}: content sha256 {hashlib.sha256(content).hexdigest()[:12]}; request {asked}')
    if work.accounts:
        verify_held(grant(asked, ask=input).stem, action=ACTION, subject=wanted)
    return distribute(work, content, connect=grant_runner, say=say)
