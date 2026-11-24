"""The agent deny registry, NO-BACKUP-COPIES row -- pure DATA.

USER RULING 2026-11-23: "Forbid backing up content into output and scratch! Everything is either cleaned or merged,
no backup." Measured the same day: ~3.4 M source files as copied checkouts under one repo's ``output/`` (333 GB),
made by ``git worktree add``/``clone`` into ``output/logs/<date>/{cleanup6,bisect,base_tree,...}``, by copying a
tree there, and by the retired ``worktrees --archive``. This row is the SHELL half: a command that makes a checkout
or copies a tree or a backup into ``output/`` or ``scratch/``. The Write/Edit half and the filesystem scan are
:mod:`dev_lab.dev.layout` (:func:`~dev_lab.dev.layout.refuse_layout`, :func:`~dev_lab.dev.layout.layout_violations`);
OUTPUT-HOLDS-NO-CODE already refuses a single code file or bundle written under ``output/``.

A ``mv`` is not refused: moving an approved path into ``scratch/`` and clearing it there is RECURSIVE-DELETE's door.
"""

from __future__ import annotations

__all__ = ['NO_BACKUP_COPIES']

_P = r'[^\s"\'<>|;&]'
#: A path under any output/ or scratch/: the destination this row refuses.
_ROOT = rf'["\']?(?:{_P}*[/\\])?(?:output|scratch)(?:[/\\]{_P}*)?["\']?'
_END = r'\s*(?=$|[;&|)])'
_GIT = r'\bgit\s+(?:-C\s+\S+\s+)?'
_ARGS = r'[^;&|\n]*'
#: Each maker with where its DESTINATION sits: a copy is refused only when it LANDS under output/ or scratch/.
_MAKERS = (
    rf'{_GIT}(?:worktree\s+add|clone|archive)\b{_ARGS}?\s{_ROOT}',
    rf'{_GIT}bundle\s+create\s+{_ROOT}',
    rf'{_GIT}diff\b{_ARGS}?>\s*["\']?(?:(?:{_P}*[/\\])?scratch[/\\]|(?:{_P}*[/\\])?output[/\\]{_P}*\.(?:patch|diff)\b)',
    rf'{_GIT}format-patch\b{_ARGS}?(?:-o\s+|--output-directory[=\s]+){_ROOT}',
    rf'\b(?:cp|rsync)\s+-\w*[rRa]\w*\s{_ARGS}\s{_ROOT}{_END}',
    rf'\bCopy-Item\b(?={_ARGS}\s-Recurse\b){_ARGS}\s(?:-Destination\s+)?{_ROOT}(?:\s+-Recurse)?{_END}',
    rf'\b(?:robocopy|xcopy)\s+\S+\s+{_ROOT}',
    rf'\b(?:tar\s+-?\w*c\w*f|zip\s+-\w*r\w*|7z\s+a|Compress-Archive\b{_ARGS}?-DestinationPath)\s+{_ROOT}',
)

NO_BACKUP_COPIES: dict[str, object] = {
    'id': 'NO-BACKUP-COPIES',
    'pattern': '|'.join(f'(?:{one})' for one in _MAKERS),
    'matches': 'argument',
    'hazard': (
        'output/ and scratch/ never hold a copy or backup of work: a parked checkout, tree, bundle, patch or archive '
        'is unlanded work nothing merges, and it grew one repo`s output/ to 3.4 M copied source files.'
    ),
    'remedy': (
        'MERGE-OR-DELETE: commit the work on its branch and land it through a PR, or delete it '
        '({python} -m dev_lab.dev.branchset --discard <branch> --approved "<the user words>"); a second tree of this '
        'repo is <repo>/.claude/worktrees/<name-for-the-task>.'
    ),
    'needs': None,
    'refuses': (
        'git worktree add output/logs/26/11/23/bisect HEAD~3',
        'git clone . scratch/base_tree',
        'git -C ../repo worktree add D:/repo/output/logs/26/11/23/cleanup6 main',
        'cp -r src output/logs/26/11/23/si_sizes2',
        'Copy-Item -Recurse .claude/worktrees/lane D:\\repo\\output\\lane-copy\\lane',
        'robocopy src output\\logs\\26\\11\\23\\copy /E',
        'git diff HEAD > scratch/uncommitted.patch',
        'git format-patch -o output/moved main..lane',
        'git bundle create scratch/lane.bundle HEAD',
        'tar -czf output/logs/26/11/23/tree.tgz src',
        'git archive HEAD -o output/base.zip',
    ),
    'permits': (
        'git worktree add .claude/worktrees/fix-x -b fix/x',
        'cp output/logs/26/11/23/case/record.json scratch/26/11/23/x/',
        'cp -r output/logs/26/11/23/case .claude/memory/2026/11/23/attachments/',
        'mv .claude/worktrees/dead scratch/dead',
        'git diff --stat > output/logs/26/11/23/merge/stat.txt',
        'git archive HEAD -o dist/x.zip',
        'robocopy output\\logs\\26 D:\\elsewhere /E',
    ),
}
