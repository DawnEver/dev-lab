"""``vendor_jobs``: a NAMED program's job tree ``output/logs/<yy>/<mm>/<dd>/vendor/<program>/`` goes unjudged.

A simulation program reads its model and driver scripts from disk beside its own files (``.py`` for an AEDT
driver, ``.lua`` for FEMM, ``.m`` for MATLAB), so the layout scan leaves a declared program's job tree unjudged,
code suffixes included -- the exemption symmetric to ``tool_caches``. The write hook sees AGENT tool calls only, so
the program's driver writing there at run time is never hooked; an agent's own Write/Edit into a job tree is
refused, naming the driver as the door. Every check carries its planted control: an undeclared program is judged,
a malformed entry reds at load, code under any other output kind stays refused, and the hook is shown both ways.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest

from dev_lab.dev import codeplace
from dev_lab.dev._deny_outputcode_row import OUTPUT_HOLDS_NO_CODE
from dev_lab.dev._layout_table import LayoutNotDeclared, declared_layout
from dev_lab.dev.layout import layout_violations, refuse_layout
from dev_lab.dev.outputcode import refuse_code_in_output
from tests.test_dev_layout import _HOMES, _checkout, _plant

_DAY = 'output/logs/26/11/25'
_BODY = f"""vendor_jobs = ['jmag', 'aedt', 'femm', 'matlab', 'c_compiler']
[layout]
{_HOMES}rust = ['.rs', '.toml']
"""
#: Each declared program's tree: the emitted scripts beside the program's own files, at any depth.
_JOB_FILES = (
    f'{_DAY}/vendor/aedt/job-1/model.py',
    f'{_DAY}/vendor/aedt/job-1/model.aedtresults/solution.sol',
    f'{_DAY}/vendor/femm/job-2/drive.lua',
    f'{_DAY}/vendor/femm/job-2/model.fem',
    f'{_DAY}/vendor/matlab/run.m',
    f'{_DAY}/vendor/matlab/run.slx',
    f'{_DAY}/vendor/jmag/model.jproj',
    f'{_DAY}/vendor/c_compiler/kernel.c',
)


def _hook(path: Path, monkeypatch) -> dict:
    """The ``codeplace`` write hook's decision on an agent Write of *path* (``{}`` when admitted)."""
    # tmp_path lies under the OS temp dir, which WRITES-STAY-IN-THE-TREE refuses first; this file is about layout.
    monkeypatch.setattr(codeplace, 'refuse_outside_tree', lambda _path: None)
    out = io.StringIO()
    monkeypatch.setattr('sys.stdout', out)
    payload = json.dumps({'tool_name': 'Write', 'tool_input': {'file_path': str(path), 'content': 'x'}})
    assert codeplace.main(stdin=io.StringIO(payload)) == 0
    text = out.getvalue().strip()
    return json.loads(text)['hookSpecificOutput'] if text else {}


def test_a_declared_programs_job_tree_passes_the_scan_code_suffixes_included(tmp_path) -> None:
    """PLANTED CONTROL: the same ``.py`` in an output kind that is no vendor job is named."""
    root = _checkout(tmp_path, _BODY)
    for rel in _JOB_FILES:
        _plant(root, rel)
    assert layout_violations(root)[1] == []
    _plant(root, f'{_DAY}/run/model.py')
    assert [line for line in layout_violations(root)[1] if f'{_DAY}/run' in line] != []


def test_an_undeclared_program_under_vendor_is_judged_and_refused(tmp_path) -> None:
    """Named programs only: ``plecs`` is not in ``vendor_jobs``, so its tree is an undeclared directory."""
    root = _checkout(tmp_path, _BODY)
    _plant(root, f'{_DAY}/vendor/jmag/model.jproj')
    _plant(root, f'{_DAY}/vendor/plecs/model.py')
    found = layout_violations(root)[1]
    assert [line for line in found if f'{_DAY}/vendor/plecs/' in line and 'not declared' in line] != []
    assert [line for line in found if 'vendor/jmag' in line] == []


