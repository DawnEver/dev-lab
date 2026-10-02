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
)

#: EVERY command in this repo's declared door files that moves a POPULATION, as
#: ``(repo, path, line)``, with why it is the only one. Compared by EQUALITY against the live scan:
#: a row table alone can say that known selections still measure what they measured and can never
#: notice a new `uv sync` arriving in a Makefile.
SITES: dict[tuple[str, str, int], str] = {
    ('lab-commons', '.github/workflows/python-verify.yml', 119): (
        'THE KIT HAS EXACTLY ONE PRUNING COMMAND IN A DECLARED DOOR, and it is in a file that '
        'runs in every caller checkout. Its extras are `$extra_flags`, built by the shell loop above '
        'it from a workflow input, so the command text cannot say what survives -- the reader '
        'answers UNMEASURED here by construction and the ROWS above carry the judgement, one per '
        'caller. Every other lock-consuming door here takes `--no-sync`, which is what '
        'makes this set a singleton rather than a sample. '
        'REPOINTED 2026-09-19 FROM LINE 83: the OS-matrix merge added a `runner-os` input, a matrix '
        'axis and a 30-line comment block above this step, moving the command down 36 lines. The '
        'command TEXT is unchanged, so what this key says about the family is unchanged and only '
        'the position was re-measured.'
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
