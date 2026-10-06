"""AUTO-MODE-RUNS-THE-DOORS: the family's checked doors, ONE table rendered for Claude Code AND Codex.

USER DIRECTIVE 2026-10-04: in both clients' auto mode the family's sanctioned script doors must run
without an approval prompt or a classifier refusal. MEASURED THE SAME DAY: every refusal that cost a
session time came from Claude Code's auto-mode CLASSIFIER, none from a deny hook. Claude Code SUSPENDS
broad rows in auto mode -- ``Bash(*)`` and wildcarded interpreters such as ``Bash(.venv/*/python* *)``
-- while a NARROW row naming one door stays live and skips the classifier. So every row here names
ONE door: one per door module, one per tracked ``scripts/`` entry point. No ``lab_commons.dev.*``.
The dependency bootstrap prefix is explicit; its interpreter and every tracked Python script
door's interpreter may live in a WORKTREE of this repository, while the invoked door remains exact.

THE INTERPRETER'S DIRECTORY IS THE ONE THING THAT VARIES, AND IT IS ANCHORED RATHER THAN WILDCARDED.
The first spelling of this was ``*/.venv/Scripts/python.exe`` -- a leading ``*``, which permits any
invocation prefix and is the row shape every consumer's allow guard refuses by name. MEASURED
2026-10-06 in a consuming repo: 86 of its 271 rendered rows led with ``*``, all of them from this
function. The prefix is not free-form after all: a linked worktree lives under
:data:`lab_commons.dev.worktreeplace.WORKTREES_REL` (rule WORKTREES-STAY-INSIDE -- a deny row
refuses a misplaced ``git worktree add|move|clone``, and ``famtests.worktreeplace`` detects one that
got past it), so the spelling anchors on that directory and wildcards only the worktree's NAME.

WHAT THE ANCHOR DOES NOT ADMIT, stated rather than discovered later: an interpreter spelled by an
ABSOLUTE path (``D:/repo/.claude/worktrees/lane/.venv/Scripts/python.exe``) or by a ``..`` route.
No row that does not lead with ``*`` can admit one -- the first character of the command is a drive
letter or a root this file, TRACKED IN GIT, cannot know -- so an agent reaching for another
checkout's interpreter that way is prompted once. The road it can take instead is the one
``docs-src/dev/fanout.md`` already spells: run the door from the repository root, where the
interpreter is this checkout's ``.venv/...`` (the plain heads below) or a worktree's
``.claude/worktrees/<lane>/.venv/...`` (this anchor).

USER RULING 2026-10-04: "pushes and remote deletions are never automatic" -- they stay with a human
or the gated push hook. LOCAL cleanup is a door: :mod:`lab_commons.dev.branchset` ``--apply`` (local
branches only; origin is listed), :mod:`lab_commons.dev.worktrees` ``--prune`` and
:mod:`lab_commons.dev.stoprun` ``--pid``. The raw verbs (:data:`NEVER_ALLOWED`) are never rendered.

ONE SOURCE, TWO RENDERINGS, so the clients cannot drift:

* :func:`claude_rows` -- ``Bash(...)`` rows :mod:`lab_commons.dev.allow_adoption` appends to every
  adopting repo's ``permissions.allow`` (held current by ``settings_problems``).
* :func:`codex_rules` -- a Codex execpolicy file of ``prefix_rule(..., decision = "allow")`` rows,
  read from a trusted project's ``.codex/rules/``. ``python -m lab_commons.dev.autodoors --write``.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Final

from lab_commons.dev.venvpath import VENV_INTERPRETER_GLOB, VENV_LAYOUTS
from lab_commons.dev.worktreeplace import WORKTREES_REL
from lab_commons.log import emit

__all__ = [
    'CODEX_RULES_REL',
    'DOOR_MODULES',
    'NEVER_ALLOWED',
    'claude_rows',
    'codex_rules',
    'doors',
    'main',
    'promises_raw',
    'script_doors',
]

#: Where Codex reads a trusted project's execpolicy rules.
CODEX_RULES_REL: Final = '.codex/rules/family-doors.rules'

#: THE TABLE: every ``lab_commons.dev`` door an agent runs unattended, with why.
DOOR_MODULES: Final[dict[str, str]] = {
    'lab_commons.dev.verify': 'the family verdict',
    'lab_commons.dev.branchset': 'branch census; --apply deletes merged LOCAL branches only',
    'lab_commons.dev.worktrees': (
        'worktree census; --prune removes a worktree only if it is clean and pushed;'
        ' nothing is archived aside, and anything blocking is listed and refused'
    ),
    'lab_commons.dev.stoprun': 'stops ONE identifiable gate/verify run and its subtree',
    'lab_commons.dev.netverb': 'the bounded-retry network verb',
    'lab_commons.dev.famfiles': 'renders the family project files',
    'lab_commons.dev.autodoors': 'renders these door rules',
}

#: Bootstrap is a checked dependency door, not permission to invoke arbitrary installers.
_DEPENDENCY_BOOTSTRAP: Final = ('python', '-m', 'lab_commons.dev.dep', '--bootstrap')

#: The raw verbs the doors replace. Never rendered as an allow on either client.
NEVER_ALLOWED: Final = (
    'git push',
    '--delete',
    'branch -D',
    'worktree remove --force',
    'rm -rf',
    'taskkill',
)

_MAIN_GUARD: Final = re.compile(r"""^if __name__ == ['"]__main__['"]:""", flags=re.MULTILINE)


