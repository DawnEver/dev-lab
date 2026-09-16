"""FIX-THE-CAUSE, in the one shape a shared library can check mechanically.

TWO HAZARDS, ONE RULE. A module that binds the same module-level name twice has one definition
shadowing another, and whichever one a reader is looking at is the wrong one half the time -- that
is a patched symptom that no longer advertises its cause. And a ``_legacy``/``_compat``/deprecation
alias is the same defect with a name on it: a second entry point kept alive so callers need not
move, in a package whose callers are four repos that WILL not move once they are not made to.

THE ALIAS HALF IS THE ONE THAT MATTERS HERE. This package is imported by repos that cannot see its
history; the only way a rename reaches them is by breaking, deliberately, at a point somebody
chooses. An alias converts that into a silent fork where two spellings of one idea drift apart.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from _arch_corpus import SOURCE_FLOOR, assert_floor, parse, source_modules

#: WORDS that announce a second entry point kept alive for callers that did not move. Each is
#: matched as a whole SEGMENT of the bound name, never as a substring of a longer word.
_ALIAS_MARKERS = ('legacy', 'compat', 'deprecated', 'old')

#: The marker set is the whole subject of the alias half; an empty one passes over nothing.
ALIAS_MARKER_FLOOR = 4

#: One snake_case or CamelCase word of an identifier. ``ABCThing`` -> ``ABC``, ``Thing``.
_WORD = re.compile(r'[A-Z]+(?![a-z])|[A-Z]?[a-z0-9]+|[A-Z]')


def alias_words(name: str) -> tuple[str, ...]:
    """The lowercased WORDS of *name*, split on underscores and on CamelCase humps."""
    return tuple(word.lower() for part in name.split('_') for word in _WORD.findall(part))


def is_alias_shaped(name: str) -> bool:
    """Whether *name* carries an alias marker as a WORD of its own.

    WHY WORDS, AND NOT SUBSTRINGS -- NOR WHOLE IDENTIFIERS EITHER. The markers used to be spelled
    with their separators baked in (``'_compat'``, ``'compat_'``) and matched with ``in``, which is
    a substring test wearing a boundary as decoration: it convicted ``quantity_values._compatible``
    -- a module-private predicate that was never exported, was not a second entry point, and shares
    nothing with the hazard but six letters. That false positive cost two agents an afternoon and
    two renames of one function before anyone read the marker. It is not a fluke of that module
    either: pint's public API is ``is_compatible_with``, so any units-adjacent code here will reach
    for ``compatible``/``compatibility`` again, and a guard that cannot coexist with the vocabulary
    of what it guards gets worked around rather than obeyed.

    Whole-identifier matching -- the shape used for a RETIRED SPELLING, where the subject is a
    complete name -- is the wrong fix here, because these markers are not names: ``compat`` exists
    to catch ``_compat_shim`` and ``legacy`` to catch ``legacy_read_toml``, and a whole-identifier
    rule would catch neither. What the markers actually mean is a WORD appearing anywhere in the
    name, so SEGMENTATION, not anchoring, is the operation -- which is also why the leading and
    trailing underscores in the old spellings could be dropped: they were standing in for a word
    boundary the segmentation now computes properly, in both directions at once.

    A MARKER STANDING ALONE IS NOT AN ALIAS, and this repo already holds the proof: the public
    ``exceptions.deprecated`` decorator, whose whole body RAISES. The hazard is a second spelling of
    an idea, which needs the idea IN THE NAME -- ``read_toml_legacy`` is ``read_toml`` plus a
    qualifier. A bare ``deprecated``/``compat`` names the MECHANISM instead, and nothing about it is
    a duplicate entry point. So a marker convicts only when the name carries another word for it to
    qualify.

    THE DELIBERATE GAP: a name gluing a marker to another word with no separator at all
    (``compatshim``) is not convicted. That is the price of letting ``compatible`` live, and it is
    the right side to err on -- this guard's remedy is a rename nobody can argue with, so a false
    positive costs more than a miss of a spelling that was never a naming convention here anyway.
    """
    words = alias_words(name)
    return any(word in _ALIAS_MARKERS for word in words) and any(word not in _ALIAS_MARKERS for word in words)


def duplicate_and_alias_problems(paths: tuple[Path, ...]) -> tuple[str, ...]:
    """Every module-level name bound twice, and every alias-shaped name -- pure over its argument."""
    out: list[str] = []
    for path in paths:
        seen: dict[str, int] = {}
        for node in parse(path).body:
            for name in _bound(node):
                if name in seen:
                    out.append(
                        f'{path.name}: {name!r} is defined twice (lines {seen[name]} and {node.lineno}); '
                        f'one of the two is the definition a reader will not be looking at'
                    )
                else:
                    seen[name] = node.lineno
                if is_alias_shaped(name):
                    out.append(
                        f'{path.name}: {name!r} is a second entry point for callers that did not move; '
                        f'move the callers WITH the code instead'
                    )
    return tuple(out)


def _bound(node: ast.stmt) -> tuple[str, ...]:
    """The module-level names one top-level statement binds by DEFINITION (not by import)."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return (node.name,)
    if isinstance(node, ast.Assign):
        return tuple(t.id for t in node.targets if isinstance(t, ast.Name))
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
        return (node.target.id,)
    return ()


