"""WHAT THE FOUR PLACEMENT ROSTERS ACTUALLY MEASURED -- DATA, one row per reading.

READ AS DATA by :mod:`lab_commons.dev.famtests.placement`'s controls, so the family's four answers
are a declaration the tests CONSULT rather than a paragraph a reader has to trust. The reasoning is
in `.claude/memory/2026/09/18/`; what lives here is the numbers and the one-line reason each was
taken.

THE ROSTERS, read 2026-09-18. motronics' pair was read at that sha inside the ``feat/optimi-lab``
worktree -- the tree those rosters' own prose quotes -- because its main checkout holds older
partitions and reads differently. A working tree that moves under a measurement is how a stamp names
a tree that was never the input, so the sha is part of the row.

THE CEILING IS TWO NUMBERS AND THE INTERVALS ARE DISJOINT, which is why
:func:`lab_commons.dev.famtests.placement.assert_ceiling_is_bounded` exists and a shared
``OWN_MECHANISM_CEILING`` does not. ``(35, 42)`` excludes 50; ``(49, 55)`` excludes 40. Shipping one
value would have been wrong for one of four consumers ON THAT CONSUMER'S OWN MEASUREMENT, and wrong
in the ADMITTING direction, which is the silent one.

THE DENSITY MINIMUM IS THE OPPOSITE READING AND IS WORTH AS MUCH. All four bound 3.0, their intervals
INTERSECT in ``(2.54, 3.06]``, and 3.0 sits inside it -- four independent measurements of one number.
It still does not ship as a constant: publishing it would delete the evidence and replace it with a
copy, and the fifth repo would inherit a number nothing measured against ITS files. The agreement is
data here, checked by a test, and importable by nobody as a bar.
"""

from __future__ import annotations

from typing import Final

__all__ = ['CEILINGS', 'MINIMUMS', 'NOT_FAMILY', 'ROSTERS']

#: ``roster -> (path, commit, rows)``. The population each bar below was bounded against.
ROSTERS: Final[dict[str, tuple[str, str, int]]] = {
    'wdg-lab': ('tests/architecture/_placement.py', 'cc8d8c11', 31),
    'optimi-lab': ('tests/architecture/_placement.py', '9299999', 23),
    'motronics tests': ('tests/architecture/layering/_tests_placement.py', '3befb376b', 77),
    'motronics scripts': ('tests/architecture/layering/_helpers.py', '3befb376b', 57),
}

#: ``roster -> (value, admits, refuses)`` for the OWN-MECHANISM CEILING, in ``own`` lines: the largest
#: reading the bar must admit, and the smallest it must refuse. Every number is `measure_density` run
#: on a real file by that roster's own author, quoted from the comment that bounds it.
CEILINGS: Final[dict[str, tuple[int, int, int]]] = {
    'wdg-lab': (50, 49, 55),
    'optimi-lab': (50, 43, 67),
    'motronics tests': (50, 47, 56),
    'motronics scripts': (40, 35, 42),
}

#: ``roster -> (value, admits, refuses)`` for the DENSITY MINIMUM, as percentages: the smallest
#: reading the bar must admit, and the largest it must refuse.
MINIMUMS: Final[dict[str, tuple[float, float, float]]] = {
    'wdg-lab': (3.0, 4.79, 1.41),
    'optimi-lab': (3.0, 3.06, 0.65),
    'motronics tests': (3.0, 3.06, 2.54),
    'motronics scripts': (3.0, 4.57, 0.67),
}

#: THE BOUNDARY, AND IT IS THE MORE VALUABLE HALF OF THE ANSWER. ``part -> (rosters holding it, why
#: it is not family)``. Direction alone is not a boundary and neither is a shared filename, so each
#: row carries the COUNT that decided it. A part held by 4 of 4 and identical is in the kit; anything
#: less is named here with its number, so the next reader can see it was decided rather than missed.
NOT_FAMILY: Final[dict[str, tuple[int, str]]] = {
    'partition composer': (
        2,
        (
            'merging per-subdirectory manifests and raising on a collision or on a row outside its partition. '
            'Both holders are motronics -- one repo`s answer written twice is not a family fact. It becomes one '
            'the day a lab partitions its roster.'
        ),
    ),
    'non-python reading': (
        3,
        (
            'three answers in four rosters: wdg-lab reads a shell file WHOLE, motronics strips whole-line '
            'comments and calls that its code-only reading, optimi-lab declares `.sh` runnable and has no '
            'reading at all -- so the day a shell file arrives there, `ast.parse` ERRORS rather than fails and '
            'an error carries no measurement. The named-set ceiling on the exemption (wdg-lab`s SHELL_ROWS) is '
            '1 of 4.'
        ),
    ),
    'pytest.param construction': (
        4,
        (
            '4 of 4 and four lines over a mapping the repo owns. This package publishes assertion BODIES and '
            'pure readers, never a plugin or a parametrize helper; a repo`s debt belongs where the repo can see '
            'it. `assert_no_stale_debt` is the half of that ratchet no consumer wrote.'
        ),
    ),
    'the bars, nouns, trees, floor and debt rows': (
        4,
        (
            'held by all four and DIFFERENT in all four. Data, which is the one thing a family half must never '
            'carry: a bar that arrived without its argument.'
        ),
    ),
}
