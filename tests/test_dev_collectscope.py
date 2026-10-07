"""THE READER CAN FAIL, over PLANTED files, driving the real functions in `lab_commons.dev.collectscope`.

`test_the_test_trees_collect_after_a_sync.py` is the MEASUREMENT of the family. This file is the
control: every claim the reader makes is planted here in BOTH directions, because a scan that
convicts everything and a scan that convicts nothing produce the same green on a tree that happens
to be clean.

THE PAIR THAT MATTERS MOST is the guard one. A module-scope `import cv2` must be reported and a
`pytest.importorskip('cv2')` must NOT be, from the same manifest and the same distribution -- one
direction alone would be satisfied by a reader that always answers the same way.

THE LOCAL-NAME POPULATION IS A THIRD SUCH PAIR, and it is over a REAL git checkout rather than a
planted directory. `local_modules` decides which import names "this checkout supplies"; taken from
the DISK it answers yes for whatever the box happens to have left lying around, and every such name
is a distribution the stranded-import census can no longer convict. So a name that is tracked must
be found and a name that is only debris must not, from the same tree, in both directions.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import pytest

from lab_commons.dev.collectscope import (
    ALIASES,
    Fate,
    NotACheckout,
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


def test_an_import_after_a_module_scope_importorskip_of_it_degrades() -> None:
    """MEASURED in a consumer 2026-10-01: ``importorskip('cv2')`` then ``from cv2 import x``.

    Collection raises the skip at the first statement, so the later bare import never runs on a box
    without the distribution. Only an import AFTER the skip is covered; one before it still errors.
    """
    after = "import pytest\n\npytest.importorskip('cv2')\n\nfrom cv2 import imread\n"
    errors, degrades, _ = _reach(**{'tests/test_after.py': after})
    assert errors == frozenset(), errors
    assert degrades == frozenset({'opencv-python'}), degrades
    before = "import pytest\nfrom cv2 import imread\n\npytest.importorskip('cv2')\n"
    errors, _, _ = _reach(**{'tests/test_before.py': before})
    assert errors == frozenset({'opencv-python'}), errors


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


def test_pytests_implementation_package_resolves_to_pytest() -> None:
    """``from _pytest.mark.expression import Expression`` is pytest, not a transitive unknown."""
    assert resolve('_pytest', _DECLARED, frozenset()) == frozenset({'pytest'})


def test_stdlib_and_local_names_resolve_to_nothing_prunable() -> None:
    """The two EMPTY answers, which are not the ``None`` one: neither is a miss."""
    assert resolve('pathlib', _DECLARED, frozenset()) == frozenset()
    assert resolve('helpers', _DECLARED, frozenset({'helpers'})) == frozenset()
    assert resolve('tomlkit', _DECLARED, frozenset()) is None


def test_an_alias_offers_every_declared_supplier_and_only_declared_ones() -> None:
    """THE BUILD-VARIANT CASE consumer-a forced: `cv2` is whichever opencv THIS manifest declares."""
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
    rows were each measured against consumer-a' live manifest -- ``pdfminer`` -> ``pdfminer.six`` in
    the ``img-to-cad`` extra, ``pywintypes`` and ``win32com`` -> ``pywin32`` in BOTH ``femm`` and
    ``tooldrivers`` -- and each had been sitting in the UNRESOLVED residue being reported as a
    transitive dependency no manifest declares. The table was short, not blind.

    RE-TAKEN 2026-10-01: ``_pytest`` -> ``pytest``, reached by consumer-b's tier-partition test importing
    pytest's expression parser, which the residue had been reporting as an undeclared transitive.
    """
    expected = {'OCP', 'PIL', '_pytest', 'cv2', 'pdfminer', 'pywintypes', 'win32com', 'yaml'}
    assert set(ALIASES) == expected, sorted(ALIASES)
    for name, suppliers in ALIASES.items():
        assert name not in suppliers, f'{name} needs no alias: it already spells its own distribution'
        assert suppliers, f'{name} maps to no supplier, so the row can never resolve anything'


def _git(root: Path, *arguments: str) -> None:
    """Run git at *root* and refuse a non-zero exit, so a broken plant fails loudly."""
    subprocess.run(
        ['git', '-C', str(root), *arguments],  # noqa: S607
        capture_output=True,
        check=True,
    )


