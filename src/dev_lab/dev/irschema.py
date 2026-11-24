"""THE IR SCHEMA DOOR: ``python -m dev_lab.dev.irschema {generate,check,rust,migrate,affected} [--root ROOT]``.

The format is ``docs-src/dev/ir-schema.md``. ``generate`` writes the Python (git-ignored) after refusing a version
bump below the change's class; ``check`` refuses a missing or stale generated file by name, and
:func:`stale_refusal` is the same check as ``verify`` runs it; ``rust --out DIR`` is what a ``build.rs`` calls;
``migrate`` is the one migrate door; ``affected`` names the modules consuming the records a change touched.
:func:`changed_reach` is how ``verify --changed`` widens or narrows a selection by the change's class.

EXIT CODES: 0 done or nothing to do; 1 refused (each refusal printed with its door).
"""

from __future__ import annotations

import argparse
import ast
import shutil
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev import irmigrate, irpython, irrust
from dev_lab.dev.ircheck import load
from dev_lab.dev.irmodel import IRSchemaError
from dev_lab.dev.irversion import Level, at_revision, bump_refusal, classify

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dev_lab.dev.irmodel import IR

__all__ = ['changed_reach', 'consumers', 'main', 'stale', 'stale_refusal']

_GIT: Final = shutil.which('git') or 'git'
_GIT_TIMEOUT_S: Final = 60.0
_GENERATE: Final = 'python -m dev_lab.dev.irschema generate'
#: The path every test's footprint reaches (pytest's configuration): a MAJOR change selects through it.
_EVERYTHING: Final = 'pyproject.toml'


def stale(ir: IR) -> list[str]:
    """One ``IR-STALE-GENERATED`` line per generated file that is missing or whose fingerprint line moved."""
    out = []
    for path, content in irpython.expected_files(ir).items():
        want = content.splitlines()[0]
        have = path.read_text(encoding='utf-8').splitlines()[:1] if path.is_file() else []
        if have != [want]:
            state = 'is missing' if not path.is_file() else 'predates its schema or generator'
            out.append(f'IR-STALE-GENERATED: {path} {state} -- {_GENERATE}')
    return out


def stale_refusal(root: Path) -> str | None:
    """What ``verify`` refuses on: a malformed IR, a missing bump, or a stale generated file; ``None`` otherwise."""
    if not (root / 'pyproject.toml').is_file():
        return None
    try:
        ir = load(root)
    except IRSchemaError as error:
        return str(error)
    if ir is None:
        return None
    lines = [line for line in (bump_refusal(at_revision(root, 'HEAD'), ir),) if line] + stale(ir)
    return '\n'.join(lines) or None


