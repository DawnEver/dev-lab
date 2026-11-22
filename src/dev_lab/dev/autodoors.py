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

A CONSUMER'S OWN CLI VERBS are doors too (decision 2026-11-15): the repo declares them as data in
``[tool.dev_lab.cli_doors]`` of its ``pyproject.toml`` (:func:`cli_doors`), never as hand rows in its settings,
which this renderer owns. A row is read-only unless it says ``act = true``: then it is a WRITING verb the repo
admits explicitly, and its one intent is prefixed :data:`ACT_LABEL` wherever it renders (allow row, Codex rule,
classifier intent). A prefix ending in a verb of :data:`REFUSED_ACTS` or of the repo's own ``acts`` list (the
verbs that stay prompted) is refused by name either way (:class:`ActDeclaredAsDoor`).
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
from dev_lab.dev.codexdeny import CODEX_DENY_REL, codex_deny_rules
from dev_lab.dev.doorrows import INTERPRETERS, allow_rows
from dev_lab.dev.family import declared_table

__all__ = [
    'ACT_LABEL',
    'CLI_DOORS_TABLE',
    'CODEX_RULES_REL',
    'NEVER_ALLOWED',
    'REFUSED_ACTS',
    'ActDeclaredAsDoor',
    'claude_rows',
    'cli_doors',
    'cli_modules',
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

#: The consumer's table: ``acts = [<verb>...]`` (verbs that stay prompted) and
#: ``doors = [{verb = [<verb>...], why = <line>, act = <bool, default false>, script = <name>}...]``.
#: The MODULE is never typed here: it is the repo's own ``[project.scripts]`` target (:func:`cli_modules`).
CLI_DOORS_TABLE: Final = 'cli_doors'

#: The prefix of an act row's intent, so every rendering says the door writes.
ACT_LABEL: Final = 'Acts (writes): '

#: The keys a declared CLI door may carry; any other (a typo such as ``acts``) is refused by name.
_CLI_ROW_KEYS: Final = frozenset({'verb', 'why', 'act', 'actor', 'script'})

#: The act verbs no repo may declare as a door, whatever its own ``acts`` list says.
REFUSED_ACTS: Final = frozenset({'press', 'set-value', 'close', 'kill', 'delete', 'push'})

#: One argv token of a declared CLI door: no space, glob or leading dash, so a row admits only its verb.
_CLI_TOKEN: Final = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]*')

_MAIN_SUFFIX: Final = '.__main__'

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


def cli_modules(data: Mapping[str, Any]) -> dict[str, str]:
    """``{script name: python -m module}`` from the repo's own ``[project.scripts]`` -- the module's ONE source.

    A target ``pkg.__main__:main`` is the module ``pkg`` (what ``python -m pkg`` runs). A target in any other
    module is refused by name: ``python -m`` would run that module's guard, not the script's function.
    """
    out: dict[str, str] = {}
    for name, target in data.get('project', {}).get('scripts', {}).items():
        module = str(target).split(':', 1)[0].strip()
        if not module.endswith(_MAIN_SUFFIX):
            msg = (
                f'[project.scripts] {name} = {target!r} is not a package __main__: a CLI door runs '
                f'`python -m <package>`, so point the script at `<package>{_MAIN_SUFFIX}:main`'
            )
            raise ValueError(msg)
        out[name] = module.removesuffix(_MAIN_SUFFIX)
    return out


def _module_of(row: Mapping[str, Any], modules: Mapping[str, str], where: str) -> str:
    script = row.get('script')
    if script is not None:
        if script not in modules:
            msg = f'{where}: script {script!r} is none of [project.scripts] {sorted(modules)}'
            raise ValueError(msg)
        return modules[script]
    distinct = sorted(set(modules.values()))
    if len(distinct) != 1:
        msg = (
            f'{where} names no script and [project.scripts] declares {sorted(modules) or "none"}: '
            'declare the CLI there, and with several modules say which with `script = "<name>"`'
        )
        raise ValueError(msg)
    return distinct[0]


