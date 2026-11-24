"""A REPO'S DOCUMENTATION SITE AS DATA: ``python -m dev_lab.dev.docrows [--root ROOT] [--out DIR] [--serve]``.

:mod:`dev_lab.dev.docsite` is the driver (a requirement, a skip that is announced, a checked and bounded
subprocess, the portal); it took :class:`~dev_lab.dev.docsite.SubSite` rows that each repo built in its own
Python. Those builders were the same four everywhere -- pdoc over a package, rustdoc over a Cargo workspace, a
markdown tree, the licence notice -- so they live here once, and a repo declares only ROWS::

    [tool.dev_lab.docsite]
    title = "Example"                              # the portal's title
    out = "docs"                                   # optional, the default output root
    logo = "https://..."; favicon = "https://..."  # optional

    [[tool.dev_lab.docsite.sites]]
    slug = "python"; title = "Python API"; kind = "pdoc"; modules = ["example"]
    options = { edit_url = "example=https://...", logo_link = "https://..." }   # pdoc_argv's keywords
    [[tool.dev_lab.docsite.sites]]
    slug = "rust"; title = "Rust crates"; kind = "cargo"; workspace = "rust"
    exclude = { some_crate = "why rustdoc cannot document it" }
    [[tool.dev_lab.docsite.sites]]
    slug = "guide"; title = "Guide"; kind = "markdown"; source = "docs-src"
    [[tool.dev_lab.docsite.sites]]
    slug = "family"; title = "Shared mechanism"; kind = "markdown"; sibling = "dev-lab"; source = "docs-src"
    [[tool.dev_lab.docsite.sites]]
    slug = "notices"; title = "Legal notices"; kind = "notices"   # reads [tool.dev_lab.notices]

Every row may carry ``blurb`` and ``absent_means`` (what a reader loses when its requirement is unmet). A
``sibling`` markdown source is read beside the MAIN checkout (:func:`dev_lab.dev.familyroot.family_root`), never
``<checkout>/..``, which is wrong in a worktree. The version is the installed distribution's.
"""

from __future__ import annotations

import argparse
import html
import importlib.metadata as imd
import re
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from lab_commons.log import emit

from dev_lab.dev import notices
from dev_lab.dev.docsite import (
    BuildReport,
    Every,
    Exe,
    Module,
    Requirement,
    SubSite,
    Tree,
    build_all,
    open_site,
    pdoc_site,
    run,
)
from dev_lab.dev.familyroot import family_root

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

__all__ = ['KINDS', 'SiteData', 'build', 'main', 'site_data', 'subsites']

#: Every row kind and the builder it names.
KINDS: Final = ('pdoc', 'cargo', 'markdown', 'notices')

#: A relative ``href="...md"`` the renderer produced; an external ``.md`` URL is never rewritten.
_MD_LINK: Final = re.compile(r'(href="(?!\w+:)(?!//)[^"]+?)\.md(["#])')


@dataclass(frozen=True)
class SiteData:
    """``[tool.dev_lab.docsite]``: the portal's facts and its rows, as declared."""

    title: str
    rows: tuple[Mapping[str, Any], ...]
    out: str = 'docs'
    logo: str | None = None
    favicon: str | None = None


def site_data(root: Path) -> SiteData:
    """*root*'s declared site.

    Raises:
        ValueError: the table is absent, lacks a title, or a row lacks ``slug``/``title`` or names no known kind.

    """
    manifest = root / 'pyproject.toml'
    table = tomllib.loads(manifest.read_text(encoding='utf-8')).get('tool', {}).get('dev_lab', {}).get('docsite')
    if not isinstance(table, dict) or not table.get('title'):
        msg = f'{manifest} declares no [tool.dev_lab.docsite] title: declare the site (see dev_lab.dev.docrows)'
        raise ValueError(msg)
    rows = tuple(table.get('sites', ()))
    for row in rows:
        if not row.get('slug') or not row.get('title') or row.get('kind') not in KINDS:
            msg = f'[[tool.dev_lab.docsite.sites]] row {row!r} in {manifest}: needs slug, title and kind in {KINDS}'
            raise ValueError(msg)
    return SiteData(
        title=table['title'],
        rows=rows,
        out=table.get('out', 'docs'),
        logo=table.get('logo'),
        favicon=table.get('favicon'),
    )


def _markdown_tree(source: Path, out_dir: Path, *, title: str) -> None:
    """Render every ``*.md`` under *source* to HTML under *out_dir*, the tree's shape kept, ``.md`` links rewritten."""
    pages = sorted(source.rglob('*.md'))
    if not pages:
        msg = f'{source} contains no .md files -- an empty render is not a successful one'
        raise FileNotFoundError(msg)
    from markdown_it import MarkdownIt  # noqa: PLC0415 -- an optional docs dependency, gated by Module('markdown_it')

    md = MarkdownIt('commonmark', {'html': True, 'linkify': True}).enable('table')
    for page in pages:
        rel = page.relative_to(source)
        target = out_dir / rel.with_suffix('.html')
        target.parent.mkdir(parents=True, exist_ok=True)
        body = _MD_LINK.sub(lambda m: f'{m.group(1)}.html{m.group(2)}', md.render(page.read_text(encoding='utf-8')))
        up = '../' * (len(rel.parts) - 1)
        target.write_text(
            f'<!doctype html>\n<html lang="en">\n<head><meta charset="utf-8">\n'
            f'<title>{html.escape(rel.as_posix())} - {html.escape(title)}</title></head>\n<body>\n'
            f'<p><a href="{up}../index.html">&larr; {html.escape(title)} docs</a></p>\n{body}\n</body>\n</html>\n',
            encoding='utf-8',
        )
    if not (out_dir / 'index.html').is_file():
        hrefs = [(p.relative_to(source).with_suffix('.html').as_posix(), p.stem) for p in pages]
        listing = '\n'.join(f'<li><a href="{href}">{name}</a></li>' for href, name in hrefs)
        (out_dir / 'index.html').write_text(
            f'<!doctype html>\n<html lang="en">\n<body>\n<ul>\n{listing}\n</ul>\n</body>\n</html>\n', encoding='utf-8'
        )


