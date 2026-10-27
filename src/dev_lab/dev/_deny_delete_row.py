"""The agent deny registry, RECURSIVE-DELETE row -- pure DATA.

INCIDENT 2026-10-27: an agent hand-built a delete list from ``git worktree list`` and ran a raw
``Remove-Item -Recurse -Force`` over it; one entry was a MAIN checkout, deleted with its ``.git``,
unpushed work and ``output/``, past the recycle bin. The door that decides what is deletable --
``branchset --apply`` -> ``reclaim``, which refuses a main checkout and keeps real work -- existed and
was bypassed. So every raw recursive delete is refused, in both shells, unless EVERY target it names
is regenerable scratch: system temp, or a path inside an ``output/`` tree (no ``..`` segment).
"""

from __future__ import annotations

__all__ = ['RECURSIVE_DELETE']

#: A shell TOKEN: a quoted string or a bare word.
_WORD = r"""(?:"[^"\n]*"|'[^'\n]*'|[^\s"';&|()]+)"""


def _ci(word: str) -> str:
    """A case-insensitive spelling of ``word`` (PowerShell is; the engine's regex is not)."""
    return ''.join(f'[{c.lower()}{c.upper()}]' if c.isalpha() else c for c in word)


#: A target that is PROVABLY scratch: one token with no whitespace inside its quotes and no `..` anywhere,
#: under system temp or inside an `output/` tree.
_SCRATCH = (
    r"""(?![^\s;&|()]*\.\.)["']?(?:/tmp/|\$\{?(?:TEMP|TMP|TMPDIR)\}?[\\/]|%(?:TEMP|TMP)%[\\/]|\$env:(?:TEMP|TMP)[\\/]"""
    r"""|(?:[^\s"';&|()]*[\\/])?""" + _ci('AppData') + r'[\\/]' + _ci('Local') + r'[\\/]' + _ci('Temp') + r'[\\/]'
    r"""|(?:[^\s"';&|()]*[\\/])?output[\\/])[^\s"'\\/;&|()][^\s"';&|()]*["']?(?=\s|$)"""
)
#: An option word: `-x`, `--x`, or a cmd switch `/s` `/q`.
_OPTION = r"""(?:-[^\s"';&|()]*|/[a-zA-Z])(?=\s|$)"""
#: Permitted only when the delete NAMES a target and EVERY word after the verb is an option or scratch.
#: A delete naming no target reads its targets from a pipe or `xargs`, and nothing proves those scratch.
_ALL_SCRATCH = (
    r'(?=(?:\s+' + _WORD + r')*?\s+' + _SCRATCH + r')(?:\s+(?:' + _OPTION + r'|' + _SCRATCH + r"""))+\s*["']?\s*$"""
)
_END = r'(?=\s|$|:)'
#: The recursion switch: a short cluster (`-r`, `-rf`, `-fR`), `--recursive`, PowerShell's `-Recurse`
#: under any abbreviation, or cmd's `/s`. The cluster's letters exclude `-Force`'s, so it never matches.
_RECURSE = r'(?:-[fvidI]*[rR][fvidI]*|--recursive|-[rR](?:[eE](?:[cC](?:[uU](?:[rR](?:[sS][eE]?)?)?)?)?)?|/[sS])' + _END
_RM_VERBS = '|'.join(_ci(verb) for verb in ('Remove-Item', 'rmdir', 'erase', 'rm', 'ri', 'rd', 'del'))
#: What hands the verb its targets: `cmd /c`, `xargs [opts]`, `find ... -exec`.
_LAUNCHER = (
    r"""(?:[cC][mM][dD](?:\.[eE][xX][eE])?\s+/[cCkK]\s+["']?"""
    r"""|xargs(?:\s+-\S+)*\s+|find\b[^\n;&|]*?\s-exec(?:dir)?\s+)?"""
)
_RM = (
    _LAUNCHER + r'(?:' + _RM_VERBS + r')(?:\.exe)?'
    r'(?=(?:\s+' + _WORD + r')*?\s+' + _RECURSE + r')(?!' + _ALL_SCRATCH + r')'
)
_GIT = r'git(?:\.exe)?(?:\s+-[Cc]\s+' + _WORD + r')*\s+'
#: `git clean` removing directories or ignored files; a dry run is exempt only within ITS OWN argument list.
_ARGS = r'[^\n;&|]*'
_GIT_CLEAN = (
    _GIT + r'clean\b(?=' + _ARGS + r'\s(?:-[a-zA-Z]*[xXd]|--directory)\b)'
    r'(?!' + _ARGS + r'\s(?:-[a-zA-Z]*n[a-zA-Z]*|--dry-run)(?=\s|$|[;&|]))'
)
#: Interpreter code: statements with no quote before the call, so prose QUOTING it never matches;
#: and the `python -c` segment itself, whose code the engine also reads line by line.
_RMTREE = (
    r"""\S*python[\w.]*(?:\.exe)?\s+-c\s+[^\n]*?\bshutil\.rmtree\b"""
    r"""|(?:[^;\n'"]*;\s*)*(?:shutil\.)?rmtree\s*\("""
)

RECURSIVE_DELETE: dict[str, object] = {
    'id': 'RECURSIVE-DELETE',
    'pattern': r'(?:' + _RM + r'|' + _GIT + r'worktree\s+remove\b|' + _GIT_CLEAN + r'|' + _RMTREE + r')',
    'matches': 'command',
    'hazard': 'a raw recursive delete judges deletability by hand; on 2026-10-27 one took a MAIN checkout.',
    'remedy': (
        'Worktrees and branches: <venv python> -m dev_lab.dev.branchset --apply (reclaim refuses '
        'a main checkout and keeps real work). Anything else: ask the user. Scratch under system temp or output/ '
        'is not refused.'
    ),
    'needs': None,
    'refuses': (
        'rm -rf .claude/worktrees/lane',
        'rm -fr ../repo',
        'rm --recursive C:/work/repo',
        'Remove-Item -LiteralPath "C:/work/repo" -Recurse -Force',
        'remove-item -rec C:/work/repo',
        'rmdir /s /q C:/work/repo',
        'cmd /c rd /s C:/work/repo',
        'git worktree remove --force C:/work/repo',
        'git clean -fdx',
        'xargs rm -rf',
        'Remove-Item -Recurse -Force',
        'rm -rf "/tmp/a b/../../repo"',
        'git clean -fX',
        'python -c \'import shutil; shutil.rmtree(r"C:/work/repo")\'',
    ),
    'permits': (
        'rm -rf /tmp/probe',
        'Remove-Item -Recurse -Force $env:TEMP/probe',
        'rmdir /s /q %TEMP%/probe',
        'rm -rf output/logs/26',
        'rm notes.txt',
        'Remove-Item -Force file.txt',
        'rmdir empty-dir',
        'git worktree list',
        'git clean -n',
        'git clean -nd',
        'git commit -m "refuse rm -rf"',
    ),
}
