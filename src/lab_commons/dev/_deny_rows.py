"""The agent deny registry, FIRST half -- pure DATA, one row per UNIVERSAL denied command shape.

A row is a mapping read by :mod:`lab_commons.dev.hooks`, which is the machinery. The seam is the one
`tests/test_arch_registry_data_is_separate.py` already argues for the rules registry, for the same
reason: a table edited through the module that checks it drifts away from what it describes, because
the same edit that adds a row can relax the check that would have refused it.

WHAT A ROW HOLDS, and every field is load-bearing:

``id``        the stable handle a consuming repo cites when it supplies a remedy.
``pattern``   the regex, in the subset JavaScript and Python spell identically (the engine that
              runs it is JS; the tests that prove it compiles are Python).
``matches``   ``'command'`` -- the pattern NAMES the command, so the engine anchors it at the start
              of a shell segment -- or ``'argument'``: the pattern names an OPTION, whose command
              varies, so it is searched anywhere in the segment. This mirrors the engine's own
              ``matches`` field exactly and is a property of the ROW, not of the parser.
``hazard``    WHY the shape is refused, in the words the shared source owns.
``remedy``    WHAT TO DO INSTEAD. **Non-optional, and this is the whole design.** A rule that seals
              a road with no exit gets routed around rather than obeyed -- measured in this family
              over several months on a `uv` rule that named no alternative. Where the exit is a file
              in the consuming repo, the text carries the ``{remedy}`` placeholder and the row also
              names ``needs``; the rule is then NOT SHIPPED to a repo that supplies no such file.
``needs``     the KIND of repo artefact the remedy requires, or ``None`` when the remedy is a plain
              command every checkout already has (git's own verbs). This is the ID-plus-mechanism
              split `lab_commons.dev.rules` already uses: the statement is universal, the thing that
              resolves it lives in one tree.
``allow``     a regex that opens the rule for a spelling that is sanctioned EVERYWHERE, independent
              of any repo (only ``WORKTREE-BASE-IS-EXPLICIT`` has one). A consumer's remedy may add
              a second opening; the two are combined by the machinery, never merged here.
``refuses``   command SEGMENTS this row must fire on, and ``permits`` near-misses it must not. Both
              are proof carried by the row, so a row cannot arrive without a control -- and a
              ``permits`` entry may not lean on any repo's remedy, because this file has no repo.

WHAT IS NOT HERE, AND WHY -- the judgement this file records. A shape whose HAZARD TEXT WOULD BE
FALSE in another repo stays in the repo that has the hazard, however tempting the generalisation:

* the shared-venv rules (``uv run``/``uv sync``, ``pip install``). The hazard presupposes ONE venv
  that every worktree on the box borrows, and a dependency-sync tool to route to. A repo with its
  own ``.venv`` has neither, so the rule would refuse a safe command and name an exit that does not
  exist -- the exact failure this module's remedy field is built to prevent.
* the worktree LOCATION rules (add/move/nesting). Their reason is "a tree planted elsewhere is
  invisible to the lane ledger". Three of the four repos have no ledger, so the reason is false
  there, and a false reason is a declaration that lies. Only the BASE rule below generalises: that
  a bare ``git worktree add <path>`` silently takes the current HEAD is a fact about git.

ROWS ARE NEVER DELETED TO MAKE SOMETHING PASS, and the repair for a row whose pattern misfires is a
sharper pattern with the near-miss added to ``permits`` -- never a narrower claim.
"""

from __future__ import annotations

