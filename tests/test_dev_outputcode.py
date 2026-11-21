"""OUTPUT-HOLDS-NO-CODE: ``output/`` never holds code, a bundle, a patch or a checkout (user ruling 2026-11-20).

Three halves, each with its planted control: the Write/Edit refusal (a ``.py`` or ``.bundle`` under ``output/``
is refused, a log or JSON under ``output/logs`` passes), the shell deny row (its own ``refuses``/``permits``
examples, exercised by the registry tests and once here), and the source scan of ``src/`` for a door that
writes code under ``output/`` -- planted on synthetic sources that must and must not be flagged.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from dev_lab.dev import testtemp
from dev_lab.dev._deny_outputcode_row import OUTPUT_HOLDS_NO_CODE
from dev_lab.dev.codeplace import main
from dev_lab.dev.outputcode import code_doors_into_output, refuse_code_in_output

_SRC = Path(__file__).resolve().parents[1] / 'src'


@pytest.fixture(autouse=True)
def _outside_every_write_prone_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """tmp_path may sit outside the tree; WRITES-STAY-IN-THE-TREE has its own tests."""
    monkeypatch.setattr('dev_lab.dev.codeplace.refuse_outside_tree', lambda _path: None)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    (tmp_path / '.git').mkdir()
    return tmp_path


@pytest.mark.parametrize(
    ('rel', 'refused'),
    [
        ('output/logs/26/11/20/probe/probe.py', True),
        ('output/moved/lane.bundle', True),
        ('output/parked/lane/uncommitted.patch', True),
        ('output/x.TOML', True),
        ('output/a/b.ipynb', True),
        ('output/run.sh', True),
        ('.claude/worktrees/lane/output/x.rs', True),
        ('output/logs/26/11/20/gate/measure.log', False),
        ('output/logs/26/11/20/case/record.json', False),
        ('output/logs/26/11/20/case/table.csv', False),
        ('src/pkg/a.py', False),
        ('outputs/a.py', False),
    ],
)
def test_code_under_output_is_refused_and_a_log_passes(checkout: Path, rel: str, *, refused: bool) -> None:
    reason = refuse_code_in_output(checkout / rel)
    assert (reason is not None) is refused, rel
    if refused:
        assert 'OUTPUT-HOLDS-NO-CODE' in reason
        assert 'commit' in reason.lower()


def test_the_write_hook_denies_a_py_under_output_and_admits_a_log(checkout: Path, capsys) -> None:
    bad = json.dumps({'tool_name': 'Write', 'tool_input': {'file_path': str(checkout / 'output' / 'probe.py')}})
    assert main(stdin=io.StringIO(bad)) == 0
    decision = json.loads(capsys.readouterr().out)['hookSpecificOutput']
    assert decision['permissionDecision'] == 'deny'
    assert 'OUTPUT-HOLDS-NO-CODE' in decision['permissionDecisionReason']
    good = json.dumps(
        {'tool_name': 'Write', 'tool_input': {'file_path': str(checkout / 'output' / 'logs' / 'r.jsonl')}}
    )
    assert main(stdin=io.StringIO(good)) == 0
    assert 'deny' not in capsys.readouterr().out


def test_the_shell_row_refuses_its_examples_and_permits_its_controls() -> None:
    pattern = re.compile(str(OUTPUT_HOLDS_NO_CODE['pattern']))
    for line in OUTPUT_HOLDS_NO_CODE['refuses']:
        assert pattern.search(str(line)), line
    for line in OUTPUT_HOLDS_NO_CODE['permits']:
        assert not pattern.search(str(line)), line


@pytest.mark.parametrize(
    ('source', 'flagged'),
    [
        ("def f(root):\n    return output_dir(root, 'probe') / 'probe.py'\n", True),
        ("def f(root):\n    target = root / 'output' / 'moved' / 'lane.bundle'\n    return target\n", True),
        (
            "def f(r, c):\n    t = output_dir(r, 'consumer') / 'x'\n    git(c, 'worktree', 'add', str(t))\n",
            True,
        ),
        ("def f(root, c):\n    git(c, 'bundle', 'create', str(output_path(root, 'b')))\n", True),
        ("def f(root):\n    return output_dir(root, 'verify') / 'run.log'\n", False),
        ("def f(root):\n    return output_path(root, 'runcache', 'record.jsonl')\n", False),
        ("def f(c, home):\n    git(c, 'worktree', 'add', str(home / 'x'))\n", False),
    ],
)
def test_the_source_scan_flags_a_code_door_into_output_and_passes_a_log_door(source: str, *, flagged: bool) -> None:
    assert bool(code_doors_into_output(source)) is flagged, source


def test_no_door_in_src_writes_code_under_output() -> None:
    found = [
        f'{path.relative_to(_SRC).as_posix()}:{line}'
        for path in sorted(_SRC.rglob('*.py'))
        for line in code_doors_into_output(path.read_text(encoding='utf-8'))
    ]
    assert not found, f'OUTPUT-HOLDS-NO-CODE: these doors write code/bundles/checkouts under output/: {found}'


@pytest.mark.parametrize(
    ('basetemp', 'refused'),
    [('output/logs/26/11/20/pytest/s', True), ('output/x', True), ('elsewhere/s', False)],
)
def test_a_test_temp_root_under_output_is_refused_and_one_outside_is_kept(
    checkout: Path, basetemp: str, *, refused: bool
) -> None:
    """D104: a test temp dir holds planted code, so OUTPUT-HOLDS-NO-CODE has no test-temp exception (PLANTED)."""
    config = SimpleNamespace(option=SimpleNamespace(basetemp=str(checkout / basetemp)), rootpath=checkout)
    if refused:
        with pytest.raises(pytest.UsageError, match='OUTPUT-HOLDS-NO-CODE'):
            testtemp.configure(config)
    else:
        testtemp.configure(config)
        assert config.option.basetemp == str(checkout / basetemp)


def test_an_unset_test_temp_root_is_chosen_outside_every_output_tree(checkout: Path) -> None:
    config = SimpleNamespace(option=SimpleNamespace(basetemp=None), rootpath=checkout)
    testtemp.configure(config)
    assert 'output' not in Path(config.option.basetemp).resolve().parts
    assert 'output' not in Path(testtemp.script_temp_env({})['TMPDIR']).resolve().parts
