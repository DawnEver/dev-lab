"""The rules registry's OUTPUT-TREE rows -- pure DATA, the same row shape as ``_rule_rows.py``.

Every rule about what a checkout's regenerable ``output/`` tree may hold.
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'OUTPUT-HOLDS-NO-CODE',
        (
            # Why: user ruling 2026-11-20, a serious violation -- worktree work was parked under output/.
            'output/ never holds code: no source file, notebook, config, patch, git bundle or checkout is written '
            'under any output/. A worktree with uncommitted or untracked work is REFUSED with its doors (commit and '
            'push it, or discard it explicitly through branchset --discard), never archived; a door that needs a '
            'checkout makes it in the worktree home. The agent guard refuses a Write/Edit or shell write of a '
            'code-suffixed file under output/, and a source scan of src/ refuses any door that writes one.'
        ),
        ('tests/test_dev_outputcode.py', 'tests/test_dev_verifiedby.py'),
    ),
    (
        'NEVER-LOG-SECRETS',
        (
            # Why: moved from a consumer's invariants 2026-11-24 (user ruling): license keys, tokens, fingerprints.
            'A log line, report or console message never carries a credential value -- a token, key, password or '
            'fingerprint is written as its hash or not at all; an output sink interpolating a secret-named value '
            'unwrapped is refused by a source scan.'
        ),
        ('tests/test_dev_secretlog.py',),
    ),
)
