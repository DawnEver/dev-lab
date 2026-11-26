"""The classification table: which failures of a network verb can clear on a retry, and which cannot.

DATA, AND NOTHING ELSE. The machinery that reads it is :mod:`dev_lab.dev.netverb`; the seam is
the one `_rule_rows.py`/`rules.py` already draws, and for the same measured reason -- a table edited
through the module that checks it drifts, because the edit that adds a row can relax the check that
would have refused it and the diff looks like one change.

WHY A TABLE AT ALL, rather than "retry three times and see". Retrying a REFUSAL is the cost the rule
is named for: an hour of CPU spent to be told the identical thing. Retrying a TRANSIENT is the whole
point of the wrapper. Only evidence separates them, so every row below carries the incident it was
read off, and a shape nobody has measured gets no row -- it falls through to the default, which is
stated in the machinery.

THE PATTERNS ARE MATCHED CASE-INSENSITIVELY AS SUBSTRINGS of the attempt's WHOLE combined output
(stdout and stderr together). Both halves are needed and that is measured, not defensive: a pre-push
hook writes its refusal to STDOUT while git's own failure goes to stderr, so a classifier reading
stderr alone was blind to exactly the line it had been taught to recognize.
"""

from __future__ import annotations

from typing import Final

#: ``(diagnosis, retryable, patterns)`` -- the diagnosis spelling matches
#: :class:`dev_lab.dev.netverb.Diagnosis`'s values, which is the only coupling between the two
#: halves. Order matters: the FIRST row whose pattern is present wins, so the permanent rows are
#: written above the transient ones -- a push that is rejected also prints "failed to push some
#: refs", and reading that first would turn a refusal into three refusals.
ROWS: Final[tuple[tuple[str, bool, tuple[str, ...]], ...]] = (
    (
        # AN INSTALLER COULD NOT REPLACE A FILE A RUNNING PROCESS HOLDS. Measured 2026-11-20: `winget install
        # astral-sh.uv --version X --force` failed 3/3 as unclassified with `remove: Access is denied` on
        # `WinGet/Packages/astral-sh.uv_.../uv.exe` -- running uv processes held it. Windows refuses to delete
        # a running exe but allows renaming it, so the cure is moving it aside, never waiting and retrying.
        'file-held',
        False,
        ('remove: access is denied',),
    ),
    (
        # uv REFUSED TO UPDATE ITSELF: it was not installed by its standalone scripts. Measured 2026-11-21: `uv.EXE
        # self update 0.13.9` on a Python install's `Scripts/uv.EXE` gave up 3/3 as unclassified; uv's answer is
        # about how it was installed, which no attempt changes.
        'self-update-refused',
        False,
        ('self-update is only available for uv binaries installed via the standalone installation scripts',),
    ),
    (
        # GIT'S OWN PROTOCOL POLICY REFUSED A LOCAL TRANSPORT. Measured 2026-10-19 downstream: `dep
        # --bootstrap <worktree>` ran `git submodule update --init --recursive`, whose submodule URL is a
        # LOCAL path (the main checkout's `.git/modules/...`), and git refused it as `transport 'file' not
        # allowed` (protocol.file.allow defaults to `user` since 2.38.1). Retried three times as
        # unclassified; the answer is a config value, so no attempt can change it.
        'transport-refused',
        False,
        ("transport 'file' not allowed",),
    ),
    (
        # NO INTERPRETER FITS THE PROJECT'S requires-python. Measured 2026-11-26: `dep --bootstrap` with a misfit
        # Python gave up 3/3 as unclassified ("looks transient") and never named the interpreter to use; uv's
        # answer is about the host's interpreters, which no attempt changes. Above the hook row: a hook may print it.
        'python-unfit',
        False,
        ('no interpreter found for python', "incompatible with the project's python requirement"),
    ),
    (
        # THE PROJECT HAS NO LOCK. Measured 2026-11-26: `dep --bootstrap` of a config-only repo (no uv.lock) was
        # retried 3/3 as "transient"; a frozen sync of a lock that does not exist fails the same way every time.
        'lock-absent',
        False,
        ('unable to find lockfile',),
    ),
    (
        # A GIT HOOK THAT CANNOT START. Measured 2026-11-26: a push failed on a retired pre-commit framework shim
        # (`No module named pre_commit`) and netverb called it transient 3/3; the hook file names a module its
        # interpreter lacks, so only reinstalling the hooks changes the answer.
        'hook-unrunnable',
        False,
        ('no module named pre_commit', "no module named 'pre_commit'"),
    ),
    (
        # A PRE-PUSH HOOK'S REFUSAL. Measured 2026-09-17 in this session: a repo's pre-push hook
        # refused a push and printed the identical refusal on all three attempts -- the same tree
        # re-judged by the same hook returns the same answer, and each re-judgment paid the hook's
        # full cost. The hook is LOCAL, so no backoff and no forge can change its mind.
        'hook-refused',
        False,
        # `[githooks] pre-push: N hook(s) failed` is this family's own runner (2026-10-13: a
        # session-branch refusal read as unclassified and was retried three times); a hook
        # run bare still prints its own indented `  REFUSED: <RULE-ID>` line.
        (
            'pre-push hook',
            'pre-receive hook declined',
            'hook declined',
            'hooks/pre-push',
            '[githooks] pre-push:',
            '  refused: ',
        ),
    ),
    (
        # THE REF ITSELF IS STALE OR PROTECTED -- git's own vocabulary for "your input is wrong".
        # Inherited from consumer-a's `with-retry.sh`, whose own comment records that its
        # `[rejected]` row could not fire while the classifier read only the first line, so a
        # rejected ref burned all three attempts the check existed to skip.
        'ref-rejected',
        False,
        ('[rejected]', 'non-fast-forward', 'fetch first', 'updates were rejected'),
    ),
    (
        # THE COMMAND WAS SPELLED WRONG. Measured 2026-11-26: deterministic refusals were
        # retried 3x as "transient"; an argument parser answers the same argv identically every time.
        'usage-refused',
        False,
        (
            'error: unexpected argument',
            'error: unrecognized arguments',
            'error: unrecognized subcommand',
            'is not a git command',
            'error: unknown option',
            'error: unknown switch',
        ),
    ),
    (
        # THE RESOLVER PROVED NO SOLUTION, or no artifact fits this platform. Measured 2026-11-26 (v1 #1): a missing-
        # wheel resolution was retried 3x; the index answered, and it answers the same until the requirement moves.
        'resolution-failed',
        False,
        (
            'no solution found when resolving',
            "doesn't have a source distribution or wheel",
            'no matching distribution found',
        ),
    ),
    (
        # A BUILD STEP FAILED -- a compiler error, a build backend that exited non-zero. Measured 2026-11-26 (v1 #1):
        # a C compile error was retried 3x as "transient"; the same sources compile the same way every attempt.
        'build-failed',
        False,
        ('failed to build', 'subprocess-exited-with-error', 'fatal error c', 'could not compile `'),
    ),
    (
        # THE NAMED REF DOES NOT EXIST on the remote or locally: no attempt creates it.
        'ref-absent',
        False,
        ("couldn't find remote ref", 'error: src refspec'),
    ),
    (
        # THE SERVER REFUSED THE KEY: ssh authenticated nothing, and no wait installs one.
        'permission-refused',
        False,
        ('permission denied (publickey',),
    ),
    (
        # A RATE LIMIT, ABOVE THE 403 ROW BECAUSE IT IS ANSWERED AS A 403. Measured 2026-11-05: GitHub's
        # `403 API rate limit exceeded` read as a refused credential and was never retried. The limit
        # resets on its own clock, so an attempt after the wait clears it; the forge door reads that
        # wait off `Retry-After` / `X-RateLimit-Reset` (`forgefailure.pause`).
        'rate-limited',
        True,
        ('rate limit exceeded', 'secondary rate limit', 'too many requests', 'error: 429', 'http 429'),
    ),
    (
        # THE FORGE REFUSED THE IDENTITY IT ALREADY RESOLVED. A 403 is an answered request: the
        # server read the credential, matched it against a protected branch or a missing scope, and
        # said no. Repeating it three seconds later asks the same question of the same policy.
        # The forge API's own 401/403 is NOT read off this row: `forgework` measures it against
        # `GET /user` first (2026-10-18, a single API 401 whose credential authenticated minutes later).
        'forge-refused',
        False,
        (
            '403 forbidden',
            'error: 403',
            'protected branch',
            'you are not allowed to push',
            'permission denied to',
            # `gh`'s spelling of a token the API does not accept (`HTTP 401: Bad credentials`): a stored
            # token, never git's expiring OAuth one, so no refresh between attempts can change it.
            'bad credentials',
        ),
    ),
    (
        # THE REMOTE DOES NOT EXIST. No backoff creates a repository.
        'remote-absent',
        False,
        (
            'repository not found',
            'does not appear to be a git repository',
            'remote: repository does not exist',
            'could not read from remote repository',
            # git's own spelling for a path or URL with no repository behind it: `repository '<x>'
            # does not exist` (git 2.42, Linux, measured on Ada 2026-10-19) or `... not found`.
            "fatal: repository '",
            # `gh`'s spelling of a repository (or a path under it) the API does not hold.
            'http 404: not found',
        ),
    ),
    (
        # THE MEASURED TRANSIENT, and the incident the whole rule was built on. 2026-08-21: a single
        # `git fetch` failed AUTH and succeeded on the retry, and was reported "blocked". 2026-09-17,
        # this session: a push to a gitea forge failed auth and succeeded on a later attempt while a
        # `fetch` cleared an identical HTTP 401 on its second attempt. A 401 is NOT a 403 -- the
        # attempt-1 auth failure is an EXPIRED OAuth access token (Git Credential Manager, username
        # OAUTH_USER): git rejects it on the 401 and the retry's fill refreshes it (measured 2026-10-21;
        # see the credentials section of the forge dev doc). An attempt later clears it: git refreshes in between.
        'transient',
        True,
        (
            'authentication failed',
            # uv's spelling, measured 2026-10-19 (a downstream `dep --sync`): one `uv sync` of a git
            # dependency failed with it, and the next run passed on its first attempt.
            'failed to authenticate',
            'error: 401',
            '401 unauthorized',
            'could not read username',
            'could not read password',
            'terminal prompts disabled',
            'could not resolve host',
            'could not resolve proxy',
            'connection reset',
            'connection timed out',
            'connection refused',
            'operation timed out',
            'unable to access',
            'the remote end hung up unexpectedly',
            'rpc failed',
            'early eof',
            'ssl_error',
            'gnutls_handshake',
            'internal server error',
            'bad gateway',
            'service unavailable',
            'gateway timeout',
        ),
    ),
)