def _members(workspace: Path) -> list[str]:
    """Every workspace member's PACKAGE name (what ``cargo doc -p`` takes), read from the manifests."""
    manifest = tomllib.loads((workspace / 'Cargo.toml').read_text(encoding='utf-8'))
    names = []
    for member in manifest.get('workspace', {}).get('members', []):
        member_manifest = workspace / member / 'Cargo.toml'
        if member_manifest.is_file():
            name = tomllib.loads(member_manifest.read_text(encoding='utf-8')).get('package', {}).get('name')
            names.extend([str(name)] if name else [])
    return sorted(names)


def _cargo(workspace: Path, excluded: Mapping[str, str], out_dir: Path) -> None:
    """``cargo doc --no-deps -p`` each documentable member, copied (only this build's crates) under *out_dir*."""
    crates = [crate for crate in _members(workspace) if crate not in excluded]
    if not crates:
        msg = f'no documentable workspace members in {workspace / "Cargo.toml"}'
        raise FileNotFoundError(msg)
    run(['cargo', 'doc', '--no-deps', *(arg for crate in crates for arg in ('-p', crate))], cwd=workspace)
    generated = workspace / 'target' / 'doc'
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(generated, out_dir, ignore=shutil.ignore_patterns('index.html', *excluded))
    links = '\n'.join(f'<li><a href="{crate}/index.html">{crate}</a></li>' for crate in crates)
    (out_dir / 'index.html').write_text(
        f'<!doctype html>\n<html lang="en">\n<body>\n<h1>Rust crates</h1>\n<ul>\n{links}\n</ul>\n</body>\n</html>\n',
        encoding='utf-8',
    )


def _row(root: Path, row: Mapping[str, Any], title: str) -> tuple[Requirement, Callable[[Path, Path], None], str]:
    """The requirement, the builder and the default ``absent_means`` of one declared row."""
    kind = row['kind']
    if kind == 'pdoc':
        modules, options = list(row.get('modules', ())), dict(row.get('options', {}))
        return Module('pdoc'), lambda r, out: pdoc_site(r, out, modules, **options), 'the Python API reference'
    if kind == 'cargo':
        workspace, excluded = root / row.get('workspace', '.'), dict(row.get('exclude', {}))
        return Exe('cargo'), lambda _r, out: _cargo(workspace, excluded, out), 'the Rust crate docs'
    if kind == 'markdown':
        base = family_root(root) / row['sibling'] if row.get('sibling') else root
        source = base / row.get('source', 'docs-src')
        need = Every((Module('markdown_it'), Tree(str(source))))
        return need, lambda _r, out: _markdown_tree(source, out, title=title), f'the pages under {source}'
    data = notices.notice_data(root)

    def notice(r: Path, out: Path) -> None:
        notices.build_notices(r, out, data)

    need = Exe('cargo') if data.cargo_manifest else Module('importlib.metadata')
    return need, notice, 'the third-party licence notice'


def subsites(root: Path, data: SiteData) -> tuple[SubSite, ...]:
    """The declared rows as the driver's :class:`~dev_lab.dev.docsite.SubSite` table, in declared order."""
    sites = []
    for row in data.rows:
        need, builder, loses = _row(root, row, data.title)
        sites.append(
            SubSite(
                slug=row['slug'],
                title=row['title'],
                requires=need,
                absent_means=row.get('absent_means', loses),
                build=builder,
                blurb=row.get('blurb', ''),
            )
        )
    return tuple(sites)


def _version(root: Path) -> str:
    project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8')).get('project', {})
    try:
        return imd.version(project.get('name', ''))
    except imd.PackageNotFoundError:
        return str(project.get('version', ''))


def build(root: Path, out_root: Path | None = None) -> BuildReport:
    """Build *root*'s declared site into *out_root* (default: its declared ``out``)."""
    data = site_data(root)
    return build_all(
        subsites(root, data),
        root,
        out_root or root / data.out,
        title=data.title,
        version=_version(root),
        logo=data.logo,
        favicon=data.favicon,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Build the site; exit 0 with the report, 1 with a named refusal."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.docrows', description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='the checkout (default: cwd)')
    parser.add_argument('--out', type=Path, default=None, help='output root (default: the declared out)')
    parser.add_argument('--serve', action='store_true', help='open the portal in a browser afterwards')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        report = build(root, args.out)
    except (ValueError, notices.UnknownLicense, FileNotFoundError) as why:
        emit(f'docrows: refused -- {why}', err=True)
        return 1
    emit(report.summary())
    if args.serve:
        open_site((args.out or root / site_data(root).out) / 'index.html')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
