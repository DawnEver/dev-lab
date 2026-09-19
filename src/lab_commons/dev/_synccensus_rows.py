"""THE SYNC-SELECTION CENSUS, pure DATA -- one row per place a set of extras is CHOSEN.

The machinery is `synccensus.py` and the reader under it is `syncscope.py`; the seam is the one
`test_arch_registry_data_is_separate.py` names for `_rule_rows.py`. Nothing here computes: a table
edited through the module that checks it drifts away from what it describes, because the same edit
that adds a row can relax the check that would have refused it and the diff reads as one change.

MEASURED 2026-09-19 against four checkouts, at the commits `_doorcensus_rows.py` names, by joining
each selection with its repo's own `[project.optional-dependencies]`. Every scope and every stranded
name below is re-derived by `assert_scopes`, so a row that stops being true REDS.

THE FINDING, AND IT IS NOW CLOSED, WITH BOTH NUMBERS ON RECORD. motronics'
`scripts/gate/dep_sync.py` printed, immediately AFTER a prune had removed distributions, "re-run
naming every extra you need (`--extra all` where the project declares it)". That project DOES
declare `all`, and `all` there is `motronics[euclid,maxwell,pareto,femm,gui,native]` -- no `dev` --
so following the advice left the tree with no pytest, no xdist, no timeout plugin and no ruff: the
incident of 2026-09-18 a second time, arriving through the remedy for the first. motronics commit
1a50949 rewrote that text on 2026-09-19 and the row below is REPOINTED to the line that makes the
selection today, STRANDS -> COMPLETE. The evidence pin is what forced the visit; without it the row
would still be describing a sentence nobody prints.

WHY THE CI ROWS ARE FILED UNDER THE CALLER AND NOT UNDER THE WORKFLOW THAT SYNCS. The `uv sync` is
in `lab-commons/.github/workflows/python-verify.yml` and its extras come from `$extra_flags`, a
shell loop over a workflow INPUT -- unreadable at the file that runs it, and different for every
caller. `SITES` records that file as the one pruning command in the family's declared doors, and the
rows below record the two callers that decide what it syncs. That is the `SharedDoor` finding one
axis over: the selection and the command live in different repositories.

WDG-LAB HAS NO ROW AND THAT IS A MEASUREMENT. Its only lock-consuming doors carry `--no-sync`, so no
command in its declared door set chooses a population at all. `SITES` is compared by EQUALITY, so
the day a `uv sync` lands in any of the four, it reds as uncensused rather than joining quietly.
"""

from __future__ import annotations

from lab_commons.dev.synccensus import ScopeRow

__all__ = [
    'REPO_FLOOR',
    'ROWS',
    'ROW_FLOOR',
    'SITES',
    'SITE_COMMAND_FLOOR',
]