#: What to DO about a permanent diagnosis whose answer is not in the command's own output.
REMEDIES: Final[dict[str, str]] = {
    'transport-refused': (
        'a LOCAL-path remote (a submodule cloned from a checkout .git/modules directory) needs '
        '`git -c protocol.file.allow=always ...` on that one command -- '
        'dev_lab.dev._dep_network.init_submodules passes it'
    ),
    'file-held': (
        'a running process holds a file the installer must replace -- move the held file aside (renaming a '
        'running exe is allowed) and install again; dev_lab.dev.uvfollow does this for uv'
    ),
    'self-update-refused': (
        'this uv was installed by pip or a package manager, so move it through that installer (`<its python> -m '
        'pip install uv==<version>`); a lock never needs it moved -- dev_lab.dev.uvrelease installs the pinned '
        'release beside it as the lock writer'
    ),
    'python-unfit': (
        'no interpreter this command found fits the project requires-python -- name one that does with '
        '`uv python find "<requires-python>"` (`uv python install "<requires-python>"` fetches one), then rerun '
        'with it: `<that python> -m dev_lab.dev.dep --bootstrap <tree>`'
    ),
    'lock-absent': (
        'the project has no uv.lock, so there is nothing to build -- a repo with no Python environment (config '
        'only) needs no bootstrap; a Python project locks first (`uv lock`) and commits uv.lock'
    ),
    'hook-unrunnable': (
        'a git hook could not start: it imports a module its interpreter lacks (a retired pre-commit framework '
        'shim) -- reinstall the family hooks: `<venv python> -m dev_lab.dev.hook_install --install`, then retry'
    ),
    'usage-refused': 'the command line itself was refused -- fix the arguments its usage line names',
    'resolution-failed': (
        'the resolver proved the requirements unsatisfiable on this platform -- move the requirement or the pin it '
        'names (`<venv python> -m dev_lab.dev.dep --lock-upgrade <tree>`), never retry it'
    ),
    'build-failed': 'a build step failed the same way it will fail again -- fix the error the build output names',
    'ref-absent': 'the ref named does not exist there -- check the spelling with `git ls-remote <remote>`',
    'permission-refused': 'the server refused this credential -- fix the key or the grant it names, then retry once',
    # A forge refusal's answer is a JSON body no reader sees unless it is quoted: ForgeCallFailed appends it.
    'forge-refused': 'the forge answered and refused this call -- fix what its answer names',
}
