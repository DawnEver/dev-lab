"""OWNER-DAG's declaration: a root ``dependencies.toml`` read by its SHAPE, every malformed row refused by name."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dev_lab.dev import deptable
from dev_lab.dev.deptable import ADDS, DependenciesError, Edge, Grant

if TYPE_CHECKING:
    from pathlib import Path

DECLARED = """
[python.owners]
alpha = []
beta = ["alpha"]
gamma = ["alpha", { name = "beta", adds = "translation" }]

[python.siblings.alpha]
one = ["two", { name = "three", adds = "policy" }]

[python.siblings."alpha/one"]
inner = ["outer"]

[python.importers]
"alpha/formats" = ["gamma/emit", "tests"]

[python.native]
kernel = "beta"

[python.packages]
numpy = { owners = ["*"], reason = "arrays" }
"fam.log" = { owners = ["src/pkg/gamma"], reason = "the one log" }

[python.stdlib]
"os.environ" = { owners = [], reason = "explicit configuration only" }

[rust.crates]
core_a = []
core_b = ["core_a"]
binding = [{ name = "*", adds = "translation" }]

[rust.external]
rayon = { crates = ["core_b"], reason = "data parallelism" }
serde_json = { crates = ["*"], kind = "dev", features = ["float_roundtrip"], reason = "goldens" }

[rust.std]
"std::env" = { crates = [], reason = "explicit configuration only" }
"""


def _declare(root: Path, text: str) -> deptable.Declared | None:
    (root / deptable.FILE).write_text(text, encoding='utf-8')
    return deptable.load(root)


def test_an_undeclared_repo_is_not_judged(tmp_path: Path) -> None:
    assert not deptable.declared(tmp_path)
    assert deptable.load(tmp_path) is None


def test_every_table_of_the_shape_is_read(tmp_path: Path) -> None:
    got = _declare(tmp_path, DECLARED)
    assert got is not None
    assert got.owners['gamma'] == (Edge('alpha'), Edge('beta', 'translation'))
    assert got.native == {'kernel': 'beta'}
    assert got.siblings == {
        'alpha': {'one': (Edge('two'), Edge('three', 'policy'))},
        'alpha/one': {'inner': (Edge('outer'),)},
    }
    assert got.importers == {'alpha/formats': ('gamma/emit', 'tests')}
    assert got.packages['fam.log'] == Grant(('src/pkg/gamma',), 'the one log')
    assert got.stdlib['os.environ'] == Grant((), 'explicit configuration only')
    assert got.crates['binding'] == (Edge('*', 'translation'),)
    assert got.external['serde_json'] == Grant(('*',), 'goldens', kind='dev', features=('float_roundtrip',))
    assert got.std['std::env'].holders == ()
    assert {'translation', 'policy', 'control'} == ADDS
    assert _declare(tmp_path, '[python.owners]\nalpha = []\n') is not None  # a partial shape is a declaration


@pytest.mark.parametrize(
    ('text', 'named'),
    [
        ('[python.owners]\nalpha = ["beta"]\nbeta = ["alpha"]\n', 'cycle: alpha -> beta -> alpha'),
        ('[rust.crates]\na = ["b"]\nb = ["a"]\n', 'cycle: a -> b -> a'),
        ('[python.owners]\nalpha = ["ghost"]\n', "alpha lists 'ghost', which is no [python.owners] row"),
        ('[python.owners]\nalpha = ["alpha"]\n', 'alpha lists itself'),
        ('[python.owners]\nalpha = []\n[python.siblings.alpha]\none = ["two"]\ntwo = ["one"]\n', 'cycle: one -> two'),
        ('[python.owners]\nalpha = []\n[python.siblings.ghost]\none = []\n', "'ghost' lies under no [python.owners]"),
        ('[python.owners]\nalpha = []\n[python.siblings]\nalpha = ["x"]\n', "'alpha' must be a table"),
        ('[python.owners]\nalpha = []\n[python.importers]\n"alpha/x" = []\n', 'alpha/x must be a non-empty list'),
        ('[python.owners]\nalpha = []\n[python.importers]\n"ghost/x" = ["a"]\n', "'ghost/x' lies under no"),
        ('[python.owners]\nalpha = []\nbeta = ["alpha", "alpha"]\n', "beta lists 'alpha' twice"),
        ('[python.owners]\nalpha = []\nbeta = [{ name = "alpha", adds = "speed" }]\n', "adds 'speed'"),
        ('[python.owners]\nalpha = []\nbeta = [{ name = "alpha", why = "x" }]\n', "unknown key(s) ['why']"),
        ('[python.owners]\nalpha = "beta"\n', 'alpha must be a list'),
        ('[python.native]\nkernel = "ghost"\n', "kernel names owner 'ghost'"),
        ('[python.packages]\nnumpy = { owners = ["*"] }\n', 'numpy has no reason'),
        ('[python.packages]\nnumpy = { owners = "*", reason = "x" }\n', 'numpy owners must be a list'),
        ('[rust.external]\nrayon = { crates = [], kind = "test", reason = "x" }\n', "kind 'test'"),
        ('[python.extras]\nx = 1\n', 'unknown table [python.extras]'),
        ('[golang]\nx = 1\n', 'unknown table [golang]'),
        ('[python.owners\n', 'does not parse'),
    ],
)
def test_a_malformed_declaration_is_refused_by_name(tmp_path: Path, text: str, named: str) -> None:
    with pytest.raises(DependenciesError, match='OWNER-DAG') as caught:
        _declare(tmp_path, text)
    assert named in str(caught.value)
    assert 'dependencies.toml' in str(caught.value)
