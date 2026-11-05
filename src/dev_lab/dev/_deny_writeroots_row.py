"""The agent deny registry, WRITES-STAY-IN-THE-TREE row -- pure DATA.

The SHELL half of :mod:`dev_lab.dev.writeroots`: a redirect, ``tee``, ``cp``/``mv``/``Copy-Item``/``Move-Item``
(by their LAST argument), ``mkdir``/``touch``/``New-Item``, ``Out-File``/``Set-Content``/``Add-Content`` whose
target is a write-prone root -- temp (``/tmp``, ``/var/tmp``, ``$TEMP``, ``%TEMP%``, ``$env:TEMP``,
``AppData/Local/Temp``), a drive's or the home's ``tmp``/``temp``/``var``/``src``, or a loose non-dot entry in the
home. The engine reads text, so the roots are spelled here as a pattern; their one declaration is
:func:`dev_lab.dev.writeroots.write_prone_roots`, whose hazard and remedy this row speaks. The harness's own
``<temp>/claude/`` subtree is never matched. Reading a root, and deleting from one, stay allowed.
"""

from __future__ import annotations

from dev_lab.dev.writeroots import DRIVE_NAMES, EXCLUDED_IN_TEMP, HAZARD, REMEDY, RULE_ID

__all__ = ['WRITES_STAY_IN_THE_TREE']


def _ci(word: str) -> str:
    """A case-insensitive spelling of *word* (Windows paths and PowerShell are; the engine's regex is not)."""
    return ''.join(f'[{c.lower()}{c.upper()}]' if c.isalpha() else c for c in word)


_PATHCHAR = r"""[^\s"';&|()<>]"""
#: One path SEGMENT: a token character that is no separator.
_SEG = r"""[^\s"';&|()<>\\/]"""
_END = r"""(?=["'\s;&|)]|$)"""
_NAMES = '(?:' + '|'.join(_ci(name) for name in DRIVE_NAMES) + ')'
_EXCLUDED = '|'.join(EXCLUDED_IN_TEMP)
#: The OS temp dir, by every spelling a shell gives it, not followed by an excluded name.
_TEMP = (
    r'(?:/tmp|/var/tmp|\$\{?(?:TEMP|TMP|TMPDIR)\}?|%(?:TEMP|TMP)%|\$env:(?:TEMP|TMP)'
    rf'|(?:{_PATHCHAR}*[\\/])?{_ci("AppData")}[\\/]{_ci("Local")}[\\/]{_ci("Temp")})'
    rf'(?![\\/]+(?:{_EXCLUDED})(?:[\\/"\'\s;&|)]|$))'
)
#: A drive root: ``C:/``, ``C:\``, Git Bash's ``/c/``.
_DRIVE = r'(?:[A-Za-z]:[\\/]+|/[A-Za-z]/)'
#: The home, by every spelling a shell gives it.
_HOME = (
    r'(?:~|\$HOME|\$\{HOME\}|\$env:USERPROFILE|%USERPROFILE%'
    rf'|[A-Za-z]:[\\/]+{_ci("Users")}[\\/]+{_SEG}+|/[A-Za-z]/{_ci("Users")}/{_SEG}+|/home/{_SEG}+)'
)
_SEP = r'[\\/]'
#: A target path, closing quote included: a root and anything beneath it, or one loose non-dot home entry.
_TARGET = (
    r"""["']?(?:"""
    rf'(?:{_TEMP}|{_DRIVE}{_NAMES}|{_HOME}{_SEP}+{_NAMES})(?:{_SEP}{_PATHCHAR}*)?'
    rf'|{_HOME}{_SEP}+[^\s"\';&|()<>.\\/]{_SEG}*'
    rf'){_END}["\']?'
)
_WRITERS = (
    rf'>>?\s*{_TARGET}'
    rf'|\btee\b(?:\s+-\S+)*\s+{_TARGET}'
    rf'|\b(?:mkdir|touch|{_ci("New-Item")}|{_ci("Out-File")}|{_ci("Set-Content")}|{_ci("Add-Content")})\b'
    rf'[^;&|\n]*?\s(?:-\w+\s+)?{_TARGET}'
    rf'|\b(?:cp|mv|copy|move|rsync|{_ci("Copy-Item")}|{_ci("Move-Item")})\b[^;&|\n]*\s{_TARGET}\s*(?=[;&|)]|$)'
)

WRITES_STAY_IN_THE_TREE: dict[str, object] = {
    'id': RULE_ID,
    'pattern': f'(?:{_WRITERS})',
    'matches': 'argument',
    'hazard': HAZARD,
    'remedy': REMEDY,
    'needs': None,
    'refuses': (
        'echo x > /tmp/probe.py',
        'python a.py 2>> /var/tmp/err.log',
        'git log | tee -a $TEMP/log.txt',
        'cp a.py /tmp/',
        'mv out.csv "C:/tmp/out.csv"',
        'mkdir -p /c/temp/probe',
        'touch $HOME/src/x.py',
        'Get-Content a | Out-File -FilePath $env:TEMP\\x.txt',
        'New-Item -ItemType File D:\\var\\x.txt',
        'Copy-Item a.py %TEMP%\\a.py',
        'echo x > ~/loose.txt',
    ),
    'permits': (
        'cat /tmp/probe.py',
        'ls $TEMP',
        'cp /tmp/x.csv output/logs/26/11/05/probe/x.csv',
        'echo x > /tmp/claude/abc/tasks/out.txt',
        'echo x > scratch/26/11/05/probe/run.sh',
        'echo x > ~/.bashrc',
        'rm /tmp/probe.py',
        'echo x 2>/dev/null',
    ),
}
