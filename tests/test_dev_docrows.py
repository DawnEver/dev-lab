"""A documentation site is rows of data: each kind names its builder, its requirement and what a skip loses."""

from __future__ import annotations

import re
import sys
import types
from typing import TYPE_CHECKING

import pytest

from dev_lab.dev import docrows
from dev_lab.dev.docsite import Every, Exe, Module

if TYPE_CHECKING:
    from pathlib import Path

_SITE = """[project]
name = "no-such-dist-here"
version = "1.2"
[tool.dev_lab.docsite]
title = "Example"
[[tool.dev_lab.docsite.sites]]
slug = "python"
title = "Python API"
kind = "pdoc"
modules = ["example"]
[[tool.dev_lab.docsite.sites]]
slug = "rust"
title = "Rust"
kind = "cargo"
workspace = "rust"
absent_means = "the crate docs"
[[tool.dev_lab.docsite.sites]]
slug = "guide"
title = "Guide"
kind = "markdown"
"""


def _root(tmp_path: Path, text: str = _SITE) -> Path:
    (tmp_path / 'pyproject.toml').write_text(text, encoding='utf-8')
    return tmp_path


def test_each_row_kind_names_its_requirement_and_what_a_skip_loses(tmp_path: Path) -> None:
    root = _root(tmp_path)
    sites = docrows.subsites(root, docrows.site_data(root))
    assert [site.slug for site in sites] == ['python', 'rust', 'guide']
    assert sites[0].requires == Module('pdoc')
    assert sites[1].requires == Exe('cargo')
    assert sites[1].absent_means == 'the crate docs'
    assert isinstance(sites[2].requires, Every)


@pytest.mark.parametrize(
    'bad',
    [
        '[project]\nname = "x"\n',
        (
            '[tool.dev_lab.docsite]\ntitle = "T"\n[[tool.dev_lab.docsite.sites]]\n'
            'slug = "s"\ntitle = "t"\nkind = "sphinx"\n'
        ),
    ],
)
def test_an_undeclared_site_or_an_unknown_kind_is_refused_by_name(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError, match=r'tool\.dev_lab\.docsite'):
        docrows.site_data(_root(tmp_path, bad))


class _Renderer:
    """A stand-in for markdown-it: each ``[text](href)`` becomes an anchor, which is all the link rewrite reads."""

    def __init__(self, *_args: object) -> None:
        pass

    def enable(self, _rule: str) -> _Renderer:
        return self

    def render(self, text: str) -> str:
        return re.sub(r'\[([^]]*)\]\(([^)]*)\)', r'<a href="\2">\1</a>', text)


@pytest.fixture
def renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, 'markdown_it', types.SimpleNamespace(MarkdownIt=_Renderer))


@pytest.mark.usefixtures('renderer')
def test_a_markdown_tree_renders_with_relative_md_links_rewritten(tmp_path: Path) -> None:
    source = tmp_path / 'docs-src'
    (source / 'dev').mkdir(parents=True)
    (source / 'index.md').write_text('[gate](dev/gate.md) [ext](https://x.org/a.md)\n', encoding='utf-8')
    (source / 'dev' / 'gate.md').write_text('# Gate\n', encoding='utf-8')
    docrows._markdown_tree(source, tmp_path / 'out', title='Example')
    page = (tmp_path / 'out' / 'index.html').read_text(encoding='utf-8')
    assert 'href="dev/gate.html"' in page
    assert 'href="https://x.org/a.md"' in page
    assert (tmp_path / 'out' / 'dev' / 'gate.html').is_file()


def test_an_empty_markdown_tree_is_not_a_successful_build(tmp_path: Path) -> None:
    """Planted control: a build with nothing to render must fail, never report built."""
    (tmp_path / 'docs-src').mkdir()
    with pytest.raises(FileNotFoundError, match=r'no \.md files'):
        docrows._markdown_tree(tmp_path / 'docs-src', tmp_path / 'out', title='Example')
