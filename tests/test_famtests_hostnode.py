"""``dev_lab.dev.famtests.hostnode`` -- planted host-Node spellings both ways, then the floor."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev.famtests.hostnode import (
    EngineNotDevOnly,
    HostNode,
    assert_engine_is_dev_only,
    assert_no_host_node,
    engine_leaks,
    host_node_uses,
)

ROOT = Path(__file__).resolve().parents[1]

_PLANTED = """
import shutil, subprocess
from shutil import which
from dev_lab.dev.jsrun import run_js

node = shutil.which('node')
subprocess.run(['node', '--check'], input='x')
subprocess.run([which("node")], input='x')
subprocess.run('node -e 1', shell=True)

run_js('1')
shutil.which('git')
subprocess.run(['git', 'node'])
label = 'node'
assert line.startswith('node ')
"""


def test_a_planted_module_is_read_both_ways() -> None:
    """PLANTED: four host-Node spellings red; the helper, another tool and a bare word stay green."""
    assert host_node_uses(_PLANTED) == (6, 7, 8, 9)


def test_the_assertion_names_the_helper_and_floors(tmp_path: Path) -> None:
    """A host Node reds naming ``dev_lab.dev.jsrun``; a clean tree passes; an empty scan reds."""
    (tmp_path / 'test_x.py').write_text(_PLANTED, encoding='utf-8')
    with pytest.raises(HostNode, match=r'(?s)4 host Node use\(s\).*dev_lab\.dev\.jsrun\.run_js'):
        assert_no_host_node(tests=tmp_path, floor=1)
    (tmp_path / 'test_x.py').write_text('from dev_lab.dev.jsrun import run_js\nrun_js("1")\n', encoding='utf-8')
    assert_no_host_node(tests=tmp_path, floor=1)
    with pytest.raises(HostNode, match='under the floor'):
        assert_no_host_node(tests=tmp_path, floor=2)


_LEAKY = """
[project]
dependencies = ["numpy", "nodejs-wheel-binaries>=20"]
[project.optional-dependencies]
viz = ["dev-lab[test] @ git+https://example.invalid/dev-lab.git"]
dev = ["dev-lab[test]", "nodejs_wheel"]
cli = ["dev-lab", "dev-lab[other]"]
"""


def test_a_planted_runtime_engine_is_found_and_a_dev_extra_is_not() -> None:
    """PLANTED: the engine in the base list and a product extra reds; the dev extra and a plain dev-lab stay green."""
    assert engine_leaks(_LEAKY, dev_extras={'dev'}) == (
        'dependencies: nodejs-wheel-binaries>=20',
        'optional-dependencies.viz: dev-lab[test] @ git+https://example.invalid/dev-lab.git',
    )
    with pytest.raises(EngineNotDevOnly, match=r'2 runtime requirement\(s\)'):
        assert_engine_is_dev_only(pyproject=_LEAKY, dev_extras={'dev'})


def test_the_kit_keeps_its_engine_in_the_test_extra() -> None:
    """The kit adopts both halves: its own extra is the one dev extra, and its tests launch no host Node."""
    assert_engine_is_dev_only(pyproject=(ROOT / 'pyproject.toml').read_text(encoding='utf-8'), dev_extras={'test'})
    assert engine_leaks((ROOT / 'pyproject.toml').read_text(encoding='utf-8'), dev_extras=()) == (
        'optional-dependencies.test: nodejs-wheel-binaries',
    )
    assert_no_host_node(tests=ROOT / 'tests', floor=50)
