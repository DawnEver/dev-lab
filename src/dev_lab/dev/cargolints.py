"""RUST-LINTS: every Rust workspace holds the family ``[workspace.lints]`` and every member crate inherits it.

The base is :mod:`dev_lab.dev._famconfig_cargo_rows` (``[workspace.lints.rust]`` and ``[workspace.lints.clippy]``),
judged through the section mechanism (:func:`dev_lab.dev.famconfig.inspect_section`): an owned key missing or set
to another level is drift, refused by name. A member crate without ``[lints] workspace = true`` is refused too --
the workspace table is otherwise read by nobody. A workspace is every tracked ``Cargo.toml`` holding ``[workspace]``;
a repo with none is not judged and says so. ``verify`` runs this as a lint step; ``--write`` renders the base into
each workspace manifest (:func:`dev_lab.dev.sectionrender.render_section`) and adds the member opt-in.

Exit codes follow :func:`dev_lab.dev.reports.read_lint`: ``0`` clean, ``1`` refused (printed), ``2`` unreadable.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path, PurePosixPath
from typing import IO, Final

import tomlkit

from dev_lab.dev.famconfig import CARGO_SECTIONS, SectionDelta, inspect_section
from dev_lab.dev.rules import tracked_files
from dev_lab.dev.sectionrender import render_section

__all__ = ['CLEAN', 'ERRORED', 'FOUND', 'RULE_ID', 'check', 'main', 'problems', 'workspaces']

RULE_ID: Final = 'RUST-LINTS'
CLEAN: Final = 0
FOUND: Final = 1
ERRORED: Final = 2
_MANIFEST: Final = 'Cargo.toml'
_DOOR: Final = 'python -m dev_lab.dev.cargolints --write renders the family base and the member opt-in'
_DETAILS: Final = 'details: docs-src/dev/refusals.md#rust-lints (dev-lab)'


def workspaces(root: Path, files: list[str]) -> list[str]:
    """The repo-relative workspace manifests among *files* (each a ``Cargo.toml`` holding ``[workspace]``)."""
    manifests = [rel for rel in sorted(files) if PurePosixPath(rel).name == _MANIFEST]
    return [rel for rel in manifests if 'workspace' in tomllib.loads((root / rel).read_text('utf-8'))]


def _members(root: Path, manifest: str) -> list[str]:
    """The member manifests a workspace names (globs expanded), plus its own when it is also a package."""
    directory = (root / manifest).parent
    data = tomllib.loads((root / manifest).read_text(encoding='utf-8'))
    found = [manifest] if 'package' in data else []
    for pattern in data['workspace'].get('members', []):
        found += [
            (member / _MANIFEST).relative_to(root).as_posix()
            for member in sorted(directory.glob(pattern))
            if (member / _MANIFEST).is_file()
        ]
    return found


def _inherits(root: Path, member: str) -> bool:
    lints = tomllib.loads((root / member).read_text(encoding='utf-8')).get('lints', {})
    return isinstance(lints, dict) and lints.get('workspace') is True


def problems(root: Path, files: list[str]) -> list[str]:
    """Every drift from the base and every member not inheriting it, across *root*'s workspaces."""
    out: list[str] = []
    for manifest in workspaces(root, files):
        for name, base in sorted(CARGO_SECTIONS.items()):
            report = inspect_section(
                root / manifest, base, SectionDelta(repo=root.name, added={}, dropped={}, ceiling=0)
            )
            if not report.ok:
                out.append(f'{manifest}: {name} is {report.status} -- {"; ".join(report.offending) or report.detail}')
        out += [
            f'{member}: no [lints] workspace = true, so the family lints in {manifest} do not reach it'
            for member in _members(root, manifest)
            if not _inherits(root, member)
        ]
    return out


def _write(root: Path, files: list[str]) -> None:
    for manifest in workspaces(root, files):
        for base in CARGO_SECTIONS.values():
            render_section(root / manifest, base)
        for member in _members(root, manifest):
            document = tomlkit.parse((root / member).read_text(encoding='utf-8'))
            lints = document.setdefault('lints', tomlkit.table())
            lints['workspace'] = True
            (root / member).write_text(tomlkit.dumps(document), encoding='utf-8', newline='')


def check(root: Path, *, handle: IO[str], write: bool = False, files: list[str] | None = None) -> int:
    """Judge (or with *write*, render) *root*'s workspaces; ``CLEAN``, ``FOUND`` or ``ERRORED``."""
    listed = files if files is not None else [f for f in tracked_files(root) if (root / f).is_file()]
    try:
        if not workspaces(root, listed):
            handle.write(f'{RULE_ID}: {root.name} holds no Rust workspace, so no lints are judged\n')
            return CLEAN
        if write:
            _write(root, listed)
        found = problems(root, listed)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        handle.write(f'{RULE_ID}: a manifest could not be read ({exc})\n')
        return ERRORED
    if not found:
        handle.write(f'{RULE_ID}: every workspace holds the family lints and every member inherits them\n')
        return CLEAN
    handle.write('\n'.join([f'{RULE_ID}: {len(found)} refusal(s)', *found, f'door: {_DOOR}', _DETAILS]) + '\n')
    return FOUND


def main(argv: list[str] | None = None) -> int:
    """Judge the checkout at the working directory; ``--write`` renders first."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.cargolints', description=__doc__.splitlines()[0])
    parser.add_argument('--write', action='store_true', help='render the base and the member opt-in, then judge')
    parsed = parser.parse_args(argv)
    return check(Path.cwd(), handle=sys.stdout, write=parsed.write)


if __name__ == '__main__':
    raise SystemExit(main())
