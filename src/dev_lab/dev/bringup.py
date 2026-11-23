"""BRING-UP PREFLIGHT: every wall a new or migrated workstation hits, named with its door, BEFORE any code is asked.

``python -m dev_lab.dev.devhost bringup --check`` -- read only; one line per wall, exit 0 only when every one is
green. Measured on a workstation 2026-11-20 (the walls, in the order they were hit, then the order they are checked):

1. ``config-source`` -- the machine file names a config-source clone that exists here (``[devhost] source``);
2. ``enrolment`` -- the config source declares ``hosts/<this host>.toml`` (an undeclared machine renders the
   family default and is refused every write and HPC door, :mod:`dev_lab.dev.devprofile`);
3. ``bridge-interpreter`` -- the session bridge's interpreter is DERIVED from ``[repos] dev-lab``
   (:func:`dev_lab.dev.devprofile.bridge_python`) and exists; never a hand-set or invented path;
4. ``machine-file`` -- the machine file is its render (:func:`dev_lab.dev.devhost.drift`);
5. ``client-key`` -- one of this machine's ssh public keys (``~/.ssh/*.pub``) is declared in its host file's
   ``[dev] client_keys``: the ONE place the approval servers derive their authorised keys from
   (:mod:`dev_lab.ops.clientkeys`);
6. ``issuer`` -- the consent issuer (``[consent] endpoint``) is reached with a known host key, admits this key, and
   speaks this client's version (:func:`dev_lab.ops.consent.door.handshake`): the break-glass account takes the
   same derived key set, so this one probe stands for both;
7. ``forge-credential`` -- every declared forge login has a stored credential (:func:`.forgecredential.drift`).

A wall whose door SPENDS A CODE says which (``code:``): the ``ops.config`` consent that applies a new client key on
the issuer, the consent that mints a forge token. Those are asked only once every no-code wall is green (the rule a
code is asked only after its preflight passes) -- so the output lists them last, in the order to ask.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from lab_commons.log import emit

from dev_lab.dev import devprofile, familyrepos, forgecredential
from dev_lab.dev.devdeclared import OWN_TABLE, declared
from dev_lab.dev.venvpath import running_interpreter
from dev_lab.ops.clientkeys import DEV_KEY
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.door import Send, handshake, ssh_send

__all__ = ['HOST_KEY_DOOR', 'ISSUER_DEPLOY', 'Wall', 'main', 'walls']

#: Where the issuer's ssh HOST key is declared and checked strictly (a sibling change: pr/toolchain/ssh-host-key).
HOST_KEY_DOOR: Final = (
    "the issuer's ssh host key is not known here: take it from the config source's declaration of the issuer's host "
    'key (never a trust-on-first-use prompt), then re-run'
)
#: The deploy step on the issuer host that installs the derived client keys (:mod:`dev_lab.ops.clientkeys`).
ISSUER_DEPLOY: Final = (
    'on the issuer host, through its ops login: `ops --config /etc/dev-lab/supervise.toml config apply --credential '
    '<file>` (an ops.config consent for the subject `planrun subject --config <issuer host>` derives), then '
    '`ops --config /etc/dev-lab/supervise.toml install` writes the break-glass and consent key files'
)


#: ssh's exit status when it could not reach the host at all (no route, timeout, refused authentication).
_SSH_UNREACHED: Final = 255


@dataclass(frozen=True)
class Wall:
    """One bring-up check: *name*, whether *green*, what was found or its door (*said*), the *code* it spends."""

    name: str
    green: bool
    said: str
    code: str = ''


def _public_keys(ssh_dir: Path) -> tuple[str, ...]:
    """The machine's ssh public key lines, without their comments (``<type> <base64>``)."""
    found = []
    for pub in sorted(ssh_dir.glob('*.pub')) if ssh_dir.is_dir() else ():
        kind, *rest = pub.read_text(encoding='utf-8', errors='replace').split() or ['']
        if rest:  # a key line is "<type> <base64> [comment]"
            found.append(f'{kind} {rest[0]}')
    return tuple(found)


def _bare(key: str) -> str:
    return ' '.join(key.split()[:2])


def _issuer(table: Mapping[str, Any], send: Send) -> Wall:
    """Reach, host key, authorisation and version of the consent issuer, from ONE ``hello``."""
    endpoint = table.get('endpoint')
    if not endpoint:
        return Wall('issuer', green=False, said='the family file declares no [consent] endpoint')
    answers: list[tuple[int, str]] = []

    def once(t: Mapping[str, Any], request: dict[str, Any]) -> tuple[int, str]:
        if not answers:
            answers.append(send(t, request))
        return answers[0]

    try:
        runs = handshake(table, send=once)
    except ConsentRefused as refused:
        status, said = answers[0] if answers else (0, '')
        if 'Host key verification failed' in said or 'REMOTE HOST IDENTIFICATION HAS CHANGED' in said:
            return Wall('issuer', green=False, said=HOST_KEY_DOOR)
        if 'Permission denied' in said:
            door = f"{endpoint} does not admit this machine's key: once client-key is green and merged, {ISSUER_DEPLOY}"
            return Wall('issuer', green=False, said=door, code='ops.config')
        if status == _SSH_UNREACHED:
            return Wall('issuer', green=False, said=f'{endpoint} is not reached ({said[-200:]}): fix the network path')
        return Wall('issuer', green=False, said=str(refused))
    said = f'its dev-lab is {runs[:12]}' if runs else 'it reports no dev-lab commit (older than that report)'
    return Wall('issuer', green=True, said=f'{endpoint} admits this key and speaks this version; {said}')