def test_no_module_binds_one_name_twice_or_keeps_an_alias() -> None:
    """THE CHECK, over this repo's own source tree."""
    paths = source_modules()
    assert_floor(len(paths), SOURCE_FLOOR, 'one-name-one-definition')
    assert len(_ALIAS_MARKERS) >= ALIAS_MARKER_FLOOR, (
        f'{len(_ALIAS_MARKERS)} alias markers left, below the {ALIAS_MARKER_FLOOR} floor. A marker '
        f'set emptied to make a red go away reports exactly what a clean tree reports.'
    )
    problems = duplicate_and_alias_problems(paths)
    assert problems == (), 'a name has two definitions, or an alias outlived its callers:\n  ' + '\n  '.join(problems)


def test_a_planted_duplicate_and_a_planted_alias_are_refused(tmp_path: Path) -> None:
    """THE PLANTED CONTROL, through the REAL checker, with a clean file to keep it honest."""
    twice = tmp_path / 'twice.py'
    twice.write_text('def f() -> None: ...\n\n\ndef f() -> None: ...\n', encoding='utf-8')
    alias = tmp_path / 'alias.py'
    alias.write_text('def read_toml_legacy() -> None: ...\n', encoding='utf-8')
    clean = tmp_path / 'fine.py'
    clean.write_text('def f() -> None: ...\n\n\ndef g() -> None: ...\n', encoding='utf-8')
    problems = duplicate_and_alias_problems((twice, alias, clean))
    assert any('defined twice' in p for p in problems)
    assert any('second entry point' in p for p in problems)
    assert not any('fine.py' in p for p in problems)


def test_the_markers_match_words_and_not_substrings_of_them() -> None:
    """BOTH HALVES. The alias shapes are still convicted; the units vocabulary is not.

    The negative half alone would be a guard loosened to fit the code it reddened on; the positive
    half is what proves the loosening did not reach the hazard.
    """
    convicted = (
        'read_toml_legacy',
        'legacy_read_toml',
        '_compat_shim',
        'compat_table',
        'read_toml_deprecated',
        'deprecated_read_toml',
        'old_read_toml',
        'LegacyReader',
        'HTTPCompatShim',
    )
    for name in convicted:
        assert is_alias_shaped(name), f'{name!r} is a second entry point and the guard let it through'
    acquitted = (
        '_compatible',
        '_converts_to',
        'is_compatible_with',
        'compatibility',
        'compatible_units',
        'threshold',
        'fold',
        'golden',
        'bold_text',
        'deprecated',
        'compat',
    )
    for name in acquitted:
        assert not is_alias_shaped(name), f'{name!r} is not an alias and the guard convicted it'


def test_the_words_of_a_name_are_the_unit_of_the_match() -> None:
    """The segmentation the rule above rests on, stated directly."""
    assert alias_words('_compat_shim') == ('compat', 'shim')
    assert alias_words('_compatible') == ('compatible',)
    assert alias_words('HTTPCompatShim') == ('http', 'compat', 'shim')
    assert alias_words('read_toml_v2') == ('read', 'toml', 'v2')
