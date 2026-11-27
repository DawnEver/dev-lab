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
    (
        'SHARE-FOLDER-HOLDS-DATA',
        (
            # Why: moved from a consumer's invariants 2026-11-26 (v1 FAM-09, ruling D158): a figure rendered into a
            # synced share folder races the live human session on the other end and cannot be told from data.
            'A synced share folder holds DATA (csv/json/xlsx/npz) and, for every figure, the production command '
            'that regenerates it -- never the rendered png/jpg/svg, which regenerates under output/. A source '
            'image nothing can regenerate is INPUT and stays, declared by name. Each folder declares both in its '
            '`share.toml`; the consumer assertion over its declared folders refuses a rendered image or a '
            'command-less figure.'
        ),
        ('tests/test_dev_sharefolder.py',),
    ),
)
