"""MACHINES-MEET-ONLY-THROUGH-THE-FORGE: no development machine's host file declares a route to another one.

WHY. Development machines (host files with a ``[dev]`` table) share work through origin and the forge only: an
author pushes, a producer verifies pushed shas and posts statuses, the forge merges. A host that reaches another
development machine directly (ssh, a jump through it, a pinned host key for it) has made that machine a channel
-- work handed over outside every record the forge keeps. One family repo's user ruled it after a session probed
the workstations over ssh to hand them a workload.

THE MECHANISM. :func:`route_defects` reads every host file's declared routes -- ``[ssh] jump`` destinations and
bastions, ``[ssh] host_keys`` endpoints, and the ``endpoint`` of any table that declares one -- and refuses each
that names a development machine other than the declaring one. A machine is known by its file's stem, its
``[dev] hostname`` and the host part of each ``[dev] client_keys`` comment, compared case-insensitively on the
first DNS label. Called by :func:`dev_lab.ops.configcheck.main` over the host files of a config-source repository.
Which machines are development machines is the binding's (the host files); this module names none.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, Final

__all__ = ['RULE', 'identities', 'route_defects', 'routes']

#: The rule this refuses for.
RULE: Final = 'MACHINES-MEET-ONLY-THROUGH-THE-FORGE'


def _label(address: str) -> str:
    """``user@Host.example.org:22`` -> ``host``: the first DNS label of an address, lower-cased."""
    host = address.rpartition('@')[2].split(':')[0]
    return host.split('.')[0].strip().lower()


def identities(name: str, card: Mapping[str, Any]) -> frozenset[str]:
    """Every label development machine *name* is known by: its stem, its hostname, its client keys' hosts."""
    dev = card.get('dev', {})
    found = {name.lower()}
    if isinstance(dev.get('hostname'), str):
        found.add(_label(dev['hostname']))
    for key in dev.get('client_keys', ()):
        if isinstance(key, str) and '@' in (comment := key.split()[-1]):
            found.add(_label(comment))
    return frozenset(one for one in found if one)


def routes(card: Mapping[str, Any]) -> Iterator[tuple[str, str]]:
    """Each ``(where, address)`` route *card* declares."""
    ssh = card.get('ssh', {})
    for dest, bastion in (ssh.get('jump') or {}).items():
        yield f'[ssh] jump {dest!r}', str(dest)
        yield f'[ssh] jump {dest!r} via', str(bastion)
    for host in ssh.get('host_keys') or {}:
        yield f'[ssh] host_keys {host!r}', str(host)
    for table, value in card.items():
        if isinstance(value, Mapping) and isinstance(value.get('endpoint'), str):
            yield f'[{table}] endpoint', value['endpoint']


def route_defects(cards: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Each declared route from a development machine to ANOTHER development machine, named; host = file stem."""
    machines = {name: identities(name, card) for name, card in cards.items() if 'dev' in card}
    found = []
    for name in machines:
        for where, address in routes(cards[name]):
            target = _label(address)
            for other, known in machines.items():
                if other != name and target in known:
                    found.append(
                        f'{name}: {where} = {address!r} reaches the development machine {other}: {RULE} -- '
                        f'development machines meet only through the forge (push, a producer verifies, the forge '
                        f'merges); delete the route and hand the work over as a pushed branch'
                    )
    return found
