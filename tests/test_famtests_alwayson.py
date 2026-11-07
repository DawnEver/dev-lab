"""The controls for :mod:`dev_lab.dev.famtests.alwayson` -- the family rows no repo can drop.

Planted, both directions, through a REAL pytest session over a REAL git repo: a tracked CJK file is
refused, a clean tree passes, and a session outside a git checkout gets no item at all. No CJK
character is written into this file; the planted one is built with :func:`chr` from the shared ranges.
"""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from dev_lab.dev import cjk, rules
from dev_lab.dev.famtests import alwayson

pytest_plugins = ['pytester']

_CHAR = chr(cjk.CJK_RANGES[2][0])
_ROOT = Path(__file__).resolve().parents[1]
_GIT = shutil.which('git') or 'git'


def _git_repo(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    subprocess.run([_GIT, 'init', '-q'], cwd=root, check=True, timeout=60)
    subprocess.run([_GIT, 'add', '--', *files], cwd=root, check=True, timeout=60)


def _run(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.RunResult:
    # Autoload off, so the plugin is the module under test rather than whatever dev-lab is installed.
    monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    return pytester.runpytest_subprocess('-p', alwayson.__name__, '-q', '-rA', timeout=300)


def test_a_tracked_cjk_file_is_refused(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    """THE PLANTED CONTROL: a repo with no CJK test of its own still reds on a tracked CJK file."""
    _git_repo(pytester.path, {'dirty.md': f'ahead {_CHAR}\n', 'test_x.py': 'def test_x():\n    pass\n'})
    result = _run(pytester, monkeypatch)
    result.assert_outcomes(passed=1, failed=1)
    result.stdout.fnmatch_lines(['*NO-CJK-IN-TRACKED-SOURCE*', '*dirty.md*'])


def test_a_clean_tree_passes_and_exemptions_hold(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    """The other direction: exempt prefixes and a translation beside its source stay exempt."""
    _git_repo(
        pytester.path,
        {
            'clean.md': 'plain\n',
            'page.md': 'english\n',
            'page.zh.md': f'{_CHAR}\n',
            'attic/old.py': f'# {_CHAR}\n',
            'test_x.py': 'def test_x():\n    pass\n',
        },
    )
    _run(pytester, monkeypatch).assert_outcomes(passed=2)


def test_an_orphaned_translation_is_refused(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    _git_repo(pytester.path, {'lone.zh.md': f'{_CHAR}\n', 'test_x.py': 'def test_x():\n    pass\n'})
    result = _run(pytester, monkeypatch)
    result.assert_outcomes(passed=1, failed=1)
    result.stdout.fnmatch_lines(['*ORPHANED TRANSLATION*lone.zh.md*'])


def test_no_item_outside_a_git_checkout(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    """A session rooted outside any checkout (a pytester tree) has no tracked corpus to judge."""
    pytester.makepyfile(test_x='def test_x():\n    pass\n')
    _run(pytester, monkeypatch).assert_outcomes(passed=1)


def test_the_plugin_is_an_entry_point() -> None:
    """Installed is enforced: the plugin rides pytest's own entry-point autoload, not a consumer file."""
    project = tomllib.loads((_ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    assert project['project']['entry-points']['pytest11'] == {'dev_lab_family': alwayson.__name__}


def test_an_always_on_rule_cannot_be_waived_or_copied() -> None:
    """No opt-out and no per-repo row: the family plugin is the one mechanism."""
    assert 'NO-CJK-IN-TRACKED-SOURCE' in rules.ALWAYS_ON
    with pytest.raises(ValueError, match='always on'):
        rules.Adoption(app_name='x', declared_absent=frozenset({'NO-CJK-IN-TRACKED-SOURCE'}))
    with pytest.raises(ValueError, match='always on'):
        rules.Adoption(app_name='x', mechanisms={'NO-CJK-IN-TRACKED-SOURCE': (rules.guard('tests/t.py'),)})
    assert 'NO-CJK-IN-TRACKED-SOURCE' not in rules.unadopted(rules.RULES, rules.Adoption(app_name='x'))
