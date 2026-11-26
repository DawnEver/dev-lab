"""BRING-UP PREFLIGHT: every wall a new or migrated workstation hits, named with its door, BEFORE any code is asked.

``python -m dev_lab.dev.devhost bringup --check`` -- read only; one line per wall, exit 0 only when every one is
green. Measured on a workstation 2026-11-20 (the walls, in the order they were hit, then the order they are checked):

1. ``config-source`` -- the machine file names a config-source clone that exists here (``[devhost] source``);
2. ``enrollment`` -- the config source declares ``hosts/<this host>.toml`` (an undeclared machine renders the
   family default and is refused every write and HPC door, :mod:`dev_lab.dev.devprofile`);
3. ``bridge-interpreter`` -- the session bridge's interpreter is DERIVED from ``[repos] dev-lab``
   (:func:`dev_lab.dev.devprofile.bridge_python`) and exists; never a hand-set or invented path;
4. ``dev-lab-kit`` -- the ``[repos] dev-lab`` checkout lags the family's ``[dev] ref`` by no more than
   :data:`~dev_lab.dev.locklag.LAG_WINDOW`, THE one "current enough" (:func:`kit`): a stale kit is a wall, never a
   silent older behavior (2026-11-23);
5. ``machine-file`` -- the machine file is its render (:func:`dev_lab.dev.devhost.drift`);
6. ``client-key`` -- one of this machine's ssh public keys (``~/.ssh/*.pub``) is declared in its host file's
   ``[dev] client_keys``: the ONE place the approval servers derive their authorized keys from
   (:mod:`dev_lab.ops.clientkeys`);
7. ``issuer`` -- the consent issuer (``[consent] endpoint``) is reached with a known host key, admits this key, and
   speaks this client's version (:func:`dev_lab.ops.consent.door.handshake`): the break-glass account takes the
   same derived key set, so this one probe stands for both;
8. ``forge-credential`` -- every declared forge login has a stored credential (:func:`.forgecredential.drift`).

A wall whose door SPENDS A CODE says which (``code:``): the ``ops.config`` consent that applies a new client key on
the issuer, the consent that mints a forge token. Those are asked only once every no-code wall is green (the rule a
code is asked only after its preflight passes) -- so the output lists them last, in the order to ask.
"""

from __future__ import annotations

import subprocess
import tomllib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev import devprofile, devservers, familyrepos, forgecredential
from dev_lab.dev.devdeclared import OWN_TABLE, declared, declared_by
from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S
from dev_lab.dev.gitenv import unlocated
from dev_lab.dev.locklag import LAG_WINDOW, LOCAL_ONLY, Lag, hours, lag_of
from dev_lab.dev.relock import RelockFailed
from dev_lab.dev.venvpath import running_interpreter
from dev_lab.ops.clientkeys import DEV_KEY
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.door import Send, endpoint_send, handshake

__all__ = ['ADMIT_DOOR', 'HOST_KEY_DOOR', 'Wall', 'checkout_lag', 'kit', 'main', 'stale_kit', 'walls']

#: Where the issuer's ssh HOST key is declared and checked strictly (a sibling change: pr/toolchain/ssh-host-key).
HOST_KEY_DOOR: Final = (
    "the issuer's ssh host key is not known here: take it from the config source's declaration of the issuer's host "
    'key (never a trust-on-first-use prompt), then re-run'
)
#: The door that admits a declared key (:mod:`dev_lab.dev.devhostadmit`), run by ANOTHER machine's agent.
ADMIT_DOOR: Final = 'python -m dev_lab.dev.devhost admit --host {host}'


#: ``(checkout, ref)`` -> how far the checkout's HEAD lags ``origin/<ref>`` (:func:`.locklag.lag_of`); None: unread.
type Measure = Callable[[str, str], Lag | None]


def checkout_lag(checkout: str, ref: str) -> Lag | None:
    """:func:`~dev_lab.dev.locklag.lag_of` HEAD against ``origin/<ref>`` as last fetched, in *checkout*; None unread."""

    def git(*argv: str) -> subprocess.CompletedProcess[str]:
        return _door.run(
            [_GIT, '-C', checkout, *argv], capture_output=True, text=True, encoding='utf-8', errors='replace',
            check=False, timeout=_GIT_TIMEOUT_S, env={**unlocated(), **LOCAL_ONLY},
        )  # fmt: skip

    try:
        return lag_of(git, 'HEAD', f'origin/{ref}')
    except (RelockFailed, OSError):
        return None


