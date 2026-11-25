"""THE THIRD-PARTY LICENSE NOTICE, generated from the installed environment: ``python -m dev_lab.dev.notices``.

WHY THE ENVIRONMENT, NOT A LOCK. A lock carries names and versions but no license text; the installed metadata does,
and PEP 610 ``direct_url.json`` records where each distribution came from, including the transitive closure of git
dependencies -- the installed environment IS the resolved graph whose notice is being built.

WHY A BUILD PRODUCT, NOT A TRACKED FILE. A committed notice is only as current as the last regeneration, and a notice
saying "we comply" while the graph moved is a declaration that lies in a document where the lie is a legal one.

THE COMPLIANCE CHECK. A third-party license that normalizes to no SPDX expression is an ALARM:
:func:`refuse_unknown` raises :class:`UnknownLicense` naming every such package, and the CLI exits non-zero.

A REPO DECLARES ONLY DATA -- the product, never a mechanism::

    [tool.dev_lab.notices]
    entity = "Example Org"                 # the copyright holder
    product = "Example"                    # the product's name in the notice
    in_tree = ["example", "example_native"]  # own distributions, never listed as third party
    cargo_manifest = "rust/Cargo.toml"     # optional: crate licenses from `cargo metadata`
    out = "docs/notices"                   # optional: the default output directory
    [tool.dev_lab.notices.overrides]       # name -> curated SPDX, for metadata too broken to trust
    scipy = "BSD-3-Clause"
    [[tool.dev_lab.notices.vendored]]      # code with no package identity of its own
    name = "x"; author = "y"; license = "MIT"; url = "https://..."; note = "..."

Deterministic: no timestamps, everything sorted, so the output is a fixed point.
"""

from __future__ import annotations

import argparse
import html
import importlib.metadata as imd
import json
import re
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from importlib.metadata import PackageMetadata

__all__ = [
    'NOTICE_BASENAME',
    'UNKNOWN',
    'NoticeData',
    'UnknownLicense',
    'build_notices',
    'git_sources',
    'grouped',
    'main',
    'normalize_license',
    'notice_data',
    'notices_markdown',
    'python_packages',
    'refuse_unknown',
    'rust_crates',
]

#: The generated notice's file name inside its output directory.
NOTICE_BASENAME: Final = 'THIRD_PARTY_NOTICES.md'

#: What an unidentifiable license normalizes to -- an alarm, never a footnote.
UNKNOWN: Final = 'UNKNOWN'

#: Generic raw-license-string -> SPDX, applied after the repo's overrides to the lowercased, space-collapsed string.
_RAW_TO_SPDX: Final[dict[str, str]] = {
    'mit': 'MIT',
    'mit license': 'MIT',
    'mit-0': 'MIT-0',
    'mit-cmu': 'MIT-CMU',
    'apache software license': 'Apache-2.0',
    'apache 2.0': 'Apache-2.0',
    'apache-2.0': 'Apache-2.0',
    'bsd': 'BSD-3-Clause',
    'bsd license': 'BSD-3-Clause',
    'bsd-2-clause': 'BSD-2-Clause',
    'bsd-3-clause': 'BSD-3-Clause',
    '3-clause bsd license': 'BSD-3-Clause',
    'psf': 'PSF-2.0',
    'psf-2.0': 'PSF-2.0',
    'mpl-2.0': 'MPL-2.0',
    'gplv2+': 'GPL-2.0-or-later',
    'gpl-2.0-only': 'GPL-2.0-only',
    'lgpl-3.0': 'LGPL-3.0',
    'lgpl-3.0-or-later': 'LGPL-3.0-or-later',
    'mit/apache-2.0': 'MIT OR Apache-2.0',  # Cargo's pre-SPDX slash spelling of a dual license
}
_EXPRESSION: Final = re.compile(r'^[A-Za-z0-9.+-]+(?: (?:AND|OR|WITH) [A-Za-z0-9.+-]+)+$')
_FULL_TEXT: Final = re.compile(r'^(copyright|permission is|license agreement|===)', re.IGNORECASE | re.MULTILINE)
_FAMILIES: Final = ('Apache 2.0', 'BSD', 'GPL / LGPL', 'MIT', 'MPL', 'PSF', 'Other')
_HEADINGS: Final = {
    'Apache 2.0': 'Software under the Apache 2.0 License',
    'BSD': 'Software under the BSD Software Licenses',
    'GPL / LGPL': 'Software under the GPL and/or LGPL Licenses',
    'MIT': 'Software under the MIT License',
    'MPL': 'Software under the MPL 2.0 (Mozilla Public License)',
    'PSF': 'Software under the PSF (Python Software Foundation) Licenses',
    'Other': 'Software under other licenses',
}
_DASH: Final = '—'
_DIRECT_GIT: Final = re.compile(r'^([A-Za-z0-9_.-]+) @ git\+(\S+)$')
_CARGO_TIMEOUT_S: Final = 300


