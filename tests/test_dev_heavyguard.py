"""NO-LOCAL-HEAVY, the agent's half: a declared heavy entry is refused on a workstation, admitted on a compute host.

Every arm says NO on a planted case beside its YES: the row's prefilter on the declared launch shapes and on light
commands, the ``--admit`` judge on a planted workstation and a planted compute host, and the pytest marking.
"""

from __future__ import annotations

import io
import json
from dataclasses import replace
from pathlib import Path

import pytest
from lab_commons.box.heavy import CAPABILITY, RULE, WORKSTATION
from lab_commons.config import CONFIG_ENV
from lab_commons.hostenv import HEAVY_APPROVED_ENV

from dev_lab.dev import heavyguard
from dev_lab.dev.agenthooks import engine_path, run_engine
from dev_lab.dev.disclosure import details_for, problems
from dev_lab.dev.heavyguard import Heavy, declared, heavy_rules, mark_heavy_tests
from dev_lab.dev.hooks import denies

pytest_plugins = ['pytester']

_DECLARED = """
[tool.dev_lab.heavy]
modules = ["pkg.campaign_driver"]
scripts = ["examples/tasks/design/design_workflow.py"]
bins = ["optimizer"]
"""

#: The forms a workstation must refuse, beyond the row's own derived examples.
_REFUSED = (
    'python -m pkg.campaign_driver run set.toml',
    '.venv/Scripts/python.exe -m pkg.campaign_driver.__main__ once set.toml',
    'uv run python -m pkg.campaign_driver status set.toml',
    'RAYON_NUM_THREADS=4 python examples/tasks/design/design_workflow.py --n-slot 72',
    'python ./examples/tasks/design/design_workflow.py --n-slot 72',
    'NOTE="two words" python -m pkg.campaign_driver run set.toml',
    'python D:/w/repo/examples/tasks/design/design_workflow.py',
    'cargo run --release --bin optimizer -- --cells 72',
    'cargo run --bin=optimizer',
    './target/release/optimizer --cells 72',
    f'python -m pytest -m {CAPABILITY} tests/integration',
    f"pytest -q -m '{CAPABILITY}'",
    f'.venv/Scripts/python.exe -m dev_lab.dev.verify --part {CAPABILITY}',
)
#: Light commands the row must let through.
_PERMITTED = (
    'cargo test -p wdg_core --lib',
    'cargo build --release',
    'cargo run --bin other',
    'python -m pkg.campaign_driver_tools',
    'python -m pkg.campaign_driverx',
    'python -m pytest tests/unit/test_x.py',
    f'python -m pytest -m "not {CAPABILITY}" tests',
    'git add examples/tasks/design/design_workflow.py',
    'ruff check examples/tasks/design/design_workflow.py',
    'git commit -m "python -m pkg.campaign_driver is heavy"',
    '.venv/Scripts/python.exe -m dev_lab.dev.verify -- tests/unit/test_x.py',
)


def _root(tmp_path: Path, text: str = _DECLARED) -> Path:
    (tmp_path / 'pyproject.toml').write_text(text, encoding='utf-8')
    return tmp_path


def _machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *tables: str) -> None:
    path = tmp_path / 'machine.toml'
    path.write_text(''.join(f'[capabilities.{name}]\n' for name in tables), encoding='utf-8')
    monkeypatch.setenv(CONFIG_ENV, str(path))
    monkeypatch.delenv(HEAVY_APPROVED_ENV, raising=False)


def test_the_table_is_read_and_its_defects_are_named() -> None:
    assert declared({}) is None, 'no table, no row'
    heavy = declared({'tool': {'dev_lab': {'heavy': {'modules': ['a.b'], 'bins': ['x']}}}})
    assert heavy == Heavy(modules=('a.b',), bins=('x',))
    with pytest.raises(ValueError, match="unknown key 'entry'"):
        declared({'tool': {'dev_lab': {'heavy': {'entry': ['a']}}}})
    with pytest.raises(ValueError, match='modules must be a list'):
        declared({'tool': {'dev_lab': {'heavy': {'modules': 'a.b'}}}})


def test_a_repo_declaring_nothing_ships_no_row(tmp_path: Path) -> None:
    assert heavy_rules(_root(tmp_path, '[project]\nname = "x"\n')) == ()


@pytest.fixture
def row(tmp_path: Path) -> object:
    (rule,) = heavy_rules(_root(tmp_path))
    return rule


def test_the_row_names_its_judge_and_its_door(row: object) -> None:
    rendered = row.rendered()  # type: ignore[attr-defined]
    assert rendered['name'] == RULE
    assert rendered['asks'] == 'dev_lab.dev.heavyguard'
    assert 'dev_lab.dev.forge request' in rendered['reason']
    assert 'lab_commons.hpc submit' in rendered['reason']


