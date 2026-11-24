"""THE RUST SIDE OF DEPENDENCY FRESHNESS: ``python -m dev_lab.dev.cratefresh [--root ROOT] [--json]``.

The Python side is :mod:`dev_lab.dev.locklag` (how far a pinned family sha trails its branch); this asks the same
question of crates: is a newer release out that the DECLARED spec cannot reach? Deliberately narrow -- a lock that
trails INSIDE the range is local staleness ``cargo update`` fixes; what no clone fixes is a spec whose range ends
below the newest release. For a 0.x crate Cargo's caret makes the MINOR the breaking slot, so ``0.29`` refuses
``0.30`` -- an upper bound nobody decided to add (:func:`allows`).

A REPORT, NOT A GATE: it asks crates.io (``cargo search``, through the family retry door
:func:`dev_lab.dev.netverb.run_network_verb`), and a network call inside a verdict makes it depend on somebody
else's uptime. EXIT CODES: 0 nothing stale; 1 something is (named); 2 the index could not answer for some crate --
NOT the same answer as "fresh", so never folded into it.

Every ``Cargo.toml`` under the checkout (outside ``target``) is read; a crate declared at two specs reports the
LOWER, since any manifest holding it back is enough.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev.netverb import run_network_verb

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = ['allows', 'declared_crates', 'latest_stable', 'main', 'survey']

_SEARCH_TIMEOUT_S: Final = 60.0
_SKIPPED: Final = frozenset({'target', '.git', '.venv', 'node_modules'})


def _parts(spec: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r'\d+', spec)) or (0,)


def declared_crates(root: Path) -> dict[str, str]:
    """``{crate: version spec}`` across every ``Cargo.toml`` under *root*; path/git dependencies have none."""
    out: dict[str, str] = {}
    for manifest in sorted(root.rglob('Cargo.toml')):
        if _SKIPPED & set(manifest.relative_to(root).parts):
            continue
        data = tomllib.loads(manifest.read_text(encoding='utf-8'))
        tables = (
            data.get('dependencies') or {},
            data.get('build-dependencies') or {},
            data.get('dev-dependencies') or {},
            (data.get('workspace') or {}).get('dependencies') or {},
        )
        for table in tables:
            for crate, spec in table.items():
                version = spec if isinstance(spec, str) else (spec or {}).get('version')
                if version:
                    out[crate] = min(out.get(crate, str(version)), str(version), key=_parts)
    return out


def allows(spec: str, version: str) -> bool:
    """Whether Cargo's CARET semantics let *spec* resolve to *version* (0.x: the minor is the breaking slot)."""
    want, have = _parts(version), _parts(spec.lstrip('^').strip())
    if have[0] != 0:
        return want[0] == have[0] and want >= have
    if len(have) == 1:
        return want[0] == 0
    return want[:2] == have[:2] and want >= have


def _cargo_search(crate: str) -> str:
    cargo = shutil.which('cargo')
    if not cargo:
        msg = 'cargo is not on PATH: install a Rust toolchain to ask crates.io'
        raise OSError(msg)
    report = run_network_verb([cargo, 'search', crate, '--limit', '1'], timeout=_SEARCH_TIMEOUT_S)
    if not report.ok:
        msg = f'cargo search {crate}: {report.diagnosis.name.lower()} after {report.attempt_count} attempt(s)'
        raise OSError(msg)
    lines = report.attempts[-1].output.splitlines()
    return lines[0] if lines else ''


def latest_stable(crate: str, *, search: Callable[[str], str] = _cargo_search) -> str:
    """The newest version crates.io offers for *crate*; raises rather than guess.

    Raises:
        ValueError: the first line of ``cargo search`` does not name *crate*.

    """
    line = search(crate)
    match = re.match(rf'^{re.escape(crate)}\s*=\s*"([^"]+)"', line.strip())
    if not match:
        msg = f'cargo search did not name {crate!r} on its first line: {line.strip()[:120]!r}'
        raise ValueError(msg)
    return match.group(1)


def survey(
    crates: dict[str, str], *, fetch: Callable[[str], str] = latest_stable
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    """``(rows, unreachable)``: one row per crate, and the crates the index would not answer for."""
    rows: list[dict[str, object]] = []
    unreachable: list[dict[str, str]] = []
    for crate, spec in sorted(crates.items()):
        try:
            newest = fetch(crate)
        except (OSError, ValueError) as exc:
            unreachable.append({'crate': crate, 'spec': spec, 'error': str(exc)})
            continue
        rows.append({'crate': crate, 'spec': spec, 'latest': newest, 'stale': not allows(spec, newest)})
    return rows, unreachable


def main(argv: Sequence[str] | None = None, *, fetch: Callable[[str], str] = latest_stable) -> int:
    """Report each declared crate against crates.io; the exit code is the module docstring's."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.cratefresh', description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='the checkout to read (default: cwd)')
    parser.add_argument('--json', action='store_true', help='machine-readable output')
    args = parser.parse_args(argv)
    rows, unreachable = survey(declared_crates(args.root), fetch=fetch)
    if args.json:
        emit(json.dumps({'crates': rows, 'unreachable': unreachable}, indent=2))
    else:
        for row in rows:
            flag = '  STALE -- the declared spec cannot reach it' if row['stale'] else ''
            emit(f'{row["crate"]:<20}{row["spec"]:<12}{row["latest"]:<12}{flag}')
        for miss in unreachable:
            emit(f'{miss["crate"]:<20}{miss["spec"]:<12}{"?":<12}  UNREACHABLE: {miss["error"]}')
    if unreachable:
        emit(f'cratefresh: {len(unreachable)} crate(s) could not be checked -- this is not a clean result', err=True)
        return 2
    stale = [row for row in rows if row['stale']]
    if stale:
        names = ', '.join(f'{r["crate"]} {r["spec"]} -> {r["latest"]}' for r in stale)
        emit(
            f'cratefresh: STALE: {names}. Raise the declared spec to take the release; for a 0.x crate the minor '
            'is the breaking slot, and ABI-coupled crates move together in one commit.',
            err=True,
        )
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
