"""``lab_commons.dev.famtests.boxneeds`` -- planted modules both ways, then the kit's own tests."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

from lab_commons.dev.famtests.boxneeds import NEEDS, UnmarkedNeed, assert_box_bodies_are_marked, unmarked

ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = '[tool.lab_commons.tests]\nresources = ["dev_checkout", "node"]\n'

_PLANTED = """
from pathlib import Path
import pytest
from lab_commons.dev.famtests import agentguard
from lab_commons.dev.famtests.worktreeplace import assert_every_worktree_stays_inside
from lab_commons.dev.famtests.visibility import assert_origin_branch_set

ROOT = Path(__file__).parent

def _guard():
    agentguard.assert_node_is_available()

def test_live_unmarked():
    assert_every_worktree_stays_inside(root=ROOT)

@pytest.mark.dev_checkout
def test_live_marked():
    assert_every_worktree_stays_inside(root=ROOT)

def test_planted_tree(tmp_path):
    assert_every_worktree_stays_inside(root=tmp_path / 'x')

def test_node_through_a_helper():
    _guard()

def test_engine_on_a_planted_tree(tmp_path):
    agentguard.assert_refused_by(root=tmp_path, command='x', rule='Y')

def test_the_refusal_is_measurable_anywhere(tmp_path):
    with pytest.raises(agentguard.GuardNotLive):
        agentguard.decision_for(root=ROOT, command='x')

def test_origin_stays_on_the_cluster():
    assert_origin_branch_set(root=ROOT, declared=frozenset())

@pytest.mark.node
class TestGrouped:
    def test_marked_on_its_class(self):
        _guard()
"""


def test_a_planted_module_is_read_both_ways() -> None:
    """PLANTED: live unmarked reds, marked/planted/origin green; node follows the body even when planted."""
    assert unmarked(_PLANTED) == {
        'test_live_unmarked': frozenset({'dev_checkout'}),
        'test_node_through_a_helper': frozenset({'node'}),
        'test_engine_on_a_planted_tree': frozenset({'node'}),
    }


def test_a_module_mark_covers_every_test() -> None:
    """``pytestmark = [pytest.mark.dev_checkout, pytest.mark.node]`` clears the whole module."""
    marked = _PLANTED.replace('ROOT = Path', 'pytestmark = [pytest.mark.dev_checkout, pytest.mark.node]\nROOT = Path')
    assert unmarked(marked) == {}


def test_the_assertion_reds_on_unmarked_undeclared_and_unread(tmp_path: Path) -> None:
    """Each refusal in turn: an unmarked test, a need the pyproject lacks, a scan under its floor."""
    (tmp_path / 'test_x.py').write_text(_PLANTED, encoding='utf-8')
    with pytest.raises(UnmarkedNeed, match=r'test_live_unmarked: mark \[.dev_checkout.\]'):
        assert_box_bodies_are_marked(tests=tmp_path, pyproject=_PYPROJECT, floor=1)
    with pytest.raises(UnmarkedNeed, match=r"lacks \['node'\]"):
        assert_box_bodies_are_marked(
            tests=tmp_path, pyproject='[tool.lab_commons.tests]\nresources = ["dev_checkout"]\n', floor=1
        )
    with pytest.raises(UnmarkedNeed, match='under the floor'):
        assert_box_bodies_are_marked(tests=tmp_path, pyproject=_PYPROJECT, floor=99)


def test_every_need_names_a_real_body() -> None:
    """A row naming a body that moved would police nothing: each must be a top-level def of its module."""
    for name in NEEDS:
        module, _, attr = name.rpartition('.')
        spec = importlib.util.find_spec(module)
        assert spec is not None, name
        assert spec.origin is not None, name
        tree = ast.parse(Path(spec.origin).read_text(encoding='utf-8'))
        assert attr in {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}, name


def test_the_kits_own_tests_mark_what_they_judge() -> None:
    """The kit adopts its own row: its tests that read this checkout or run node carry the marker."""
    assert_box_bodies_are_marked(
        tests=ROOT / 'tests', pyproject=(ROOT / 'pyproject.toml').read_text(encoding='utf-8'), floor=5
    )
