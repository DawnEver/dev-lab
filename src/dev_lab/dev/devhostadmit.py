"""``devhost admit --host <machine>``: put a DECLARED client key into the issuer, from ANY machine it already admits.

User ruling 2026-11-23: a key declared in the config source (``hosts/<machine>.toml`` ``[dev] client_keys``) reaches
the consent issuer and the break-glass login only when the issuer host applies that source -- a boundary change,
so ONE user code. Every new machine and every key rotation needs it, and nothing said who could do it: the machine
being admitted cannot reach the issuer yet, so its agent concluded a person must log in on the forge host. This door
is that step, run by the agent of any machine the issuer already admits:

1. it reads the machine's declared keys at the config source's main (none: the ``client-key`` wall comes first);
2. it finds the issuer's host file in the config-source clone (the one host file declaring ``[ops.consent]``) and the
   ``config apply *`` sudo line of its ``[ops.access]`` login (:func:`.forgeenrol.ops_door`);
3. it asks the issuer for the subject its host derives (the read-only ``subject`` verb, no code): the issuer's
   standing :data:`~dev_lab.ops.configdoor.UNCHANGED` means its live file already IS main -- nothing to admit, no
   plan; a subject other than the one derived HERE through the same function ``planrun`` checks
   (:func:`.planrunpreflight.config_subject`) is refused before a plan exists;
4. it writes the one-grant ``ops.config`` plan and its steps file, preflights them (no code), and only when green
   prints ``ask the user for one code`` with the two lines that spend it.

The applied config renders the key files in the same step (:mod:`dev_lab.ops.configverbs`): no ``install`` follows.
"""

from __future__ import annotations

import argparse
import json
import tomllib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from lab_commons.log import emit

from dev_lab.dev import devhost
from dev_lab.dev.forgeenrol import EnrolRefused, ops_door
from dev_lab.dev.planremote import remote_for
from dev_lab.dev.planrunoffer import offered
from dev_lab.dev.planrunpreflight import UNREAD, Readers, config_subject, preflight
from dev_lab.dev.planrunsteps import load_steps
from dev_lab.dev.venvpath import running_interpreter
from dev_lab.ops import configdoor
from dev_lab.ops.clientkeys import DEV_KEY
from dev_lab.ops.consent.plan import DIGEST_SHOWN, digest
from dev_lab.ops.consent.plan import load as load_plan

__all__ = ['add_admit', 'offer', 'run']

_ACTION: Final = configdoor.ACTION
_APPLY: Final = ('config', 'apply')

#: Preflights a written plan and steps file with no code: ``(green, lines)``.
type Check = Callable[[Path, Path], tuple[bool, list[str]]]


def _issuer_file(clone: Path) -> Path:
    found = []
    for path in sorted((clone / 'hosts').glob('*.toml')):
        try:
            if tomllib.loads(path.read_text(encoding='utf-8')).get('ops', {}).get('consent'):
                found.append(path)
        except (OSError, tomllib.TOMLDecodeError):
            continue
    if len(found) != 1:
        msg = f'{len(found)} host files under {clone / "hosts"} declare [ops.consent]; the issuer host must be one'
        raise EnrolRefused(msg)
    return found[0]


def _keys(machine: str, source: str, readers: Readers) -> list[str]:
    where = devhost.host_file(machine)
    declared = tomllib.loads(readers.text(source, where, 'main')).get('dev', {}).get(DEV_KEY, [])
    if not declared:
        msg = (f'{where} at main declares no [dev] {DEV_KEY}: on {machine}, `devhost bringup --check` names the line '
               'to propose (the client-key wall) -- merge it, then admit')  # fmt: skip
        raise EnrolRefused(msg)
    return list(declared)


