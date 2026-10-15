"""THE SYNC-SELECTION CENSUS, pure DATA -- one row per place a set of extras is CHOSEN.

The machinery is `synccensus.py` and the reader under it is `syncscope.py`; the seam is the one
`test_arch_registry_data_is_separate.py` names for `_rule_rows.py`. Nothing here computes: a table
edited through the module that checks it drifts away from what it describes, because the same edit
that adds a row can relax the check that would have refused it and the diff reads as one change.

THE KIT'S OWN SELECTIONS ONLY. Every other repo declares the places IT chooses a set of extras, with
its own name and its own paths, in its own tests, and calls
:func:`lab_commons.dev.synccensus.assert_scopes` over its own checkout. Every scope and every stranded
name below is re-derived by `assert_scopes` from this repo's WORKING TREE, so a row that stops being
true REDS.

THE CI ROW IS THE CALLER SIDE OF A SHARED WORKFLOW. The `uv sync` is in
`.github/workflows/python-verify.yml` and its extras come from `$extra_flags`, a shell loop over a
workflow INPUT -- unreadable at the file that runs it, and different for every caller. `SITES`
records that file as the one pruning command in this repo's declared doors, and each caller --
this repo included -- records the `extras:` line that decides what it syncs.
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
        path='pyproject.toml',
        evidence='extras = "dev viz-mpl viz-bokeh"',
        selected=('dev', 'viz-mpl', 'viz-bokeh'),
        scope='COMPLETE',
        stranded=frozenset(),
        why=(
            'THE CALLER SIDE OF THE SHARED WORKFLOW. This line is the whole input to the `for extra '
            'in ...` loop that builds `$extra_flags`, so it decides what the reusable workflow syncs '
            'in THIS repo. `dev` here is pytest, pytest-mock, ruff and commitizen -- the extra that '
            'gates `lab_commons.dev` -- and this manifest names no pytest plugin in `addopts`, so '
            'the verdict set is pytest and ruff and both arrive. Dropping `dev` from this one line '
            'would leave CI green-looking and unable to run a single test. '
            'The selection grew on 2026-10-06 to name both `viz-` extras, because an adapter whose '
            'extra is absent degrades: `matplotlib` and `bokeh` arrive with it, no test module imports '
            'either unguarded, so the scope stays COMPLETE and nothing is stranded. Read where it is '
            'made: the workflow is rendered from `[tool.lab_commons.ci."ci.yml"]` in pyproject.toml.'
            ' The row carries no line number: six hand repoints (32 -> 48 -> 51 -> 242 -> 253 -> 254 '
            '-> 253 -> 257) each re-typed a position nothing had changed the meaning of, and the '
            'seventh went unmade and redded base on 2026-10-15. The position is now derived from the text.'
        ),
    ),
)

#: EVERY command in this repo's declared door files that moves a POPULATION, as
#: ``(repo, path, command text)``, with why it is the only one. Compared by EQUALITY against the live scan:
#: a row table alone can say that known selections still measure what they measured and can never
#: notice a new `uv sync` arriving in a Makefile.
SITES: dict[tuple[str, str, str], str] = {
    ('lab-commons', 'pyproject.toml', 'uv sync --python ${{ matrix.python-version }} $extra_flags'): (
        'THE KIT HAS EXACTLY ONE PRUNING COMMAND IN A DECLARED DOOR, and it is in a file that '
        'runs in every caller checkout. Its extras are `$extra_flags`, built by the shell loop above '
        'it from a workflow input, so the command text cannot say what survives -- the reader '
        'answers UNMEASURED here by construction and the ROWS above carry the judgement, one per '
        'caller. Every other lock-consuming door here takes `--no-sync`, which is what '
        'makes this set a singleton rather than a sample. '
        'Keyed by the command TEXT, not its line: four hand repoints each re-typed a position no '
        'edit had given a meaning, and a fifth went unmade. Lives in `[tool.lab_commons.ci."python-verify.yml"]`, '
        'the TOML the workflow is rendered from.'
    ),
}

#: The floor under how many repos a run must read: the one it runs in.
REPO_FLOOR: int = 1

#: The floor under how many ROWS were checked. The kit makes one selection, and reading none of it
#: would be a census of nothing.
ROW_FLOOR: int = 1

#: The floor under how many installer commands the SITES scan read before its equality means
#: anything. MEASURED 2026-10-02 at 17 across the kit's three door files (14 + 0 + 3); the floor sits
#: under it so an ordinary door edit does not red, and well above the zero an unread scan returns.
SITE_COMMAND_FLOOR: int = 12
