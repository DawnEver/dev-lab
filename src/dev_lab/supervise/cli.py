"""The three verbs a supervisor is driven by: check once, serve, or summarise a day.

CHECK IS THE ONE THAT RUNS UNDER A TIMER. ``serve`` is for a host that keeps a daemon and lets the
service manager restart it; ``check`` is for a host that would rather use a systemd timer, which
this family already does elsewhere. Both call the same cycle, so a timer and a daemon cannot drift
into running different things -- the defect the predecessor had, where the daemon and the AI loop
each carried their own copy of the remedy chain.

NOTHING IS PRINTED DIRECTLY. Every line goes through :func:`lab_commons.log.emit`, which is the
kit's one sanctioned console writer and the only place that decides an encoding.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from lab_commons.log import emit

from dev_lab.supervise.component import Registry, load_components
from dev_lab.supervise.components import COMPONENTS
from dev_lab.supervise.config import load_config
from dev_lab.supervise.daemon import Definition, Loop, definition_signature, serve
from dev_lab.supervise.loop import CycleResult, run_cycle
from dev_lab.supervise.policy import now
from dev_lab.supervise.process import manager_for
from dev_lab.supervise.report import digest, record, summary
from dev_lab.supervise.state import StateStore

__all__ = ['build_registry', 'main']

#: The journal a day's cycle records are appended to, relative to the target.
JOURNAL: Final = 'output/supervise/cycles.jsonl'

#: How large the journal may grow before it is rewritten down to its newest records, and how many
#: of those to keep. Four megabytes is roughly two months of five-minute cycles; five thousand
#: records is a bit over two weeks, which is what a digest is ever asked about.
JOURNAL_MAX_BYTES: Final = 4 * 1024 * 1024
JOURNAL_KEPT: Final = 5000


def build_registry(config: dict[str, Any]) -> Registry:
    """Assemble the registry a configuration describes.

    The shipped roster is registered first, then the target's. A target component sharing a
    shipped name REPLACES it, and the replacement is explicit rather than a load-order accident.
    Project components are named by ``project.components`` and read from that module's declared
    ``COMPONENTS`` list, so what a target contributes is something it states rather than something
    a directory walk happened to find.

    Args:
        config: the merged configuration.

    Returns:
        The registry, configured and ready.

    """
    registry = Registry()
    for component in COMPONENTS:
        registry.register(component)
    dotted = str(config.get('project', {}).get('components', '') or '')
    if dotted:
        for component in load_components(dotted):
            # A target MAY replace a shipped component by declaring one under the same name. The
            # replacement is explicit -- the name is dropped first -- rather than the silent
            # last-writer-wins the predecessor used, where which probe ran depended on load order.
            if registry.get(component.name) is not None:
                del registry.components[component.name]
            registry.register(component)
    sections = config.get('components', {})
    registry.configure({name: section for name, section in sections.items() if isinstance(section, dict)})
    remedies = config.get('remedies', {})
    registry.set_remedies({kind: chain for kind, chain in remedies.items() if isinstance(chain, list)})
    return registry


def _context(args: argparse.Namespace) -> tuple[dict[str, Any], Registry, StateStore, Path]:
    """Read the configuration, build the registry, and locate the state.

    Args:
        args: the parsed command line.

    Returns:
        The configuration, the registry, the state store and the target directory.

    """
    project = Path(args.project).resolve()
    config = load_config(Path(args.config) if args.config else project / 'config' / 'supervise.toml')
    registry = build_registry(config)
    state_path = Path(str(config.get('state', {}).get('file', '') or project / 'output' / 'supervise' / 'state.json'))
    return config, registry, StateStore(state_path), project


def _journal(project: Path) -> Path:
    """Return the path a day's cycle records are appended to.

    Args:
        project: the target's directory.

    Returns:
        The journal path.

    """
    return project / JOURNAL


def _append_bounded(path: Path, line: str) -> None:
    """Append *line*, and keep the file from growing without bound.

    THE ONLY THING IN THIS PACKAGE WHOSE SIZE IS A FUNCTION OF UPTIME. A daemon writes one record
    per cycle, forever -- about 2 MB a month at a five-minute interval, which is small on a 40 GB
    disk and unbounded all the same. The state module's own docstring names its predecessor's
    growing log ring as one of the defects it exists to fix, and this file had no ring at all.

    `_read_journal` reads it whole, so an unbounded journal is also an unbounded allocation in the
    daily digest -- on a host whose whole discipline is about what a process may allocate.

    The rewrite is a plain write rather than a staged publish, which is the one place in this
    package that is true: a crash in the middle of it loses a CONVENIENCE LOG, and the alternative
    costs an atomic publish on every cycle for a file nothing depends on.

    Args:
        path: the journal.
        line: the record, newline included.

    """
    with path.open('a', encoding='utf-8') as handle:
        handle.write(line)
    if path.stat().st_size <= JOURNAL_MAX_BYTES:
        return
    kept = path.read_text(encoding='utf-8').splitlines()[-JOURNAL_KEPT:]
    path.write_text('\n'.join(kept) + '\n', encoding='utf-8')


def _read_journal(path: Path) -> list[dict[str, Any]]:
    """Read back the records a run of cycles appended.

    An unreadable or half-written line is skipped rather than fatal: the digest is a convenience
    built on a log, and a log that cannot be parsed in full is still mostly true.

    Args:
        path: the journal.

    Returns:
        The records, in the order they were written.

    """
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            entries.append(parsed)
    return entries


def _definition(project: Path, config: dict[str, Any]) -> Definition:
    """Return the signature this daemon re-takes every cycle, built from its own config.

    The list is a DEPLOYMENT's fact and not the kit's: which files are part of a given supervisor's
    definition depends on which unit starts it and what that unit reads. The kit's own version is
    always part of the signature and is not configurable -- it is the one ingredient no config can
    know about, because it changes when a deployment upgrades the kit under a running process.

    Args:
        project: the target's directory, which the configured paths are relative to.
        config: the merged configuration.

    Returns:
        A callable re-taking the signature from disk.

    """
    paths = tuple(str(one) for one in (config.get('daemon', {}) or {}).get('definition', ()))
    return lambda: definition_signature(project, paths)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one of the supervisor's verbs.

    Args:
        argv: the arguments, or None to read the process's.

    Returns:
        0 on success, 1 when a cycle found something wrong, 2 for a usage error.

    """
    parser = argparse.ArgumentParser(prog='python -m dev_lab.supervise')
    parser.add_argument('verb', choices=('check', 'serve', 'digest'))
    parser.add_argument('--project', default='.', help="the target's directory")
    parser.add_argument('--config', default='', help='the configuration file, when it is not under the target')
    parser.add_argument('--dry-run', action='store_true', help='resolve and gate, but act on nothing')
    args = parser.parse_args(argv)

    config, registry, store, project = _context(args)
    if args.verb == 'digest':
        emit(digest(_read_journal(_journal(project))))
        return 0

    manager = manager_for(str(config.get('process', {}).get('manager', 'systemd')))
    if args.verb == 'check':
        result = run_cycle(registry, store, config, project, manager, clock=now(), dry_run=args.dry_run)
        emit(summary(result))
        return 0 if result.status == 'healthy' else 1

    loop = Loop(
        registry=registry,
        store=store,
        config=config,
        project=project,
        manager=manager,
        definition=_definition(project, config),
    )
    journal = _journal(project)
    journal.parent.mkdir(parents=True, exist_ok=True)

    def append(result: CycleResult, at: datetime) -> None:
        _append_bounded(journal, json.dumps(record(result, at)) + '\n')

    degraded = serve(loop, on_cycle=append)
    return 0 if degraded == 0 else 1