def _cli_door(row: Mapping[str, Any], modules: Mapping[str, str], acts: set[str], where: str) -> Door:
    """One declared row as a ``python -m <module> <verb...>`` door, refused by name when it would widen or lie."""
    if 'argv' in row:
        msg = f'{where}: `argv` is retired -- write `verb = [<verb>...]`; the module comes from [project.scripts]'
        raise ValueError(msg)
    if unknown := sorted(set(row) - _CLI_ROW_KEYS):
        msg = f'{where} carries unknown keys {unknown}: a row holds only {sorted(_CLI_ROW_KEYS)}'
        raise ValueError(msg)
    verb = tuple(row.get('verb', ()))
    if not verb or not all(isinstance(t, str) and _CLI_TOKEN.fullmatch(t) for t in verb):
        msg = f'{where} must name at least one verb, each a plain token: a bare module would admit every verb'
        raise ValueError(msg)
    if verb[-1] in acts:
        msg = f'{where} ends in the act {verb[-1]!r}: an act stays prompted, never a door'
        raise ActDeclaredAsDoor(msg)
    act = row.get('act', False)
    if not isinstance(act, bool):
        msg = f'{where}: act must be true or false, not {act!r}'
        raise TypeError(msg)
    if row.get('actor', SUBAGENT) != SUBAGENT:
        msg = (
            f'{where}: actor {row["actor"]!r} cannot be declared here -- SUBAGENT-NO-PUSH, MAIN-ONLY-DOOR derive from '
            f'the kit POLICY only, so a repo row is a {SUBAGENT!r} door; ask for the row in the policy table instead'
        )
        raise ValueError(msg)
    why = row['why']
    if act and why.lstrip().lower().startswith('read-only'):
        msg = f'{where} is an act row whose why claims read-only: say what it writes'
        raise ValueError(msg)
    module = _module_of(row, modules, where)
    return Door(('python', '-m', module, *verb), SUBAGENT, f'{ACT_LABEL}{why}' if act else why)


def cli_doors(root: Path) -> tuple[Door, ...]:
    """The repo's declared CLI verbs, each a ``python -m <module> <verb...>`` door; the module from :func:`cli_modules`.

    A row is read-only, its intent its ``why``; an ``act = true`` row is a writing verb, its intent
    :data:`ACT_LABEL` + ``why``. Every row is a :data:`~dev_lab.dev.agentpolicy.SUBAGENT` door.

    Raises:
        ActDeclaredAsDoor: a prefix's last verb is in :data:`REFUSED_ACTS` or the table's ``acts``.
        TypeError: a non-boolean ``act``.
        ValueError: no verb (a bare module admits every verb), a non-token verb, an unknown or retired key,
            an ``actor`` other than subagent, an act row whose ``why`` claims read-only, or
            no single ``[project.scripts]`` module to run it under.

    """
    manifest = root / 'pyproject.toml'
    data = tomllib.loads(manifest.read_text(encoding='utf-8')) if manifest.is_file() else {}
    table: Mapping[str, Any] = declared_table(data, CLI_DOORS_TABLE, {})
    rows = table.get('doors', ())
    if not rows:
        return ()
    modules = cli_modules(data)
    acts = REFUSED_ACTS | set(table.get('acts', ()))
    return tuple(
        _cli_door(row, modules, acts, f'{manifest}: [tool.dev_lab.{CLI_DOORS_TABLE}] door {dict(row)}') for row in rows
    )


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
    files = {CODEX_RULES_REL: codex_rules(scripts, cli), CODEX_DENY_REL: codex_deny_rules()}
    for row in claude_rows(scripts, cli):
        emit(f'[autodoors] claude  {row}')
    stale = 0
    for rel, text in files.items():
        target = root / rel
        if args.write:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8', newline='\n')
            emit(f'[autodoors] codex   wrote {rel}')
            continue
        current = target.is_file() and target.read_text(encoding='utf-8') == text
        stale += not current
        emit(f'[autodoors] codex   {rel}: {"current" if current else "STALE -- run with --write"}')
    return 1 if stale else 0


if __name__ == '__main__':
    raise SystemExit(main())