#: One row per selection. `scope` and `stranded` are compared by EQUALITY in both directions: a
#: selection that starts stranding something reds, and so does one recorded as stranding what it no
#: longer strands -- a ratchet with one side is a capability that can only be lowered.
ROWS: tuple[ScopeRow, ...] = (
    ScopeRow(
        repo='lab-commons',
        path='.github/workflows/ci.yml',
        line=48,
        evidence="extras: 'dev'",
        selected=('dev',),
        scope='COMPLETE',
        stranded=frozenset(),
        why=(
            'THE CALLER SIDE OF THE SHARED WORKFLOW. This line is the whole input to the `for extra '
            'in ...` loop that builds `$extra_flags`, so it decides what the reusable workflow syncs '
            'in THIS repo. `dev` here is pytest, pytest-mock, ruff and pre-commit -- the extra that '
            'gates `lab_commons.dev` -- and this manifest names no pytest plugin in `addopts`, so '
            'the verdict set is pytest and ruff and both arrive. Dropping `dev` from this one line '
            'would leave CI green-looking and unable to run a single test. '
            'REPOINTED 2026-09-19 FROM LINE 32, AND BOTH NUMBERS STAY ON RECORD. The OS-matrix merge '
            'inserted a 16-line `runner-os` block above this input, so the evidence text moved 32 -> '
            '48 with not one character of it changed. The SELECTION is therefore re-measured and '
            'identical -- `dev`, COMPLETE, stranding nothing -- and only the position moved: this is '
            'the row doing its job, since a pin that could not notice a 16-line shift could not '
            'notice a deletion either.'
        ),
    ),
    ScopeRow(
        repo='optimi-lab',
        path='.github/workflows/ci.yml',
        line=38,
        evidence="extras: 'dev'",
        selected=('dev',),
        scope='COMPLETE',
        stranded=frozenset(),
        why=(
            'THE SAME LINE IN THE REPO WITH THE LONGER VERDICT SET, which is why it is worth a second '
            'row rather than reading as a duplicate. This manifest `addopts` carries `--cov`, so '
            'pytest-cov is as load-bearing as pytest -- pytest exits 4 on an unrecognised option and '
            'reports no verdict at all -- and it declares lab-commons only INSIDE the `dev` extra, '
            'so this selection is the only thing putting the verify entry point in the environment. '
            'Three of its four critical distributions hang on this one word.'
        ),
    ),
    ScopeRow(
        repo='motronics-studio',
        path='scripts/gate/dep_sync.py',
        line=4,
        evidence='--sync --extra pareto --extra dev',
        selected=('pareto', 'dev'),
        scope='COMPLETE',
        stranded=frozenset(),
        why=(
            'THE SANCTIONED SPELLING, and the row that says it is sanctioned for the right reason. '
            'It survives because `dev` carries pytest, pytest-xdist, pytest-timeout and ruff and '
            'because lab-commons is a REQUIRED dependency there, not because the author enumerated '
            'the environment. What it does remove is real -- measured 2026-09-15, cadquery-ocp and '
            'wdg-lab -- so COMPLETE here means the tree can still report a verdict, never that the '
            'environment is whole. That distinction is the module docstring of `syncscope`.'
        ),
    ),
    ScopeRow(
        repo='motronics-studio',
        path='scripts/gate/dep_sync.py',
        line=475,
        evidence='--extra all --extra dev --extra img-to-cad',
        selected=('all', 'dev', 'img-to-cad'),
        scope='COMPLETE',
        stranded=frozenset(),
        why=(
            'THE FINDING, RE-MEASURED 2026-09-19 AFTER IT WAS FIXED, AND BOTH NUMBERS STAY ON RECORD. '
            'At `dep_sync.py:458` this row read `--extra all`, scope STRANDS, stranded pytest, '
            'pytest-xdist, pytest-timeout and ruff: the REMEDY the tool printed to an operator who '
            'had just watched it remove distributions. motronics commit 1a50949 rewrote that text -- '
            'it now says `all` is not all of them and names the whole set -- so the row is repointed '
            'to the line that makes the selection today, and the scope moved STRANDS -> COMPLETE. '
            'That is a ratchet closing, not a band loosening; the evidence pin is what forced the '
            'visit. Note what COMPLETE still does not mean: `test_the_test_trees_collect_after_a_sync` '
            'measures this same selection stranding `pillow` at COLLECTION.'
        ),
    ),
)

#: EVERY command in the family's declared door files that moves a POPULATION, as
#: ``(repo, path, line)``, with why it is the only one. Compared by EQUALITY against the live scan:
#: a row table alone can say that known selections still measure what they measured and can never
#: notice a new `uv sync` arriving in a Makefile.
SITES: dict[tuple[str, str, int], str] = {
    ('lab-commons', '.github/workflows/python-verify.yml', 119): (
        'THE FAMILY HAS EXACTLY ONE PRUNING COMMAND IN A DECLARED DOOR, and it is in a file that '
        'runs in every caller checkout. Its extras are `$extra_flags`, built by the shell loop above '
        'it from a workflow input, so the command text cannot say what survives -- the reader '
        'answers UNMEASURED here by construction and the ROWS above carry the judgement, one per '
        'caller. Every other lock-consuming door in the family takes `--no-sync`, which is what '
        'makes this set a singleton rather than a sample. '
        'REPOINTED 2026-09-19 FROM LINE 83: the OS-matrix merge added a `runner-os` input, a matrix '
        'axis and a 30-line comment block above this step, moving the command down 36 lines. The '
        'command TEXT is unchanged, so what this key says about the family is unchanged and only '
        'the position was re-measured.'
    ),
}

#: The floor under how many repos a run must reach before an empty finding means anything. A census
#: of one tree is not a census, and every finding this table holds is cross-repo.
REPO_FLOOR: int = 2

#: The floor under how many ROWS were checked. Below it the run reached repos and read no selection.
ROW_FLOOR: int = 3

#: The floor under how many installer commands the SITES scan read before its equality means
#: anything. An empty scan finds no uncensused site and reads exactly like a censused family.
SITE_COMMAND_FLOOR: int = 10
