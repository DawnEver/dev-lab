"""NO-DETOUR: a file that only forwards to another owner is refused until its edge names what the hop adds."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from dev_lab.dev import deptable, passthrough

if TYPE_CHECKING:
    from pathlib import Path

_GIT = shutil.which('git') or 'git'
DECLARED = """
[python.owners]
alpha = []
beta = ["alpha"]

[python.native]
kernel = "alpha"

[rust.crates]
base = []
upper = ["base"]
"""
ADDED = DECLARED.replace('beta = ["alpha"]', 'beta = [{ name = "alpha", adds = "translation" }]').replace(
    'upper = ["base"]', 'upper = [{ name = "base", adds = "control" }]'
)
#: A pure Python forward: every public function passes its own parameters, unchanged, to owner alpha.
FORWARD = '''"""A hop."""
from __future__ import annotations

from typing import TYPE_CHECKING

from pkg.alpha import core
from pkg.alpha.core import solve

if TYPE_CHECKING:
    from pkg.alpha.types import T

__all__ = ['run', 'solve_it', 'spread']


def run(a, b, *, c):
    """Forward."""
    return core.run(a, b=b, c=c)


async def solve_it(x, *args, **kwargs):
    return await solve(x, *args, **kwargs)


def spread(a):
    core.spread(a)


def _private(z):
    return z + 1
'''
RUST_FORWARD = (
    'use base::solve;\n'
    'pub fn run(a: u8, b: u8) -> u8 { base::run(a, b) }\n'
    'pub fn go(x: u8) -> u8 { return solve(x); }\n'
)


def _problems(root: Path, files: dict[str, str], declared: str = DECLARED) -> list[str]:
    base = {
        'pyproject.toml': '[project]\nname = "pkg"\n',
        'src/pkg/__init__.py': '',
        'src/pkg/alpha/__init__.py': '',
        'src/pkg/alpha/core.py': 'def run(a, b, c): return a\n',
        'src/pkg/beta/__init__.py': '',
        'rust/base/Cargo.toml': '[package]\nname = "base"\n',
        'rust/base/src/lib.rs': 'pub fn run(a: u8, b: u8) -> u8 { a + b }\n',
        'rust/upper/Cargo.toml': '[package]\nname = "upper"\n[dependencies]\nbase = { path = "../base" }\n',
        deptable.FILE: declared,
        **files,
    }
    for rel, text in base.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding='utf-8')
    decl = deptable.load(root)
    assert decl is not None
    return passthrough.problems(root, decl, base)


def test_a_python_module_that_only_forwards_is_refused_until_its_edge_names_what_it_adds(tmp_path: Path) -> None:
    found = _problems(tmp_path, {'src/pkg/beta/hop.py': FORWARD})
    assert found == [
        (
            'src/pkg/beta/hop.py: every public function forwards to owner alpha unchanged (run, solve_it, spread), '
            'and [python.owners] beta -> alpha names nothing the hop adds'
        )
    ]
    assert _problems(tmp_path, {'src/pkg/beta/hop.py': FORWARD}, ADDED) == []


def test_a_forward_to_a_native_crate_is_a_forward_to_its_owner(tmp_path: Path) -> None:
    native = 'from pkg_native import kernel\n\ndef run(a):\n    return kernel.run(a)\n'
    assert 'forwards to owner alpha' in _problems(tmp_path, {'src/pkg/beta/hop.py': native})[0]


def test_a_forward_to_a_sibling_needs_adds_on_its_siblings_edge(tmp_path: Path) -> None:
    files = {
        'src/pkg/alpha/one/hop.py': 'from pkg.alpha.two import core\n\ndef run(a):\n    return core.run(a)\n',
        'src/pkg/alpha/two/core.py': 'def run(a):\n    return a + 1\n',
    }
    assert _problems(tmp_path, files) == [
        (
            'src/pkg/alpha/one/hop.py: every public function forwards to sibling two unchanged (run), and '
            '[python.siblings."alpha"] one -> two names nothing the hop adds'
        )
    ]
    declared = DECLARED + '\n[python.siblings.alpha]\none = [{ name = "two", adds = "policy" }]\n'
    assert _problems(tmp_path, files, declared) == []


@pytest.mark.parametrize(
    'adds',
    [
        FORWARD.replace('return core.run(a, b=b, c=c)', 'return core.run(a, b=b * 2, c=c)'),  # a translation
        FORWARD.replace('return core.run(a, b=b, c=c)', 'return core.run(b, a, c=c)'),  # reordered
        FORWARD.replace('return core.run(a, b=b, c=c)', 'return core.run(a, b=b)'),  # a default chosen
        FORWARD.replace('def spread(a):', '@cache\ndef spread(a):'),  # a policy
        FORWARD + '\nLIMIT = 3\n',  # a public constant
        FORWARD + '\nclass Shape:\n    pass\n',  # a public class
        FORWARD.replace('    core.spread(a)', '    core.spread(a)\n    core.spread(a)'),  # two calls
        FORWARD.replace('from pkg.alpha import core', 'from pkg.beta import core'),  # within its own owner
        FORWARD.replace('from pkg.alpha import core', 'import numpy as core'),  # third-party: not an owner
    ],
)
def test_a_module_that_adds_anything_is_not_a_pass_through(tmp_path: Path, adds: str) -> None:
    """THE PLANTED CONTROLS: each one-line change from a pure forward is a module that adds something."""
    assert _problems(tmp_path, {'src/pkg/beta/hop.py': adds}) == []


def test_a_rust_file_that_only_forwards_is_refused_until_its_edge_names_what_it_adds(tmp_path: Path) -> None:
    files = {'rust/upper/src/lib.rs': RUST_FORWARD}
    assert _problems(tmp_path, files) == [
        (
            'rust/upper/src/lib.rs: every pub fn forwards to crate base unchanged (run, go), and [rust.crates] '
            'upper -> base names nothing the hop adds'
        )
    ]
    assert _problems(tmp_path, files, ADDED) == []
    for adds in (
        RUST_FORWARD.replace('base::run(a, b)', 'base::run(b, a)'),
        RUST_FORWARD.replace('base::run(a, b)', 'base::run(a, b) + 1'),
        RUST_FORWARD.replace('base::run(a, b)', 'base::run(a, b)?'),
        RUST_FORWARD + 'pub struct Shape;\n',
        RUST_FORWARD.replace('base::run(a, b)', 'run_local(a, b)'),
    ):
        assert _problems(tmp_path, {'rust/upper/src/lib.rs': adds}) == [], adds


def test_check_refusal_and_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert passthrough.main([], cwd=tmp_path) == 0
    assert 'not judged' in capsys.readouterr().out
    subprocess.run([_GIT, 'init', '-q', str(tmp_path)], check=True)
    _problems(tmp_path, {'src/pkg/beta/hop.py': FORWARD})
    subprocess.run([_GIT, '-C', str(tmp_path), 'add', '.'], check=True)
    with pytest.raises(AssertionError, match=r'(?s)NO-DETOUR.*src/pkg/beta/hop\.py.*adds'):
        passthrough.check(tmp_path)
    assert 'door:' in (passthrough.refusal(tmp_path) or '')
    assert passthrough.main([], cwd=tmp_path) == 1
    (tmp_path / deptable.FILE).write_text(ADDED, encoding='utf-8')
    passthrough.check(tmp_path)
    assert passthrough.refusal(tmp_path) is None
