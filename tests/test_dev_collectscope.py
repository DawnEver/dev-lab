"""THE READER CAN FAIL, over PLANTED files, driving the real functions in `lab_commons.dev.collectscope`.

`test_the_test_trees_collect_after_a_sync.py` is the MEASUREMENT of the family. This file is the
control: every claim the reader makes is planted here in BOTH directions, because a scan that
convicts everything and a scan that convicts nothing produce the same green on a tree that happens
to be clean.

THE PAIR THAT MATTERS MOST is the guard one. A module-scope `import cv2` must be reported and a
`pytest.importorskip('cv2')` must NOT be, from the same manifest and the same distribution -- one
direction alone would be satisfied by a reader that always answers the same way.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from lab_commons.dev.collectscope import (
    ALIASES,
    Fate,
    Use,
    fate,
    local_modules,
    reach,
    read_imports,
    resolve,
)
from lab_commons.dev.syncscope import Selection

#: A manifest with the two shapes the join needs: a distribution whose import name matches it, and
#: two whose names do not. `dev` is the selection every control below makes.
MANIFEST: Final = """
[project]
name = 'planted'
dependencies = ['structlog']

[project.optional-dependencies]
dev = ['pytest']
vision = ['opencv-python', 'pillow']
"""

#: The selection under test: `dev` only, so `vision` is pruned and `structlog` survives as a base.
DEV: Final = Selection(prunes=True, extras=frozenset({'dev'}))

_DECLARED: Final = frozenset({'planted', 'structlog', 'pytest', 'opencv-python', 'pillow'})


def _reach(**files: str) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """Run the REAL reader over planted file texts and return its three sets."""
    readings = {name: read_imports(name, text) for name, text in files.items()}
    found = reach(readings, DEV, MANIFEST, _DECLARED, frozenset({'helpers'}))
    return found.errors, found.degrades, found.unresolved


def test_a_bare_module_scope_import_of_a_pruned_distribution_errors() -> None:
    """THE SUBJECT: `cv2` is not `opencv-python`, and the selection does not carry it."""
    errors, degrades, unresolved = _reach(**{'tests/test_a.py': 'import cv2\n'})
    assert errors == frozenset({'opencv-python'}), errors
    assert degrades == frozenset()
    assert unresolved == frozenset()


@pytest.mark.parametrize(
    'body',
    [
        "import pytest\n\ncv2 = pytest.importorskip('cv2')\n",
        'try:\n    import cv2\nexcept ImportError:\n    cv2 = None\n',
        'from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    import cv2\n',
        'def test_it():\n    import cv2\n\n    assert cv2\n',
    ],
)
def test_a_conditional_import_of_the_same_distribution_never_errors(body: str) -> None:
    """THE OTHER DIRECTION, four spellings, same distribution and same selection as the test above.

    Without this pair the reader could convict every optional integration in the family and still
    look right on the one file that proves it convicts anything at all.
    """
    errors, degrades, _ = _reach(**{'tests/test_b.py': body})
    assert errors == frozenset(), errors
    assert degrades <= frozenset({'opencv-python'}), degrades


def test_a_skip_mark_is_not_a_guard_and_the_import_beside_it_still_errors() -> None:
    """THE BRIEF SAID A SKIP MARK DEGRADES. It does not: the module body must run to CREATE the mark."""
    body = "import cv2\nimport pytest\n\npytestmark = pytest.mark.skipif(True, reason='no vision')\n"
    errors, _, _ = _reach(**{'tests/test_c.py': body})
    assert errors == frozenset({'opencv-python'}), errors


def test_a_narrow_except_does_not_guard_an_import() -> None:
    """`except ValueError` around an import catches nothing an absent distribution raises."""
    errors, degrades, _ = _reach(**{'tests/test_d.py': 'try:\n    import cv2\nexcept ValueError:\n    cv2 = None\n'})
    assert errors == frozenset({'opencv-python'}), errors
    assert degrades == frozenset()


def test_a_surviving_distribution_is_not_reported_in_either_column() -> None:
    """THE FLOOR ON CONVICTION: a base dependency and a selected extra are silent, guarded or not."""
    files = {
        'tests/test_e.py': 'import structlog\nimport pytest\n',
        'tests/test_f.py': "import pytest\n\npytest.importorskip('structlog')\n",
    }
    assert _reach(**files) == (frozenset(), frozenset(), frozenset())


def test_an_unresolvable_name_is_named_and_never_guessed_in_either_direction() -> None:
    """A transitive distribution no manifest declares is UNRESOLVED -- not a survivor, not a strand."""
    errors, degrades, unresolved = _reach(**{'tests/test_g.py': 'import tomlkit\n'})
    assert unresolved == frozenset({'tomlkit'}), unresolved
    assert errors == frozenset()
    assert degrades == frozenset()


def test_stdlib_and_local_names_resolve_to_nothing_prunable() -> None:
    """The two EMPTY answers, which are not the ``None`` one: neither is a miss."""
    assert resolve('pathlib', _DECLARED, frozenset()) == frozenset()
    assert resolve('helpers', _DECLARED, frozenset({'helpers'})) == frozenset()
    assert resolve('tomlkit', _DECLARED, frozenset()) is None


def test_an_alias_offers_every_declared_supplier_and_only_declared_ones() -> None:
    """THE BUILD-VARIANT CASE motronics forced: `cv2` is whichever opencv THIS manifest declares."""
    assert resolve('cv2', _DECLARED, frozenset()) == frozenset({'opencv-python'})
    headless = frozenset({'opencv-python-headless'})
    assert resolve('cv2', headless, frozenset()) == headless
    assert resolve('cv2', frozenset({'planted'}), frozenset()) is None


def test_any_surviving_supplier_is_enough() -> None:
    """One build variant satisfies the import as well as another, so the fate is over the INTERSECTION."""
    use = Use('cv2', 1, guarded=False)
    both = frozenset({'opencv-python', 'opencv-python-headless'})
    assert fate(use, both, frozenset({'opencv-python-headless'})) is Fate.SURVIVES
    assert fate(use, both, frozenset()) is Fate.ERRORS
    assert fate(Use('cv2', 1, guarded=True), both, frozenset()) is Fate.DEGRADES
    assert fate(use, None, frozenset()) is Fate.UNRESOLVED


def test_every_alias_row_is_reached_by_the_family_scan() -> None:
    """A RATCHET WITH TWO SIDES over the one table that is not derived: no unused row, no missing one.

    The set of import names the four test trees actually need an alias for is DERIVED by the live
    census beside this file; here it is only asserted that the table is small, keyed by import name
    and never keyed by a distribution -- the mistake the whole module exists to avoid.

    RE-TAKEN 2026-09-19 with BOTH READINGS QUOTED, because the pin went UP and a pin that goes up is
    where a bar gets quietly widened. It read ``{OCP, PIL, cv2, yaml}`` and now reads
    ``{OCP, PIL, cv2, pdfminer, pywintypes, win32com, yaml}``. Nothing was widened: the three new
    rows were each measured against motronics' live manifest -- ``pdfminer`` -> ``pdfminer.six`` in
    the ``img-to-cad`` extra, ``pywintypes`` and ``win32com`` -> ``pywin32`` in BOTH ``femm`` and
    ``tooldrivers`` -- and each had been sitting in the UNRESOLVED residue being reported as a
    transitive dependency no manifest declares. The table was short, not blind.
    """
    assert set(ALIASES) == {'OCP', 'PIL', 'cv2', 'pdfminer', 'pywintypes', 'win32com', 'yaml'}, sorted(ALIASES)
    for name, suppliers in ALIASES.items():
        assert name not in suppliers, f'{name} needs no alias: it already spells its own distribution'
        assert suppliers, f'{name} maps to no supplier, so the row can never resolve anything'


def test_local_modules_never_descends_into_an_installed_environment(tmp_path: Path) -> None:
    """THE ONE EXCLUSION THAT MATTERS: a walk into `.venv` calls every third-party import LOCAL."""
    (tmp_path / '.venv' / 'Lib' / 'site-packages' / 'cv2').mkdir(parents=True)
    (tmp_path / 'helpers.py').write_text('', encoding='utf-8')
    (tmp_path / 'pkg').mkdir()
    found = local_modules(tmp_path)
    assert 'helpers' in found
    assert 'pkg' in found
    assert 'cv2' not in found, 'the scan entered the environment and would never convict anything again'


def test_an_unparseable_file_is_reported_rather_than_dropped() -> None:
    """Dropping it would shrink the population every count is taken over, silently."""
    reading = read_imports('tests/test_broken.py', 'import cv2\ndef (\n')
    assert reading.parse_error
    assert reading.uses == ()


def test_the_hard_half_of_a_reading_is_the_unguarded_half() -> None:
    """`hard` is DERIVED from the same uses, so the two readings cannot disagree."""
    reading = read_imports('tests/test_h.py', 'import cv2\ntry:\n    import ezdxf\nexcept ImportError:\n    pass\n')
    assert [use.name for use in reading.uses] == ['cv2', 'ezdxf']
    assert [use.name for use in reading.hard] == ['cv2']
