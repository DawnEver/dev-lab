"""FOOTPRINT: the repo paths a test file's outcome can depend on, derived statically at one commit.

Every repo here is a REAL git history in a temp dir. The planted control of each carry is the same history
with one changed path INSIDE the footprint: that test must NOT carry.
"""

from __future__ import annotations

from pathlib import Path

from _forge_fake import git_out, run_git

from lab_commons.dev import footprint, forgecarry

PYPROJECT = '[tool.lab_commons.parts]\noutput = "output/logs"\n'
BASE = {
    'pyproject.toml': PYPROJECT,
    'src/pkg/__init__.py': '',
    'src/pkg/core.py': 'from pkg import util\nX = util.Y\n',
    'src/pkg/util.py': 'Y = 1\n',
    'src/pkg/other.py': 'Z = 2\n',
    'tests/conftest.py': 'import pytest\n',
    'tests/test_core.py': 'from pkg.core import X\n\ndef test_x():\n    assert X == 1\n',
    'tests/test_other.py': 'from pkg import other\n\ndef test_z():\n    assert other.Z == 2\n',
    'tests/test_reads.py': 'from pathlib import Path\n\ndef test_r():\n    assert Path(__file__).parent.exists()\n',
    'docs/guide.md': 'g\n',
}


def _commit(root: Path, files: dict[str, str], message: str = 'c') -> str:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding='utf-8')
    run_git(root, 'add', '-A')
    run_git(root, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', message)
    return git_out(root, 'rev-parse', 'HEAD')


def _repo(root: Path, **extra: str) -> str:
    run_git(root, 'init', '-q')
    return _commit(root, {**BASE, **extra})


def _carried(root: Path, a: str, b: str) -> set[str]:
    return {node.split('::')[0] for node in forgecarry.carried(root, a, b, NODES)}


NODES = ('tests/test_core.py::test_x', 'tests/test_other.py::test_z', 'tests/test_reads.py::test_r')


def test_the_footprint_is_the_transitive_import_closure_and_the_conftest_chain(tmp_path: Path) -> None:
    a = _repo(tmp_path)
    prints = footprint.Footprints.at(tmp_path, a)
    core = prints.of('tests/test_core.py')
    for path in ('tests/test_core.py', 'tests/conftest.py', 'src/pkg/core.py', 'src/pkg/util.py', 'pyproject.toml'):
        assert core.reaches(path), path
    assert not core.reaches('src/pkg/other.py')
    assert not core.reaches('docs/guide.md')
    assert core.reaches('tests/sub/conftest.py') is False, 'a conftest below the test does not apply to it'
    assert core.reaches('conftest.py'), 'a conftest added above the test would apply: its candidate is in'
    assert core.reaches('src/pkg/util/__init__.py'), 'a package shadowing the module is a candidate too'


def test_a_change_outside_every_footprint_carries_and_inside_one_does_not(tmp_path: Path) -> None:
    a = _repo(tmp_path)
    b = _commit(tmp_path, {'src/pkg/other.py': 'Z = 3\n', 'docs/guide.md': 'h\n'})
    assert _carried(tmp_path, a, b) == {'tests/test_core.py'}, 'other.py reaches test_other; reads reaches all'
    c = _commit(tmp_path, {'src/pkg/util.py': 'Y = 2\n'})
    assert _carried(tmp_path, b, c) == {'tests/test_other.py'}, 'PLANTED: util.py is in test_core by transitivity'


def test_a_test_reading_by_path_depends_on_everything_unless_its_reads_are_declared(tmp_path: Path) -> None:
    a = _repo(tmp_path)
    assert footprint.Footprints.at(tmp_path, a).of('tests/test_reads.py').reaches('docs/guide.md')
    declared = PYPROJECT + '[tool.lab_commons.carry.reads]\n"tests/test_reads.py" = ["tests/**"]\n'
    b = _commit(tmp_path, {'pyproject.toml': declared})
    c = _commit(tmp_path, {'docs/guide.md': 'h\n'})
    assert _carried(tmp_path, b, c) == {'tests/test_core.py', 'tests/test_other.py', 'tests/test_reads.py'}
    d = _commit(tmp_path, {'tests/data.txt': 'd\n'})
    assert _carried(tmp_path, c, d) == {'tests/test_core.py', 'tests/test_other.py'}, 'PLANTED: a declared read'


def test_a_repo_path_literal_or_a_dynamic_import_is_a_read_by_path(tmp_path: Path) -> None:
    a = _repo(
        tmp_path,
        **{
            'tests/test_lit.py': 'def test_l():\n    assert open("docs/guide.md").read()\n',
            'tests/test_dyn.py': 'import importlib\n\ndef test_d():\n    importlib.import_module("pkg.other")\n',
        },
    )
    prints = footprint.Footprints.at(tmp_path, a)
    assert prints.of('tests/test_lit.py').reaches('docs/guide.md')
    assert prints.of('tests/test_dyn.py').reaches('src/pkg/other.py')


def test_everywhere_globs_and_the_lock_reach_every_test(tmp_path: Path) -> None:
    a = _repo(tmp_path, **{'pyproject.toml': PYPROJECT + '[tool.lab_commons.carry]\neverywhere = ["rust/**"]\n'})
    b = _commit(tmp_path, {'rust/lib.rs': 'fn f() {}\n'})
    assert _carried(tmp_path, a, b) == set()
    c = _commit(tmp_path, {'uv.lock': 'x\n'})
    assert _carried(tmp_path, b, c) == set()


def test_no_ancestry_or_an_unreadable_declaration_carries_nothing(tmp_path: Path) -> None:
    a = _repo(tmp_path)
    run_git(tmp_path, 'checkout', '-q', '-b', 'side', a)
    side = _commit(tmp_path, {'docs/guide.md': 's\n'})
    run_git(tmp_path, 'checkout', '-q', '-')
    main = _commit(tmp_path, {'docs/guide.md': 'm\n'})
    assert not forgecarry.carried(tmp_path, side, main, NODES)
    bad = _commit(tmp_path, {'pyproject.toml': PYPROJECT + '[tool.lab_commons.carry]\neverywhere = "rust"\n'})
    later = _commit(tmp_path, {'docs/guide.md': 'n\n'})
    assert not forgecarry.carried(tmp_path, bad, later, NODES)


def test_equivalence_is_derived_every_test_carries_and_no_test_file_is_added(tmp_path: Path) -> None:
    a = _repo(tmp_path, **{'tests/test_reads.py': 'def test_r():\n    pass\n'})
    docs = _commit(tmp_path, {'docs/guide.md': 'h\n'})
    assert forgecarry.equivalent(tmp_path, a, docs)
    added = _commit(tmp_path, {'docs/test_new.py': 'def test_n():\n    pass\n'})
    assert not forgecarry.equivalent(tmp_path, docs, added), 'a new test file is reached by no old footprint'
    code = _commit(tmp_path, {'src/pkg/other.py': 'Z = 9\n'})
    assert not forgecarry.equivalent(tmp_path, added, code), 'PLANTED: a path inside one footprint'
