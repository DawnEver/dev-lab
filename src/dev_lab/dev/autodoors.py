"""AUTO-MODE-RUNS-THE-DOORS: the family's checked doors, rendered for Claude Code AND Codex from ONE table.

USER DIRECTIVE 2026-10-04: in both clients' auto mode the family's sanctioned doors must run without an
approval prompt or a classifier refusal. Claude Code SUSPENDS broad rows in auto mode -- ``Bash(*)`` and a
blanket interpreter row -- while a NARROW row naming one door stays live and skips the classifier. So every
row here names ONE door. THE DOORS ARE :data:`dev_lab.dev.agentpolicy.POLICY` (user ruling 2026-11-07: one
source for agent permissions); this module renders them, plus the repo's tracked ``scripts/`` entry points.

THE INTERPRETER IS :data:`dev_lab.dev.agentpolicy.INTERPRETERS`, one literal per platform layout -- never a
``./`` or worktree variant (six rows per script before 2026-11-07), and never the ``.venv/*/python*`` glob, whose
trailing ``*`` admits ``python.exe -c <code>`` ahead of the door. A door run through another checkout's
interpreter is prompted once; from the repository root it is this checkout's.

USER RULING 2026-10-08 (MAIN-SESSION-PUBLISHES), superseding the push half of 2026-10-04: a MAIN
session pushes and fast-forwards its trunks without waiting for a user decision. So the publishing
verbs are doors too (main-session rows of the policy table): ``git merge --ff-only`` (also as ``git -C <repo>``), and
the push, ALWAYS RETRY-WRAPPED and never raw (NETWORK-VERB refuses a raw one): the repo's own
wrapper (``sh <rel> *``), a sibling checkout's wrapper (``sh */<rel> push *``), or the family verb
:mod:`dev_lab.dev.netverb` in a repo without one. A subagent is still refused every push by the
scoped deny row SUBAGENT-NO-PUSH, and a force push by PUSH-FORCE: a deny hook fires before
an allow row is consulted. REMOTE DELETIONS ARE STILL NEVER AUTOMATIC -- a push glob admits
``--delete`` and ``:<ref>``, so PUSH-REMOTE-DELETE refuses them.

LOCAL cleanup is a door: :mod:`dev_lab.dev.branchset` ``--apply`` (local
branches only; origin is listed), :mod:`dev_lab.dev.worktrees` ``--prune`` and
:mod:`dev_lab.dev.stoprun` ``--pid``. The raw verbs (:data:`NEVER_ALLOWED`) are never rendered.

ONE SOURCE, TWO RENDERINGS, so the clients cannot drift:

* :func:`claude_rows` -- ``Bash(...)`` rows :mod:`dev_lab.dev.allow_adoption` appends to every
  adopting repo's ``permissions.allow`` (held current by ``settings_problems``).
* :func:`codex_rules` -- a Codex execpolicy file of ``prefix_rule(..., decision = "allow")`` rows,
  read from a trusted project's ``.codex/rules/``. ``python -m dev_lab.dev.autodoors --write``.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.agentpolicy import INTERPRETERS, POLICY, USER, allow_rows

__all__ = [
    'CODEX_RULES_REL',
    'NEVER_ALLOWED',
    'claude_rows',
    'codex_rules',
    'doors',
    'main',
    'promises_raw',
    'script_doors',
]

CODEX_RULES_REL: Final = '.codex/rules/family-doors.rules'

_RETRY_WRAPPER: Final = 'with-retry.sh'

#: The raw verbs the doors replace. Never rendered as an allow on either client.
NEVER_ALLOWED: Final = (
    '--force',
    'push -f',
    '--delete',
    'branch -D',
    'worktree remove --force',
    'rm -rf',
    'taskkill',
)

_MAIN_GUARD: Final = re.compile(r"""^if __name__ == ['"]__main__['"]:""", flags=re.MULTILINE)


def _tracked(root: Path) -> tuple[str, ...]:
    done = _door.run(
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
    """``{(runner, *argv prefix): intent}`` -- every door an agent may run, the one table both renderings read."""
    out = {('sh', rel) if rel.endswith('.sh') else ('python', rel): f'repo door {rel}' for rel in scripts}
    out.update({door.argv: door.intent for door in POLICY if door.argv and door.actor != USER})
    return out


def _wrappers(scripts: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(rel for rel in scripts if rel.rsplit('/', 1)[-1] == _RETRY_WRAPPER)


def claude_rows(scripts: tuple[str, ...] = ()) -> dict[str, str]:
    """Each narrow door row (:func:`dev_lab.dev.agentpolicy.allow_rows`), mapped to what the door is for."""
    out = {row: why for argv, why in doors(scripts).items() for row in allow_rows(argv)}
    for rel in _wrappers(scripts):
        out[f'Bash(sh */{rel} push *)'] = 'a push through a checkout`s retry wrapper (MAIN-SESSION-PUBLISHES)'
    return out


def codex_rules(scripts: tuple[str, ...] = ()) -> str:
    """The Codex execpolicy file: one ``prefix_rule`` per door, same table as :func:`claude_rows`."""
    blocks = [
        '# GENERATED by `python -m dev_lab.dev.autodoors --write` (dev_lab.dev.autodoors). Do not edit.',
        '# The same table renders the Claude Code permissions.allow rows. A main session publishes',
        '# (MAIN-SESSION-PUBLISHES); force pushes and remote deletions are never allowed here.',
    ]
    for (runner, *argv), why in doors(scripts).items():
        head = json.dumps(list(INTERPRETERS)) if runner == 'python' else json.dumps(runner)
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
    """Print the Claude rows and check (or ``--write``) the Codex rules for a repo. Exit 1 when stale.

    The auto-mode prose is NOT here: it is machine-local and never committed (:mod:`dev_lab.dev.automode`).
    """
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.autodoors', description=main.__doc__)
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
