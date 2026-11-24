"""REM-RETIRED: the rem plugin is archived; what it left in a repo or on a machine is refused, and removed by a door.

User rulings 2026-11-23: memory stays in each repo's root, and rem is retired whole -- doc freshness, scope config,
the derived memory index, per-turn recall, crystallized rules, the forced end-of-session pass, investigate, todo,
session bindings and rem's state file. Its kept duties are dev-lab's (rendered into ``.claude/settings.json``):
the ledger guard (:mod:`dev_lab.dev.ledgerguard`),
the task derived from the branch, the task's forge events, and memory write and search (:mod:`dev_lab.dev.memory`).

WHAT IS REFUSED, AND ITS DOOR:

* in a repo, :data:`REPO_LEFTOVERS` -- found by :func:`leftovers` in the root's ``.claude/`` and every scope's
  (a directory whose ``.claude/`` git tracks). The door is ``migrate --apply``, run ONCE per repo
  (FORMATS-MIGRATE-ONCE): each ``.claude/rules/rem/<page>.md`` moves to the topic page ``.claude/rules/<page>.md``
  (a page whose topic page exists is refused by name: fold it by hand), then the index, state and config files
  are deleted. ``.claude/memory/`` is never touched. After the move, a moved page keeps only the repo's own hard
  constraints: a statement :mod:`dev_lab.dev.rules` holds is cited by its ID, and incident prose moves to the
  memory entry it cites or a ``docs-src/dev/`` page (an edit no program can judge, so the door says it).
* on a machine, an installed rem (:func:`installed`): its Claude Code registry rows, cache and data, its
  ``enabledPlugins`` switch, the ``env`` keys rem read (:data:`SETTINGS_ENV`), and Codex's ``rem@`` config tables
  and cache. The door is ``uninstall --apply``; the authority store under ``~/.claude/rem/`` is the user's data
  and stays. Until a machine runs it, every family repo's own settings turn rem off
  (:data:`dev_lab.dev.claudesettings.DISABLED_PLUGINS`).

The repo refusal is always on (:mod:`dev_lab.dev.famtests.alwayson`, :func:`check`); the ``SessionStart`` notice
(``session-start``) names both doors where the session starts.

``python -m dev_lab.dev.remretired {check | migrate [--apply] | uninstall [--apply] | session-start}``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from lab_commons.launch import run
from lab_commons.log import emit

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    'MIGRATE_DOOR',
    'REPO_LEFTOVERS',
    'RULE_ID',
    'SETTINGS_ENV',
    'UNINSTALL_DOOR',
    'check',
    'installed',
    'leftovers',
    'main',
    'migrate',
    'uninstall',
]

RULE_ID: Final = 'REM-RETIRED'
MIGRATE_DOOR: Final = 'python -m dev_lab.dev.remretired migrate --apply'
UNINSTALL_DOOR: Final = 'python -m dev_lab.dev.remretired uninstall --apply'
#: A retired file or directory, relative to a ``.claude/`` directory -> what it was.
REPO_LEFTOVERS: Final = {
    'rules/rem': 'rem`s crystallized rules: folded into the topic pages under .claude/rules/',
    'memory-index.md': 'rem`s derived memory index: memory is searched by reading the files',
    '.rem-state.json': 'rem`s session state (bindings, the forced end-of-session pass)',
    'rem.json': 'rem`s config: the backlog is the issue tracker and needs no file',
}
#: The user-settings ``env`` keys rem read: the machine home and the forge door it was handed.
SETTINGS_ENV: Final = ('LAB_COMMONS_HOME', 'REM_FORGE')
_PLUGIN: Final = 'rem'
_CODEX_TABLE: Final = re.compile(r'^\s*\[\[?\s*[^\]]*"rem@[^"]*"')
_TABLE: Final = re.compile(r'^\s*\[')
_GIT: Final = shutil.which('git') or 'git'


def _claude_dirs(root: Path) -> list[Path]:
    """The root's ``.claude/`` and every scope's: a directory holding a tracked ``.claude/`` path."""
    out = run(
        [_GIT, '-c', 'core.quotepath=off', 'ls-files', '-z', '--', ':(glob)**/.claude/**'],
        cwd=root,
        capture_output=True,
        check=False,
        timeout=60,
    )
    found = {root / '.claude'}
    for name in out.stdout.decode('utf-8', 'replace').split('\0') if out.returncode == 0 else ():
        if '/.claude/' in f'/{name}':
            found.add(root / f'/{name}'.split('/.claude/', 1)[0].lstrip('/') / '.claude')
    return sorted(found)


def leftovers(root: Path) -> list[str]:
    """Every retired rem file or directory under *root*, repo-relative POSIX, sorted."""
    root = root.resolve()
    hits = [
        (claude / name).relative_to(root).as_posix()
        for claude in _claude_dirs(root)
        for name in REPO_LEFTOVERS
        if (claude / name).exists()
    ]
    return sorted(hits)


def _what(rel: str) -> str:
    return next(what for name, what in REPO_LEFTOVERS.items() if rel.endswith(f'.claude/{name}'))


def check(root: Path) -> None:
    """Raise naming every leftover and the migration door; silent when the repo holds none."""
    if found := leftovers(root):
        lines = [f'{rel} ({_what(rel)})' for rel in found]
        msg = '\n  '.join((f'{RULE_ID}: the rem plugin is retired (user, 2026-11-23); run `{MIGRATE_DOOR}`:', *lines))
        raise AssertionError(msg)


def migrate(root: Path, *, apply: bool) -> tuple[list[str], list[str]]:
    """The one-time repo migration: (what it did or would do, what it refuses and leaves for a hand fold)."""
    root = root.resolve()
    done: list[str] = []
    refused: list[str] = []
    verb = 'moved' if apply else 'would move'
    for rel in leftovers(root):
        path = root / rel
        if rel.endswith('rules/rem'):
            for page in sorted(path.glob('*.md')):
                topic = path.parent / page.name
                if topic.exists():
                    refused.append(
                        f'{page.relative_to(root).as_posix()}: its topic page {page.name} exists -- fold it by hand'
                    )
                    continue
                if apply:
                    page.replace(topic)
                done.append(f'{page.relative_to(root).as_posix()}: {verb} to {topic.relative_to(root).as_posix()}')
            if apply and path.is_dir() and not any(path.iterdir()):
                path.rmdir()
            continue
        if apply:
            path.unlink()
        done.append(f'{rel}: {"deleted" if apply else "would delete"}')
    if any('rules/rem/' in line for line in done):
        done.append(
            'now cut each moved page to the repo`s own hard constraints: a statement dev_lab.dev.rules holds is '
            'cited by its ID; incident prose moves to the memory entry it cites or a docs-src/dev/ page'
        )
    return done, refused


def _claude_config() -> Path:
    return Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude')


def _codex_home() -> Path:
    return Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')


def _json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _is_rem(key: object) -> bool:
    return isinstance(key, str) and key.split('@', 1)[0] == _PLUGIN and '@' in key


def _codex_kept(text: str) -> tuple[str, int]:
    """*text* without its ``rem@`` tables; the number of tables dropped."""
    kept: list[str] = []
    dropping, dropped = False, 0
    for line in text.splitlines(keepends=True):
        if _TABLE.match(line):
            dropping = bool(_CODEX_TABLE.match(line))
            dropped += dropping
        if not dropping:
            kept.append(line)
    return ''.join(kept), dropped


def _plugin_dirs(base: Path) -> list[Path]:
    cache = [market / _PLUGIN for market in sorted((base / 'cache').glob('*')) if (market / _PLUGIN).is_dir()]
    data = [p for p in sorted((base / 'data').glob(f'{_PLUGIN}-*')) if p.is_dir()]
    return cache + data


def installed(claude: Path | None = None, codex: Path | None = None) -> list[str]:
    """Every footprint of an installed rem on this machine, one line each; empty when none."""
    claude, codex = claude or _claude_config(), codex or _codex_home()
    out: list[str] = []
    registry = claude / 'plugins' / 'installed_plugins.json'
    out += [f'{registry}: {key}' for key in (_json(registry).get('plugins') or {}) if _is_rem(key)]
    settings = _json(claude / 'settings.json')
    out += [
        f'{claude / "settings.json"}: enabledPlugins {k}' for k in settings.get('enabledPlugins') or {} if _is_rem(k)
    ]
    out += [f'{claude / "settings.json"}: env {k}' for k in SETTINGS_ENV if k in (settings.get('env') or {})]
    out += [str(path) for path in (*_plugin_dirs(claude / 'plugins'), *_plugin_dirs(codex / 'plugins'))]
    config = codex / 'config.toml'
    if config.is_file() and _codex_kept(config.read_text(encoding='utf-8'))[1]:
        out.append(f'{config}: rem@ tables')
    return out


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')


def uninstall(claude: Path | None = None, codex: Path | None = None, *, apply: bool) -> list[str]:
    """Remove every footprint :func:`installed` names (*apply*), else only name them; returns the lines."""
    claude, codex = claude or _claude_config(), codex or _codex_home()
    found = installed(claude, codex)
    if not apply or not found:
        return found
    registry = claude / 'plugins' / 'installed_plugins.json'
    if (data := _json(registry)).get('plugins'):
        data['plugins'] = {k: v for k, v in data['plugins'].items() if not _is_rem(k)}
        _write_json(registry, data)
    settings_path = claude / 'settings.json'
    if settings := _json(settings_path):
        if isinstance(settings.get('enabledPlugins'), dict):
            settings['enabledPlugins'] = {k: v for k, v in settings['enabledPlugins'].items() if not _is_rem(k)}
        if isinstance(settings.get('env'), dict):
            settings['env'] = {k: v for k, v in settings['env'].items() if k not in SETTINGS_ENV}
        _write_json(settings_path, settings)
    for path in (*_plugin_dirs(claude / 'plugins'), *_plugin_dirs(codex / 'plugins')):
        shutil.rmtree(path)
    config = codex / 'config.toml'
    if config.is_file():
        kept, dropped = _codex_kept(config.read_text(encoding='utf-8'))
        if dropped:
            config.write_text(kept, encoding='utf-8', newline='')
    return [f'removed {line}' for line in found]


def _notice(root: Path) -> str:
    lines: list[str] = []
    if found := leftovers(root):
        lines.append(f'{RULE_ID}: this repo still holds rem files ({", ".join(found)}); run `{MIGRATE_DOOR}`.')
    if installed():
        lines.append(f'{RULE_ID}: rem is still installed on this machine; run `{UNINSTALL_DOOR}`.')
    return '\n'.join(lines)


def _session_root() -> Path:
    try:
        payload = json.loads(sys.stdin.read() or '{}')
    except ValueError:
        payload = {}
    cwd = payload.get('cwd') if isinstance(payload, dict) else None
    return Path(os.environ.get('CLAUDE_PROJECT_DIR') or cwd or Path.cwd())


def main(argv: Sequence[str] | None = None) -> int:
    """The CLI: ``check`` exits 1 on a leftover; ``migrate``/``uninstall`` exit 1 while anything stays."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.remretired', description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, default=None, help='the repo (default: the cwd)')
    verbs = parser.add_subparsers(dest='verb', required=True)
    verbs.add_parser('check', help='refuse a repo holding rem files')
    for verb in ('migrate', 'uninstall'):
        verbs.add_parser(verb).add_argument('--apply', action='store_true', help='act; without it only report')
    verbs.add_parser('session-start', help='the SessionStart notice; always 0')
    args = parser.parse_args(argv)
    if args.verb == 'session-start':
        if said := _notice(args.root or _session_root()):
            emit(said)
        return 0
    root = (args.root or Path.cwd()).resolve()
    if args.verb == 'check':
        try:
            check(root)
        except AssertionError as refused:
            emit(refused, err=True)
            return 1
        return 0
    if args.verb == 'migrate':
        done, refused = migrate(root, apply=args.apply)
        emit('\n'.join(done) or 'no rem files: nothing to migrate')
        if refused:
            emit('\n'.join(refused), err=True)
        return 1 if refused or (done and not args.apply) else 0
    lines = uninstall(apply=args.apply)
    emit('\n'.join(lines) or 'rem is not installed on this machine')
    return 1 if lines and not args.apply else 0


if __name__ == '__main__':
    raise SystemExit(main())
