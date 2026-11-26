"""OWNER-COVERAGE's declaration half: the family bars and a repo's ``[tool.dev_lab.coverage]`` read by its shape.

Split out of :mod:`dev_lab.dev.ownercov` (MODULE-SIZE-ALARM) along its seam: this reads and refuses the declaration
(bars, floors, each a share written with its unit); that one judges a measurement against it and writes floors.
A share is kept as an exact :class:`~fractions.Fraction` and shown truncated to 0.01 %, so a floor ``record`` wrote
is always met by the measurement it came from.
"""

from __future__ import annotations

import math
import re
import tomllib
from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING, Final, NoReturn

from dev_lab.dev.family import declared_table

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

__all__ = ['BARS', 'GRID', 'ROWS', 'TABLE', 'WHERE', 'Floor', 'Policy', 'Refused', 'policy', 'shown']

#: THE FAMILY BARS: a repo may only raise them (``BAR-IS-A-CONSTANT``).
BARS: Final[Mapping[str, str]] = {'line': '95 %', 'branch': '90 %'}
#: ``[tool.dev_lab.<TABLE>]`` of pyproject.toml.
TABLE: Final = 'coverage'
WHERE: Final = f'pyproject.toml [tool.dev_lab.{TABLE}'
ROWS: Final = {'python': '[python.owners]', 'rust': '[rust.crates]'}
_KEYS: Final = frozenset({*BARS, 'floors'})
_PERCENT: Final = re.compile(r'^\s*(\d+(?:\.\d+)?)\s*%\s*$')
_NUMBER: Final = re.compile(r'^\s*(\d+(?:\.\d+)?)\s*$')
#: A share is kept to 0.01 %.
GRID: Final = 10_000


class Refused(ValueError):
    """``[tool.dev_lab.coverage]`` is not the declared shape; the message names the key."""


def _refuse(why: str) -> NoReturn:
    raise Refused(why)


def shown(share: Fraction) -> str:
    """*share* as a percentage truncated to 0.01 %: ``Fraction(2, 3)`` -> ``66.66 %``."""
    n = math.floor(share * GRID)
    return f'{n // 100}.{n % 100:02d} %'


def _share(where: str, value: object) -> Fraction:
    """*value* (declared at *where*) as a share of one: ``"95 %"`` -> 19/20."""
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        _refuse(f'{where} = {value!r} is not a share: write it with its unit, such as "96 %"')
    if not isinstance(value, str):
        _refuse(f'{where} = {value!r} is a bare number: write it with its unit, such as "{_example(value)} %"')
    if not (match := _PERCENT.match(value)):
        bare = _NUMBER.match(value)
        example = _example(float(bare[1])) if bare else '96'
        _refuse(f'{where} = "{value}" carries no unit: write it with its unit, such as "{example} %"')
    share = Fraction(match[1]) / 100
    if share > 1:
        _refuse(f'{where} = "{value}" is not a share between 0 % and 100 %')
    return share


def _example(number: float) -> str:
    return f'{number * 100 if number <= 1 else number:g}'


@dataclass(frozen=True, slots=True)
class Floor:
    """One recorded floor: its share, and the text the declaration wrote."""

    share: Fraction
    text: str


@dataclass(frozen=True)
class Policy:
    """The bars in force (the family's, or a repo's raise) and the recorded floors."""

    bars: dict[str, Fraction]
    floors: dict[str, dict[str, dict[str, Floor]]]  # language -> owner -> kind -> floor


def _unknown(where: str, keys: Iterable[str], allowed: Iterable[str]) -> None:
    if unknown := sorted(set(keys) - set(allowed)):
        _refuse(f'{where} unknown key(s) {unknown}; it holds {", ".join(sorted(allowed))}')


def policy(root: Path) -> Policy:
    """*root*'s bars and floors.

    Raises:
        Refused: a bare number, a share outside 0..100 %, an unknown key, a lowered or restated bar.

    """
    table = declared_table(tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8')), TABLE, {})
    _unknown(f'{WHERE}]', table, _KEYS)
    bars: dict[str, Fraction] = {}
    for kind, text in BARS.items():
        family = _share(f'{WHERE}] family {kind}', text)
        if kind not in table:
            bars[kind] = family
            continue
        mine = _share(f'{WHERE}] {kind}', table[kind])
        if mine < family:
            _refuse(
                f'{WHERE}] {kind} = "{table[kind]}" lowers the family bar {text}: a repo may only raise it '
                '(BAR-IS-A-CONSTANT)'
            )
        if mine == family:
            _refuse(
                f'{WHERE}] {kind} = "{table[kind]}" restates the family bar {text}: delete it, the family bar holds'
            )
        bars[kind] = mine
    raw = table.get('floors', {})
    if unknown := sorted(set(raw) - set(ROWS)):
        _refuse(f'{WHERE}.floors] unknown language(s) {unknown}; it holds {", ".join(ROWS)}')
    floors: dict[str, dict[str, dict[str, Floor]]] = {}
    for language, rows in raw.items():
        where = f'{WHERE}.floors.{language}]'
        floors[language] = {}
        for owner, row in rows.items():
            if not isinstance(row, dict) or not row:
                _refuse(f'{where} {owner} holds no floor: {{ line = "<share> %", branch = "<share> %" }}, from record')
            _unknown(f'{where} {owner}', row, BARS)
            floors[language][owner] = {k: Floor(_share(f'{where} {owner} {k}', v), v) for k, v in row.items()}
    return Policy(bars, floors)
