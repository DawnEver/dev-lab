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
        'ENV-IS-READ-ONCE',
        (
            # Why: user-approved family policy 2026-11-25 (v1-migration D67/D68) -- env reads changed results unseen.
            'A repo reads the process environment only in the entry module(s) it declares in `[tool.dev_lab.env] '
            'entry = [...]`: a value that changes a result or behavior is configuration, a fact only the '
            'environment offers is read there once and passed on as a typed record, and a test switch is a pytest '
            'option or a resource need -- a read deciding whether a test runs is refused in test code in every mode, '
            'and an entry never launders one. Existing reads are on record in `pending`, which only shrinks (a stale '
            'path reds; the `env-pending-shrinks` pre-push row refuses an addition since the merge-base); '
            '`strict = true` judges every test read too. An AST read of Python `os.environ`/`getenv`/`putenv` and '
            'a scan of Rust `env::var` (`dev_lab.dev.envreads`), every family checkout`s always-on check.'
        ),
        ('tests/test_dev_envreads.py',),
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
