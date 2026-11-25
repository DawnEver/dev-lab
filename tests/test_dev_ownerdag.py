"""OWNER-DAG over a Python tree: undeclared edges, siblings, rows against the tree, packages and stdlib by name."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from dev_lab.dev import deptable, ownerdag

if TYPE_CHECKING:
    from pathlib import Path

_GIT = shutil.which('git') or 'git'
DECLARED = """
[python.owners]
alpha = []
beta = ["alpha"]
gamma = ["alpha", "beta"]

[python.siblings.alpha]
two = ["one"]

[python.importers]
"alpha/formats" = ["gamma", "tests"]

[python.native]
kernel = "beta"

[python.packages]
numpy = { owners = ["*"], reason = "arrays" }
"fam.log" = { owners = ["src/pkg/gamma", "tests"], reason = "the one log" }

[python.stdlib]
"os.environ" = { owners = [], reason = "explicit configuration only" }
subprocess = { owners = ["src/pkg/gamma/run.py"], reason = "launching tools" }
"""
#: The tree every case starts from: three owners, each with a module and (alpha) two child packages.
BASE = {
    'pyproject.toml': '[project]\nname = "pkg"\n',
    'src/pkg/__init__.py': '',
    'src/pkg/alpha/__init__.py': '',
    'src/pkg/alpha/one/__init__.py': '',
    'src/pkg/alpha/one/x.py': 'from pkg.alpha import common\n',
    'src/pkg/alpha/two/__init__.py': '',
    'src/pkg/alpha/two/y.py': 'from pkg.alpha.one import x\n',  # declared in [python.siblings.alpha]
    'src/pkg/alpha/formats/__init__.py': '',
    'src/pkg/gamma/emit.py': 'from pkg.alpha.formats import read\n',  # a listed importer
    'tests/test_formats.py': 'from pkg.alpha import formats\n',  # a listed importer outside every owner
    'src/pkg/alpha/common.py': 'import numpy as np\nimport os\nos.path.join("a")\n',
    'src/pkg/beta/__init__.py': 'from pkg.alpha import common\nfrom pkg_native import kernel\n',
    'src/pkg/gamma/__init__.py': 'from pkg.beta import f\nfrom fam.log import emit\n',
    'src/pkg/gamma/run.py': 'import subprocess\n',
    'tests/test_x.py': 'from tests import helpers\nfrom fam.log import emit\n',
    'tests/helpers.py': '',
}


def _tree(root: Path, extra: dict[str, str] | None = None, declared: str = DECLARED) -> list[str]:
    files = {**BASE, deptable.FILE: declared, **(extra or {})}
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding='utf-8')
    return [rel for rel, text in files.items() if text is not None]


def _problems(root: Path, extra: dict[str, str] | None = None, declared: str = DECLARED) -> list[str]:
    files = _tree(root, extra, declared)
    decl = deptable.load(root)
    assert decl is not None
    return ownerdag.problems(root, decl, files)


def test_the_declared_tree_passes(tmp_path: Path) -> None:
    """THE PLANTED CONTROL for every refusal below: the base tree, unchanged, is judged clean."""
    assert _problems(tmp_path) == []


@pytest.mark.parametrize(
    ('extra', 'named'),
    [
        ({'src/pkg/alpha/up.py': 'from pkg.gamma import g\n'}, 'owner alpha imports pkg.gamma.g (owner gamma)'),
        ({'src/pkg/beta/b.py': 'import pkg.gamma\n'}, 'owner beta imports pkg.gamma (owner gamma)'),
        (
            {'src/pkg/alpha/one/z.py': 'from ..two import y\n'},
            'alpha/one imports its sibling alpha/two, but [python.siblings."alpha"] one does not list two',
        ),
        (
            {'src/pkg/alpha/one/b/m.py': 'from ..a import f\n', 'src/pkg/alpha/one/a/__init__.py': ''},
            'alpha/one/b imports its sibling alpha/one/a, but [python.siblings."alpha/one"] b does not list a',
        ),
        (
            {'src/pkg/beta/f.py': 'from pkg.alpha.formats import read\n'},
            'imports pkg.alpha.formats.read, but [python.importers] "alpha/formats" allows only gamma, tests',
        ),
        ({'scripts/tool.py': 'import pkg.alpha.formats\n'}, '[python.importers] "alpha/formats" allows only'),
        ({'src/pkg/alpha/n.py': 'from pkg_native import kernel\n'}, 'pkg_native.kernel, whose crate kernel'),
        ({'src/pkg/beta/n.py': 'from pkg_native import other\n'}, 'other is no [python.native] row'),
        ({'src/pkg/beta/n.py': 'import pkg_native\n'}, 'the bare native module pkg_native'),
        ({'src/pkg/delta/__init__.py': ''}, 'src/pkg/delta is an owner no [python.owners] row names'),
        ({'src/pkg/alpha/s.py': 'import scipy.linalg\n'}, 'scipy.linalg, which no [python.packages] row names'),
        ({'src/pkg/alpha/s.py': 'from fam.log import emit\n'}, '[python.packages] fam.log allows it only in'),
        ({'src/pkg/alpha/s.py': 'import os\nos.environ.get("X")\n'}, 'os.environ.get, but [python.stdlib] os.environ'),
        ({'tests/test_env.py': 'from os import environ\n'}, '[python.stdlib] os.environ allows it only in nowhere'),
        ({'src/pkg/gamma/other.py': 'import subprocess\n'}, '[python.stdlib] subprocess allows it only in'),
    ],
)
def test_each_refusal_names_the_file_the_name_and_the_row(tmp_path: Path, extra: dict[str, str], named: str) -> None:
    found = _problems(tmp_path, extra)
    assert len(found) == 1, found
    assert named in found[0]
    assert found[0].split(' ')[0].rstrip(':') in next(iter(extra))


def test_a_row_naming_no_owner_in_the_tree_is_refused(tmp_path: Path) -> None:
    stale = DECLARED.replace('gamma = ["alpha", "beta"]', 'gamma = ["alpha", "beta"]\nghost = []')
    assert _problems(tmp_path, declared=stale) == ['[python.owners] ghost names no package src/pkg/ghost']


def test_a_file_that_does_not_parse_is_refused_not_passed(tmp_path: Path) -> None:
    found = _problems(tmp_path, {'src/pkg/alpha/broken.py': 'def (:\n'})
    assert found == [found[0]]
    assert found[0].startswith('src/pkg/alpha/broken.py: does not parse (SyntaxError')


def test_a_siblings_or_importers_row_naming_nothing_in_the_tree_is_refused(tmp_path: Path) -> None:
    stale = DECLARED.replace('two = ["one"]', 'two = ["ghost"]\n[python.siblings."alpha/gone"]\nx = []').replace(
        '"alpha/formats" = ["gamma", "tests"]', '"alpha/formats" = ["gamma", "tests"]\n"alpha/lost" = ["nowhere"]'
    )
    found = _problems(tmp_path, declared=stale)
    assert '[python.siblings."alpha"] names ghost, which is no child package of src/pkg/alpha' in found
    assert '[python.siblings."alpha/gone"] names no package src/pkg/alpha/gone' in found
    assert '[python.importers] "alpha/lost" names no path under src/pkg/' in found
    assert '[python.importers] "alpha/lost" names importer nowhere, which is no path in the tree' in found


def test_a_holder_path_naming_nothing_in_the_tree_is_refused(tmp_path: Path) -> None:
    stale = DECLARED.replace('owners = ["src/pkg/gamma", "tests"]', 'owners = ["src/pkg/gone"]')
    found = _problems(tmp_path, declared=stale)
    assert '[python.packages] fam.log names src/pkg/gone, which is no path in the tree' in found


def test_python_tables_need_the_package_the_project_names(tmp_path: Path) -> None:
    found = _problems(tmp_path, {'pyproject.toml': '[project]\nname = "other"\n'})
    assert len(found) == 1
    assert 'src/other' in found[0]


def test_an_undeclared_repo_is_not_judged_and_the_cli_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert ownerdag.main([], cwd=tmp_path) == 0
    assert 'not judged' in capsys.readouterr().out
    assert ownerdag.refusal(tmp_path) is None
    ownerdag.check(tmp_path)


def test_check_and_refusal_read_the_tracked_tree(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    subprocess.run([_GIT, 'init', '-q', str(tmp_path)], check=True)
    _tree(tmp_path, {'src/pkg/alpha/up.py': 'from pkg.gamma import g\n'})
    subprocess.run([_GIT, '-C', str(tmp_path), 'add', '.'], check=True)
    with pytest.raises(AssertionError, match=r'(?s)OWNER-DAG.*src/pkg/alpha/up\.py'):
        ownerdag.check(tmp_path)
    refused = ownerdag.refusal(tmp_path)
    assert refused is not None
    assert 'door:' in refused
    assert ownerdag.main([], cwd=tmp_path) == 1
    assert 'src/pkg/alpha/up.py' in capsys.readouterr().out
    (tmp_path / 'src/pkg/alpha/up.py').write_text('from pkg.alpha import common\n', encoding='utf-8')
    ownerdag.check(tmp_path)
    assert ownerdag.refusal(tmp_path) is None


def test_a_malformed_declaration_is_refused_by_check_and_refusal(tmp_path: Path) -> None:
    subprocess.run([_GIT, 'init', '-q', str(tmp_path)], check=True)
    _tree(tmp_path, declared='[python.owners]\nalpha = ["alpha"]\n')
    with pytest.raises(AssertionError, match='alpha lists itself'):
        ownerdag.check(tmp_path)
    assert 'alpha lists itself' in (ownerdag.refusal(tmp_path) or '')