def _checkout(root: Path, *, files: Mapping[str, str], ignores: tuple[str, ...] = ()) -> Path:
    """A REAL git checkout at *root*: a ``.gitignore`` naming *ignores*, then *files* STAGED.

    Staged rather than committed, because ``git ls-files`` reads the INDEX and a commit would need
    an identity this box may not have. Nothing here is a test OF git: the subject is the reader, and
    what the plant has to supply is a tree where "tracked" and "on disk" are different questions.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / '.gitignore').write_text(''.join(f'{pattern}\n' for pattern in ignores), encoding='utf-8')
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding='utf-8')
    _git(root, 'init', '--quiet')
    _git(root, 'add', '-A')
    return root


def _write(root: Path, name: str, body: str = '') -> None:
    """One debris file, creating whatever directories it needs."""
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding='utf-8')


#: What the family's own ``.gitignore`` leaves behind on a box that has RUN things -- every entry
#: measured as a directory the walk used to descend into and git does not track.
DEBRIS: Final[tuple[str, ...]] = (
    # A clone the sibling-repo pattern leaves at the root; `lib` is a plausible import name.
    '.venv/Lib/site-packages/cv2/__init__.py',
    '.pytest_cache/v/cache/lastfailed',
    '.ruff_cache/0.16.10/somehash',
    'htmlcov/index.html',
    # THE MEASURED ONE, from consumer-b 2026-10-07: a directory retired from the index but left on disk
    # holding nothing but a `__pycache__`. `src/app/viz/backend/bokeh/` still existed on the
    # box, so the walk answered that `import bokeh` was supplied by a checkout that does not.
    'src/app/viz/backend/bokeh/__pycache__/plot.cpython-313.pyc',
    # The same shape one directory higher: `design` and `wdg` were names an output tree supplied.
    'output/logs/26/09/14/design/3Ph-48/wdg/result.toml',
)

_IGNORES: Final[tuple[str, ...]] = (
    '.venv/',
    '.pytest_cache/',
    '.ruff_cache/',
    '__pycache__/',
    'htmlcov/',
    'output/',
    '*.pyc',
)

_TRACKED: Final[dict[str, str]] = {
    'src/real_module.py': '',
    'helpers.py': '',
    'tests/unit/test_a.py': '',
}


class TestTheLocalNamePopulationIsTheCheckouts:
    """D1, MEASURED 2026-10-07: a filesystem walk and a checkout are not the same set of files.

    ``local_modules`` answers "what can be imported from THIS CHECKOUT", and `resolve` reads a local
    name as SUPPLIED -- so every name the box adds beyond the checkout is a distribution the
    stranded-import census can no longer convict. The walk's answer was a fact about the machine;
    the population is now git's own, which is a fact about the checkout and nothing else.
    """

    def test_a_tracked_file_and_a_tracked_directory_are_local(self, tmp_path: Path) -> None:
        """THE FLOOR. A scan that found nothing would agree with the debris tests below vacuously."""
        root = _checkout(tmp_path, files=_TRACKED)
        found = local_modules(root)
        assert {'real_module', 'helpers', 'tests', 'unit', 'src'} <= found, sorted(found)

    def test_a_file_the_author_has_just_written_is_local(self, tmp_path: Path) -> None:
        """``-o`` IS LOAD-BEARING and it is the half ``--cached`` alone would lose.

        A file that is untracked and NOT ignored is one somebody wrote this minute and will commit;
        it is part of the checkout in every sense that matters to this reader. Only IGNORED debris
        is not.
        """
        root = _checkout(tmp_path, files=_TRACKED, ignores=_IGNORES)
        _write(root, 'fresh_module.py')
        assert 'fresh_module' in local_modules(root)

    @pytest.mark.parametrize('debris', DEBRIS, ids=lambda name: name.split('/')[0])
    def test_ignored_debris_never_supplies_an_import_name(self, tmp_path: Path, debris: str) -> None:
        """THE SUBJECT, one plant per shape, each of them a directory the walk answered for.

        A directory is a name to this reader -- the tree position of a module is decided by pytest's
        rootdir insertion, not by the package layout -- so a directory that exists only as debris is
        a name that exists only as debris.
        """
        root = _checkout(tmp_path, files=_TRACKED, ignores=_IGNORES)
        _write(root, debris)
        found = local_modules(root)
        assert 'real_module' in found, 'the control: the checkout is still read'
        assert not found & {'cv2', 'venv', 'cache', 'bokeh', 'design', 'wdg', '__pycache__'}, sorted(found)

    def test_a_checkout_with_debris_and_one_without_agree(self, tmp_path: Path) -> None:
        """THE TWO TREES ARE THE SAME COMMIT, which is the whole complaint.

        MEASURED before the fix on consumer-b: one ``tree=`` hash produced a different census in two
        worktrees, because a stale ``__pycache__`` under a retired module changed the local set. A
        verdict that cannot be reproduced from its own tree hash is not a verdict, so this asserts
        equality between a checkout that has run things and one that has not.
        """
        clean = _checkout(tmp_path / 'clean', files=_TRACKED, ignores=_IGNORES)
        dirty = _checkout(tmp_path / 'dirty', files=_TRACKED, ignores=_IGNORES)
        for debris in DEBRIS:
            _write(dirty, debris)
        assert local_modules(clean) == local_modules(dirty)

    def test_debris_does_not_mask_a_distribution_that_the_checkout_does_not_supply(self, tmp_path: Path) -> None:
        """THE HARM, AT THE JOIN. ``resolve`` answers ``None`` for a name no text settled.

        An empty answer is the honest residue; the empty SET is "supplied, nothing can prune it".
        A ``bokeh/`` left over from a retirement commit turned the first into the second, which is
        the false negative this module's docstring argues the derivation never errs in.
        """
        root = _checkout(tmp_path, files=_TRACKED, ignores=_IGNORES)
        _write(root, 'output/bokeh/plot.py')
        assert resolve('bokeh', frozenset(), local_modules(root)) is None

    def test_a_directory_that_is_not_a_checkout_is_refused(self, tmp_path: Path) -> None:
        """UNSUPPORTED-RAISES. A tree git does not answer for has no checkout-supplied names.

        The empty set would not be a smaller answer, it would be the OPPOSITE one: every local name
        would fall through to UNRESOLVED, and the census would report a residue that is not there.
        """
        _write(tmp_path, 'helpers.py')
        with pytest.raises(NotACheckout, match='not in a git work tree'):
            local_modules(tmp_path)


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
