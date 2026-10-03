"""The agent deny registry, FORGE-WRITE rows -- pure DATA, split from `_deny_rows` by the size band.

Also the venv-interpreter example subjects every row file shares, derived from the owner `venvpath`.
"""

from __future__ import annotations

from lab_commons.dev.venvpath import VENV_LAYOUTS

__all__ = ['FORGE_WRITE_ROWS', 'VENV_PYTHONS']

#: The venv interpreter, spelled for EVERY platform this kit knows, as example subjects below.
#: DERIVED rather than typed, and the derivation is the correction: this table used to carry the
#: Windows spelling alone, so `BARE-TEST-INVOCATION`'s pattern was only ever PROVED to refuse a
#: venv interpreter on Windows. It does refuse the POSIX one -- `\S*python[\w.]*` reaches
#: `.venv/bin/python` -- but nothing demonstrated it, and an example set that covers one platform
#: is a control with a hole exactly where this family's other half runs.
VENV_PYTHONS: tuple[str, ...] = tuple('/'.join(parts) for parts in VENV_LAYOUTS.values())

#: The hazard and the exit every FORGE-WRITE row shares, spelled once: three rows, one reason.
_FORGE_HAZARD = (
    'a forge write through any client but the family door carries no PROVENANCE. The forge records only '
    'the token`s login, and every agent on a box shares one token, so an issue, comment, close or PR '
    'written this way cannot say which machine or which agent wrote it. The family door opens every body '
    'it writes with `[<machine> · <agent> · <branch>]`, read from HARNESS_MACHINE / HARNESS_AGENT.'
)
_FORGE_REMEDY = (
    f'Write through the family door: {" or ".join(VENV_PYTHONS)} -m lab_commons.dev.forge '
    'issue create|comment|close, pr create '
    '(reads: issue list|view, pr view; token: auth login|status). A write the door has no verb for -- merge, '
    'edit, review -- is the integrator`s to make: report it rather than reaching for another client.'
)

#: The HTTP verbs that WRITE, in every case spelling a shell accepts (curl and PowerShell both do).
_WRITE_METHODS = r'(?:POST|PATCH|PUT|DELETE|Post|Patch|Put|Delete|post|patch|put|delete)'

#: An issue or pull collection on either forge's REST API: Gitea's `/api/v1/repos/<o>/<r>/...` or GitHub's.
_FORGE_COLLECTION = r'(?:/api/v1/repos/|api\.github\.com/repos/)[^\s/\'"]+/[^\s/\'"]+/(?:issues|pulls)\b'

