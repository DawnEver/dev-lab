r"""A base whose subject is a TOML TABLE: it owns named keys and leaves the rest of the file alone.

THE GAP THIS CLOSES, measured 2026-09-18 against the live kit. :mod:`lab_commons.dev.famconfig` is a
WHOLE-FILE mechanism keyed by FILENAME -- ``artefact_base('[tool.ruff]')``, ``('ruff.toml')`` and
``('pyproject.toml')`` all raise `ForkedDelta` -- and ``[tool.ruff]`` is a SECTION. Pointing the
whole-file base at ``pyproject.toml`` is not the workaround, because ``RENDERED`` would then demand
the base own ``[build-system]``, ``[project]``, ``[tool.pytest.ini_options]`` and ``[tool.pyright]``
too. ``REQUIRED`` is the nearest existing shape and is the WRONG one: it asserts PRESENCE, so it
cannot see a consumer ADD an ``ignore`` entry, and stopping exactly that is the ruff arm's point.

WHY THIS IS NEW SURFACE RATHER THAN A MODE ON `Base`. The two mechanisms differ in what they can
KNOW. A whole-file base renders, so it can demand byte equality and stamp its output; a section base
cannot render -- a table inside somebody else's ``pyproject.toml`` has no place to carry a
provenance block, and writing one would claim ownership of a file the base does not own. So this
half COMPARES and never writes, and it says so by having no renderer at all.

ITS STATUSES ARE ITS OWN, and that is a consequence rather than a duplication. `famconfig`'s
``FOREIGN`` distinguishes "somebody's own file" from "ours, edited", which only a STAMP can answer
and a section has none. What a section has instead is :data:`NO_TABLE` -- the file is there and
declares no such table -- which has no whole-file analogue, because a missing file and a file
missing a table are the same answer only when the file IS the artefact.

EVERY KEY IS EXACT, and the two kinds differ only in how a delta may move them:

* a SCALAR key must equal the base's value, or carry a ``(key, None)`` drop saying why;
* a SET key must equal ``base entries - dropped entries + the delta's added entries``. That is the
  arm: an entry on disk that no declaration produced is named, and a base entry gone with no drop is
  named. Both directions, from one comparison.

THE FILE IS NOT THE ARTEFACT, which is this arm's second decision. :func:`locate_section` resolves a
base's dotted path OR that path with its ``prefix`` stripped, so one base binds a table wherever a
repo keeps it, and it refuses a file declaring both -- the dead-block shape where one spelling wins
and the other is a decision nothing reads. Why keying by TABLE rather than by FILE was the cheap
direction is a fact about one repo's tree, and it is argued where that repo's data lives, in
`_famconfig_ruff_rows`.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lab_commons.dev._famconfig_pyproject_rows import PYPROJECT_SECTION_PREFIX, PYPROJECT_SECTION_ROWS
from lab_commons.dev._famconfig_ruff_rows import RUFF_CONFIG_NAMES, RUFF_SECTION_PREFIX, RUFF_SECTION_ROWS
from lab_commons.dev._famconfig_survey import assert_base_floor

__all__ = [
    'DIVERGED',
    'NO_FILE',
    'NO_TABLE',
    'OWNED',
    'PYPROJECT_SECTIONS',
    'RUFF_SECTIONS',
    'SECTION_BASES',
    'SECTION_KEY_FLOOR',
    'AmbiguousSection',
    'ForkedSectionDelta',
    'SectionBase',
    'SectionDelta',
    'SectionReport',
    'expected_entries',
    'inspect_section',
    'locate_section',
    'ruff_config_path',
    'section_base',
    'section_problems',
]

#: STATUS. No file at the path -- the table is absent rather than conforming, and those differ.
NO_FILE: Final = 'NO_FILE'
#: STATUS. The file is there and declares no such table. It has no whole-file analogue: a missing
#: file and a file missing a table are the same answer only when the file IS the artefact.
NO_TABLE: Final = 'NO_TABLE'
#: STATUS. Every key the base owns is exactly what the base and this repo's delta declare.
OWNED: Final = 'OWNED'
#: STATUS. At least one owned key disagrees, and the report names which and in which direction.
DIVERGED: Final = 'DIVERGED'


class ForkedSectionDelta(ValueError):
    """A section delta touches a key the base does not own, re-states one it has, or over-runs."""


class AmbiguousSection(ValueError):
    """One file declares the same table under both spellings, so one of the two is never read."""


@dataclass(frozen=True, slots=True)
class SectionBase:
    """One owned TOML table: where it sits, which keys are EXACT scalars, and which are SETS.

    *table* is the dotted path in the family spelling (``('tool', 'ruff', 'lint')``). *prefix* is the
    leading part a DEDICATED config file drops, so one base binds on both spellings without a branch
    per repo -- the shape `lab_commons.dev.rules.lint_selection` already reads and this makes
    declarable.
    """

    artefact: str
    table: tuple[str, ...]
    prefix: tuple[str, ...]
    scalars: Mapping[str, object]
    sets: Mapping[str, tuple[str, ...]]

    @property
    def suffix(self) -> tuple[str, ...]:
        """The dotted path as a dedicated config file spells it -- *table* with *prefix* removed."""
        return self.table[len(self.prefix) :] if self.table[: len(self.prefix)] == self.prefix else self.table

    @property
    def owned_keys(self) -> tuple[str, ...]:
        """Every key this base makes a claim about. What a floor counts, and what a delta may name."""
        return tuple(sorted({*self.scalars, *self.sets}))


@dataclass(frozen=True, slots=True)
class SectionDelta:
    """What one repo adds to a section base's SET keys, and which base entries it drops WITH a reason.

    ``dropped`` is keyed by ``(key, entry)`` for one member of a set and ``(key, None)`` for a whole
    scalar key, so a drop names its subject precisely enough to die with it. It is a MAPPING to a
    reason and never a set, for the reason the whole-file `Delta` gives: a removal and a drift are
    the same bytes on disk, and only the declaration can tell them apart.

    ``ceiling`` has no default. An escape hatch needs a ceiling rather than a reason, and the number
    is the point at which this repo's waiver list has stopped being a delta -- only the repo can say
    where that is.
    """

    repo: str
    added: Mapping[str, tuple[str, ...]]
    dropped: Mapping[tuple[str, str | None], str]
    ceiling: int


@dataclass(frozen=True, slots=True)
class SectionReport:
    """One table in one file: where it is, what state it is in, and which keys say so."""

    artefact: str
    path: Path
    status: str
    detail: str
    offending: tuple[str, ...]

    @property
    def ok(self) -> bool:
        """Whether the table on disk is what the live base and delta say it should be."""
        return self.status == OWNED


#: The floor under a section base's key count: a base owning NO key reports every file it reads as
#: conforming, which is the vacuous green every floor in this package exists to refuse. ONE, because
#: the ``[tool.ruff]`` and ``[tool.pytest.ini_options]`` rows each legitimately own a single key.
#:
#: IT IS NOT NAMED FOR ONE ARTEFACT, and that is why it lives here rather than in a rows module.
#: `section_problems` binds it for EVERY base, so an artefact-shaped name on it would be a
#: declaration that lies the moment a second artefact arrives -- which it now has.
SECTION_KEY_FLOOR: Final = 1


def _bases(
    rows: Mapping[str, tuple[tuple[str, ...], Mapping[str, object], Mapping[str, tuple[str, ...]]]],
    prefix: tuple[str, ...],
) -> dict[str, SectionBase]:
    """A rows table turned into bases, so WHICH tables and WHICH keys stay declared as data."""
    return {
        artefact: SectionBase(artefact=artefact, table=table, prefix=prefix, scalars=scalars, sets=sets)
        for artefact, (table, scalars, sets) in rows.items()
    }


#: Every ruff table this package owns, built from the DATA table rather than restated here, so a row
#: added there arrives here and a row deleted there cannot leave a live entry behind.
RUFF_SECTIONS: Final[dict[str, SectionBase]] = _bases(RUFF_SECTION_ROWS, RUFF_SECTION_PREFIX)

#: Every ``pyproject.toml`` table this package owns. Its prefix is EMPTY -- these tables have one
#: home -- which is what makes the pair below a real test of the resolver rather than two copies of
#: one case: the ruff bases exercise the dedicated-file branch and these exercise the other.
PYPROJECT_SECTIONS: Final[dict[str, SectionBase]] = _bases(PYPROJECT_SECTION_ROWS, PYPROJECT_SECTION_PREFIX)

#: ONE registry over both artefacts, so :func:`section_base` is one lookup rather than one per rows
#: module. The two names above stay as the SUBSETS each suite is a claim about; a second lookup
#: function would be the dual entry point this codebase refuses.
SECTION_BASES: Final[dict[str, SectionBase]] = {**RUFF_SECTIONS, **PYPROJECT_SECTIONS}


def section_base(artefact: str) -> SectionBase:
    """The base for *artefact*, or a refusal naming the ones that exist.

    A lookup rather than an attribute, for the reason `famconfig.artefact_base` is one: a table this
    package does not own fails HERE, with the set it could have meant, instead of at the point a
    caller indexes ``None``.
    """
    base = SECTION_BASES.get(artefact)
    if base is None:
        msg = (
            f'no family section base for {artefact!r}. Declared sections: {sorted(SECTION_BASES)}. A '
            f'config table with no base is not shared by default -- add the row to '
            f'lab_commons.dev._famconfig_ruff_rows or _famconfig_pyproject_rows with the measurement '
            f'that says it is, or record it in PYPROJECT_DECLINED with the number that declined it.'
        )
        raise ForkedSectionDelta(msg)
    return base


def ruff_config_path(root: Path) -> Path:
    """Where *root* keeps its ruff rules, taking ruff's own precedence. Raises if it keeps none.

    RAISED RATHER THAN DEFAULTED. A path to a file that is not there would make every reading below
    it report on nothing, and reporting on nothing is indistinguishable from reporting agreement.
    """
    for name in RUFF_CONFIG_NAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    msg = (
        f'no ruff config under {root}: none of {list(RUFF_CONFIG_NAMES)} is there. A section base '
        f'cannot be checked against a file that does not exist, and defaulting to one would report a '
        f'tree it never read as conforming.'
    )
    raise FileNotFoundError(msg)


def locate_section(document: Mapping[str, object], base: SectionBase) -> Mapping[str, object] | None:
    """*base*'s table inside a parsed TOML *document*, under either spelling, or ``None``.

    Refuses a document declaring BOTH, because ruff reads one of them and the other is a decision
    nothing consults -- the dead-block shape this family has already measured once, in the repo that
    kept a ``[tool.ruff]`` block beside the ``ruff.toml`` that outranked it.

    WHICH SPELLING IS EVEN ELIGIBLE IS DECIDED BY THE DOCUMENT, and the first cut of this got it
    wrong in the one way a planted test could not have predicted: the root section's suffix is EMPTY,
    an empty path resolves to the document itself, and so every `pyproject.toml` on earth "declared"
    ``[tool.ruff]`` twice. A file is DEDICATED when it does not declare the base's prefix at all --
    that is what tells a ``ruff.toml`` from a ``pyproject.toml`` -- and only a dedicated file may be
    read under the short spelling.
    """
    full = _walk(document, base.table)
    dedicated = _walk(document, base.prefix) is None if base.prefix else True
    short = _walk(document, base.suffix) if base.suffix != base.table else None
    if not dedicated and base.suffix and short is not None:
        msg = (
            f'{base.artefact} is declared under both spellings in one file: {list(base.table)} and '
            f'{list(base.suffix)}. Only one of the two is ever read, so the other is a decision '
            f'nothing consults. Delete the one this file does not resolve.'
        )
        raise AmbiguousSection(msg)
    if not dedicated:
        return full
    return full if full is not None else short


def _walk(document: Mapping[str, object], path: tuple[str, ...]) -> Mapping[str, object] | None:
    """*path* resolved through nested mappings, or ``None`` at the first step that is not there."""
    node: object = document
    for step in path:
        if not isinstance(node, Mapping) or step not in node:
            return None
        node = node[step]
    return node if isinstance(node, Mapping) else None


def expected_entries(base: SectionBase, delta: SectionDelta, key: str) -> frozenset[str]:
    """What a SET key must hold: the base's entries, less this repo's declared drops, plus its adds.

    Pure over its arguments, so a control drives THIS reading rather than a second implementation
    that would agree with it by construction.
    """
    dropped = {entry for (name, entry), _ in delta.dropped.items() if name == key and entry is not None}
    return frozenset(set(base.sets.get(key, ())) - dropped) | frozenset(delta.added.get(key, ()))


def section_problems(base: SectionBase, delta: SectionDelta) -> tuple[str, ...]:
    """Every way *delta* is not a delta of *base*. Pure, and it binds the base's key floor first."""
    assert_base_floor(len(base.owned_keys), SECTION_KEY_FLOOR, f'{base.artefact} section')
    out: list[str] = []
    out += _drop_problems(base, delta)
    out += _addition_problems(base, delta)
    added = sum(len(entries) for entries in delta.added.values())
    if added > delta.ceiling:
        out.append(
            f'{delta.repo} adds {added} entr(ies) to {base.artefact}, past its ceiling of '
            f'{delta.ceiling}. Raise the ceiling with the reason, or move what is shared into the '
            f'base. A waiver list with no ceiling is an escape hatch nobody bounded.'
        )
    out += [
        f'{delta.repo} drops {subject!r} from {base.artefact} with an empty reason. A removal and a '
        f'drift are the same bytes on disk; the reason is the only thing that tells them apart.'
        for subject, reason in sorted(delta.dropped.items(), key=repr)
        if not reason.strip()
    ]
    return tuple(out)


