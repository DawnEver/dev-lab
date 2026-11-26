"""PUBLIC-SURFACE-DECLARED and DECLARATION-LIES, adopted over this package's own modules by the family body.

The scan, the private-by-shape exemption and the refusal are `dev_lab.dev.famtests.publicsurface`'s; this module
supplies this tree's floor and plants the controls the body must convict.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from _arch_corpus import SOURCE_FLOOR

from dev_lab.dev.famtests.publicsurface import assert_public_surface, public_modules, surface_problems

_ROOT = Path(__file__).resolve().parents[1]
_GIT = shutil.which('git') or 'git'


def test_every_public_module_declares_a_surface_that_resolves() -> None:
    """THE CHECK, over this repo's own tree -- which no planted fixture can speak for."""
    assert_public_surface(root=_ROOT, floor=SOURCE_FLOOR)


def test_a_planted_module_is_refused(tmp_path: Path) -> None:
    """THE PLANTED CONTROL. Both halves of the claim, through the REAL checker."""
    planted = {
        'silent.py': 'X = 1\n',
        'lying.py': "__all__ = ['gone']\n",
        'clean.py': "__all__ = ['X']\nX = 1\n",
        'aliased.py': "__all__ = ['Row']\ntype Row = tuple[str, ...]\n",
        'annotated.py': '__all__: list[str] = []\n',
        'guarded.py': "__all__ = ['X']\nwith open(__file__):\n    from os import sep as X\n",
        '_private.py': 'X = 1\n',
    }
    for name, body in planted.items():
        (tmp_path / name).write_text(body, encoding='utf-8')
    problems = surface_problems(sorted(tmp_path.iterdir()))
    assert any('silent.py declares no __all__' in p for p in problems)
    assert any("lying.py: __all__ names 'gone'" in p for p in problems)
    # Clean, a PEP 695 alias, an EMPTY annotated surface, a name bound inside an import guard, a private module.
    assert not [p for p in problems if any(n in p for n in ('clean', 'aliased', 'annotated', 'guarded', '_private'))]


def test_the_body_reads_a_consumers_tracked_source_roots(tmp_path: Path) -> None:
    """A consumer's tree, tracked: a lying module under ``src`` is refused; outside the roots it is not read.

    PLANTED CONTROL: the same lie under ``scripts`` passes until ``scripts`` is a declared source root.
    """
    (tmp_path / 'src' / 'pkg').mkdir(parents=True)
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'src' / 'pkg' / '__init__.py').write_text("__all__ = ['X']\nX = 1\n", encoding='utf-8')
    (tmp_path / 'scripts' / 'tool.py').write_text("__all__ = ['gone']\n", encoding='utf-8')
    subprocess.run([_GIT, 'init', '-q'], cwd=tmp_path, check=True, timeout=60)
    subprocess.run([_GIT, 'add', '--', '.'], cwd=tmp_path, check=True, timeout=60)
    assert [p.relative_to(tmp_path).as_posix() for p in public_modules(tmp_path)] == ['src/pkg/__init__.py']
    assert_public_surface(root=tmp_path, floor=1)
    with pytest.raises(AssertionError, match=r"tool\.py: __all__ names 'gone'"):
        assert_public_surface(root=tmp_path, floor=1, source_roots=('src', 'scripts'))
    with pytest.raises(AssertionError, match='public surface'):
        assert_public_surface(root=tmp_path, floor=2)


def test_the_guard_reads_this_repo() -> None:
    """The corpus really is this tree, spelled the way a refusal would spell it."""
    assert _ROOT / 'src/dev_lab/dev/rules.py' in set(public_modules(_ROOT))
