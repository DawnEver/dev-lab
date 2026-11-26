"""RUST-LINTS: the [workspace.lints] base rendered into a workspace; drift and a non-inheriting member refused."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from dev_lab.dev import cargolints, sectionrender
from dev_lab.dev.famconfig import PYPROJECT_SECTIONS, SectionDelta, inspect_section

if TYPE_CHECKING:
    from pathlib import Path

FILES = ['rust/Cargo.toml', 'rust/crates/a/Cargo.toml', 'rust/crates/b/Cargo.toml']


def _workspace(root: Path) -> None:
    (root / 'rust/crates/a').mkdir(parents=True)
    (root / 'rust/crates/b').mkdir(parents=True)
    (root / 'rust/Cargo.toml').write_text('# the workspace\n[workspace]\nmembers = ["crates/*"]\n', encoding='utf-8')
    for name in ('a', 'b'):
        (root / f'rust/crates/{name}/Cargo.toml').write_text(f'[package]\nname = "{name}"\n', encoding='utf-8')


def _judge(root: Path, *, write: bool = False) -> tuple[int, str]:
    out = io.StringIO()
    return cargolints.check(root, handle=out, write=write, files=FILES), out.getvalue()


def test_a_rendered_workspace_passes_and_keeps_its_own_lines(tmp_path: Path) -> None:
    """THE PLANTED CONTROL for the refusals below: --write renders, then the same tree is clean."""
    _workspace(tmp_path)
    code, said = _judge(tmp_path)
    assert code == cargolints.FOUND
    assert 'no [lints] workspace = true' in said
    assert '[workspace.lints.clippy] is NO_TABLE' in said
    assert _judge(tmp_path, write=True)[0] == cargolints.CLEAN
    text = (tmp_path / 'rust/Cargo.toml').read_text(encoding='utf-8')
    assert '# the workspace' in text
    assert 'members = ["crates/*"]' in text


def test_a_lint_level_moved_by_hand_is_refused_by_name(tmp_path: Path) -> None:
    _workspace(tmp_path)
    _judge(tmp_path, write=True)
    manifest = tmp_path / 'rust/Cargo.toml'
    manifest.write_text(manifest.read_text(encoding='utf-8').replace('todo = "deny"', 'todo = "allow"'), 'utf-8')
    code, said = _judge(tmp_path)
    assert code == cargolints.FOUND
    assert "todo: the file says 'allow' and the base says 'deny'" in said


def test_a_member_that_stops_inheriting_is_refused(tmp_path: Path) -> None:
    _workspace(tmp_path)
    _judge(tmp_path, write=True)
    (tmp_path / 'rust/crates/b/Cargo.toml').write_text('[package]\nname = "b"\n', encoding='utf-8')
    code, said = _judge(tmp_path)
    assert code == cargolints.FOUND
    assert said.count('no [lints] workspace = true') == 1
    assert 'rust/crates/b/Cargo.toml' in said


def test_a_repo_without_rust_is_not_judged_and_says_so(tmp_path: Path) -> None:
    out = io.StringIO()
    assert cargolints.check(tmp_path, handle=out, files=[]) == cargolints.CLEAN
    assert 'not judged' in out.getvalue() or 'no lints are judged' in out.getvalue()


def test_the_pyright_base_renders_into_a_pyproject_and_then_owns_it(tmp_path: Path) -> None:
    """T1's render through the same writer: a pyproject without the table gets it, and it inspects OWNED."""
    path = tmp_path / 'pyproject.toml'
    path.write_text('[project]\nname = "x"\n', encoding='utf-8')
    base = PYPROJECT_SECTIONS['[tool.pyright]']
    empty = SectionDelta(repo='x', added={}, dropped={}, ceiling=0)
    assert not inspect_section(path, base, empty).ok
    sectionrender.main([str(path), '[tool.pyright]'])
    assert inspect_section(path, base, empty).ok
    assert 'name = "x"' in path.read_text(encoding='utf-8')