def _drop_problems(base: SectionBase, delta: SectionDelta) -> list[str]:
    """A drop whose subject the base does not have -- a declaration outliving the thing it names."""
    out: list[str] = []
    for key, entry in sorted(delta.dropped, key=repr):
        if entry is None:
            if key not in base.scalars:
                out.append(
                    f'{delta.repo} drops the whole key {key!r} from {base.artefact}, and the base '
                    f'owns no such scalar. Delete the drop in the edit that removed the key; a drop '
                    f'that outlives its subject reads as a decision and refuses nothing.'
                )
        elif entry not in base.sets.get(key, ()):
            out.append(
                f'{delta.repo} drops {entry!r} from {key!r} in {base.artefact}, and the base does not '
                f'have that entry. A drop dies with the entry it names -- delete it.'
            )
    return out


def _addition_problems(base: SectionBase, delta: SectionDelta) -> list[str]:
    """A delta reaching a key the base does not own, re-stating the base, or adding nothing."""
    out: list[str] = []
    for key, entries in sorted(delta.added.items()):
        if key not in base.sets:
            out.append(
                f'{delta.repo} adds to {key!r} in {base.artefact}, and the base owns no such SET key. '
                f'A base owns named keys; a delta cannot legislate one that was never declared. '
                "Either the key is the family's -- promote it into "
                "lab_commons.dev._famconfig_ruff_rows with its measurement -- or it is this repo's "
                f'own and this base says nothing about it.'
            )
            continue
        if not entries:
            out.append(
                f'{delta.repo} adds no entries to {key!r} in {base.artefact}. An addition that adds '
                f'nothing is a waiver nothing uses -- delete the entry.'
            )
        out += [
            f'{delta.repo} adds {entry!r} to {key!r} in {base.artefact}, and the base already has it. '
            f'A delta that re-states the base is the base copied into a place re-checking does not '
            f'reach.'
            for entry in sorted(set(entries) & set(base.sets[key]))
        ]
    return out


