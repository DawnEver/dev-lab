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

UNRESOLVED IS RECORDED, NEVER TOLERATED, AND AS OF 2026-09-19 IT IS ALSO AUDITED. A name no
committed text can settle is pinned by EQUALITY like everything else -- but equality alone only
proved the list did not CHANGE, never that it was right, and the first residue this table recorded
was WRONG in three of its five names. `UNRESOLVED_WHY` below carries a reason per name and
`assert_no_unresolved_has_a_declared_supplier` refuses a name the manifest beside it already
answers, so a short table now fails where before it merely sat there looking like a blind spot.
"""

from __future__ import annotations

from _collect_census import CollectRow

__all__ = [
    'FILE_FLOORS',
    'PAIR_FLOOR',
    'REPO_FLOOR',
    'ROWS',
    'ROW_FLOOR',
    'UNRESOLVED_WHY',
    'WHY_FLOOR_PER_NAME',
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
        degrades=frozenset({'gmsh', 'pdfminer-six', 'pywin32'}),
        unresolved=frozenset({'tomlkit', 'yaml'}),
        why=(
            'THE FINDING. This is the selection `_synccensus_rows.py` scores COMPLETE and calls the '
            'sanctioned spelling, and it is right: the runner survives it. The tree it leaves cannot '
            'be collected -- seven distributions are hard module-scope imports under `tests/` and '
            'none of them is in `pareto` or `dev`. The scope and the reach disagree because they are '
            'different questions, which is the entire argument for this module existing. `pdfminer-six` and '
            '`pywin32` sit in DEGRADES rather than in the residue as first recorded: both are '
            'declared -- `pdfminer.six` in `img-to-cad`, `pywin32` in BOTH `femm` and `tooldrivers` '
            '-- and every use of them is guarded, so this selection makes them skip rather than '
            'strand. `yaml` stays UNRESOLVED because pyyaml reaches that tree transitively and no '
            'manifest in it declares any supplier, so no text here can settle whether it survives.'
        ),
    ),
    CollectRow(
        repo='motronics-studio',
        selected=('all', 'dev', 'img-to-cad'),
        errors=frozenset({'pillow'}),
        degrades=frozenset(),
        unresolved=frozenset({'tomlkit', 'yaml'}),
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


#: The shortest a residue REASON may be. Shorter than a row's `WHY_FLOOR` because the subject is one
#: name rather than a whole selection, and long enough that "transitive" alone cannot be the answer.
WHY_FLOOR_PER_NAME: int = 160

#: EVERY name the table reports UNRESOLVED, and WHY no committed text settles it. Pinned in BOTH
#: directions against the live residue: a new one cannot arrive without a reason, and a name that
#: stops being unresolved cannot leave its reason behind as a waiver nothing uses.
#:
#: THIS TABLE IS THE CORRECTION TO 2026-09-19's FIRST RESIDUE. That reading was
#: `{pdfminer, pywintypes, tomlkit, win32com, yaml}` and was reported as "all transitive, none
#: declared by any manifest". Three of the five were declared -- by the manifest being read, in
#: extras that were sitting right there -- and nothing could tell, because a residue is a bare list
#: of names and a bare list of names looks the same whether it was checked or assumed. Writing the
#: reason per name is what makes the assumption fail out loud; `derivable_suppliers` is what catches
#: the half a spelling can settle without anybody writing anything.
UNRESOLVED_WHY: dict[str, str] = {
    'pydantic_core': (
        'THE ONE THAT REALLY IS TRANSITIVE, and it is the near-miss the derivation must NOT force: '
        'wdg-lab declares `pydantic`, and `pydantic-core` is a DIFFERENT distribution -- pydantic '
        'depends on it and pins its version, so it arrives through the lock graph. No spelling rule '
        'relates a declared name to a name that merely starts with it, and inventing one would read '
        'every `foo-bar` in a manifest as the supplier of `foo`.'
    ),
    'scipy': (
        'GENUINELY UNDECLARED: `scipy` appears nowhere in the wdg-lab manifest -- not in the base, not '
        'in an extra -- and it is imported at module scope in its test tree anyway, so it is reaching '
        'that environment through the requirements of some other distribution. Whether a prune keeps it '
        'is a property of the LOCK, which no reading of a manifest can answer.'
    ),
    'tomlkit': (
        'UNDECLARED IN MOTRONICS, and unlike `yaml` it needs no alias either: the import name IS the '
        'distribution name, so `resolve` rule 1 would have claimed it the moment any manifest in that '
        'repo declared it. None does. It arrives transitively -- commitizen and pdoc-class tooling '
        'both carry it -- and a manifest cannot say whether a prune keeps it.'
    ),
    'yaml': (
        'AN ALIAS WITH NO DECLARED SUPPLIER TO POINT AT. `yaml` is `pyyaml` and the ALIASES row says '
        'so, but ALIASES only ever narrows to distributions the manifest DECLARES, and motronics '
        'declares no pyyaml anywhere. So the row resolves nothing here and the name falls to the '
        'residue, which is the rule working: an alias must never convict a manifest on a guess.'
    ),
}

#: The floor under how many (import name, declared distribution) pairs the derivation scan examined.
#: MEASURED 2026-09-19 at 222 across three present rows; below it, finding no derivable supplier
#: says only that nothing was read.
PAIR_FLOOR: int = 180
