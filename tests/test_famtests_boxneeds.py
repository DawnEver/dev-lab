"""``dev_lab.dev.famtests.boxneeds`` -- planted modules both ways, then the kit's own tests."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

from dev_lab.dev.famtests.boxneeds import NEEDS, UnmarkedNeed, assert_box_bodies_are_marked, unmarked

ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = '[tool.lab_commons.tests]\nresources = ["workstation"]\n'

_PLANTED = """
from pathlib import Path
import pytest
from dev_lab.dev.famtests import agentguard, allowguard
from dev_lab.dev.famtests.worktreeplace import assert_every_worktree_stays_inside
from dev_lab.dev.famtests.visibility import assert_origin_branch_set

ROOT = Path(__file__).parent

def _guard():
    agentguard.assert_node_is_available()

def test_live_unmarked():
    assert_every_worktree_stays_inside(root=ROOT)

@pytest.mark.workstation
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

def test_allow_rows_unmarked(tmp_path):
    allowguard.assert_no_allow_contradicts(root=ROOT, sanctioned='x')
    allowguard.assert_the_scan_can_still_see(root=ROOT)
    allowguard.contradictions(tmp_path, tmp_path, cwd=tmp_path)

def test_origin_stays_on_the_cluster():
    assert_origin_branch_set(root=ROOT, declared=frozenset())

@pytest.mark.workstation
class TestGrouped:
    def test_marked_on_its_class(self):
        _guard()
"""


def test_a_planted_module_is_read_both_ways() -> None:
    """PLANTED: live unmarked reds, marked/planted/origin green; the host node follows its body via a helper.

    Driving the engine runs on the locked Node (``dev.jsrun``), so those bodies need nothing.
    """
    assert unmarked(_PLANTED) == {
        'test_live_unmarked': frozenset({'workstation'}),
        'test_node_through_a_helper': frozenset({'workstation'}),
    }


def test_a_module_mark_covers_every_test() -> None:
    """``pytestmark = pytest.mark.workstation`` clears the whole module."""
    marked = _PLANTED.replace('ROOT = Path', 'pytestmark = pytest.mark.workstation\nROOT = Path')
    assert unmarked(marked) == {}


def test_the_assertion_reds_on_unmarked_undeclared_and_unread(tmp_path: Path) -> None:
    """Each refusal in turn: an unmarked test, a need the pyproject lacks, a scan under its floor."""
    (tmp_path / 'test_x.py').write_text(_PLANTED, encoding='utf-8')
    with pytest.raises(UnmarkedNeed, match=r'test_live_unmarked: mark \[.workstation.\]'):
        assert_box_bodies_are_marked(tests=tmp_path, pyproject=_PYPROJECT, floor=1)
    with pytest.raises(UnmarkedNeed, match=r"lacks \['workstation'\]"):
        assert_box_bodies_are_marked(
            tests=tmp_path, pyproject='[tool.lab_commons.tests]\nresources = ["femm"]\n', floor=1
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
    """The kit adopts its own row: its tests that read this checkout or ask for the host node carry the marker."""
    # Floor 3 under the 4 measured 2026-10-28, after the engine-driving bodies left NEEDS (dev.jsrun).
    assert_box_bodies_are_marked(
        tests=ROOT / 'tests', pyproject=(ROOT / 'pyproject.toml').read_text(encoding='utf-8'), floor=3
    )