#: The three FORGE-WRITE rows. Reads (`list`, `view`, a GET) stay open throughout: only a WRITE loses
#: its provenance, and a rule that also sealed reading would be routed around within a day.
FORGE_WRITE_ROWS: tuple[dict[str, object], ...] = (
    {
        'id': 'FORGE-WRITE-VIA-CLI',
        'pattern': (
            r'(?:\bgh\s+(?:issue|pr)\s+(?:create|comment|close|reopen|edit|review|merge|delete|lock|unlock'
            r'|transfer|pin|unpin|ready|develop)\b'
            r'|\btea\s+(?:(?:issues?|i|pulls?|pr)\s+(?:create|c|new|edit|e|close|reopen|open|merge|m|approve'
            r'|reject|review|comment|delete)\b|comment\b|c\s))'
        ),
        'matches': 'command',
        'hazard': _FORGE_HAZARD,
        'remedy': _FORGE_REMEDY,
        'needs': None,
        'refuses': (
            'gh issue create --title "x" --body "y"',
            'gh pr comment 9 --body "lgtm"',
            'gh pr merge 9 --squash',
            'gh issue close 7',
            'tea issues create --title x',
            'tea pulls create --head lane --base main',
            'tea comment 7 "hello"',
            'tea pr close 9',
        ),
        'permits': (
            'gh issue list --state open',
            'gh pr view 9',
            'gh issue view 7 --comments',
            'tea issues list',
            'tea pulls 9',
            f'{VENV_PYTHONS[0]} -m lab_commons.dev.forge issue create --title x --body y',
            'git commit -m "gh issue create is refused now"',
        ),
    },
    {
        'id': 'FORGE-WRITE-VIA-GH-API',
        # `gh api` WRITES when it names a mutating method, and ALSO when it carries a field (-f/-F/
        # --field/--raw-field/--input), which flips gh's default from GET to POST. Both are refused
        # against an issue or pull path; an explicit `-X GET` is the read spelling and is opened.
        'pattern': (
            r'\bgh\s+api\b(?=[^\n]*\b(?:issues|pulls)\b)'
            r'(?=[^\n]*(?:\s(?:-X|--method)[\s=]*' + _WRITE_METHODS + r'\b|\s(?:-[fF]|--field|--raw-field|--input)\b))'
        ),
        'matches': 'command',
        'allow': r'\bgh\s+api\b[^\n]*\s(?:-X|--method)[\s=]*(?:GET|get)\b',
        'hazard': _FORGE_HAZARD,
        'remedy': _FORGE_REMEDY,
        'needs': None,
        'refuses': (
            'gh api repos/o/r/issues -f title=x -f body=y',
            'gh api -X PATCH repos/o/r/issues/7 -f state=closed',
            'gh api --method POST repos/o/r/pulls --input pr.json',
            'gh api repos/o/r/issues/7/comments -F body=@note.md',
        ),
        'permits': (
            'gh api repos/o/r/issues',
            'gh api repos/o/r/pulls/9 --jq .title',
            'gh api -X GET repos/o/r/issues -f state=all',
            'gh api -X POST repos/o/r/statuses/abc123 -f state=success',
        ),
    },
    {
        'id': 'FORGE-WRITE-VIA-HTTP',
        # `argument`, because the client varies (curl, Invoke-RestMethod, Invoke-WebRequest, irm, iwr)
        # and so does where in the line the URL sits. A write is a mutating method OR, for curl, a data
        # flag, which turns curl's GET into a POST; it must also name an issue or pull collection.
        'pattern': (
            r'(?=[^\n]*' + _FORGE_COLLECTION + r')'
            r'(?:\bcurl\b(?=[^\n]*(?:\s(?:-X|--request)[\s=]*[\'"]?' + _WRITE_METHODS + r'\b'
            r'|\s(?:-d|--data(?:-raw|-binary|-urlencode)?|--json|-F|--form)\b))'
            r'|\b(?:Invoke-RestMethod|Invoke-WebRequest|irm|iwr)\b'
            r'(?=[^\n]*\s-Method\s+[\'"]?' + _WRITE_METHODS + r'\b))'
        ),
        'matches': 'argument',
        'hazard': _FORGE_HAZARD,
        'remedy': _FORGE_REMEDY,
        'needs': None,
        'refuses': (
            'curl -X POST https://forge.example/api/v1/repos/o/r/issues -d @issue.json',
            'curl -s -H "Authorization: token $T" -d "{}" https://forge.example/api/v1/repos/o/r/issues/7/comments',
            'curl --request PATCH https://api.github.com/repos/o/r/pulls/9 --json "{}"',
            'Invoke-RestMethod -Method Post -Uri https://forge.example/api/v1/repos/o/r/issues -Body $b',
            'irm https://api.github.com/repos/o/r/issues/7 -Method PATCH -Body $b',
        ),
        'permits': (
            'curl -s https://forge.example/api/v1/repos/o/r/issues',
            'curl -s https://api.github.com/repos/o/r/pulls/9',
            'Invoke-RestMethod -Uri https://forge.example/api/v1/repos/o/r/issues -Method Get',
            'curl -X POST https://forge.example/api/v1/repos/o/r/statuses/abc123 -d @status.json',
        ),
    },
)