def inspect_section(path: Path, base: SectionBase, delta: SectionDelta) -> SectionReport:
    """Compare the table at *path* against what *base* and *delta* declare RIGHT NOW.

    Re-reading rather than comparing a stored digest is the mechanism: no recorded answer can go
    stale, so a base edited here moves every consumer's verdict on the next run. An ILLEGAL
    declaration raises before the file is opened -- a delta that is not a delta has no file verdict
    to report, and returning one would let a refusal read as drift.
    """
    problems = section_problems(base, delta)
    if problems:
        raise ForkedSectionDelta('\n'.join(problems))
    if not path.is_file():
        detail = f'no {path.name} here -- {base.artefact} is absent rather than clean, and those differ'
        return SectionReport(base.artefact, path, NO_FILE, detail, ())
    table = locate_section(tomllib.loads(path.read_text(encoding='utf-8')), base)
    if table is None:
        detail = (
            f'{path.name} declares no {base.artefact}. Every key the base owns is unstated, which is '
            f'not the same as agreed: add the table, or declare this repo out of the family base.'
        )
        return SectionReport(base.artefact, path, NO_TABLE, detail, ())
    offending = _key_differences(base, delta, table)
    if not offending:
        return SectionReport(base.artefact, path, OWNED, f'all {len(base.owned_keys)} owned key(s) as declared', ())
    detail = (
        f'{len(offending)} owned key(s) of {base.artefact} in {path.name} disagree with the live base '
        f"and {delta.repo}'s delta. An entry the file holds and no declaration produced is an "
        f'undeclared local decision; a base entry gone with no drop is the base leaving through the '
        f'file instead of through the table that owns it.'
    )
    return SectionReport(base.artefact, path, DIVERGED, detail, offending)


def _key_differences(base: SectionBase, delta: SectionDelta, table: Mapping[str, object]) -> tuple[str, ...]:
    """Every owned key that disagrees, named in the DIRECTION it disagrees in."""
    out: list[str] = []
    for key, value in sorted(base.scalars.items()):
        if (key, None) in delta.dropped:
            continue
        if key not in table:
            out.append(f'{key}: absent, and the base sets it to {value!r} with no declared drop')
        elif table[key] != value:
            out.append(f'{key}: the file says {table[key]!r} and the base says {value!r}')
    for key in sorted(base.sets):
        wanted = expected_entries(base, delta, key)
        if key not in table:
            out.append(f'{key}: absent, and the base declares {len(wanted)} entr(ies) for it')
            continue
        found = frozenset(table[key]) if isinstance(table[key], list) else frozenset()
        out += [f'{key}: {entry!r} is declared and the file does not have it' for entry in sorted(wanted - found)]
        out += [
            f'{key}: {entry!r} is in the file and no declaration adds it -- an undeclared local waiver'
            for entry in sorted(found - wanted)
        ]
    return tuple(out)
