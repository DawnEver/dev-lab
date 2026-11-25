"""The rules registry's LAYOUT rows -- pure DATA, the same row shape as ``_rule_rows.py``.

Every rule about which directories a checkout may hold and what each may hold.
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'DECLARED-LAYOUT',
        (
            # Why: user rulings 2026-11-23 -- the WHOLE directory and subdirectory tree is declared with its formats.
            'A checkout`s whole tree is an ALLOW-LIST in `[layout]` of its root `layout.toml`: EVERY directory matches '
            'a row of its own (no inheritance; explicit beats glob, then fewer wildcards; a tie is ambiguous) '
            'listing the formats a file there may be; anything undeclared is refused. Every family home is '
            'declared; `output/` never allows code or `*`; a `read_only` path is never written; a `.claude/` below '
            'the root is refused. The write hook refuses a Write/Edit, every `verify` and forge tick runs the '
            'INCREMENTAL scan, and every adopter`s architecture suite walks the filesystem under a floor '
            '(`dev_lab.dev.famtests.layout`).'
        ),
        ('tests/test_dev_layout.py', 'tests/test_arch_code_placement.py'),
    ),
    (
        'NO-BACKUP-COPIES',
        (
            # Why: user ruling 2026-11-23 -- 3.4 M copied source files under one repo's output/ (333 GB).
            '`output/` and `scratch/` never hold a copy or backup of work: no clone or worktree (a `.git`), no '
            'exported tree (`pyproject.toml` beside `src/`), no bundle, patch or diff, whatever a layout row says. '
            'Work is merged or deleted (MERGE-OR-DELETE), never saved aside. The shell guard refuses a command '
            'that makes one there, the write hook refuses the file, and the layout scan names the directory.'
        ),
        ('tests/test_dev_layout.py', 'tests/test_dev_nobackup.py'),
    ),
    (
        'ZERO-CORE-CHANGE',
        (
            # Why: user ruling 2026-11-24 -- application work never changes the core without an architecture decision.
            'In a repo declaring `[tool.dev_lab.layers] core = [...]` and `applications = "<glob>"` (opt-in; an '
            'undeclared repo is said to be not judged), a change set touching an application root AND the core is '
            'refused unless a commit of it carries `Architecture-Decision: <task>#D<n>` naming a decision RECORDED '
            'in the task ledger (a made-up id is refused); the door is `python -m dev_lab.dev.task decide`, then the '
            'trailer. The set is judged net since its merge-base (the `zero-core-change` pre-push row; '
            '`corechange range <base> <head>` for a PR diff). Always on where declared: the core never imports an '
            'application, and the applications form an acyclic import graph, the cycle named '
            '(`dev_lab.dev.corechange`).'
        ),
        ('tests/test_dev_corechange.py',),
    ),
    (
        'NATIVE-FIRST',
        (
            # Why: user ruling 2026-11-25 (principle `native-first`) -- Python orchestrates, Rust computes.
            'In a repo declaring `[tool.dev_lab.native] orchestration = [...]` and `[tool.dev_lab.native.stages] '
            '<stage> = "<native module>"` (opt-in; undeclared is not judged), an AST read refuses, '
            'under an orchestration path, an index loop (`range`/`ndindex`/counted `while`) that stores, '
            'updates or computes on an element or calls `math` per element, and a module named for a native-owned '
            'stage that never imports its native module; anywhere, a test importing both a stage`s native module '
            'and a same-named Python module. No types: a dict index loop reads as an array one; direct '
            'iteration, comprehensions and a renamed twin are not seen. The `native-first` pre-commit row and the '
            'always-on check (`dev_lab.dev.nativefirst`).'
        ),
        ('tests/test_dev_nativefirst.py',),
    ),
    (
        'OWNER-DAG',
        (
            # Why: user-approved 2026-11-25 (principles `everything-in-its-place`, `no-detour`; v1 D67/D68).
            'In a repo holding a root `dependencies.toml` (opt-in; undeclared is not judged), actual imports match '
            'the declared graph: `[python.owners]` and `[python.siblings."<package>"]` (explicit acyclic DAGs at '
            'every level, default none), `[python.importers]` (the only importers of a path), `[python.native]`, '
            '`[python.packages]`/`[python.stdlib]` (a package no row names is refused; std is restricted by row), '
            '`[rust.crates]`/`[rust.external]`/`[rust.std]` (Cargo dependencies by kind and feature, std paths and '
            'tokens). A cycle, an undeclared edge and a row naming nothing in the tree are refused by name. The '
            'always-on check and every `verify` (`dev_lab.dev.ownerdag`, `dev_lab.dev.rustdeps`).'
        ),
        ('tests/test_dev_ownerdag.py', 'tests/test_dev_rustdeps.py', 'tests/test_dev_deptable.py'),
    ),
    (
        'NO-DETOUR',
        (
            # Why: user-approved 2026-11-25 (principle `no-detour`: every hop must add something).
            'In a repo holding a root `dependencies.toml`, a Python module or Rust file whose every public function '
            'only forwards its own parameters unchanged to another owner, sibling or crate (and has no other public '
            'item) is refused unless that edge names what the hop adds: `{ name = "<target>", adds = "translation" | '
            '"policy" | "control" }`. A forward that changes an argument, wraps the result or is decorated adds '
            'something. The always-on check and every `verify` (`dev_lab.dev.passthrough`).'
        ),
        ('tests/test_dev_passthrough.py',),
    ),
    (
        'ONE-FORMAT-PER-NEED',
        (
            # Why: user ruling R3 -- one format per need, so no reader ever parses a second shape of one fact.
            'Each need has ONE format: configuration is TOML (one `--set section.key=value` overrides it), structured '
            'logs are JSONL lines with OpenTelemetry field names, reports are Markdown in memory. The layout '
            'allow-list (DECLARED-LAYOUT) refuses any format a directory does not declare, and refuses a declaration '
            'that admits a second configuration format (`.yaml`, `.yml`, `.ini`, `.cfg`) outside a forge`s own '
            'workflow directories and `output/`; the record writer emits one OTel-named JSONL line (`metrics`); '
            'a Markdown report under `output/` is refused (REPORTS-LIVE-IN-MEMORY).'
        ),
        ('tests/test_dev_layout.py', 'tests/test_dev_metrics.py', 'tests/test_dev_reportplace.py'),
    ),
    (
        'PRIOR-ART-FIRST',
        (
            # Why: two sessions writing one concept twice under one name, neither having searched the tree first.
            'Before new code, search the tree and memory for the capability. A NEW product-source module named like '
            'a tracked one is refused at the write (`priorart`, the `codeplace` hook) until its own text cites each '
            'such module by path or dotted name, saying how it differs; same concept, extend the existing one.'
        ),
        ('tests/test_dev_priorart.py',),
    ),
)