@pytest.mark.parametrize('command', _REFUSED)
def test_the_prefilter_catches_every_declared_launch_form(row: object, command: str) -> None:
    assert denies([row], command) == RULE  # type: ignore[list-item]


@pytest.mark.parametrize('command', _PERMITTED)
def test_the_prefilter_admits_light_commands(row: object, command: str) -> None:
    assert denies([row], command) is None  # type: ignore[list-item]


def test_the_rows_own_examples_hold(row: object) -> None:
    """The derived refuses/permits are the row's controls in every repo that renders it."""
    assert [c for c in row.refuses if denies([row], c) is None] == []  # type: ignore[attr-defined,list-item]
    assert [c for c in row.permits if denies([row], c) is not None] == []  # type: ignore[attr-defined,list-item]


def test_the_real_engine_runs_the_prefilter(row: object, tmp_path: Path) -> None:
    """The ENGINE, not a model: the row without its judge refuses a launch and admits a light command."""
    rules = tmp_path / 'deny-rules.json'
    rules.write_text(json.dumps([replace(row, asks=None).rendered()]), encoding='utf-8')  # type: ignore[type-var]
    assert RULE in (run_engine(engine_path(), 'python -m pkg.campaign_driver run s.toml', rules) or '')
    assert run_engine(engine_path(), 'cargo test -p wdg_core --lib', rules) is None


def _admit(command: str) -> tuple[int, str]:
    out = io.BytesIO()
    payload = {'tool_name': 'Bash', 'tool_input': {'command': command}}
    code = heavyguard.main(['--admit'], stdin=io.BytesIO(json.dumps(payload).encode()), stdout=out)
    return code, out.getvalue().decode('utf-8')


def test_the_judge_refuses_on_a_workstation_and_admits_on_a_compute_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PLANTED CONTROL, both answers through the real machine-file reader."""
    _machine(tmp_path, monkeypatch, WORKSTATION)
    code, said = _admit('python -m pkg.campaign_driver run s.toml')
    assert code == 1
    assert said.startswith(f'{RULE}: python -m pkg.campaign_driver')
    assert 'lab_commons.hpc submit' in said
    _machine(tmp_path, monkeypatch, WORKSTATION, CAPABILITY)
    assert _admit('python -m pkg.campaign_driver run s.toml') == (0, '')
    _machine(tmp_path, monkeypatch, CAPABILITY)
    assert _admit('python -m pkg.campaign_driver run s.toml') == (0, '')


def test_the_users_words_on_the_line_admit_one_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _machine(tmp_path, monkeypatch, WORKSTATION)
    assert _admit(f'{HEAVY_APPROVED_ENV}="run it now, I am watching" python -m pkg.campaign_driver once s')[0] == 0
    assert _admit(f'{HEAVY_APPROVED_ENV}="" python -m pkg.campaign_driver once s')[0] == 1, 'empty is no consent'


#: The inner session without the family plugin, whose own verdict on THIS host would mark the planted test too.
_ALONE = ('-p', 'no:cacheprovider', '-p', 'no:dev_lab_family')


def test_heavy_tests_become_never_run_xfails_only_where_refused(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On a refusing host the marked test never runs (its body would fail); elsewhere it runs."""
    pytester.makeini(f'[pytest]\nmarkers =\n    {CAPABILITY}: heavy\n')
    pytester.makeconftest(
        'from dev_lab.dev.heavyguard import mark_heavy_tests\n'
        'import os\n'
        'def pytest_collection_modifyitems(items):\n'
        "    mark_heavy_tests(items, why=os.environ.get('WHY') or None)\n"
    )
    pytester.makepyfile(
        f'import pytest\n@pytest.mark.{CAPABILITY}\ndef test_heavy():\n    raise AssertionError("heavy work started")\n'
        'def test_light():\n    pass\n'
    )
    monkeypatch.setenv('WHY', f'{RULE}: host box-a is a workstation')
    refused = pytester.runpytest_inprocess('-rx', *_ALONE)
    refused.assert_outcomes(passed=1, xfailed=1)
    refused.stdout.fnmatch_lines([f'*{RULE}: host box-a is a workstation*'])
    monkeypatch.delenv('WHY')
    ran = pytester.runpytest_inprocess(*_ALONE)
    ran.assert_outcomes(passed=1, failed=1)


def test_marking_counts_only_heavy_items() -> None:
    assert mark_heavy_tests([], why='x') == 0
    assert mark_heavy_tests([], why=None) == 0


def test_the_judges_refusal_has_a_refusals_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Three lines inside the refusal budget, the last the details pointer to this rule's section."""
    _machine(tmp_path, monkeypatch, WORKSTATION)
    _, said = _admit('python -m pkg.campaign_driver run ' + 'x' * 500)
    assert problems(said, 'refusal') == []
    assert said.rstrip('\n').rsplit('\n', 1)[-1] == details_for(RULE)