def _tracked(root: Path) -> tuple[str, ...]:
    done = subprocess.run(
        [shutil.which('git') or 'git', '-C', str(root), 'ls-files', '--', 'scripts'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=60,
    )
    if done.returncode != 0:
        msg = f'git ls-files failed in {root}: {done.stderr.strip()}'
        raise RuntimeError(msg)
    return tuple(sorted(done.stdout.splitlines()))


def script_doors(root: Path, *, shell_doors: tuple[str, ...]) -> tuple[str, ...]:
    """The repo's tracked ``scripts/**.py`` ENTRY POINTS (a ``__main__`` guard), plus its tracked *shell_doors*.

    *shell_doors* is the repo's own list (e.g. its netverb wrapper), with no default: a consumer's path
    is that consumer's data, never this leaf's.
    """
    out: list[str] = []
    for rel in _tracked(root):
        path = root / rel
        if rel in shell_doors or (
            rel.endswith('.py') and path.is_file() and _MAIN_GUARD.search(path.read_text('utf-8'))
        ):
            out.append(rel)
    return tuple(out)


def doors(scripts: tuple[str, ...] = ()) -> dict[tuple[str, ...], str]:
    """``{(runner, *argv prefix): why}`` -- the one table both renderings read."""
    out: dict[tuple[str, ...], str] = {('python', '-m', m): why for m, why in DOOR_MODULES.items()}
    out[_DEPENDENCY_BOOTSTRAP] = "creates the named checkout's own environment through the checked dependency door"
    for rel in scripts:
        out[('sh', rel) if rel.endswith('.sh') else ('python', rel)] = f'repo door {rel}'
    return out


def claude_rows(scripts: tuple[str, ...] = ()) -> dict[str, str]:
    """Each narrow door row, with the interpreter's directory anchored rather than wildcarded."""
    out: dict[str, str] = {}
    for (runner, *argv), why in doors(scripts).items():
        heads = [VENV_INTERPRETER_GLOB if runner == 'python' else runner]
        if runner == 'python' and ((runner, *argv) == _DEPENDENCY_BOOTSTRAP or (len(argv) == 1 and argv[0] in scripts)):
            # Only the directory prefix varies, never the executable or its argument boundary.
            # A python* suffix could swallow -c before the named door and permit unrelated code.
            heads = [*_interpreters(), *_worktree_interpreters()]
        for head in heads:
            out[f'Bash({head} {" ".join(argv)} *)'] = why
    return out


def _interpreters() -> list[str]:
    """The checkout's own interpreter: the concrete layout per platform, and the ``./`` spelling of each."""
    plain = ['/'.join(VENV_LAYOUTS[name]) for name in sorted(VENV_LAYOUTS)]
    return [*plain, *(f'./{p}' for p in plain)]


def _worktree_interpreters() -> list[str]:
    """A LINKED WORKTREE's interpreter, spelled from the repository root, one per platform layout.

    THE ``*`` HERE IS THE WORKTREE'S NAME AND NOTHING ELSE. :data:`~lab_commons.dev.worktreeplace.WORKTREES_REL`
    is the one spelling of where a worktree lives, enforcement included, so the directory that varies
    is that one and the row can open with a literal instead of the ``*/`` this replaced -- the shape
    every consumer's allow guard refuses. What it does NOT admit is the same interpreter reached by
    an absolute path or a ``..`` route: no row that does not lead with a wildcard can, because the
    command's first character is a drive or a root a TRACKED file cannot know.

    One wildcard segment rather than several: a worktree NAME carrying a separator (``a/b``) or a
    ``..`` is admitted by this glob and refused by ``WORKTREES-STAY-INSIDE`` where the tree is
    CREATED, which is the half that reads the filesystem and can tell.
    """
    base = f'{WORKTREES_REL}/*'
    return [f'{base}/{"/".join(parts)}' for parts in VENV_LAYOUTS.values()]


def codex_rules(scripts: tuple[str, ...] = ()) -> str:
    """The Codex execpolicy file: one ``prefix_rule`` per door, same table as :func:`claude_rows`."""
    blocks = [
        '# GENERATED by `python -m lab_commons.dev.autodoors --write` (lab_commons.dev.autodoors). Do not edit.',
        '# The same table renders the Claude Code permissions.allow rows. Pushes and remote deletions',
        '# are never allowed here: they stay with a human or the gated push hook (ruling 2026-10-04).',
    ]
    for (runner, *argv), why in doors(scripts).items():
        head = json.dumps(_interpreters()) if runner == 'python' else json.dumps(runner)
        pattern = ', '.join([head, *(json.dumps(token) for token in argv)])
        blocks.append(
            f'prefix_rule(\n    pattern = [{pattern}],\n    decision = "allow",\n'
            f'    justification = {json.dumps(why)},\n)'
        )
    return '\n\n'.join(blocks) + '\n'


_RAW: Final = re.compile('|'.join(re.escape(verb) for verb in NEVER_ALLOWED))


def promises_raw(text: str) -> tuple[str, ...]:
    """The raw destructive verbs *text* (a rendered row or rules body) would allow -- must be empty."""
    return tuple(sorted({m.group(0) for m in _RAW.finditer(text)}))


def main(argv: list[str] | None = None) -> int:
    """Print the Claude rows and check (or ``--write``) the Codex rules for a repo. Exit 1 when stale."""
    parser = argparse.ArgumentParser(prog='python -m lab_commons.dev.autodoors', description=main.__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--write', action='store_true', help=f'write {CODEX_RULES_REL}')
    parser.add_argument('--shell-door', action='append', default=[], help='a tracked shell door (repeatable)')
    args = parser.parse_args(argv)
    root = args.repo.resolve()
    scripts = script_doors(root, shell_doors=tuple(args.shell_door))
    text = codex_rules(scripts)
    target = root / CODEX_RULES_REL
    for row in claude_rows(scripts):
        emit(f'[autodoors] claude  {row}')
    if args.write:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8', newline='\n')
        emit(f'[autodoors] codex   wrote {CODEX_RULES_REL}')
        return 0
    current = target.is_file() and target.read_text(encoding='utf-8') == text
    emit(f'[autodoors] codex   {CODEX_RULES_REL}: {"current" if current else "STALE -- run with --write"}')
    return 0 if current else 1


if __name__ == '__main__':
    raise SystemExit(main())
