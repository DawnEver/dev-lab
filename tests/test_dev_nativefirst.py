"""NATIVE-FIRST: the three refusals, each with its planted control, and the orchestration they let through."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from dev_lab.dev import nativefirst
from dev_lab.dev.nativefirst import Native

if TYPE_CHECKING:
    from pathlib import Path

_GIT = shutil.which('git') or 'git'
NATIVE = Native(orchestration=('src/pkg/flow',), stages={'assemble': 'pkg_native.assemble'})
_DECLARED = (
    '[tool.dev_lab.native]\norchestration = ["src/pkg/flow"]\n'
    '[tool.dev_lab.native.stages]\nassemble = "pkg_native.assemble"\n'
)


def _write(root: Path, rel: str, text: str = '') -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding='utf-8')


def _problems(tmp_path: Path, files: dict[str, str]) -> list[str]:
    for rel, text in files.items():
        _write(tmp_path, rel, text)
    return nativefirst.problems(tmp_path, NATIVE, files)


# -- the declaration (opt-in) ------------------------------------------------------------------------------------


def test_an_undeclared_repo_is_not_judged_and_a_malformed_table_is_refused(tmp_path: Path) -> None:
    assert nativefirst.declared_native(tmp_path) is None
    _write(tmp_path, 'pyproject.toml', '[project]\nname = "x"\n')
    assert nativefirst.declared_native(tmp_path) is None
    _write(tmp_path, 'pyproject.toml', '[tool.dev_lab.native]\norchestration = "src/pkg/flow"\n')
    with pytest.raises(ValueError, match='orchestration'):
        nativefirst.declared_native(tmp_path)
    _write(tmp_path, 'pyproject.toml', '[tool.dev_lab.native]\norchestration = ["a"]\nstages = {s = 1}\n')
    with pytest.raises(ValueError, match='stages'):
        nativefirst.declared_native(tmp_path)
    _write(tmp_path, 'pyproject.toml', _DECLARED)
    assert nativefirst.declared_native(tmp_path) == NATIVE


def test_the_cli_states_an_undeclared_repo_is_not_judged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert nativefirst.main([], cwd=tmp_path) == 0
    assert 'not judged' in capsys.readouterr().out


# -- refusal 1: a numeric loop over array data under an orchestration path ----------------------------------------

_LOOPS = {
    'element store': 'def f(a, n):\n    for i in range(n):\n        a[i] = 2.0 * i\n',
    'element update': 'def f(a, n):\n    for i in range(n):\n        a[i] += 1\n',
    'element arithmetic': 'def f(a):\n    s = 0.0\n    for i in range(len(a)):\n        s = s + a[i] * a[i]\n',
    'per-element math': 'import math\ndef f(a, n):\n    for i in range(n):\n        a.append(math.sin(i))\n',
    'ndindex': 'import numpy as np\ndef f(a):\n    for idx in np.ndindex(a.shape):\n        a[idx] *= 2\n',
    'while counter': 'def f(a, n):\n    i = 0\n    while i < n:\n        a[i] = a[i] - 1\n        i += 1\n',
}


@pytest.mark.parametrize('source', _LOOPS.values(), ids=_LOOPS.keys())
def test_a_numeric_loop_under_orchestration_is_refused(tmp_path: Path, source: str) -> None:
    found = _problems(tmp_path, {'src/pkg/flow/m.py': source})
    assert len(found) == 1
    assert 'NATIVE-FIRST' in found[0]
    assert 'src/pkg/flow/m.py:' in found[0]
    assert 'numeric loop' in found[0]


def test_the_same_loop_outside_orchestration_is_not_judged(tmp_path: Path) -> None:
    assert _problems(tmp_path, {'src/pkg/other/m.py': _LOOPS['element store']}) == []


_ORCHESTRATION = {
    'vectorized numpy': 'import numpy as np\ndef f(a):\n    return np.sin(a) * 2.0 + a[1:] @ a[:-1]\n',
    'loop over records': 'def f(records, out):\n    for rec in records:\n        out[rec.name] = rec.value + 1\n',
    'loop over files': (
        'from pathlib import Path\ndef f(root):\n    sizes = {}\n'
        '    for p in Path(root).glob("*.toml"):\n        sizes[p.name] = p.stat().st_size\n    return sizes\n'
    ),
    'enumerate records': 'def f(cases):\n    for i, case in enumerate(cases):\n        print(i, case[0])\n',
    'range without arithmetic': 'def f(names, n):\n    for i in range(n):\n        print(names[i])\n',
    'while over a queue': 'def f(queue):\n    while queue:\n        job = queue.pop()\n        job.run()\n',
}


@pytest.mark.parametrize('source', _ORCHESTRATION.values(), ids=_ORCHESTRATION.keys())
def test_orchestration_passes(tmp_path: Path, source: str) -> None:
    assert _problems(tmp_path, {'src/pkg/flow/m.py': source}) == []


# -- refusal 2: a Python module for a native-owned stage ----------------------------------------------------------


def test_a_python_module_named_for_a_native_stage_is_refused_unless_it_calls_the_native_one(tmp_path: Path) -> None:
    twin = _problems(tmp_path, {'src/pkg/flow/assemble.py': 'def assemble(k):\n    return k\n'})
    assert len(twin) == 1
    assert 'stage `assemble`' in twin[0]
    assert 'pkg_native.assemble' in twin[0]
    package = _problems(tmp_path, {'src/pkg/flow/assemble/__init__.py': 'X = 1\n'})
    assert len(package) == 1
    wrapper = 'from pkg_native.assemble import assemble as _a\ndef assemble(k):\n    return _a(k)\n'
    assert _problems(tmp_path, {'src/pkg/flow/assemble.py': wrapper}) == []


# -- refusal 3: a test comparing the native stage against a Python twin --------------------------------------------


def test_a_test_importing_the_native_stage_and_a_python_twin_is_refused(tmp_path: Path) -> None:
    both = 'from pkg_native.assemble import assemble\nfrom pkg.reference import assemble as py\n'
    found = _problems(tmp_path, {'tests/test_assemble.py': both})
    assert len(found) == 1
    assert 'Python twin' in found[0]
    assert 'pkg.reference.assemble' in found[0]
    module_twin = 'import pkg_native.assemble\nimport pkg.slow.assemble\n'
    assert len(_problems(tmp_path, {'tests/test_twin.py': module_twin})) == 1


def test_a_test_against_a_reference_or_the_native_stage_alone_passes(tmp_path: Path) -> None:
    alone = 'import numpy as np\nfrom pkg_native.assemble import assemble\nfrom pkg.goldens import load\n'
    assert _problems(tmp_path, {'tests/test_assemble.py': alone}) == []
    python_only = 'from pkg.reference import assemble\n'
    assert _problems(tmp_path, {'tests/test_ref.py': python_only}) == []


# -- the always-on family check -----------------------------------------------------------------------------------


def test_check_reads_the_tracked_tree_and_names_every_refusal(tmp_path: Path) -> None:
    subprocess.run([_GIT, 'init', '-q', str(tmp_path)], check=True)
    _write(tmp_path, 'pyproject.toml', _DECLARED)
    _write(tmp_path, 'src/pkg/flow/m.py', _LOOPS['element store'])
    _write(tmp_path, 'src/pkg/flow/ok.py', _ORCHESTRATION['vectorized numpy'])
    subprocess.run([_GIT, '-C', str(tmp_path), 'add', '.'], check=True)
    with pytest.raises(AssertionError, match=r'NATIVE-FIRST.*src/pkg/flow/m\.py'):
        nativefirst.check(tmp_path)
    (tmp_path / 'src/pkg/flow/m.py').write_text(_ORCHESTRATION['loop over records'], encoding='utf-8')
    nativefirst.check(tmp_path)