class UnknownLicense(RuntimeError):
    """A third-party dependency whose license could not be identified."""


@dataclass(frozen=True)
class NoticeData:
    """A repo's ``[tool.dev_lab.notices]``: the product, never the mechanism."""

    entity: str
    product: str
    in_tree: frozenset[str] = frozenset()
    overrides: Mapping[str, str] = field(default_factory=dict)
    vendored: tuple[Mapping[str, str], ...] = ()
    cargo_manifest: str = ''
    out: str = 'docs/notices'


def notice_data(root: Path) -> NoticeData:
    """*root*'s declared notice data.

    Raises:
        ValueError: ``[tool.dev_lab.notices]`` is absent or lacks ``entity`` / ``product``.

    """
    manifest = root / 'pyproject.toml'
    table = tomllib.loads(manifest.read_text(encoding='utf-8')).get('tool', {}).get('dev_lab', {}).get('notices')
    if not isinstance(table, dict) or not table.get('entity') or not table.get('product'):
        msg = (
            f'{manifest} declares no [tool.dev_lab.notices] entity and product: declare them (see dev_lab.dev.notices)'
        )
        raise ValueError(msg)
    return NoticeData(
        entity=table['entity'],
        product=table['product'],
        in_tree=frozenset(table.get('in_tree', ())),
        overrides=dict(table.get('overrides', {})),
        vendored=tuple(table.get('vendored', ())),
        cargo_manifest=table.get('cargo_manifest', ''),
        out=table.get('out', 'docs/notices'),
    )


def _family(spdx: str) -> str:
    first = spdx.strip('()').split(' AND ')[0].split(' OR ')[0].strip('()')
    if first.startswith('LGPL'):
        return 'GPL / LGPL'
    return next((name for name in _FAMILIES[:-1] if first.startswith(name.split(' ')[0])), 'Other')


def normalize_license(name: str, raw: str, *, overrides: Mapping[str, str]) -> str:
    """The SPDX expression for *raw* (the repo's curated *overrides* first), else :data:`UNKNOWN`."""
    if name in overrides:
        return overrides[name]
    text = ' '.join((raw or '').split())
    if not text or _FULL_TEXT.search(text):
        return UNKNOWN
    text = re.sub(r'^(?:License :: )?OSI Approved :: ', '', text)
    if text.lower() in _RAW_TO_SPDX:
        return _RAW_TO_SPDX[text.lower()]
    return text if _EXPRESSION.match(text.replace('(', '').replace(')', '')) else UNKNOWN


def _raw_license(md: PackageMetadata) -> str:
    raw = md.get('License-Expression') or md.get('License') or ''
    if raw:
        return raw
    return next((c for c in md.get_all('Classifier') or [] if c.startswith('License ::')), '')


