"""The agent deny registry, RECURSIVE-GREP row -- pure DATA.

A recursive ``grep`` walks the filesystem, so it descends into every git-ignored tree a checkout
carries (`.venv`, `output`, `target`); ``git grep`` reads the index and skips them. MEASURED
2026-10-05 in one consumer repo: ``grep -r`` over the repo did not finish in 4 min, ``git grep -l`` took
0.28 s, and about 66k git-ignored files were walked. A grep on a named file, a grep reading a pipe,
and ``git grep`` itself never walk, so they are permitted -- the row keys on the recursion flag.
"""

from __future__ import annotations

__all__ = ['RECURSIVE_GREP']

RECURSIVE_GREP: dict[str, object] = {
    'id': 'RECURSIVE-GREP',
    # A short-flag cluster carrying r/R (-r, -rn, -nR) or the long spelling, anywhere after the verb.
    'pattern': r'[ef]?grep(?:\.exe)?(?:\s+\S+)*?\s+(?:-[a-zA-Z]*[rR][a-zA-Z]*|--(?:dereference-)?recursive)(?=\s|$)',
    'matches': 'command',
    'hazard': 'a recursive grep walks every git-ignored tree (.venv, output, target) and can run for minutes.',
    'remedy': 'Search tracked files: git grep -n <pattern> [-- <paths>], or use the built-in Grep tool.',
    'needs': None,
    'refuses': (
        'grep -r pattern .',
        'grep -rn "TODO" src',
        'grep -nR x src tests',
        'grep --recursive -l x .',
        'grep -i -r x',
        'egrep -r "a|b" src',
    ),
    'permits': (
        'grep -n "x" src/a.py',
        'grep -c error build.log',
        'grep -v "^??"',
        'git grep -n pattern',
        'git grep -rn pattern -- src',
        'grep -e "-r" notes.txt',
    ),
}