def _tracked_python(root: Path) -> list[str]:
    done = _door.run(
        [_GIT, '-C', str(root), 'ls-files', '-z', '--', '*.py'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=_GIT_TIMEOUT_S,
    )
    return [p for p in done.stdout.split('\0') if p] if done.returncode == 0 else []


def consumers(root: Path, ir: IR, records: frozenset[str]) -> tuple[str, ...]:
    """The tracked modules importing one of *records* (qualified) from its generated module, repo-relative."""
    wanted = {}
    for qualified in records:
        module, name = qualified.split('.')
        wanted.setdefault(f'{ir.declaration.package}._ir_{module}', set()).add(name)
    found = []
    for relative in _tracked_python(root):
        try:
            tree = ast.parse((root / relative).read_text(encoding='utf-8'))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in wanted:
                hit = {alias.name for alias in node.names} & wanted[node.module] or '*' in {a.name for a in node.names}
            elif isinstance(node, ast.Import):
                hit = any(alias.name in wanted for alias in node.names)
            else:
                continue
            if hit:
                found.append(relative)
                break
    return tuple(sorted(found))


def _without_version(text: str) -> dict:
    data = tomllib.loads(text)
    data.get('tool', {}).get('dev_lab', {}).get('ir_schema', {}).pop('version', None)
    return data


def _pyproject_moved_beyond_the_version(root: Path, revision: str) -> bool:
    done = _door.run(
        [_GIT, '-C', str(root), 'show', f'{revision}:pyproject.toml'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=_GIT_TIMEOUT_S,
    )
    now = (root / 'pyproject.toml').read_text(encoding='utf-8')
    return done.returncode != 0 or _without_version(done.stdout) != _without_version(now)


def changed_reach(root: Path, changed: list[str], range_spec: str = '') -> list[str]:
    """*changed*, re-read by the IR change's class.

    PATCH reaches nothing of its own, MINOR reaches the consumers of the touched records, MAJOR reaches everything;
    a version-only ``pyproject.toml`` edit reaches nothing.
    """
    try:
        ir = load(root)
    except IRSchemaError:
        return changed
    if ir is None:
        return changed
    sources = {*ir.declaration.modules.values(), ir.declaration.quantities}
    if not (sources | {_EVERYTHING}) & set(changed):
        return changed
    revision = range_spec.split('..', maxsplit=1)[0] or 'HEAD'
    change = classify(at_revision(root, revision), ir)
    out = [p for p in changed if p != _EVERYTHING or _pyproject_moved_beyond_the_version(root, revision)]
    if change.level == Level.MAJOR:
        return sorted({*out, _EVERYTHING})
    if change.level == Level.MINOR:
        return sorted({*out, *consumers(root, ir, change.records)})
    return out


def _loaded(root: Path) -> IR | None:
    try:
        ir = load(root)
    except IRSchemaError as error:
        emit(str(error), err=True)
        return None
    if ir is None:
        emit(f'irschema: {root} declares no [tool.dev_lab.ir_schema]; nothing to do')
    return ir


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m dev_lab.dev.irschema``; the process exit code."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.irschema', description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='the repo root (default: the current directory)')
    verbs = parser.add_subparsers(dest='verb', required=True)
    verbs.add_parser('generate', help='write the generated Python (git-ignored)')
    verbs.add_parser('check', help='refuse a malformed IR, a missing bump or a stale generated file')
    rust = verbs.add_parser('rust', help='write ir.rs into a build directory (a build.rs calls this)')
    rust.add_argument('--out', type=Path, required=True)
    migrate = verbs.add_parser('migrate', help='rewrite stored records at the current version')
    migrate.add_argument('paths', nargs='+', type=Path)
    affected = verbs.add_parser('affected', help='the change class and the modules consuming the touched records')
    affected.add_argument('--revision', default='HEAD')
    parsed = parser.parse_args(argv)
    root = parsed.root.resolve()
    if parsed.verb == 'check':
        return _report([stale_refusal(root)])
    ir = _loaded(root)
    if ir is None:
        return 0 if (root / 'pyproject.toml').is_file() else 1
    return _VERBS[parsed.verb](root, ir, parsed)


def _report(refusals: list[str | None]) -> int:
    lines = [line for line in refusals if line]
    for line in lines:
        emit(line, err=True)
    return 1 if lines else 0


def _generate(root: Path, ir: IR, _parsed: argparse.Namespace) -> int:
    refused = bump_refusal(at_revision(root, 'HEAD'), ir)
    if refused:
        return _report([refused])
    for path in irpython.write(ir):
        emit(f'irschema: wrote {path}')
    return 0


def _rust(_root: Path, ir: IR, parsed: argparse.Namespace) -> int:
    emit(f'irschema: {irrust.write(ir, parsed.out)}')
    return 0


def _migrate(_root: Path, ir: IR, parsed: argparse.Namespace) -> int:
    return _report([irmigrate.migrate(ir, path) for path in parsed.paths])


def _affected(root: Path, ir: IR, parsed: argparse.Namespace) -> int:
    change = classify(at_revision(root, parsed.revision), ir)
    emit(f'irschema: {change.level.name} -- {"; ".join(change.why) or "no change"}')
    for path in consumers(root, ir, change.records):
        emit(f'  consumer: {path}')
    return 0


_VERBS: Final = {'generate': _generate, 'rust': _rust, 'migrate': _migrate, 'affected': _affected}

if __name__ == '__main__':
    raise SystemExit(main())