def kit(checkout: str, ref: str, *, measure: Measure = checkout_lag) -> Wall:
    """The ``dev-lab-kit`` wall: red when the checkout lags *ref* past :data:`~dev_lab.dev.locklag.LAG_WINDOW`."""
    lag = measure(checkout, ref)
    if lag is None:
        return Wall('dev-lab-kit', green=False, said=f'{checkout} cannot be read as a git checkout of {ref}')
    said = f'{lag} behind origin/{ref} (window {hours(LAG_WINDOW)})'
    if not lag.past(LAG_WINDOW):
        return Wall('dev-lab-kit', green=True, said=said)
    pull = f'{running_interpreter()} -m dev_lab.dev.netverb -- git pull --ff-only'
    return Wall('dev-lab-kit', green=False, said=f'{said}: in {checkout}, {pull}, then uv sync --frozen')


def stale_kit(live: Mapping[str, Any], *, measure: Measure = checkout_lag) -> list[str]:
    """The SessionStart line of a ``dev-lab-kit`` wall on the machine whose *live* file is given; ``[]`` when none."""
    checkout = live.get(familyrepos.LOCAL_TABLE, {}).get(devprofile.BRIDGE_CHECKOUT)
    ref = declared_by(live.get(OWN_TABLE, {})).get('ref')
    lag = measure(str(checkout), str(ref)) if checkout and ref else None  # unread: bringup says so, not every session
    wall = kit(str(checkout), str(ref), measure=lambda _c, _r: lag) if lag is not None else None
    return [f'DEV-LAB-KIT STALE: {wall.said}'] if wall is not None and not wall.green else []


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


def _not_admitted(endpoint: str, host: str, *, declared: bool) -> str:
    """The door when the issuer refuses this key: declare it, or have it admitted from any admitted machine."""
    if not declared:
        return f"{endpoint} does not admit this machine's key: make client-key green and merged first, then admit it"
    door = ADMIT_DOOR.format(host=host)
    return (f"{endpoint} does not admit this machine's key: declared but not yet admitted. The door: the agent of ANY "
            f'machine the issuer already admits runs `{door}` (one ops.config code; it prints when to ask); then the '
            f'forge-credential mint here (`python -m dev_lab.dev.devhost enroll`) waits on it')  # fmt: skip


def _issuer(table: Mapping[str, Any], send: Send, host: str = '', *, declared: bool = False) -> Wall:
    """Reach, host key, authorization and version of the consent issuer, from ONE ``hello``."""
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
            door = _not_admitted(str(endpoint), host, declared=declared)
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
    live: Mapping[str, Any], *, ssh_dir: Path | None = None, send: Send = endpoint_send,
    exists: Callable[[str], bool] = lambda path: Path(path).is_file(),
    credential: Callable[[Mapping[str, Any]], list[str]] = forgecredential.drift, measure: Measure = checkout_lag,
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
        return [*found, Wall('enrollment', green=False, said=devprofile.enrollment(host))]
    found.append(Wall('enrollment', green=True, said=f'{host} is declared'))
    dev = declared(host_file, clone / 'family.toml')
    found.append(_interpreter(live, dev, exists))
    if (checkout := live.get(familyrepos.LOCAL_TABLE, {}).get(devprofile.BRIDGE_CHECKOUT)) and dev.get('ref'):
        found.append(kit(str(checkout), str(dev['ref']), measure=measure))
    drifted = devhost.drift(live, clone)
    found.append(Wall('machine-file', green=not drifted, said='; '.join(drifted) or 'is its render'))
    if not devservers.joins(dev):  # a declared opt-out: no key to authorize, no server or issuer to reach
        said = f'hosts/{host}.toml declares {devservers.OPT_OUT} = false: this machine joins no server'
        found += [Wall('client-key', green=True, said=said), Wall('issuer', green=True, said=said)]
    else:
        found.append(keyed := _client_key(host, host_file, ssh_dir or Path.home() / '.ssh'))
        family = tomllib.loads((clone / 'family.toml').read_text(encoding='utf-8'))
        consent = {**family.get('consent', {}), **live.get('consent', {})}  # a family fact stays home
        found.append(_issuer(consent, send, host, declared=keyed.green))
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