def test_a_vendor_job_tree_is_only_the_dated_vendor_directory(tmp_path) -> None:
    """``vendor/<program>/`` anywhere else is no job tree: ``output/cache/vendor/jmag/`` is still judged."""
    root = _checkout(tmp_path, _BODY.replace('[layout]\n', "[layout]\n'output/cache' = []\n"))
    _plant(root, 'output/cache/vendor/jmag/model.py')
    assert [line for line in layout_violations(root)[1] if 'output/cache/vendor' in line] != []


@pytest.mark.parametrize('entry', ['*', 'jm*', 'jmag/sub', '../jmag', '', '[jf]mag'])
def test_a_vendor_jobs_entry_that_is_not_one_named_program_is_refused(tmp_path, entry) -> None:
    """One program per entry, never a wildcard: a glob, a path or an empty name reds at load, naming the key."""
    root = _checkout(tmp_path, _BODY.replace("'c_compiler'", f"'c_compiler', {entry!r}"))
    with pytest.raises(LayoutNotDeclared, match='vendor_jobs'):
        declared_layout(root)


def test_vendor_jobs_that_is_not_a_list_is_refused(tmp_path) -> None:
    root = _checkout(tmp_path, re.sub(r'vendor_jobs = \[[^]]*\]', "vendor_jobs = 'jmag'", _BODY))
    with pytest.raises(LayoutNotDeclared, match='vendor_jobs'):
        declared_layout(root)


def test_code_under_any_other_output_kind_is_still_refused(tmp_path, monkeypatch) -> None:
    """The exemption is the vendor tree's alone: OUTPUT-HOLDS-NO-CODE still refuses ``.py`` beside it.

    PLANTED CONTROL for the shell half: the deny row still fires on a copy of code into a vendor job tree, so a
    hand-copy has no shell road around the write hook.
    """
    root = _checkout(tmp_path, _BODY)
    probe = root / _DAY / 'run' / 'probe.py'
    assert 'OUTPUT-HOLDS-NO-CODE' in (refuse_code_in_output(probe) or '')
    assert 'OUTPUT-HOLDS-NO-CODE' in _hook(probe, monkeypatch).get('permissionDecisionReason', '')
    row = re.compile(str(OUTPUT_HOLDS_NO_CODE['pattern']))
    assert row.search(f'cp probe.py {_DAY}/run/probe.py')
    assert row.search(f'cp model.py {_DAY}/vendor/aedt/job-1/model.py')


@pytest.mark.parametrize('rel', ['vendor/aedt/job-1/model.py', 'vendor/femm/drive.lua', 'vendor/jmag/model.jproj'])
def test_an_agent_never_hand_writes_a_vendor_job(tmp_path, monkeypatch, rel) -> None:
    """The hook refuses an AGENT's Write/Edit into a declared job tree, whatever the suffix, naming the driver.

    The scan cannot tell a hand-written file from the program's, so the hook is the only place an agent's write
    there is seen; the program's driver writes at run time and no agent hook ever sees it.
    """
    root = _checkout(tmp_path, _BODY)
    target = root / _DAY / rel
    for refusal in (refuse_layout(target), _hook(target, monkeypatch).get('permissionDecisionReason')):
        assert refusal is not None
        assert 'vendor_jobs' in refusal
        assert "program's driver" in refusal


def test_the_hook_admits_outside_a_job_tree_and_gives_no_driver_door_to_an_undeclared_program(
    tmp_path, monkeypatch
) -> None:
    """The other direction: a declared output kind is admitted; an undeclared program is plain DECLARED-LAYOUT."""
    root = _checkout(tmp_path, _BODY)
    assert _hook(root / _DAY / 'run' / 'record.json', monkeypatch) == {}
    assert refuse_layout(root / 'src' / 'vendor' / 'jmag.py') is None
    undeclared = refuse_layout(root / _DAY / 'vendor' / 'plecs' / 'model.json') or ''
    assert 'not declared' in undeclared
    assert "program's driver" not in undeclared
