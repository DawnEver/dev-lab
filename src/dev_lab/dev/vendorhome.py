"""A VENDOR'S INSTALL HOME on this machine -- the ``[dev.vendors.<name>] home`` placeholder, its fill and its read.

Split from :mod:`dev_lab.dev.devschema` at the module-size band (2026-11-28): the schema checks a host file's
``[dev]`` shape; this is the one fact a code path reads from it about a vendor, and the one door that fills it.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from dev_lab.dev.venvpath import running_interpreter

__all__ = ['DETECT_DOOR', 'UNFILLED', 'HomeUnfilled', 'fill_remedy', 'home_of', 'unfilled']

#: The ONE placeholder for an install home not yet found on its machine: never a plausible path. configcheck accepts
#: it; the session start names it first, the stop blocks once on it, and :func:`home_of` refuses it.
UNFILLED: Final = 'FILL-ON-THIS-MACHINE'
#: The door that finds this machine's vendor install homes.
DETECT_DOOR: Final = f'{running_interpreter()} -m dev_lab.dev.devhost detect'


def unfilled(dev: Mapping[str, Any]) -> list[str]:
    """The vendors whose install home this machine has yet to fill: the placeholder, or seats with no home."""
    return [
        name
        for name, vendor in dev.get('vendors', {}).items()
        if vendor.get('home') == UNFILLED or (vendor.get('seats') and not vendor.get('home'))
    ]


def fill_remedy(names: list[str]) -> str:
    """What a machine does about *names*: detect here, then propose the lines through a config-source PR."""
    return (
        f'install home not filled for {", ".join(names)} ({UNFILLED}): run {DETECT_DOOR} on this machine and open a '
        "pull request on the config source replacing the placeholder in this machine's host file"
    )


class HomeUnfilled(LookupError):
    """A code path needs a vendor's install home this machine has not filled."""


def home_of(dev: Mapping[str, Any], vendor: str) -> Path:
    """*vendor*'s declared install home.

    Raises:
        HomeUnfilled: it is the placeholder or absent -- never a fallback guess.

    """
    home = dev.get('vendors', {}).get(vendor, {}).get('home')
    if not home or home == UNFILLED:
        raise HomeUnfilled(fill_remedy([vendor]))
    return Path(home)
