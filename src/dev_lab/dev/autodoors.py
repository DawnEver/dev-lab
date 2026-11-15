"""AUTO-MODE-RUNS-THE-DOORS: the family's checked doors, rendered for Claude Code AND Codex from ONE table.

USER DIRECTIVE 2026-10-04: in both clients' auto mode the family's sanctioned doors must run without an
approval prompt or a classifier refusal. Claude Code SUSPENDS broad rows in auto mode -- ``Bash(*)`` and a
blanket interpreter row -- while a NARROW row naming one door stays live and skips the classifier. So every
row here names ONE door. THE DOORS ARE :data:`dev_lab.dev.agentpolicy.POLICY` (user ruling 2026-11-07: one
source for agent permissions); this module renders them, plus the repo's tracked ``scripts/`` entry points.

THE INTERPRETER IS :data:`dev_lab.dev.doorrows.INTERPRETERS`, one literal per platform layout -- never a
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

A CONSUMER'S OWN READ-ONLY CLI VERBS are doors too (decision 2026-11-15): the repo declares them as data in
``[tool.dev_lab.cli_doors]`` of its ``pyproject.toml`` (:func:`cli_doors`), never as hand rows in its settings,
which this renderer owns. An act is never declarable: a prefix ending in a verb of :data:`REFUSED_ACTS` or of the
repo's own ``acts`` list is refused by name (:class:`ActDeclaredAsDoor`).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.agentpolicy import POLICY, SUBAGENT, USER, Door
from dev_lab.dev.doorrows import INTERPRETERS, allow_rows
from dev_lab.dev.family import declared_table

__all__ = [
    'CLI_DOORS_TABLE',
    'CODEX_RULES_REL',
    'NEVER_ALLOWED',
    'REFUSED_ACTS',
    'ActDeclaredAsDoor',
    'claude_rows',
    'cli_doors',
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

#: The consumer's table: ``acts = [<verb>...]`` and ``doors = [{argv = [<module>, <verb>...], why = <line>}...]``.
CLI_DOORS_TABLE: Final = 'cli_doors'

#: The act verbs no repo may declare as a door, whatever its own ``acts`` list says.
REFUSED_ACTS: Final = frozenset({'press', 'set-value', 'close', 'kill', 'delete', 'push'})

#: One argv token of a declared CLI door: no space, glob or leading dash, so a row admits only its verb.
_CLI_TOKEN: Final = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]*')

#: A declared CLI door's shortest argv: the module and one verb (a bare module admits every verb).
_MODULE_AND_VERB: Final = 2

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


class ActDeclaredAsDoor(ValueError):
    """A declared CLI door names an act verb: an act stays prompted, never a door."""


def cli_doors(root: Path) -> tuple[Door, ...]:
    """The repo's declared read-only CLI verbs (``[tool.dev_lab.cli_doors] doors``), each a ``python -m`` door.

    Raises:
        ActDeclaredAsDoor: a prefix's last element is in :data:`REFUSED_ACTS` or the table's ``acts``.
        ValueError: a prefix is a bare module (it would admit every verb) or carries a non-token element.

    """
    manifest = root / 'pyproject.toml'
    data = tomllib.loads(manifest.read_text(encoding='utf-8')) if manifest.is_file() else {}
    table: Mapping[str, Any] = declared_table(data, CLI_DOORS_TABLE, {})
    acts = REFUSED_ACTS | set(table.get('acts', ()))
    out: list[Door] = []
    for row in table.get('doors', ()):
        argv = tuple(row['argv'])
        where = f'{manifest}: [tool.dev_lab.{CLI_DOORS_TABLE}] door {list(argv)}'
        if len(argv) < _MODULE_AND_VERB or not all(_CLI_TOKEN.fullmatch(token) for token in argv):
            msg = f'{where} must be a module and at least one verb, each a plain token, so it admits only that verb'
            raise ValueError(msg)
        if argv[-1] in acts:
            msg = f'{where} ends in the act {argv[-1]!r}: an act stays prompted, never a door'
            raise ActDeclaredAsDoor(msg)
        out.append(Door(('python', '-m', *argv), SUBAGENT, row['why']))
    return tuple(out)


def doors(scripts: tuple[str, ...] = (), cli: tuple[Door, ...] = ()) -> dict[tuple[str, ...], str]:
    """``{(runner, *argv prefix): intent}`` -- every door an agent may run, the one table both renderings read.

    *cli* is the repo's declared CLI doors (:func:`cli_doors`), with no default: a consumer's verbs are its data.
    """
    out = {('sh', rel) if rel.endswith('.sh') else ('python', rel): f'repo door {rel}' for rel in scripts}
    out.update({door.argv: door.intent for door in (*POLICY, *cli) if door.argv and door.actor != USER})
    return out


def _wrappers(scripts: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(rel for rel in scripts if rel.rsplit('/', 1)[-1] == _RETRY_WRAPPER)


def claude_rows(scripts: tuple[str, ...] = (), cli: tuple[Door, ...] = ()) -> dict[str, str]:
    """Each narrow door row (:func:`dev_lab.dev.doorrows.allow_rows`), mapped to what the door is for."""
    out = {row: why for argv, why in doors(scripts, cli).items() for row in allow_rows(argv)}
    for rel in _wrappers(scripts):
        out[f'Bash(sh */{rel} push *)'] = 'a push through a checkout`s retry wrapper (MAIN-SESSION-PUBLISHES)'
    return out


def codex_rules(scripts: tuple[str, ...] = (), cli: tuple[Door, ...] = ()) -> str:
    """The Codex execpolicy file: one ``prefix_rule`` per door, same table as :func:`claude_rows`."""
    blocks = [
        '# GENERATED by `python -m dev_lab.dev.autodoors --write` (dev_lab.dev.autodoors). Do not edit.',
        '# The same table renders the Claude Code permissions.allow rows. A main session publishes',
        '# (MAIN-SESSION-PUBLISHES); force pushes and remote deletions are never allowed here.',
    ]
    for (runner, *argv), why in doors(scripts, cli).items():
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
    cli = cli_doors(root)
    text = codex_rules(scripts, cli)
    target = root / CODEX_RULES_REL
    for row in claude_rows(scripts, cli):
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
