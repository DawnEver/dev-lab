"""FOOTPRINT: the repo paths a test file's outcome can depend on, derived statically at one commit.

Every repo here is a REAL git history in a temp dir. The planted control of each carry is the same history
with one changed path INSIDE the footprint: that test must NOT carry.
"""

from __future__ import annotations

import time
from pathlib import Path

from _forge_fake import git_out, run_git

from dev_lab.dev import footprint, forgecarry

PYPROJECT = '[tool.dev_lab.parts]\noutput = "output/logs"\n'
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
    declared = PYPROJECT + '[tool.dev_lab.carry.reads]\n"tests/test_reads.py" = ["tests/**"]\n'
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
    a = _repo(tmp_path, **{'pyproject.toml': PYPROJECT + '[tool.dev_lab.carry]\neverywhere = ["rust/**"]\n'})
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
    bad = _commit(tmp_path, {'pyproject.toml': PYPROJECT + '[tool.dev_lab.carry]\neverywhere = "rust"\n'})
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


def test_an_earlier_run_of_the_same_sha_gives_every_outcome_it_finished(tmp_path: Path) -> None:
    """A run released retryable is claimed again at the SAME sha: its finished shards stand.

    PLANTED CONTROL: without that run, only the ancestor's outcomes the footprint keeps are carried.
    """
    a = _repo(tmp_path)
    b = _commit(tmp_path, {'src/pkg/util.py': 'Y = 2\n'})  # inside test_core's footprint
    ancestor = dict.fromkeys(NODES, ('passed', a))
    earlier = {'tests/test_core.py::test_x': ('failed', b), 'tests/test_other.py::test_z': ('skipped', b)}
    taken = forgecarry.carry_from(tmp_path, b, {a: ancestor, b: earlier})
    assert taken['tests/test_core.py::test_x'] == ('failed', b, b), 'its own finished outcome, never re-judged'
    assert taken['tests/test_other.py::test_z'] == ('skipped', b, b)
    control = forgecarry.carry_from(tmp_path, b, {a: ancestor})
    assert 'tests/test_core.py::test_x' not in control


def _synthetic(texts: dict[str, str], *, reads: dict[str, tuple[str, ...]] | None = None) -> footprint.Footprints:
    tracked = frozenset({*texts, 'pyproject.toml', 'docs/guide.md', 'data/x.csv'})
    return footprint.Footprints(tracked, texts, ('rust/**',), reads or {}, PYPROJECT)


GRAPH = {
    'src/a.py': 'import b\n',  # a <-> b is a cycle
    'src/b.py': 'import a\nimport c\n',
    'src/c.py': 'X = 1\n',
    'src/d.py': 'import subprocess\n',  # by path, reads declared
    'src/e.py': 'import importlib\n',  # by path, nothing declared: everything
    'tests/test_ab.py': 'import a\n',
    'tests/test_c.py': 'import c\n',
    'tests/test_d.py': 'import d\n',
    'tests/test_e.py': 'import e\n',
    'tests/sub/test_plain.py': 'def test_p():\n    pass\n',
    'tests/check_named_otherwise.py': 'import c\n',  # not a pytest test file: outside the graph
}


def test_reaches_is_the_footprint_judged_on_every_test_and_every_change() -> None:
    """``reaches(test, changed)`` is EXACTLY ``of(test).reaches_any(changed)`` -- cycles, reads, seeds, globs.

    PLANTED CONTROL: each change below lands inside SOME footprint and outside another, so a judge
    answering always-yes or always-no fails it.
    """
    prints = _synthetic(GRAPH, reads={'src/d.py': ('data/**',)})
    changes = [
        (), ('src/c.py',), ('src/a.py',), ('src/b/__init__.py',), ('data/x.csv',), ('docs/guide.md',),
        ('rust/lib.rs',), ('uv.lock',), ('tests/conftest.py',), ('tests/sub/conftest.py',), ('src/zz.py',),
    ]  # fmt: skip
    tests = [*(p for p in GRAPH if p.startswith('tests/')), 'tests/README.md']
    verdicts = set()
    for changed in changes:
        for test in tests:
            want = prints.of(test).reaches_any(changed)
            assert prints.reaches(test, changed) == want, (test, changed)
            verdicts.add(want)
    assert verdicts == {True, False}


