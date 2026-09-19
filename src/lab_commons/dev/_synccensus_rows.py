"""THE SYNC-SELECTION CENSUS, pure DATA -- one row per place a set of extras is CHOSEN.

The machinery is `synccensus.py` and the reader under it is `syncscope.py`; the seam is the one
`test_arch_registry_data_is_separate.py` names for `_rule_rows.py`. Nothing here computes: a table
edited through the module that checks it drifts away from what it describes, because the same edit
that adds a row can relax the check that would have refused it and the diff reads as one change.

MEASURED 2026-09-19 against four checkouts, at the commits `_doorcensus_rows.py` names, by joining
each selection with its repo's own `[project.optional-dependencies]`. Every scope and every stranded
name below is re-derived by `assert_scopes`, so a row that stops being true REDS.

THE FINDING, and it is a live line of running code rather than a hypothetical: motronics'
`scripts/gate/dep_sync.py` prints, immediately AFTER a prune has removed distributions, "re-run
naming every extra you need (`--extra all` where the project declares it)". That project DOES
declare `all`, and `all` there is `motronics[euclid,maxwell,pareto,femm,gui,native]` -- no `dev`.
Following the advice leaves the tree with no pytest, no xdist, no timeout plugin and no ruff, which
is the incident of 2026-09-18 a second time, arriving through the remedy for the first.

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
        line=32,
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
            'would leave CI green-looking and unable to run a single test.'
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
        line=458,
        evidence='--extra all',
        selected=('all',),
        scope='STRANDS',
        stranded=frozenset({'pytest', 'pytest-timeout', 'pytest-xdist', 'ruff'}),
        why=(
            'THE FINDING. This is the REMEDY the tool prints to an operator who has just watched it '
            'remove distributions, and the project does declare `all`, so the advice is followed. '
            '`all` is `motronics[euclid,maxwell,pareto,femm,gui,native]` and carries no `dev`, so a '
            'sync naming it alone removes the entire test runner -- which reads as a broken TREE and '
            'sends the reader to debug the wrong thing. The repair is the incantation that actually '
            'restored the box: `--extra all --extra dev --extra img-to-cad`.'
        ),
    ),
)

#: EVERY command in the family's declared door files that moves a POPULATION, as
#: ``(repo, path, line)``, with why it is the only one. Compared by EQUALITY against the live scan:
#: a row table alone can say that known selections still measure what they measured and can never
#: notice a new `uv sync` arriving in a Makefile.
SITES: dict[tuple[str, str, int], str] = {
    ('lab-commons', '.github/workflows/python-verify.yml', 83): (
        'THE FAMILY HAS EXACTLY ONE PRUNING COMMAND IN A DECLARED DOOR, and it is in a file that '
        'runs in every caller checkout. Its extras are `$extra_flags`, built by the shell loop above '
        'it from a workflow input, so the command text cannot say what survives -- the reader '
        'answers UNMEASURED here by construction and the ROWS above carry the judgement, one per '
        'caller. Every other lock-consuming door in the family takes `--no-sync`, which is what '
        'makes this set a singleton rather than a sample.'
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
