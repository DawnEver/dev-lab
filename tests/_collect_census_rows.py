"""THE COLLECTION-REACH CENSUS, pure DATA -- one row per (repo, selection) the family actually makes.

The machinery is `_collect_census.py` and the reader under both is
`lab_commons.dev.collectscope`; the seam is the one `_config_census_rows.py` already uses. Nothing
here computes: a table edited through the module that checks it drifts away from what it describes.

MEASURED 2026-09-19 against four checkouts -- lab-commons' WORKING TREE, the other three at `HEAD` --
by joining each repo's test tree with what its own selection leaves installed. Every set below is
re-derived by `assert_reaches` and compared by EQUALITY IN BOTH DIRECTIONS, so a selection that
starts stranding something reds, and so does one recorded as stranding what it no longer strands.

WHY THE SELECTIONS ARE THE ONES `_synccensus_rows.ROWS` ALREADY NAMES. That table asked whether each
would leave the RUNNER able to start and scored three of its four COMPLETE. This one asks the
question its own docstring names as unmeasurable -- whether COLLECTION would then succeed -- so the
rows have to be the SAME selections or the two answers are about different commands.

THE FINDING, and it is two COMPLETE rows and one documented repair:

* motronics' SANCTIONED `--extra pareto --extra dev` strands SEVEN distributions at collection.
  `_synccensus_rows.py` calls it "the sanctioned spelling" and is right at its own question.
* wdg-lab's CI `extras: 'dev'` strands four, and the SAME import name that degrades safely there
  (`OCP`, behind `pytest.importorskip`) is a bare module-scope import in motronics. One reader, two
  answers, from the guard and not from the name -- which is the control this table exists to hold.
* `--extra all --extra dev --extra img-to-cad`, recorded by the sibling table as "the incantation
  that actually restored the box", leaves the runner whole and STILL strands `pillow`: motronics
  declares it only in a `tooldrivers` extra no recorded incantation names. That row is here
  precisely because it is the closest thing the family has to a correct answer.

UNRESOLVED IS RECORDED, NEVER TOLERATED. A name no committed text can settle -- a transitive
dependency no manifest declares -- is pinned by EQUALITY like everything else, so a new one is an
edit somebody looked at rather than a hole that widens quietly.
"""

from __future__ import annotations

from _collect_census import CollectRow

__all__ = [
    'FILE_FLOORS',
    'REPO_FLOOR',
    'ROWS',
    'ROW_FLOOR',
]

#: One row per (repo, selection). Three sets, each by EQUALITY in both directions.
ROWS: tuple[CollectRow, ...] = (
    CollectRow(
        repo='lab-commons',
        selected=('dev',),
        errors=frozenset(),
        degrades=frozenset(),
        unresolved=frozenset(),
        why=(
            'THE KIT COLLECTS, and it is the only repo in the family that does. Its whole test tree '
            'imports lab_commons, pytest, numpy, pint and rtoml and nothing else, every one of them '
            'in the `dev` extra or the base, and it resolves every import name it uses -- an empty '
            'UNRESOLVED set here is what proves the three resolution rules cover an entire real tree '
            'rather than only the names somebody thought to alias.'
        ),
    ),
    CollectRow(
        repo='wdg-lab',
        selected=('dev',),
        errors=frozenset({'diskcache', 'fastapi', 'httpx', 'pandas'}),
        degrades=frozenset({'cadquery-ocp', 'uvicorn'}),
        unresolved=frozenset({'pydantic_core', 'scipy'}),
        why=(
            'THE CONTROL THE FAMILY SUPPLIES ITSELF, in both directions at once and over the same '
            'repo. The web tier hard-imports fastapi, httpx, diskcache and pandas at module scope, '
            'so the CI selection that scores COMPLETE cannot collect those files; and cadquery-ocp '
            'and uvicorn reach the SAME tree through `pytest.importorskip`, so they skip. A reader '
            'that convicted every optional integration would report six, and one that trusted the '
            'scope would report none. `scipy` and `pydantic_core` are transitive: NAMED, not guessed.'
        ),
    ),
    CollectRow(
        repo='optimi-lab',
        selected=('dev',),
        errors=frozenset(),
        degrades=frozenset(),
        unresolved=frozenset(),
        why=(
            'THE SECOND CLEAN REPO, and it is not a duplicate of the kit: its `dev` extra is the only '
            'thing putting lab-commons in the environment at all, so this row is what says that the '
            'ONE selection three of its four critical distributions hang on also carries every import '
            'its tests make. A clean answer over a tree that was actually read, which the file floor '
            'beside this table is what makes checkable.'
        ),
    ),
    CollectRow(
        repo='motronics-studio',
        selected=('pareto', 'dev'),
        errors=frozenset(
            {
                'cadquery-ocp-novtk',
                'ezdxf',
                'meshio',
                'motronics-native',
                'opencv-python-headless',
                'pillow',
                'wdg-lab',
            }
        ),
        degrades=frozenset({'gmsh'}),
        unresolved=frozenset({'pdfminer', 'pywintypes', 'tomlkit', 'win32com', 'yaml'}),
        why=(
            'THE FINDING. This is the selection `_synccensus_rows.py` scores COMPLETE and calls the '
            'sanctioned spelling, and it is right: the runner survives it. The tree it leaves cannot '
            'be collected -- seven distributions are hard module-scope imports under `tests/` and '
            'none of them is in `pareto` or `dev`. The scope and the reach disagree because they are '
            'different questions, which is the entire argument for this module existing; `yaml` is '
            'UNRESOLVED rather than stranded because pyyaml reaches that tree transitively and no '
            'manifest in it declares any supplier, so no text here can settle whether it survives.'
        ),
    ),
    CollectRow(
        repo='motronics-studio',
        selected=('all', 'dev', 'img-to-cad'),
        errors=frozenset({'pillow'}),
        degrades=frozenset(),
        unresolved=frozenset({'pdfminer', 'pywintypes', 'tomlkit', 'win32com', 'yaml'}),
        why=(
            'THE RECORDED REPAIR, STILL ONE EXTRA SHORT. The sibling table names this as "the '
            'incantation that actually restored the box" and it is the best selection the family has '
            'written down: it carries the runner, the plugins, the linter and every vendor extra. It '
            'still strands `pillow`, which motronics declares ONLY in a `tooldrivers` extra that no '
            'incantation, no document and no running code in that repo names. So there is no recorded '
            'selection in motronics that collects its own test tree, and this row is where that '
            'stops being an opinion -- a repair that reaches empty here is the ratchet closing.'
        ),
    ),
)

#: Per repo, the fewest test files a run must have READ before its answer means anything. MEASURED
#: 2026-09-19 at 108 / 192 / 28 / 2632 and set below them, because a tree that was not read reports
#: the same empty stranded set as a tree whose every import survives.
FILE_FLOORS: dict[str, int] = {
    'lab-commons': 90,
    'motronics-studio': 2000,
    'optimi-lab': 20,
    'wdg-lab': 150,
}

#: The floor under how many repos a run reached. A census of one tree is not a census, and every
#: finding here is the disagreement BETWEEN two repos reading the same import name.
REPO_FLOOR: int = 2

#: The floor under how many ROWS were checked. Below it the run reached repos and judged no selection.
ROW_FLOOR: int = 3
