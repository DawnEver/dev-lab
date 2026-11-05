"""A LOCAL SIBLING IS A DECLARED OVERLAY ON THE LOCKED ENVIRONMENT.

User directive 2026-11-05: an environment is the LOCK by default. A family sibling's local checkout replaces its
locked version only when DECLARED -- per machine in the machine file's ``[dep] local`` list, or per run with
``dep --local NAME`` -- and only through :mod:`dev_lab.dev.dep`, which installs it after the sync, inside the
same seat, editable and with ``--no-deps`` (the lock still decides every other version).

THE PATH IS NEVER DECLARED HERE. It is the machine file's ``[repos]`` entry for the name when there is one (the
family's existing per-machine record of where a checkout lives), else ``family_root / NAME``.

THE DEFAULT IS THE LOCK BY CONSTRUCTION: the sync reinstalls every locked source, so a sync with nothing declared
IS the revert. The overlay is stamped into the environment (:data:`STAMP_FILE`) and the door folds that stamp into
the key it compares, because an editable checkout at the locked commit reports the locked version and would
otherwise move nothing.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from dev_lab.dev._dep_components import _tree

__all__ = [
    'STAMP_FILE',
    'Overlay',
    'OverlayRefused',
    'banner',
    'declared',
    'install_command',
    'key_suffix',
    'record',
    'resolve',
]

#: Where an environment keeps the overlays it holds, beside the components stamp.
STAMP_FILE: Final = 'dev-lab-local.json'


class OverlayRefused(ValueError):
    """A declared overlay that cannot be what it claims; the message names the fix."""


@dataclass(frozen=True)
class Overlay:
    """One sibling checkout installed over its locked version."""

    name: str
    path: Path


def _canonical(name: str) -> str:
    return re.sub(r'[-_.]+', '-', name).lower()


def declared(cli: Sequence[str], machine: Mapping[str, Any]) -> tuple[str, ...]:
    """The machine file's ``[dep] local`` list, then the run's ``--local`` names; each once, in that order."""
    listed = machine.get('local', [])
    if not isinstance(listed, list) or any(not isinstance(name, str) for name in listed):
        msg = 'the machine file\'s [dep] local must be a list of distribution names, e.g. local = ["lab-commons"]'
        raise OverlayRefused(msg)
    return tuple(dict.fromkeys([*listed, *cli]))


def _locked(root: Path) -> frozenset[str]:
    lock = root / 'uv.lock'
    if not lock.is_file():
        return frozenset()
    packages = tomllib.loads(lock.read_text(encoding='utf-8')).get('package', [])
    return frozenset(_canonical(str(row.get('name', ''))) for row in packages)


def resolve(root: Path, names: Sequence[str], *, repos: Mapping[str, Any], family: Path) -> tuple[Overlay, ...]:
    """Each declared name as an :class:`Overlay`, refusing any that cannot be what it claims."""
    locked = _locked(root)
    overlays = []
    for name in names:
        if _canonical(name) not in locked:
            msg = f'{name} is not a package in {root / "uv.lock"}; an overlay replaces a locked sibling, nothing else'
            raise OverlayRefused(msg)
        path = Path(str(repos[name])).expanduser() if name in repos else family / name
        manifest = path / 'pyproject.toml'
        if not manifest.is_file():
            msg = (
                f'no checkout of {name} at {path}: clone it there, or set [repos] {name} = "<path>" in the machine file'
            )
            raise OverlayRefused(msg)
        project = str(tomllib.loads(manifest.read_text(encoding='utf-8')).get('project', {}).get('name', ''))
        if _canonical(project) != _canonical(name):
            msg = f'{path} names {project or "no project"}, not {name}; point [repos] {name} at its checkout'
            raise OverlayRefused(msg)
        overlays.append(Overlay(name, path))
    return tuple(overlays)


def install_command(uv: str, python: str, overlays: Sequence[Overlay]) -> list[str]:
    """Editable, and ``--no-deps``: a sibling needing a newer peer is a relock, never an overlay."""
    command = [uv, 'pip', 'install', '--python', python, '--no-deps']
    for overlay in overlays:
        command.extend(('-e', str(overlay.path)))
    return command


def _stamps(overlays: Sequence[Overlay]) -> dict[str, str]:
    return {o.name: f'{o.path}@{_tree(o.path) or "unreadable"}' for o in overlays}


def banner(overlays: Sequence[Overlay]) -> list[str]:
    """One line per overlay, printed on every sync that carries it."""
    return [f'LOCAL OVERLAY: {name} -> {stamp}' for name, stamp in _stamps(overlays).items()]


def record(prefix: Path, overlays: Sequence[Overlay]) -> None:
    """Stamp the overlays into the environment; with none, remove the stamp (the revert)."""
    stamp = prefix / STAMP_FILE
    if not overlays:
        stamp.unlink(missing_ok=True)
        return
    prefix.mkdir(parents=True, exist_ok=True)
    stamp.write_text(json.dumps(_stamps(overlays), sort_keys=True), encoding='utf-8')


def key_suffix(prefix: Path) -> str:
    """What the overlay adds to the environment key: ``''`` for the bare lock."""
    try:
        text = (prefix / STAMP_FILE).read_text(encoding='utf-8')
    except OSError:
        return ''
    return '+local:' + text
