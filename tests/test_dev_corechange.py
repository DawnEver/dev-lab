"""ZERO-CORE-CHANGE: the change-set rule and the static import rules, each with its planted controls."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from dev_lab.dev import corechange
from dev_lab.dev.corechange import Layers

if TYPE_CHECKING:
    from pathlib import Path

_GIT = shutil.which('git') or 'git'
_DECLARED = '[tool.dev_lab.layers]\ncore = ["src/pkg/core"]\napplications = "src/pkg/applications/*"\n'
LAYERS = Layers(core=('src/pkg/core',), applications='src/pkg/applications/*')


def _write(root: Path, rel: str, text: str = '') -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding='utf-8')


def _ledger(root: Path, slug: str, journal: str, *, archived: str | None = None) -> Path:
    where = root / 'archive' / archived / slug if archived else root / slug
    _write(where, 'TASK.md', '---\nstatus: open\nauthority: u1\n---\n')
    _write(where, 'JOURNAL.md', journal)
    return root


# -- the declaration (opt-in) ------------------------------------------------------------------------------------


def test_an_undeclared_repo_is_not_judged_and_a_malformed_table_is_refused(tmp_path: Path) -> None:
    assert corechange.declared_layers(tmp_path) is None  # no manifest
    _write(tmp_path, 'pyproject.toml', '[project]\nname = "x"\n')
    assert corechange.declared_layers(tmp_path) is None  # no table
    _write(tmp_path, 'pyproject.toml', '[tool.dev_lab.layers]\ncore = "src/pkg/core"\napplications = "a/*"\n')
    with pytest.raises(ValueError, match='core'):
        corechange.declared_layers(tmp_path)
    _write(tmp_path, 'pyproject.toml', '[tool.dev_lab.layers]\ncore = ["src/pkg/core"]\n')
    with pytest.raises(ValueError, match='applications'):
        corechange.declared_layers(tmp_path)
    _write(
        tmp_path,
        'pyproject.toml',
        '[tool.dev_lab.layers]\ncore = ["src/pkg/core"]\napplications = "src/pkg/applications/*"\n',
    )
    assert corechange.declared_layers(tmp_path) == LAYERS


def test_the_cli_states_an_undeclared_repo_is_not_judged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    subprocess.run([_GIT, 'init', '-q', str(tmp_path)], check=True)
    assert corechange.main(['static'], cwd=tmp_path) == 0
    assert 'not judged' in capsys.readouterr().out


# -- part 1: the change set ---------------------------------------------------------------------------------------


def test_paths_are_classified_into_core_and_application_roots() -> None:
    assert corechange.application_of('src/pkg/applications/motor/a.py', LAYERS) == 'src/pkg/applications/motor'
    assert corechange.application_of('src/pkg/applications/README.md', LAYERS) is None  # not under a root
    assert corechange.application_of('src/pkg/core/a.py', LAYERS) is None
    assert corechange.in_core('src/pkg/core/x/a.py', LAYERS)
    assert not corechange.in_core('src/pkg/corex/a.py', LAYERS)  # planted: a prefix that is not a segment


def test_trailers_are_read_from_messages() -> None:
    messages = ['feat: x\n\nArchitecture-Decision: arch-split#D3\n', 'fix: y\n\nArchitecture-Decision: nope\n']
    assert corechange.decision_trailers(messages) == [('arch-split', 3)]


def test_a_decision_must_exist_in_the_ledger(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, 'arch-split', '- 2026-11-24 D1: core grows a port\n')
    _ledger(tmp_path, 'old-task', '- 2026-11-01 D2: kept\n', archived='2026-11-02')
    assert corechange.decision_missing(ledger, 'arch-split', 1) is None
    assert corechange.decision_missing(ledger, 'old-task', 2) is None  # an archived task's decision stands
    assert 'D7' in (corechange.decision_missing(ledger, 'arch-split', 7) or '')  # planted: a made-up id
    assert 'no task' in (corechange.decision_missing(ledger, 'ghost', 1) or '')


def test_core_and_application_together_need_a_recorded_decision(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, 'arch-split', '- 2026-11-24 D1: core grows a port\n')
    both = ['src/pkg/core/a.py', 'src/pkg/applications/motor/b.py']
    assert corechange.change_set_problems(LAYERS, ['src/pkg/core/a.py'], [], ledger) == []
    assert corechange.change_set_problems(LAYERS, ['src/pkg/applications/motor/b.py'], [], ledger) == []
    red = corechange.change_set_problems(LAYERS, both, [], ledger)
    assert red
    assert 'src/pkg/applications/motor' in red[0]
    assert 'Architecture-Decision' in red[0]
    assert (
        corechange.change_set_problems(LAYERS, both, ['feat: x\n\nArchitecture-Decision: arch-split#D1'], ledger) == []
    )
    made_up = corechange.change_set_problems(LAYERS, both, ['feat: x\n\nArchitecture-Decision: arch-split#D9'], ledger)
    assert made_up
    assert 'D9' in made_up[0]


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        [_GIT, '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_a_range_is_judged_net_since_its_merge_base(tmp_path: Path) -> None:
    repo, ledger = tmp_path / 'repo', _ledger(tmp_path / 'ledger', 'arch-split', '- 2026-11-24 D1: port\n')
    _git(tmp_path, 'init', '-q', '-b', 'main', str(repo))
    _write(repo, 'src/pkg/core/a.py', 'x = 1\n')
    _write(repo, 'src/pkg/applications/motor/b.py', 'y = 1\n')
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-qm', 'chore: base')
    base = _git(repo, 'rev-parse', 'HEAD')
    _write(repo, 'src/pkg/core/a.py', 'x = 2\n')
    _git(repo, 'commit', '-qam', 'feat: core')
    _write(repo, 'src/pkg/applications/motor/b.py', 'y = 2\n')
    _git(repo, 'commit', '-qam', 'feat: app')
    assert corechange.range_problems(repo, LAYERS, base, 'HEAD', ledger)  # split over two commits: still one set
    _git(repo, 'commit', '-q', '--allow-empty', '-m', 'chore: decide\n\nArchitecture-Decision: arch-split#D1')
    assert corechange.range_problems(repo, LAYERS, base, 'HEAD', ledger) == []


# -- part 2: the static import rules ------------------------------------------------------------------------------


def _tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        _write(root, rel, text)


def test_core_never_imports_an_application(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        {
            'src/pkg/core/__init__.py': '',
            'src/pkg/core/a.py': 'from pkg.core import b\n',
            'src/pkg/applications/motor/__init__.py': 'from pkg.core import a\n',
        },
    )
    files = [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob('*.py')]
    assert corechange.static_problems(tmp_path, LAYERS, files) == []  # control: app -> core is the allowed way
    _write(tmp_path, 'src/pkg/core/b.py', 'def f():\n    from pkg.applications.motor import x\n')
    files.append('src/pkg/core/b.py')
    problems = corechange.static_problems(tmp_path, LAYERS, files)
    assert len(problems) == 1
    assert 'src/pkg/core/b.py' in problems[0]
    assert 'pkg.applications.motor' in problems[0]


def test_applications_form_an_acyclic_graph_and_a_cycle_is_named(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        {
            'src/pkg/applications/a/__init__.py': 'import pkg.applications.b\n',
            'src/pkg/applications/b/__init__.py': 'from pkg.applications import c\n',
            'src/pkg/applications/c/__init__.py': 'from . import x\n',  # its own module: no edge
        },
    )
    files = [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob('*.py')]
    assert corechange.static_problems(tmp_path, LAYERS, files) == []  # control: a chain is not a cycle
    _write(tmp_path, 'src/pkg/applications/c/y.py', 'from ...applications.a import z\n')
    files.append('src/pkg/applications/c/y.py')
    problems = corechange.static_problems(tmp_path, LAYERS, files)
    assert len(problems) == 1
    assert 'cycle' in problems[0]
    for app in ('pkg.applications.a', 'pkg.applications.b', 'pkg.applications.c'):
        assert app in problems[0]


def test_the_family_check_reds_a_declared_checkout(tmp_path: Path) -> None:
    _git(tmp_path, 'init', '-q', str(tmp_path))
    _tree(tmp_path, {'pyproject.toml': _DECLARED, 'src/pkg/core/a.py': 'x = 1\n'})
    _git(tmp_path, 'add', '.')
    corechange.check(tmp_path)
    _write(tmp_path, 'src/pkg/core/a.py', 'import pkg.applications.m\n')
    _write(tmp_path, 'src/pkg/applications/m/__init__.py')
    _git(tmp_path, 'add', '.')
    with pytest.raises(AssertionError, match='ZERO-CORE-CHANGE'):
        corechange.check(tmp_path)
