"""The agent deny registry, PUSH rows -- pure DATA: a force, a remote delete and a skipped hook, by any door.

Split from :mod:`dev_lab.dev._deny_rows` (whose docstring states what every row field means) on 2026-11-13,
when the forwarder-aware :data:`PUSH_VERB` took that module past the size band.
"""

from __future__ import annotations

from dev_lab.dev._deny_forge_rows import VENV_PYTHONS

__all__ = ['PUSH_FORWARDERS', 'PUSH_ROWS', 'PUSH_VERB']

#: A family door that FORWARDS the git argv after it, so the push it runs is judged as if typed: the netverb
#: retry door (``<python> -m dev_lab.dev.netverb [--] git push ...``). 2026-11-13: anchoring the push rows at the
#: invoked program let a force, a no-verify and a remote delete through this door (a consumer's agent-guard rows).
PUSH_FORWARDERS = r'(?:"?\S*python[\w.]*(?:\.exe)?"?\s+-m\s+dev_lab\.dev\.netverb(?:\s+--)?\s+)'
#: ``push`` in VERB position: the invoked command is git (bare, by path, or quoted with spaces; ``-C``/``-c``
#: options allowed), the retry wrapper, or git behind a :data:`PUSH_FORWARDERS` door. Anchored as a ``command``
#: row, so the same words inside another command's arguments -- a ``sed`` or heredoc editing a file that
#: mentions them -- name nothing (2026-11-13).
PUSH_VERB = (
    PUSH_FORWARDERS + r'?(?:(?:"[^"]*[/\\])?"?\S*?\bgit(?:\.exe)?"?(?:\s+-[Cc]\s+\S+)*'
    r'|(?:sh\s+)?\S*with-retry\.sh)\s+push\b'
)

PUSH_ROWS: tuple[dict[str, object], ...] = (
    {
        'id': 'PUSH-FORCE',
        # `+<ref>` is the refspec spelling of the same force (MAIN-SESSION-PUBLISHES opened `push origin *`).
        'pattern': PUSH_VERB + r'[^\n]*\s(?:--force\b|--force-with-lease\b|-f\b|\+\S)',
        'matches': 'command',
        'hazard': 'rewriting a shared ref invalidates every verdict taken '
        'against the old tree; --force-with-lease included.',
        'remedy': 'Land the change FORWARD: git revert <sha> or a new commit on your own lane, then push without '
        'the force flag.',
        'needs': None,
        'refuses': (
            'git push --force origin main',
            './.venv/Scripts/python.exe -m dev_lab.dev.netverb -- git push origin main --force-with-lease',
            'git push origin main --force-with-lease',
            'sh scripts/hooks/with-retry.sh push -f origin HEAD',
            'git -C ../sib push origin +main',
        ),
        'permits': (
            'sh scripts/hooks/with-retry.sh push origin HEAD',
            'git commit -m "force a rebuild"',
            'sh scripts/hooks/with-retry.sh push origin lane/a+b',
        ),
    },
    {
        'id': 'PUSH-REMOTE-DELETE',
        'pattern': PUSH_VERB + r'[^\n]*\s(?:--delete\b|-d\b|--prune\b|--mirror\b|:\S)',
        'matches': 'command',
        'hazard': 'a raw remote delete can lose commits held nowhere else.',
        'remedy': 'a branch: `{python} -m dev_lab.dev.branchprune delete <branch>`; a tag: `{python} -m '
        'dev_lab.dev.branchprune delete-tag <tag> --approved "<the user`s words>"` (LOSSLESS-DELETE).',
        'needs': None,
        'refuses': (
            'git push origin --delete lane/x',
            'git -C ../sib push origin :lane/x',
            'sh scripts/hooks/with-retry.sh push origin -d lane/x',
            'git push --prune origin',
            'git push --mirror origin',
            './.venv/Scripts/python.exe -m dev_lab.dev.netverb -- git push origin --delete lane/x',
            './.venv/Scripts/python.exe -m dev_lab.dev.netverb -- git push origin :lane/x',
            '"C:/Program Files/Git/cmd/git.exe" push origin --delete lane/x',
            'git push origin :refs/tags/v1.0',
            'git push origin --delete refs/tags/v1.0',
        ),
        'permits': (
            'sh scripts/hooks/with-retry.sh push origin HEAD:refs/heads/lane/x',
            'sh scripts/hooks/with-retry.sh push origin main',
            'git branch -d lane/x',
            "python - <<'EOF'  # edits a file whose text says: git push origin --delete lane/x",
            f'{VENV_PYTHONS[0]} -m dev_lab.dev.branchprune delete lane/x',
            f'{VENV_PYTHONS[0]} -m dev_lab.dev.branchprune delete-tag v1.0 --approved "drop it"',
        ),
    },
    {
        'id': 'PUSH-NO-VERIFY',
        'pattern': PUSH_VERB + r'[^\n]*--no-verify\b',
        'matches': 'command',
        'hazard': '`--no-verify` skips the pre-push hooks (admission, the trunk proof), so the push publishes what '
        'no hook checked.',
        'remedy': 'Push without the flag (no hook runs a test; the forge produces the part after the push), '
        'and to check a change first measure what you touched: {remedy}',
        'needs': 'verdict-entry-point',
        'refuses': (
            './.venv/Scripts/python.exe -m dev_lab.dev.netverb -- git push --no-verify',
            'git push --no-verify origin HEAD',
            'sh scripts/hooks/with-retry.sh push origin HEAD --no-verify',
        ),
        'permits': (
            'sh scripts/hooks/with-retry.sh push origin HEAD',
            'git commit -m "x"',
            "sed -i 's/git push --no-verify/git push/' tests/test_x.py",
        ),
    },
)