def _interpreter(live: Mapping[str, Any], dev: Mapping[str, Any], exists: Callable[[str], bool]) -> Wall:
    try:
        python = devprofile.bridge_python(live, str(dev.get('os', '')))
    except ValueError as unset:
        return Wall('bridge-interpreter', green=False, said=str(unset))
    if exists(python):
        return Wall('bridge-interpreter', green=True, said=python)
    checkout = live.get(familyrepos.LOCAL_TABLE, {}).get(devprofile.BRIDGE_CHECKOUT)
    door = f'{python} does not exist: {running_interpreter()} -m dev_lab.dev.dep --bootstrap "{checkout}"'
    return Wall('bridge-interpreter', green=False, said=door)


def _client_key(host: str, host_file: Path, ssh_dir: Path) -> Wall:
    mine = _public_keys(ssh_dir)
    declared_keys = tomllib.loads(host_file.read_text(encoding='utf-8')).get('dev', {}).get(DEV_KEY, [])
    held = {_bare(key) for key in declared_keys}
    if ours := [key for key in mine if key in held]:
        return Wall('client-key', green=True, said=f'{ours[0]} is declared')
    offer = mine[0] if mine else '<run ssh-keygen -t ed25519 first>'
    door = (f"hosts/{host}.toml declares none of this machine's keys: add [dev] {DEV_KEY} = "
            f'["{offer} <comment>"] -- {devprofile.PROPOSE}')  # fmt: skip
    return Wall('client-key', green=False, said=door)


def walls(
    live: Mapping[str, Any], *, ssh_dir: Path | None = None, send: Send = ssh_send,
    exists: Callable[[str], bool] = lambda path: Path(path).is_file(),
    credential: Callable[[Mapping[str, Any]], list[str]] = forgecredential.drift,
) -> list[Wall]:  # fmt: skip
    """Every bring-up wall of the machine whose *live* file is given, in order; each later wall needs the earlier."""
    from dev_lab.dev import devhost  # noqa: PLC0415 -- devhost wires this verb, so the import is at call time

    own = live.get(OWN_TABLE, {})
    clone = Path(own['source']) if own.get('source') else None
    host = own.get('host') or ''
    if clone is None or not (clone / 'family.toml').is_file():
        door = f'no config-source clone here: {familyrepos.SET_DOOR}, then {devhost.RENDER_DOOR} --from <clone>'
        return [Wall('config-source', green=False, said=door)]
    found = [Wall('config-source', green=True, said=clone.as_posix())]
    host_file = clone / devhost.host_file(host)
    if not host_file.is_file():
        return [*found, Wall('enrolment', green=False, said=devprofile.enrolment(host))]
    found.append(Wall('enrolment', green=True, said=f'{host} is declared'))
    dev = declared(host_file, clone / 'family.toml')
    found.append(_interpreter(live, dev, exists))
    drifted = devhost.drift(live, clone)
    found.append(Wall('machine-file', green=not drifted, said='; '.join(drifted) or 'is its render'))
    found.append(_client_key(host, host_file, ssh_dir or Path.home() / '.ssh'))
    family = tomllib.loads((clone / 'family.toml').read_text(encoding='utf-8'))
    found.append(_issuer({**family.get('consent', {}), **live.get('consent', {})}, send))  # a family fact stays home
    missing = credential(dev)
    said = '; '.join(missing) or 'every declared login is stored'
    found.append(Wall('forge-credential', green=not missing, said=said, code='forge.token' if missing else ''))
    return found


def report(found: Iterable[Wall]) -> int:
    """Print each wall, then the code-spending doors in order; 0 only when every wall is green."""
    found = list(found)
    for wall in found:
        emit(f'{"green" if wall.green else "WALL "} {wall.name}: {wall.said}')
    blocked = [wall for wall in found if not wall.green]
    free = [wall for wall in blocked if not wall.code]
    coded = [wall for wall in blocked if wall.code]
    if coded:
        when = 'after the walls above are green' if free else 'now: every no-code wall is green'
        emit(f'codes, {when}, in order: ' + '; '.join(f'{wall.code} for {wall.name}' for wall in coded))
    emit('bringup: GREEN' if not blocked else f'bringup: {len(blocked)} wall(s) -- fix the no-code ones first')
    return 0 if not blocked else 1


def main(live: Mapping[str, Any]) -> int:
    """``devhost bringup --check``: :func:`walls` of this machine, reported."""
    return report(walls(live))