def offer(
    *, machine: str, clone: Path, endpoint: str, readers: Readers, out: Path, check: Check,
    say: Callable[[str], None] = emit,
) -> int:  # fmt: skip
    """The door of the module docstring; 0 when a green plan is offered or nothing is owed, 2 when refused."""
    try:
        source = readers.config_source()
        keys = _keys(machine, source, readers)
        issuer = _issuer_file(clone)
        door = ops_door(issuer, _APPLY)
        dest = f'{door.account}@{endpoint.rpartition("@")[2]}'
        asked, standing = readers.issued(dest, _ACTION, list(_APPLY))
        if standing == configdoor.UNCHANGED:
            say(f'admit: nothing to admit -- {dest} already runs the config source main, which declares {machine} '
                f'({len(keys)} key(s)); if it still refuses that key, its key files predate the apply that renders '
                'them: the next config change renders them')  # fmt: skip
            return 0
        if standing is not None:
            say(f'admit: refused, no code asked -- {dest} would refuse the apply as it stands: {standing}')
            return 2
        derived = config_subject(issuer.stem, readers.text, source, listed=readers.listed)
    except (EnrolRefused, configdoor.ConfigRefused, *UNREAD) as refused:
        say(f'admit: refused, no code asked -- {refused}')
        return 2
    if asked != derived:
        say(f'admit: refused, no code asked -- {dest} derives {asked[:12]} but {source} main derives {derived[:12]} '
            f'here: upgrade or reconcile {issuer.stem} first')  # fmt: skip
        return 2
    plan = {'hosts': [dest], 'grants': [{'host': dest, 'action': _ACTION, 'subject': derived}]}
    steps = {'config': door.config, 'python': door.python,
             'steps': [{'argv': list(_APPLY), 'config_host': issuer.stem}]}  # fmt: skip
    out.mkdir(parents=True, exist_ok=True)
    plan_path, steps_path = out / f'admit-{machine}.plan.json', out / f'admit-{machine}.steps.json'
    plan_path.write_text(json.dumps(plan, indent=1) + '\n', encoding='utf-8')
    steps_path.write_text(json.dumps(steps, indent=1) + '\n', encoding='utf-8')
    green, lines = check(plan_path, steps_path)
    for line in lines:
        say(line)
    if not green:
        say('admit: preflight BLOCKED -- fix the blocker above; no code asked')
        return 2
    shown, python = digest(plan)[:DIGEST_SHOWN], running_interpreter()
    say(f'admit: plan {plan_path} applies {source} main on {dest} (admits {machine}): ask the user for one code, then '
        f'{python} -m dev_lab.dev.sshhold open --hours 1 --plan {plan_path} --digest {shown} --code <the code>; '
        f'{python} -m dev_lab.dev.planrun run --plan {plan_path} --digest {shown} --steps {steps_path}')  # fmt: skip
    return 0


def add_admit(verbs: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``admit`` verb on *verbs* (the ``devhost`` subparsers)."""
    admitting = verbs.add_parser('admit', help='author and preflight the one-code plan admitting a declared key')
    admitting.add_argument('--host', required=True, help='the machine whose declared key the issuer should admit')


def run(args: argparse.Namespace, live: Mapping[str, Any], own: Mapping[str, Any]) -> int:
    """``devhost admit``: :func:`offer` with this machine's clone, issuer and the real preflight."""
    if not own.get('source'):
        emit('admit: refused, no code asked -- the machine file names no config-source clone: devhost render --write')
        return 2
    clone = Path(own['source'])
    family = tomllib.loads((clone / 'family.toml').read_text(encoding='utf-8'))
    endpoint = str({**family.get('consent', {}), **live.get('consent', {})}.get('endpoint') or '')

    def check(plan_path: Path, steps_path: Path) -> tuple[bool, list[str]]:
        shown = digest(json.loads(plan_path.read_text(encoding='utf-8')))
        plan = load_plan(plan_path, shown)
        return offered(plan, preflight(plan, load_steps(steps_path, plan), remote_for), steps=steps_path)

    out = Path('output/logs') / f'{datetime.now(UTC):%y/%m/%d}' / 'consent'
    return offer(machine=args.host, clone=clone, endpoint=endpoint, readers=Readers(), out=out, check=check)