DENY_ROWS: tuple[dict[str, object], ...] = (
    {
        'id': 'BARE-TEST-INVOCATION',
        # `uv\s+run\s+pytest` used to stand here as a third alternative. It is GONE because the
        # engine now yields `uv run <command>` as a command POSITION, so `pytest\b` reaches it the
        # same way it already reached `timeout 900 pytest` -- and a rule carrying its own wrapper
        # list is answering a question the engine has already answered, which is how the two
        # hand-anchored rules drifted apart in the first place. `uv run pytest` stays in `refuses`.
        'pattern': r'(?:\S*python[\w.]*\s+-m\s+pytest\b|pytest\b)',
        'matches': 'command',
        'hazard': (
            'a hand-written test line has no VERDICT. An exit code cannot say whether the run COVERED what '
            'it selected, so a dead worker, a truncated run or a collection error that reported nothing all '
            'read as green -- and the reader has merged "the tests passed" with "nobody knows".'
        ),
        'remedy': 'Re-issue through the entry point that produces a verdict: {remedy}',
        'needs': 'verdict-entry-point',
        'refuses': (
            'pytest tests/',
            'pytest -k thing -x',
            'python -m pytest tests',
            '.venv/Scripts/python.exe -m pytest -q',
            # `uv run pytest` USED to sit here. It is a SHELL LINE, not a segment, and this row's
            # examples are segments by contract (see tests/test_dev_hooks.py's docstring) -- it only
            # ever passed because the pattern hand-anchored `uv run`, which is the smell removed
            # above. It moved, WITH `uvx pytest -q` and the wrapped-heredoc shapes, to
            # test_dev_agenthooks.py, where the real engine judges it. That is a stronger control,
            # not a dropped one: it is now proved through the file the consuming repo runs.
        ),
        'permits': (
            'grep -rn "pytest" src',
            'python -m lab_commons.dev.verify',
            'git log --oneline -- tests/test_dev_verify.py',
        ),
    },
    {
        'id': 'GIT-NETWORK-VERB',
        'pattern': r'\bgit\s+(?:push|fetch|pull|clone|ls-remote)\b',
        'matches': 'command',
        'hazard': (
            'the forge is a REMOTE service that nobody in this family restarts, and a single transient '
            'auth/DNS/connection failure on any of these verbs reads as "blocked" -- which is the report the '
            'retry wrapper exists to prevent. Measured 2026-08-21 on a `git fetch`: it failed auth once and '
            'succeeded on the retry, and was reported blocked in between.'
        ),
        'remedy': 'Re-issue through the retry wrapper, which retries 3x and then REPORTS with a diagnosis: {remedy}',
        'needs': 'retry-wrapper',
        'refuses': (
            'git push origin HEAD',
            'git fetch --all',
            'git pull --rebase',
            'git ls-remote origin',
            'git clone https://example.invalid/x.git',
        ),
        'permits': (
            'git status',
            'git log --oneline -5',
            'git commit -m "mention a push in prose"',
        ),
    },
    {
        'id': 'GIT-STASH',
        'pattern': r'\bgit\s+stash(?:\s|$)',
        'matches': 'command',
        'hazard': (
            '`refs/stash` is REPO-WIDE. It is one ref per repository, not per worktree, so a stash taken in '
            'one checkout is popped by whoever pops next -- in a family whose premise is a shared, possibly '
            'concurrent checkout, that is another agent losing work it never knew existed.'
        ),
        'remedy': (
            'Keep the work where its owner can see it. Either commit it on your own lane branch (a scratch '
            'commit is cheap and is named), or take a throwaway checkout: git worktree add --detach <path> <sha>'
        ),
        'needs': None,
        'refuses': ('git stash', 'git stash push -u', 'git stash pop'),
        'permits': ('git commit -m "wip: scratch"', 'git diff --stat'),
    },
    {
        'id': 'PUSH-FORCE',
        'pattern': r'\bpush\b[^\n]*\s(?:--force\b|--force-with-lease\b|-f\b)',
        'matches': 'argument',
        'hazard': (
            'every branch here is read by someone else, and rewriting a ref silently invalidates any verdict '
            'already taken against the old tree -- the verdict still cites a `tree=` address, and the tree it '
            'names no longer exists. `--force-with-lease` is refused with the rest: it protects against a ref '
            'that MOVED, not against a reader who already judged the ref as it was.'
        ),
        'remedy': (
            'Do not rewrite a shared ref: land the change FORWARD as a new commit on your own lane, then push '
            'without the force flag. If the history really must change, it changes on a branch nobody has '
            'judged yet.'
        ),
        'needs': None,
        'refuses': (
            'git push --force origin main',
            'git push origin main --force-with-lease',
            'sh scripts/hooks/with-retry.sh push -f origin HEAD',
        ),
        'permits': (
            'sh scripts/hooks/with-retry.sh push origin HEAD',
            'git commit -m "force a rebuild"',
        ),
    },
    {
        'id': 'PUSH-NO-VERIFY',
        'pattern': r'\bpush\b[^\n]*--no-verify\b',
        'matches': 'argument',
        'hazard': (
            '`--no-verify` skips the pre-push hook, and the hook is where the verdict is taken. A push that '
            'skipped it vouches for nothing, while looking exactly like one that did not -- the commit lands '
            'with no evidence attached and nobody downstream can tell which kind it was.'
        ),
        'remedy': 'Take the verdict first, and push once it is green: {remedy}',
        'needs': 'verdict-entry-point',
        'refuses': ('git push --no-verify origin HEAD', 'sh scripts/hooks/with-retry.sh push origin HEAD --no-verify'),
        'permits': (
            'sh scripts/hooks/with-retry.sh push origin HEAD',
            'git commit --no-verify -m "x"',
        ),
    },
    {
        'id': 'RAW-PROCESS-KILL',
        'pattern': (
            r'(?:\btaskkill\b[^\n]{0,200}?[/-]{1,2}(?:PID|IM|T|F)\b'
            r'|\bStop-Process\b[^\n]{0,200}?-(?:Id|Name|InputObject)\b'
            r'|\bkill\s+(?:-(?:9|TERM|KILL)\s+)?\d+)'
        ),
        'matches': 'argument',
        'hazard': (
            'a raw kill stops what you NAMED, and a test worker names nothing on its own command line -- so '
            'the subtree that actually holds the box survives its parent. Measured twice in this family '
            '(2026-07-29, 2026-09-13): stopping a wrapper orphaned its children, and the orphan went on '
            'holding the CPU lock for a run whose own process was already dead.'
        ),
        'remedy': 'Kill the process TREE by its ROOT pid, children-first, and verify none remain: {remedy}',
        'needs': 'process-tree-killer',
        'refuses': (
            'taskkill /PID 1234 /T /F',
            'taskkill /IM python.exe /F',
            'Stop-Process -Id 1234',
            'Stop-Process -Name python',
            'kill -9 1234',
        ),
        'permits': (
            'Get-Process -Id 1234',
            'tasklist /FI "IMAGENAME eq python.exe"',
            'git commit -m "reap the orphan shells"',
        ),
    },
    {
        'id': 'WORKTREE-BASE-IS-EXPLICIT',
        'pattern': r'\bgit\s+worktree\s+add\b',
        'matches': 'command',
        'allow': r'\bgit\s+worktree\s+add\b[^\n]*\s(?:[0-9a-f]{7,40}|origin/\S+|refs/\S+|HEAD(?:[~^@]\S*)?)\s*$',
        'hazard': (
            '`git worktree add <path>` with no commit-ish silently takes the CURRENT HEAD, which on a shared '
            'checkout is routinely not the tree you meant. MEASURED 2026-09-01: two agents were handed trees '
            'based on the wrong branch and each reasoned about a codebase nobody runs -- one of them for 130k '
            'tokens -- before noticing. A bare `HEAD` is accepted because it is a choice rather than an '
            'omission, but it is the weakest one available: HEAD moves, so two trees cut from it minutes '
            'apart can differ. Prefer the sha.'
        ),
        'remedy': 'Name the commit the tree starts from: git worktree add --detach <path> <sha>',
        'needs': None,
        'refuses': ('git worktree add ../probe', 'git worktree add --detach /tmp/probe'),
        'permits': (
            'git worktree add --detach .claude/worktrees/probe 4a4e8b13f',
            'git worktree add .claude/worktrees/probe origin/main',
            'git worktree list',
            'git worktree remove .claude/worktrees/probe',
        ),
    },
)
