"""The agent deny registry, WRITES-STAY-IN-THE-TREE row -- pure DATA, its pattern a prefilter and its judge a module.

The SHELL half of :mod:`dev_lab.dev.writeroots`. The writable roots are a per-machine ALLOWLIST (ruling R8,
2026-11-24) and whether a target lies inside one is a question of the filesystem and the machine file, which no
regex reads. So this pattern only PREFILTERS: a line that writes (a redirect, ``tee``, ``mkdir``/``touch``, a copy or
move, ``dd``, a PowerShell writer) AND spells a target that may leave the call's own directory (an absolute path, the
home, a variable, ``..``). Only then does the engine ask :func:`dev_lab.dev.writeroots.main` (``--admit``), which
places every target the line writes -- ``cd`` followed -- and refuses one outside every writable root. A line writing
only relative paths below its cwd starts no interpreter.
"""

from __future__ import annotations

from dev_lab.dev.writeroots import HAZARD, REMEDY, RULE_ID

__all__ = ['WRITES_STAY_IN_THE_TREE']


def _ci(word: str) -> str:
    """A case-insensitive spelling of *word* (Windows paths and PowerShell are; the engine's regex is not)."""
    return ''.join(f'[{c.lower()}{c.upper()}]' if c.isalpha() else c for c in word)


_VERBS = ('tee', 'mkdir', 'touch', 'cp', 'mv', 'copy', 'move', 'rsync', 'install', 'dd')
_CMDLETS = ('New-Item', 'ni', 'Out-File', 'Set-Content', 'Add-Content', 'Copy-Item', 'Move-Item')
#: Something on the line WRITES: a redirect that is no fd duplication, or a writing verb.
_WRITES = r'(?:>(?!&)|\b(?:' + '|'.join((*_VERBS, *map(_ci, _CMDLETS))) + r')\b)'
#: Something on the line may name a place outside the call's own directory.
_LEAVES = (
    r"""(?:^|[\s"'=>])"""
    r"""(?:/(?!dev/(?:null|stdout|stderr|tty)(?![\w/]))|[A-Za-z]:[\\/]|~|\$|%\w+%|\.\.(?:[\\/]|$|[\s"']))"""
)

WRITES_STAY_IN_THE_TREE: dict[str, object] = {
    'id': RULE_ID,
    'pattern': rf'^(?=[\s\S]*{_WRITES})(?=[\s\S]*{_LEAVES})',
    'matches': 'line',
    'asks': 'dev_lab.dev.writeroots',
    'hazard': HAZARD,
    'remedy': REMEDY,
    'needs': None,
    # Each is refused by the judge on every machine: no allowlist may hold a temp dir, a drive root or the home.
    'refuses': (
        'echo x > /tmp/probe.py',
        "cat <<'EOF' > /tmp/run.sh\necho hi\nEOF",
        'python a.py 2>> /var/tmp/err.log',
        'git log | tee -a $TEMP/log.txt',
        'cp a.py /tmp/',
        'mv out.csv "C:/tmp/out.csv"',
        'mkdir -p /c/temp/probe',
        'touch ~/work/repo/x',
        'cd /tmp && echo x > a.py',
        'Get-Content a | Out-File -FilePath $env:TEMP\\x.txt',
        'New-Item -ItemType File D:\\var\\x.txt',
        'Copy-Item a.py %TEMP%\\a.py',
        'echo x > ~/loose.txt',
        'echo x > $CLAUDE_JOB_DIR/tmp/a.txt',
        'echo x > ../sibling/a.txt',
        'echo x > "D:/Sync/OneDrive - <org>/meeting/fig.png"',
        'cp fig.png $OneDriveCommercial/share/',
        'Set-Content -Path $env:OneDrive\notes.txt x',
    ),
    'permits': (
        'cat /tmp/probe.py',
        'ls $TEMP',
        'echo x > scratch/26/11/05/probe/run.sh',
        'python -m pkg.run > output/logs/26/11/05/run/log.txt 2>&1',
        'rm /tmp/probe.py',
        'echo x 2>/dev/null',
        'cat "D:/Sync/OneDrive - <org>/meeting/data.csv"',
        'echo onedrive > output/logs/26/11/23/sync/note.txt',
    ),
}
