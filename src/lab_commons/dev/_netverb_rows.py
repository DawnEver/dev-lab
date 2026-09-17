"""The classification table: which failures of a network verb can clear on a retry, and which cannot.

DATA, AND NOTHING ELSE. The machinery that reads it is :mod:`lab_commons.dev.netverb`; the seam is
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
stderr alone was blind to exactly the line it had been taught to recognise.
"""

from __future__ import annotations

from typing import Final

#: ``(diagnosis, retryable, patterns)`` -- the diagnosis spelling matches
#: :class:`lab_commons.dev.netverb.Diagnosis`'s values, which is the only coupling between the two
#: halves. Order matters: the FIRST row whose pattern is present wins, so the permanent rows are
#: written above the transient ones -- a push that is rejected also prints "failed to push some
#: refs", and reading that first would turn a refusal into three refusals.
ROWS: Final[tuple[tuple[str, bool, tuple[str, ...]], ...]] = (
    (
        # A PRE-PUSH HOOK'S REFUSAL. Measured 2026-09-17 in this session: a repo's pre-push hook
        # refused a push and printed the identical refusal on all three attempts -- the same tree
        # re-judged by the same hook returns the same answer, and each re-judgement paid the hook's
        # full cost. The hook is LOCAL, so no backoff and no forge can change its mind.
        'hook-refused',
        False,
        ('pre-push hook', 'pre-receive hook declined', 'hook declined', 'hooks/pre-push'),
    ),
    (
        # THE REF ITSELF IS STALE OR PROTECTED -- git's own vocabulary for "your input is wrong".
        # Inherited from motronics-studio's `with-retry.sh`, whose own comment records that its
        # `[rejected]` row could not fire while the classifier read only the first line, so a
        # rejected ref burned all three attempts the check existed to skip.
        'ref-rejected',
        False,
        ('[rejected]', 'non-fast-forward', 'fetch first', 'updates were rejected'),
    ),
    (
        # THE FORGE REFUSED THE IDENTITY IT ALREADY RESOLVED. A 403 is an answered request: the
        # server read the credential, matched it against a protected branch or a missing scope, and
        # said no. Repeating it three seconds later asks the same question of the same policy.
        'forge-refused',
        False,
        ('403 forbidden', 'error: 403', 'protected branch', 'you are not allowed to push', 'permission denied to'),
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
        ),
    ),
    (
        # THE MEASURED TRANSIENT, and the incident the whole rule was built on. 2026-08-21: a single
        # `git fetch` failed AUTH and succeeded on the retry, and was reported "blocked". 2026-09-17,
        # this session: a push to a gitea forge failed auth and succeeded on a later attempt while a
        # `fetch` cleared an identical HTTP 401 on its second attempt. A 401 is NOT a 403 -- the
        # credential helper, the token cache and the proxy in front of it are all mid-flight state,
        # and mid-flight state is exactly what an attempt later clears.
        'transient',
        True,
        (
            'authentication failed',
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