def _metadata_url(md: PackageMetadata) -> str:
    if home := md.get('Home-page'):
        return home
    urls = [url for url in md.get_all('Project-URL') or [] if ',' in url]
    preferred = [url for url in urls if url.startswith('Homepage,')] or urls
    return preferred[0].split(',', 1)[1].strip() if preferred else ''


def python_packages(*, in_tree: frozenset[str], overrides: Mapping[str, str]) -> list[dict[str, str]]:
    """Every installed distribution outside *in_tree*, its license normalized."""
    rows = []
    for dist in imd.distributions():
        md = dist.metadata
        name = md.get('Name', '?')
        if name in in_tree:
            continue
        rows.append(
            {
                'name': name,
                'version': md.get('Version', '?'),
                'license': normalize_license(name, _raw_license(md), overrides=overrides),
                'url': _metadata_url(md) or _DASH,
            }
        )
    return rows


def rust_crates(manifest: Path, *, overrides: Mapping[str, str]) -> list[dict[str, str]]:
    """Third-party crates from ``cargo metadata`` (workspace members are the repo's own code).

    Raises:
        UnknownLicense: cargo is not on PATH -- the crate licenses cannot be read, and are never guessed.

    """
    cargo = shutil.which('cargo')
    if cargo is None:
        msg = f'cargo is not on PATH: the crate licenses of {manifest} cannot be read -- install a Rust toolchain'
        raise UnknownLicense(msg)
    done = _door.run(
        [cargo, 'metadata', '--format-version', '1', '--manifest-path', str(manifest)],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=True,
        timeout=_CARGO_TIMEOUT_S,
    )
    data = json.loads(done.stdout)
    workspace = frozenset(data['workspace_members'])
    return [
        {
            'name': pkg['name'],
            'version': pkg['version'],
            'license': normalize_license(pkg['name'], pkg.get('license') or '', overrides=overrides),
            'url': f'https://crates.io/crates/{pkg["name"]}',
        }
        for pkg in data['packages']
        if pkg['id'] not in workspace
    ]


def git_sources(declared: Sequence[str]) -> dict[str, str]:
    """Distribution name -> repository URL: the environment's PEP 610 records first, *declared* specs second."""
    out: dict[str, str] = {}
    for dist in imd.distributions():
        try:
            raw = dist.read_text('direct_url.json')
            direct = json.loads(raw) if raw else {}
        except (OSError, ValueError):
            continue
        name = dist.metadata['Name']
        if (direct.get('vcs_info') or {}).get('vcs') == 'git' and name:
            out[name] = direct.get('url', '')
    for spec in declared:
        if match := _DIRECT_GIT.match(spec):
            out.setdefault(match.group(1), match.group(2))
    clean = {name: url.split('?')[0].split('#')[0] for name, url in out.items()}
    return {name: re.sub(r'@[0-9a-f]{7,40}$', '', url) for name, url in clean.items()}


def _table(rows: Sequence[Mapping[str, str]]) -> str:
    lines = ['| Package | Version | License | URL |', '|---|---|---|---|']
    lines.extend(
        f'| {r["name"]} | {r["version"]} | {r["license"]} | {r["url"]} |'
        for r in sorted(rows, key=lambda r: (r['name'].lower(), r['version']))
    )
    return '\n'.join(lines)


def grouped(rows: Sequence[Mapping[str, str]]) -> str:
    """One section per license family, in a fixed order, empty families omitted."""
    parts: list[str] = []
    for name in _FAMILIES:
        members = [r for r in rows if _family(r['license']) == name]
        if members:
            parts.extend((f'### {_HEADINGS[name]}', '', _table(members), ''))
    return '\n'.join(parts).rstrip()


def refuse_unknown(rows: Sequence[Mapping[str, str]]) -> None:
    """Raise :class:`UnknownLicense` naming every row whose license is :data:`UNKNOWN`."""
    unknown = sorted(r['name'] for r in rows if r['license'] == UNKNOWN)
    if unknown:
        msg = (
            f'UNKNOWN license metadata for: {", ".join(unknown)}. Curate each in [tool.dev_lab.notices.overrides] '
            '-- a notice must not ship a license it cannot identify.'
        )
        raise UnknownLicense(msg)