def test_reaches_judges_a_repo_of_shared_closures_in_one_pass_not_one_per_test() -> None:
    """Every test of a big repo shares most of its closure: one pass, not one walk per test (Ada 2026-10-17).

    PLANTED CONTROL: :meth:`of` walks the whole shared closure per test, so a TENTH of the tests through
    it costs more than all of them through :meth:`reaches`.
    """
    size = 800
    texts = {f'src/m{i}.py': ''.join(f'import m{(i + k) % size}\n' for k in range(1, 12)) for i in range(size)}
    texts |= {f'tests/test_{i}.py': f'import m{i}\n' for i in range(size)}
    prints = _synthetic(texts)
    tests = [f'tests/test_{i}.py' for i in range(size)]
    prints.reaches(tests[0], ('docs/guide.md',))  # every module parsed once, which of() then reuses
    start = time.perf_counter()
    judged = [prints.reaches(test, ('src/m0.py',)) for test in tests]
    fast = time.perf_counter() - start
    start = time.perf_counter()
    walked = [prints.of(test).reaches_any(('src/m0.py',)) for test in tests[: size // 10]]
    slow = time.perf_counter() - start
    assert judged[: size // 10] == walked
    assert fast < slow, f'all {size} judged in {fast:.2f} s; a tenth walked in {slow:.2f} s'


LOCK_HEAD = 'version = 1\nrequires-python = ">=3.12"\n'
MAPPED = {'dev-lab': frozenset({'dev_lab'}), 'numpy': frozenset({'numpy'}), 'scipy': frozenset({'scipy'})}
LOCK_TESTS = {
    'tests/test_dl.py': 'import dev_lab\n\ndef test_d():\n    pass\n',
    'tests/test_np.py': 'import numpy\n\ndef test_n():\n    pass\n',
    'tests/test_sp.py': 'from scipy import linalg\n\ndef test_s():\n    pass\n',
    'tests/test_js.py': 'import json\n\ndef test_j():\n    pass\n',
}
LOCK_NODES = tuple(f'{path}::test_{path[11]}' for path in LOCK_TESTS)


def _lock(*, pin: str = 'aaa', numpy: str = '2.0.0', head: str = LOCK_HEAD, extra: str = '') -> str:
    return (
        f'{head}\n[[package]]\nname = "dev-lab"\nversion = "0.1.0"\n'
        f'source = {{ git = "https://example/dev-lab?rev=main#{pin}" }}\n'
        f'\n[[package]]\nname = "numpy"\nversion = "{numpy}"\nsource = {{ registry = "https://pypi.org/simple" }}\n'
        '\n[[package]]\nname = "scipy"\nversion = "1.14.0"\nsource = { registry = "https://pypi.org/simple" }\n'
        'dependencies = [{ name = "numpy" }]\n'
        f'{extra}'
    )


def _lock_carried(tmp_path: Path, monkeypatch: object, new_lock: str) -> set[str]:
    """Which of :data:`LOCK_TESTS` carry across a commit changing ONLY ``uv.lock`` to *new_lock*."""
    monkeypatch.setattr(footprint, 'import_names', MAPPED.get)  # type: ignore[attr-defined]
    a = _repo(tmp_path, **LOCK_TESTS, **{'uv.lock': _lock()})
    b = _commit(tmp_path, {'uv.lock': new_lock})
    return {node.split('::')[0] for node in forgecarry.carried(tmp_path, a, b, LOCK_NODES)}


def test_a_relock_moving_only_the_dev_lab_pin_reaches_only_dev_lab_importers(tmp_path: Path, monkeypatch) -> None:
    """D48-2 (2026-11-01): a dev-lab pin move re-ran a consumer's whole suite (``ran=5471``) per push.

    PLANTED CONTROL: the dev_lab importer must NOT carry; the numpy, scipy and json importers carry.
    """
    carried = _lock_carried(tmp_path, monkeypatch, _lock(pin='bbb'))
    assert carried == {'tests/test_np.py', 'tests/test_sp.py', 'tests/test_js.py'}


def test_a_numpy_bump_reaches_its_reverse_dependents_importers(tmp_path: Path, monkeypatch) -> None:
    """SciPy depends on numpy, so a test importing only scipy is reached. CONTROL: json and dev_lab carry."""
    carried = _lock_carried(tmp_path, monkeypatch, _lock(numpy='2.1.0'))
    assert carried == {'tests/test_dl.py', 'tests/test_js.py'}


def test_a_lock_header_or_marker_change_reaches_every_test(tmp_path: Path, monkeypatch) -> None:
    """A change outside ``[[package]]`` is doubt. CONTROL: the same packages under the old header carry all."""
    assert _lock_carried(tmp_path, monkeypatch, _lock(head=LOCK_HEAD + 'resolution-markers = ["x"]\n')) == set()
    assert footprint.lock_reach(_lock(), _lock(), MAPPED.get) == frozenset()


def test_an_unmappable_changed_package_reaches_every_test(tmp_path: Path, monkeypatch) -> None:
    """A package the metadata cannot map is doubt. CONTROL: the mapped dev-lab move alone reaches dev_lab only."""
    extra = '\n[[package]]\nname = "mystery"\nversion = "1"\nsource = { registry = "https://pypi.org/simple" }\n'
    assert _lock_carried(tmp_path, monkeypatch, _lock(extra=extra)) == set()
    assert footprint.lock_reach(_lock(), _lock(pin='bbb'), MAPPED.get) == frozenset({'dev_lab'})


def test_an_unresolved_lock_still_reaches_every_footprint() -> None:
    """Called without :func:`footprint.resolve_lock`, ``uv.lock`` stays in every footprint: doubt is wide."""
    prints = _synthetic({'tests/test_a.py': 'import json\n'})
    assert prints.reaches('tests/test_a.py', (footprint.LOCK,))
    assert prints.of('tests/test_a.py').reaches(footprint.LOCK)
    assert prints.of('tests/test_a.py').reaches(footprint.IMPORT + 'json')
    assert not prints.reaches('tests/test_a.py', (footprint.IMPORT + 'numpy',))


def test_import_names_reads_the_installed_metadata_and_refuses_the_runner() -> None:
    """One mapping: a library maps to its top-level names; pytest and an unknown distribution reach everything."""
    assert footprint.import_names('Pluggy') == frozenset({'pluggy'}), 'pytest depends on it, so it is installed'
    assert footprint.import_names('pytest') is None
    assert footprint.import_names('no-such-distribution-d48') is None


def test_a_from_import_does_not_hide_a_later_read_by_path() -> None:
    """F-003477da3cde: a from-import's module name once clobbered the tracked-names set ``_reads_by_path`` reads.

    PLANTED CONTROL: the same read with no from-import before it was already caught; both must be.
    """
    read = "open('data/x.csv').read()\n"
    for text in (read, 'from os import path\n' + read):
        prints = _synthetic({'tests/test_r.py': text})
        assert prints.reaches('tests/test_r.py', ('data/x.csv',)), text


def test_the_repos_own_project_entry_does_not_carry_a_pin_move_to_everything() -> None:
    """F-759cb56e8a22: the root's editable entry depends on everything, so a pin move reached it and then all.

    In-repo code reaches its third-party imports through its own ``import:<name>`` paths, so the lock's
    in-repo entries (editable / virtual INSIDE the repo) are no door. CONTROL: an editable path OUTSIDE the
    repo is third-party code the footprint cannot read, so it stays one, and unmapped reaches everything.
    """

    def lock(pin: str, source: str) -> str:
        return _lock(pin=pin, extra=f'\n[[package]]\nname = "app"\nversion = "0"\nsource = {{ {source} }}\n'
                     'dependencies = [{ name = "dev-lab" }, { name = "numpy" }]\n')  # fmt: skip

    for source in ('editable = "."', 'virtual = "."', 'editable = "packages/sub"'):
        assert footprint.lock_reach(lock('aaa', source), lock('bbb', source), MAPPED.get) == {'dev_lab'}, source
    assert (
        footprint.lock_reach(lock('aaa', 'editable = "../app"'), lock('bbb', 'editable = "../app"'), MAPPED.get) is None
    )
