"""The portal PAGE for :mod:`lab_commons.dev.docsite` -- one card per sub-site, built or not.

Split from the driver because they answer different questions, and the driver is the one a reader
comes to first: what a requirement is and what a skip MEANS is policy; this file is a template.

A SKIPPED SUB-SITE IS RENDERED, NEVER OMITTED. Omission would make "not built here" and "does not
exist" read identically, so the reader cannot tell a hole from a boundary -- the defect the whole
docsite module is organised against. Everything interpolated is ESCAPED: a reason is prose written
by a person, and an unescaped ``<`` or ``&`` breaks the very page that was meant to explain the gap.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from lab_commons.dev.docsite import BuildReport, SubSite

__all__ = ['render_portal']


_PORTAL_HEAD: Final = """\
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>{favicon}
    <style>
        body {{ font-family: system-ui, sans-serif; margin: 0; background: #f7f7f8; color: #222; }}
        header {{ text-align: center; padding: 2.5rem 1rem 1rem; }}
        header img {{ height: 64px; }}
        header h1 {{ margin: .5rem 0 .25rem; font-size: 1.6rem; }}
        .version {{ color: #777; font-size: .9rem; }}
        main {{ display: flex; flex-wrap: wrap; gap: 1.25rem; justify-content: center;
               padding: 2rem 1rem 3rem; max-width: 1100px; margin: 0 auto; }}
        .card {{ display: block; width: 300px; padding: 1.25rem 1.5rem; background: #fff;
                border: 1px solid #e3e3e6; border-radius: 10px; text-decoration: none; color: inherit; }}
        a.card:hover {{ box-shadow: 0 4px 16px rgba(0,0,0,.10); }}
        .card h2 {{ margin: 0 0 .5rem; font-size: 1.15rem; }}
        .card p {{ margin: 0; color: #555; font-size: .9rem; line-height: 1.5; }}
        .card .sub {{ display: block; margin-top: .75rem; font-size: .8rem; color: #888; }}
        .absent {{ opacity: .65; }}
        footer {{ text-align: center; color: #999; font-size: .8rem; padding-bottom: 2rem; }}
        @media (prefers-color-scheme: dark) {{
            body {{ background: #1a1a1c; color: #e6e6e6; }}
            .card {{ background: #262629; border-color: #3a3a3e; }}
            .card p {{ color: #aaa; }}
        }}
    </style>
</head>
<body>
    <header>{logo}
        <h1>{title}</h1>
        <span class="version">v{version}</span>
    </header>
    <main>
"""


def _card(site: SubSite, report: BuildReport) -> str:
    """One portal card -- a link when the sub-site was built, plain text with its reason when not.

    A skipped sub-site is RENDERED and not omitted. Omission would make "not built here" and "does
    not exist" read identically, which is the defect this whole module is organised against.
    Everything interpolated is escaped: a reason is prose written by a person, and an unescaped
    ``<`` or ``&`` breaks the page.
    """
    title, blurb = html.escape(site.title), html.escape(site.blurb)
    if site.slug in report.built:
        subs = ' &middot; '.join(
            f'<a href="{html.escape(href)}">{html.escape(label)}</a>' for label, href in site.sub_links
        )
        sub = f'\n            <span class="sub">{subs}</span>' if subs else ''
        return (
            f'        <a class="card" href="{html.escape(site.slug)}/{html.escape(site.entry)}">\n'
            f'            <h2>{title}</h2>\n            <p>{blurb}</p>{sub}\n        </a>\n'
        )
    reason = html.escape(report.skipped.get(site.slug, 'not built'))
    return (
        f'        <div class="card absent">\n            <h2>{title}</h2>\n'
        f'            <p><em>not built here: {reason}</em></p>\n        </div>\n'
    )


def render_portal(
    report: BuildReport,
    subsites: Sequence[SubSite],
    *,
    title: str,
    version: str,
    logo: str | None = None,
    favicon: str | None = None,
) -> str:
    """The portal page: EVERY sub-site, built or not, with the gap named."""
    head = _PORTAL_HEAD.format(
        title=html.escape(title),
        version=html.escape(version),
        favicon=f'\n    <link rel="icon" href="{html.escape(favicon)}">' if favicon else '',
        logo=f'\n        <img src="{html.escape(logo)}" alt="{html.escape(title)}">' if logo else '',
    )
    cards = ''.join(_card(site, report) for site in subsites)
    footer = f'    <footer>{html.escape(title)} v{html.escape(version)}</footer>'
    return f'{head}{cards}    </main>\n{footer}\n</body>\n</html>\n'