def _declared_specs(root: Path) -> list[str]:
    project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8')).get('project', {})
    specs = list(project.get('dependencies') or [])
    for group in (project.get('optional-dependencies') or {}).values():
        specs.extend(group)
    return specs


def notices_markdown(root: Path, data: NoticeData) -> str:
    """The whole notice for *root*'s environment as markdown. Raises :class:`UnknownLicense`."""
    py_rows = python_packages(in_tree=data.in_tree, overrides=data.overrides)
    rust_rows = rust_crates(root / data.cargo_manifest, overrides=data.overrides) if data.cargo_manifest else []
    git = {name.replace('_', '-'): url for name, url in git_sources(_declared_specs(root)).items()}
    in_house = [
        {
            **r,
            'license': 'Not declared' if r['license'] == UNKNOWN else r['license'],
            'url': git[r['name'].replace('_', '-')],
        }
        for r in py_rows
        if r['name'].replace('_', '-') in git
    ]
    third_party = [r for r in py_rows if r['name'].replace('_', '-') not in git]
    refuse_unknown(third_party + rust_rows)
    sections = ['## Third-party Python packages', grouped(third_party)]
    if rust_rows:
        sections += ['## Rust crates', grouped(rust_rows)]
    if data.vendored:
        sections += [
            '## Vendored code',
            '\n'.join(
                f'- **{v["name"]}** ({v["license"]}) by {v["author"]} {_DASH} {v.get("note", "")} {v["url"]}'.replace(
                    '  ', ' '
                )
                for v in sorted(data.vendored, key=lambda v: v['name'])
            ),
        ]
    if in_house:
        sections += [
            '## In-house libraries',
            (
                f'Developed by the organization that owns {data.product}, so not third-party open source; their '
                'transitive dependencies appear in the tables above.'
            ),
            _table(in_house),
        ]
    return (
        f'# Legal Notices\n\n{data.product} is © {data.entity}. All Rights Reserved.\n\n'
        f'This software uses code from open-source projects not owned by {data.entity}, summarized below; follow each '
        "package's URL or read the license text at https://spdx.org/licenses/.\n\n"
        'The tables cover the complete development environment, including build and test tooling.\n\n'
        + '\n\n'.join(sections)
        + '\n'
    )


def build_notices(root: Path, out_dir: Path, data: NoticeData) -> Path:
    """Write the notice (markdown, the artifact of record) and an ``index.html`` wrapping it; the notice's path."""
    text = notices_markdown(root, data)
    out_dir.mkdir(parents=True, exist_ok=True)
    notice = out_dir / NOTICE_BASENAME
    notice.write_text(text, encoding='utf-8')
    (out_dir / 'index.html').write_text(
        '<!doctype html>\n<html lang="en">\n'
        f'<head><meta charset="utf-8"><title>{html.escape(data.product)} - legal notices</title></head>\n'
        f'<body>\n<p><a href="{NOTICE_BASENAME}">{NOTICE_BASENAME}</a></p>\n<pre>{html.escape(text)}</pre>\n'
        '</body>\n</html>\n',
        encoding='utf-8',
    )
    return notice


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m dev_lab.dev.notices [--root ROOT] [--out DIR]``: exit 0 written, 1 refused (named)."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.notices', description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='the checkout to describe (default: cwd)')
    parser.add_argument('--out', type=Path, default=None, help='output directory (default: the declared out)')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        data = notice_data(root)
        notice = build_notices(root, args.out or root / data.out, data)
    except (ValueError, UnknownLicense) as why:
        emit(f'notices: refused -- {why}', err=True)
        return 1
    emit(f'notices: wrote {notice} for {root}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
