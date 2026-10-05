"""NO-REFLECTION, adopted over this repo's tracked Python by the family body.

The scan, the banned names, the attic/archived exclusion and the two-sided allow-set are
`lab_commons.dev.famtests.noreflection`'s. This module supplies this tree's reasoned boundaries and its
floor, and plants the controls the body must convict.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
from pathlib import Path

import pytest

from lab_commons.dev.famtests.noreflection import assert_no_reflection, reflection_sites

_ROOT = Path(__file__).resolve().parents[1]

#: Measured 2026-10-04: 331 tracked *.py outside attic/archived. Below it for ordinary deletion.
_FLOOR = 300

_GIT = shutil.which('git') or 'git'


#: Path -> why reflection IS the operation there.
_ALLOWED = {
    'src/lab_commons/dev/seams.py': (
        'rebind/restore_all rebind a name handed in as DATA (a Seam path) on an arbitrary owner and put '
        'the original back; the attribute name is not known to any type, so setattr is the operation'
    ),
    'src/lab_commons/structured.py': (
        'stdlib LogRecord has no extras mapping API; _record_fields reads arbitrary caller data '
        'so secret redaction retains every key. The companion guard permits exactly this one read.'
    ),
}


def test_this_tree_carries_no_reflection() -> None:
    assert_no_reflection(root=_ROOT, allowed=_ALLOWED, floor=_FLOOR)


def test_log_record_data_has_one_read_only_namespace_boundary() -> None:
    path = _ROOT / 'src/lab_commons/structured.py'
    source = path.read_text(encoding='utf-8')
    tree = ast.parse(source)
    boundary = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_record_fields')
    reads = [
        node
        for node in ast.walk(boundary)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'vars'
    ]
    assert len(reads) == 1
    assert reflection_sites(source, str(path)) == [reads[0].lineno]
    assert isinstance(reads[0].args[0], ast.Name)
    assert reads[0].args[0].id == 'record'
    returned = next(node for node in boundary.body if isinstance(node, ast.Return))
    assert isinstance(returned.value, ast.Call)
    assert ast.unparse(returned.value.func) == 'MappingProxyType'


def test_every_banned_form_is_found() -> None:
    planted = (
        'def __getattr__(name):\n'
        '    return getattr(object(), name)\n'
        'hasattr(o, "a")\nsetattr(o, "a", 1)\ndelattr(o, "a")\n'
    )
    assert reflection_sites(planted, '<planted>') == [1, 2, 3, 4, 5]


@pytest.mark.parametrize('name', ['getattr', 'hasattr', 'setattr', 'delattr', 'vars', 'dir'])
def test_builtin_reflection_is_found_through_module_and_import_aliases(name: str) -> None:
    planted = (
        'import builtins as builtin_api\n'
        f'from builtins import {name} as probe\n'
        f'builtin_api.{name}(target)\n'
        'probe(target)\n'
    )
    assert reflection_sites(planted, '<planted>') == [3, 4]


@pytest.mark.parametrize('name', ['vars', 'dir'])
def test_namespace_and_vocabulary_probes_are_reflection(name: str) -> None:
    assert reflection_sites(f'{name}(target)\n', '<planted>') == [1]


def test_namespace_access_is_reflection_including_writes() -> None:
    planted = 'state = target.__dict__\ntarget.__dict__["field"] = value\n'
    assert reflection_sites(planted, '<planted>') == [1, 2]


@pytest.mark.parametrize(
    ('module', 'name'),
    [('operator', 'attrgetter'), ('inspect', 'getmembers'), ('inspect', 'getmembers_static')],
)
def test_reflection_helpers_are_found_through_module_and_import_aliases(module: str, name: str) -> None:
    planted = (
        f'import {module} as reflection_api\n'
        f'from {module} import {name} as probe\n'
        f'reflection_api.{name}(target)\n'
        'probe(target)\n'
    )
    assert reflection_sites(planted, '<planted>') == [3, 4]


def test_a_simple_assignment_alias_keeps_its_reflection_origin() -> None:
    planted = 'import builtins as api\nprobe = api.getattr\nlookup = probe\nlookup(target, "field")\n'
    assert reflection_sites(planted, '<planted>') == [4]


@pytest.mark.parametrize('hook', ['__getattr__', '__getattribute__', '__setattr__', '__delattr__'])
def test_reflection_hooks_are_found_as_definitions_and_assignments(hook: str) -> None:
    planted = f'class Hooked:\n    def {hook}(self, name): ...\nclass Assigned:\n    {hook} = handler\n'
    assert reflection_sites(planted, '<planted>') == [2, 4]


def test_direct_object_attribute_mutation_is_reflection() -> None:
    assert reflection_sites('object.__setattr__(target, "field", value)\n', '<planted>') == [1]


@pytest.mark.parametrize(
    'source',
    [
        'monkeypatch.setattr(target, "field", value)\n',
        'archive.getmembers()\n',
        'settings.getattr(target)\n',
        'settings.vars(target)\n',
        'def getattr(value):\n    return value\ngetattr(target)\n',
        'def run(vars):\n    return vars(target)\n',
        'def run():\n    dir = user_function\n    return dir(target)\n',
        'import operator as api\ndef run(api):\n    return api.attrgetter(target)\n',
        'from inspect import getmembers as probe\ndef run(probe):\n    return probe(target)\n',
        'import builtins as api\ndef run(api):\n    return api.getattr(target)\n',
        'text = "getattr(target), vars(target), target.__dict__"\n# dir(target)\n',
    ],
)
def test_user_bindings_and_nonreflective_apis_are_not_reflection(source: str) -> None:
    assert reflection_sites(source, '<planted>') == []


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding='utf-8')
    subprocess.run([_GIT, 'init', '-q'], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run([_GIT, 'add', '.'], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def test_a_planted_site_reds_and_history_is_excluded(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        {'a.py': 'setattr(o, "x", 1)\n', 'attic/b.py': 'getattr(o, "x")\n', 'archived/c.py': 'hasattr(o, "x")\n'},
    )
    with pytest.raises(AssertionError, match=r'a\.py:1'):
        assert_no_reflection(root=root, allowed={}, floor=1)
    assert_no_reflection(root=root, allowed={'a.py': 'planted boundary'}, floor=1)


def test_a_stale_or_unreasoned_allow_entry_reds(tmp_path: Path) -> None:
    root = _repo(tmp_path, {'a.py': 'x = 1\n', 'b.py': 'getattr(o, "x")\n'})
    with pytest.raises(AssertionError, match='stale allow entries'):
        assert_no_reflection(root=root, allowed={'a.py': 'gone', 'b.py': 'kept'}, floor=1)
    with pytest.raises(AssertionError, match=r"without a reason=\['b.py'\]"):
        assert_no_reflection(root=root, allowed={'b.py': ' '}, floor=1)


def test_an_unread_tree_reds(tmp_path: Path) -> None:
    root = _repo(tmp_path, {'a.py': 'x = 1\n'})
    with pytest.raises(AssertionError):
        assert_no_reflection(root=root, allowed={}, floor=2)
