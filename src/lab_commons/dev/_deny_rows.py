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
``hazard``    WHY the shape is refused, as ONE clause. The full reasoning and its incidents live in
              ``docs-src/dev/refusals.md#<id>``, which the rendered refusal points at.
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
              of any repo (``WORKTREE-BASE-IS-EXPLICIT`` and ``FORGE-WRITE-VIA-GH-API`` have one).
              A consumer's remedy may add a second opening; the two are combined by the machinery,
              never merged here.
``refuses``   command SEGMENTS this row must fire on, and ``permits`` near-misses it must not. Both
              are proof carried by the row, so a row cannot arrive without a control -- and a
              ``permits`` entry may not lean on any repo's remedy, because this file has no repo.

WHAT IS NOT HERE, AND WHY -- the judgement this file records. A shape whose HAZARD TEXT WOULD BE
FALSE in another repo stays in the repo that has the hazard, however tempting the generalisation:

* repo-specific dependency mutation rules (``uv sync``, ``pip install``). Each checkout owns its
  ``.venv``; the hazard is bypassing that repo's checked dependency door, not borrowing a shared
  environment. These rows require the adopting repo's concrete mutation door and verdict anchors.
  The family bootstrap door creates a missing owned environment; arbitrary installers stay closed.
* the worktree LEDGER rules (a lane registered in one repo's ledger). Three of the four repos have
  no ledger, so that reason is false there. The LOCATION itself is no longer in this list: the user
  ruled on 2026-10-03 that a checkout outside its repository is forbidden family-wide, for a reason
  every repo shares -- a tree outside the repo is outside every scan, ignore and search the repo runs
  -- so ``WORKTREES-STAY-INSIDE`` below is universal and derives its path from
  :data:`lab_commons.dev.worktreeplace.WORKTREES_REL`.

ROWS ARE NEVER DELETED TO MAKE SOMETHING PASS, and the repair for a row whose pattern misfires is a
sharper pattern with the near-miss added to ``permits`` -- never a narrower claim.
"""

from __future__ import annotations

from lab_commons.dev._deny_forge_rows import FORGE_WRITE_ROWS, VENV_PYTHONS
from lab_commons.dev._deny_grep_row import RECURSIVE_GREP
from lab_commons.dev._deny_interpreter_row import BARE_INTERPRETER
from lab_commons.dev._deny_worktree_row import BASE_IS_EXPLICIT_ALLOW, BASE_IS_EXPLICIT_PATTERN, WORKTREES_STAY_INSIDE
from lab_commons.dev.netverb import NETWORK_VERBS
from lab_commons.dev.worktreeplace import WORKTREES_REL

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
        'hazard': 'a hand-written test line has no verdict: its exit code '
        'cannot tell a covered run from a dead or truncated one.',
        'remedy': 'Re-issue through the entry point that produces a verdict: {remedy}',
        'needs': 'verdict-entry-point',
        'refuses': (
            'pytest tests/',
            'pytest -k thing -x',
            'python -m pytest tests',
            *(f'{python} -m pytest -q' for python in VENV_PYTHONS),
            # `uv run pytest` USED to sit here. It is a SHELL LINE, not a segment, and this row's
            # examples are segments by contract (see tests/test_dev_hooks.py's docstring) -- it only
            # ever passed because the pattern hand-anchored `uv run`, which is the smell removed
            # above. It moved, WITH `uvx pytest -q` and the wrapped-heredoc shapes, to
            # test_dev_agenthooks.py, where the real engine judges it. That is a stronger control,
            # not a dropped one: it is now proved through the file the consuming repo runs.
        ),
        'permits': (
            'grep -n "pytest" src/a.py',
            f'{VENV_PYTHONS[0]} -m lab_commons.dev.verify',
            'git log --oneline -- tests/test_dev_verify.py',
        ),
    },
    *FORGE_WRITE_ROWS,
    {
        'id': 'GIT-COMMIT-AMEND',
        # Spelled as PUSH-FORCE is, and deliberately: `--amend` is an OPTION, so `matches: argument`
        # reaches `git -C <tree> commit --amend` and `git commit -a --amend` alike, which a command
        # anchor on `git commit` would not. A pattern catching every `git commit` would be routed
        # around within a day, so the literal flag is the whole match.
        'pattern': r'\bcommit\b[^\n]*\s--amend\b',
        'matches': 'argument',
        'hazard': '`--amend` rewrites HEAD, and on a shared lane HEAD may be another agent`s commit.',
        'remedy': 'Land the correction FORWARD: read HEAD with git log -1 '
        '--format="%h %an %s", then commit the fix on top.',
        # `needs` is None after checking what a repo could possibly supply, and the answer is nothing:
        # `git commit` and `git log` exist in every checkout, and a follow-up convention is prose
        # rather than a file. Giving this row a `needs` would DROP it from every repo that has no
        # such artefact -- which is all four -- so a universal hazard would ship to nobody.
        'needs': None,
        # NO `allow`, and that is a decision rather than an omission. The opening would have to say
        # "this branch is reachable by nobody else", and the engine reads TEXT: whether HEAD is
        # shared is a property of the repo at that instant and is nowhere on the command line. So it
        # ships CLOSED -- a rule that fires on a real hazard and occasionally inconveniences a solo
        # lane is the better error. A rebase that rewrites history is a DIFFERENT shape and is not
        # registered here; this row reads the `--amend` spelling and claims nothing beyond it.
        'refuses': (
            'git commit --amend',
            'git commit --amend --no-edit',
            'git commit -a --amend -m "fix the digits"',
            'git -C .claude/worktrees/lane commit --amend',
        ),
        'permits': (
            'git commit -F - -- src/thing.py',
            'git commit -m "amend the ledger prose"',
            'git log -1 --format=%h',
        ),
    },
    {
        'id': 'GIT-NETWORK-VERB',
        'pattern': rf'\bgit\s+(?:{"|".join(NETWORK_VERBS)})\b',
        'matches': 'command',
        'hazard': 'one transient forge failure on a network verb reads as '
        '"blocked"; the wrapper retries, then diagnoses.',
        'remedy': 'Re-issue through the retry wrapper: {remedy}',
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
        'hazard': '`refs/stash` is repo-wide, so a stash is popped by whoever pops next -- possibly another agent.',
        'remedy': (
            'Commit it on your own lane branch, or take a throwaway checkout: '
            f'git worktree add --detach {WORKTREES_REL}/<name> <sha>'
        ),
        'needs': None,
        'refuses': ('git stash', 'git stash push -u', 'git stash pop'),
        'permits': ('git commit -m "wip: scratch"', 'git diff --stat'),
    },
    {
        'id': 'PUSH-FORCE',
        'pattern': r'\bpush\b[^\n]*\s(?:--force\b|--force-with-lease\b|-f\b)',
        'matches': 'argument',
        'hazard': 'rewriting a shared ref invalidates every verdict taken '
        'against the old tree; --force-with-lease included.',
        'remedy': 'Land the change FORWARD as a new commit on your own lane, then push without the force flag.',
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
        'hazard': '`--no-verify` skips the pre-push hook where the verdict is taken, so the push vouches for nothing.',
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
        'hazard': 'a raw kill stops only what you named; the orphaned subtree keeps holding the box.',
        'remedy': 'Kill the process TREE by its root pid, children first: {remedy}',
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
        'pattern': BASE_IS_EXPLICIT_PATTERN,
        'matches': 'command',
        'allow': BASE_IS_EXPLICIT_ALLOW,
        'hazard': '`git worktree add` with no commit-ish takes the current HEAD, '
        'which on a shared checkout is rarely the tree you meant.',
        'remedy': f'Name the commit the tree starts from: git worktree add --detach {WORKTREES_REL}/<name> <sha>',
        'needs': None,
        'refuses': (
            'git worktree add ../probe',
            'git worktree add --detach /tmp/probe',
            'git worktree add -b fix/x .claude/worktrees/x',
            'git worktree add .claude/worktrees/x -b fix/x',
            'git -C C:/work/lab-commons worktree add --detach C:/work/lab-commons/.claude/worktrees/x',
        ),
        'permits': (
            'git worktree add --detach .claude/worktrees/probe 4a4e8b13f',
            'git worktree add .claude/worktrees/probe origin/main',
            # MEASURED 2026-10-04: both of these were refused as "no commit-ish" -- `-b <branch>` in
            # either position, and a command that did not END at the commit-ish.
            'git worktree add -b fix/x .claude/worktrees/x origin/main',
            'git worktree add .claude/worktrees/x -b fix/x 4a4e8b13f',
            'git worktree add -b fix/x .claude/worktrees/x main',
            'git worktree add --detach .claude/worktrees/p 4a4e8b13f && git -C .claude/worktrees/p switch -c fix/p',
            'git worktree list',
            'git worktree remove .claude/worktrees/probe',
        ),
    },
    WORKTREES_STAY_INSIDE,
    BARE_INTERPRETER,
    RECURSIVE_GREP,
)
