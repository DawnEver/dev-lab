"""EVERY REFUSAL NAMES ITS DOORS (user ruling 2026-11-11, restating "a refusal must name the door to use instead").

A deny row's remedy names at least one concrete door for the purpose it blocks, or says plainly that none exists.
A door is one of: a ``-m <module>`` command (``{python} -m dev_lab.dev.verify``), the ``{remedy}`` slot the adopting
repo fills with its own command (``hooks.Remedy`` refuses one naming no command), or a ``git <verb>`` -- git's own
vocabulary, which every checkout has. Otherwise the remedy opens with ``No door:`` and says what to do by hand. Detail
stays in ``docs-src/dev/refusals.md``; the remedy is the command, the page is the reasoning.
"""

from __future__ import annotations

import re

import pytest

from dev_lab.dev._deny_hpc_row import HPC_THROUGH_THE_DOOR
from dev_lab.dev.hooks import DENY_RULES

#: The door shapes a remedy may name, else the explicit no-door opener.
_DOOR = re.compile(r'-m [a-z_]+(?:\.[a-z_]+)+|\{remedy\}|\bgit [a-z][a-z-]+|^No door: ')


def names_a_door(remedy: str) -> bool:
    """Whether *remedy* names a concrete door command, or says plainly that there is none."""
    return _DOOR.search(remedy) is not None


@pytest.mark.parametrize('rule', DENY_RULES, ids=lambda rule: rule.id)
def test_every_refusal_names_a_door_command(rule) -> None:
    assert names_a_door(rule.remedy), f'{rule.id}: the remedy names no door -- {rule.remedy!r}'


@pytest.mark.parametrize(
    'vague',
    [
        'Use the door that records why: forge review again <pr>.',
        'Commit on your lane and hand the SHA back; a targeted measure is yours.',
        'Write it as a dated memory entry.',
    ],
)
def test_a_remedy_naming_no_door_fails(vague: str) -> None:
    """PLANTED CONTROL: the three shapes this audit rewrote (a bare verb, prose, a path) are each refused."""
    assert not names_a_door(vague)


def test_the_hpc_refusal_names_every_door_by_purpose() -> None:
    """User ruling 2026-11-11: an account shell, deploy, verify work and a research batch; flags in refusals.md."""
    text = str(HPC_THROUGH_THE_DOOR['remedy'])
    for door in (
        '`sshhold open|run --code`',
        '`hpcaccount <verb>`',
        '`forge queue|run show <sha>`',
        '`lab_commons.hpc plan|submit|status|gather|retry|run`',
        '`lab_commons.hpc clean`',
    ):
        assert door in text
    assert 'TOTP host `sshhold open|run --code` (key-only: no code)' in text  # user ruling 2026-11-11: no code


def test_the_key_only_hpc_doors_are_admitted() -> None:
    """The doors the refusal names must not themselves be refused, even when they name a login host."""
    pattern = re.compile(str(HPC_THROUGH_THE_DOOR['pattern']))
    for door in (
        'python -m lab_commons.hpc clean --root /gpfs01/home/alice/out --at alice@hpclogin01.example.org e69',
        'python -m lab_commons.hpc gather -c job.toml --wait',
        'python -m lab_commons.hpc run submit --sha 0123abc',
    ):
        assert door in HPC_THROUGH_THE_DOOR['permits']
        assert not pattern.search(door)
