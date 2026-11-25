"""The agent deny registry, OUTPUT-HOLDS-NO-CODE row -- pure DATA.

USER RULING 2026-11-20 (a serious violation): ``output/`` must NEVER hold code -- no source file, no git
bundle, no patch, no parked worktree. ``output/`` holds what a program regenerates; work is committed and
pushed, or explicitly discarded through its door. This row is the SHELL half: a redirection, ``tee``,
``Out-File``, copy, move or ``git bundle create`` that lands a code-suffixed file under any ``output/``. The
Write/Edit half is :func:`dev_lab.dev.outputcode.refuse_code_in_output`, called by the ``codeplace`` write
hook with this row's hazard and remedy; the source-scan half is
:func:`dev_lab.dev.outputcode.code_doors_into_output`.
"""

from __future__ import annotations

__all__ = ['CODE_SUFFIXES', 'OUTPUT_HOLDS_NO_CODE']

#: The ONE list of what counts as code, a bundle or a patch: never written under ``output/``.
CODE_SUFFIXES: tuple[str, ...] = (
    '.py', '.pyi', '.pyx', '.ipynb', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.rs', '.c', '.h', '.cpp',
    '.hpp', '.go', '.java', '.m', '.jl', '.sh', '.bash', '.ps1', '.psm1', '.bat', '.cmd', '.toml', '.patch',
    '.diff', '.bundle', '.whl',
)  # fmt: skip

_SUFFIX = '(?:' + '|'.join(s[1:] for s in CODE_SUFFIXES) + ')'
_VERB = (
    r'(?:>>?|\btee\b(?:\s+-a)?|\bOut-File\b(?:\s+-FilePath)?|\b(?:Set|Add)-Content\b(?:\s+-Path)?'
    r'|\b(?:cp|mv|Copy-Item|Move-Item)\b[^;&|\n]*?\s|\bgit\s+bundle\s+create\b)'
)

OUTPUT_HOLDS_NO_CODE: dict[str, object] = {
    'id': 'OUTPUT-HOLDS-NO-CODE',
    'pattern': (
        _VERB + r'\s*["\']?(?:[^\s"\'<>|;&]*[/\\])?output[/\\][^\s"\'<>|;&]*\.' + _SUFFIX + r'(?=["\'\s;&|)]|$)'
    ),
    'matches': 'argument',
    'hazard': 'output/ holds only what a program regenerates; code, a patch or a bundle there is unlanded work.',
    'remedy': 'Commit it on its branch and push it; a one-off goes to scratch/; unwanted work is discarded: '
    '{python} -m dev_lab.dev.branchset --discard <branch> --approved "<the user words>".',
    'needs': None,
    'refuses': (
        'git diff > output/logs/26/11/20/lane/uncommitted.patch',
        'git bundle create output/moved/lane.bundle HEAD',
        'cp probe.py output/logs/26/11/20/probe/probe.py',
        r'Get-Content a | Out-File -FilePath D:\repo\output\run.ps1',
    ),
    'permits': (
        'git log > output/logs/26/11/20/merge/log.txt',
        'git status > output/logs/26/11/20/merge/status.txt',
        'cp output/logs/26/11/20/case/record.json scratch/26/11/20/x/',
        'git bundle verify output/moved/lane.bundle',
    ),
}
