"""A data repo's PR runs its consumers' tests at the PR head; the consumer list is derived, never declared twice."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dev_lab.dev import dataconsumers, datadeps

if TYPE_CHECKING:
    from pathlib import Path

URL = 'https://forge.example.org/team/recipes.git'
PIN = 'a' * 40
HEAD = 'b' * 40


def _member(root: Path, name: str, *, url: str = URL, tests: str = '') -> Path:
    repo = root / name
    repo.mkdir(parents=True)
    extra = f'tests = [{tests}]\n' if tests else ''
    (repo / 'pyproject.toml').write_text(
        f'[tool.dev_lab.data.recipes]\nurl = "{url}"\nline = "integrate/main"\n'
        f'rev = "{PIN}"\npath = "recipes"\n{extra}',
        encoding='utf-8',
    )
    return repo


def test_a_consumer_is_the_member_whose_data_row_names_the_url(tmp_path: Path) -> None:
    members = {
        'app': _member(tmp_path, 'app', tests='"tests/architecture/test_recipes.py"'),
        'other': _member(tmp_path, 'other', url='https://forge.example.org/team/elsewhere.git'),
        'plain': tmp_path / 'plain',
    }
    (tmp_path / 'plain').mkdir()
    runs = dataconsumers.runs(URL + '/', HEAD, members)  # a trailing slash names the same repo
    assert [run.context for run in runs] == ['tests/consumer:app']
    (run,) = runs
    assert run.root == members['app']
    assert run.env == {datadeps.OVERRIDE: f'recipes={HEAD}'}
    assert run.argv[-2:] == ('--', 'tests/architecture/test_recipes.py')


def test_a_data_pr_with_no_consumer_posts_nothing(tmp_path: Path) -> None:
    members = {'other': _member(tmp_path, 'other', url='https://forge.example.org/team/elsewhere.git')}
    assert dataconsumers.runs(URL, HEAD, members) == ()


def test_a_consumer_that_names_no_tests_runs_its_suite(tmp_path: Path) -> None:
    (run,) = dataconsumers.runs(URL, HEAD, {'app': _member(tmp_path, 'app')})
    assert run.argv == ('python', '-m', 'dev_lab.dev.verify')


def test_the_override_is_read_only_where_it_is_given(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _member(tmp_path, 'app')
    monkeypatch.setenv(datadeps.OVERRIDE, f'recipes={HEAD}')
    assert [dep.rev for dep in datadeps.declared(repo)] == [HEAD]
    monkeypatch.delenv(datadeps.OVERRIDE)
    assert [dep.rev for dep in datadeps.declared(repo)] == [PIN]


def test_a_relock_never_writes_the_override_into_the_pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED control: a consumer run's override must not leak into the consumer's own integrate/main."""
    repo = _member(tmp_path, 'app')
    monkeypatch.setenv(datadeps.OVERRIDE, f'recipes={HEAD}')
    monkeypatch.setattr(datadeps, '_line_head', lambda _dep: PIN)
    assert datadeps.relock(repo) == ()
    assert PIN in (repo / 'pyproject.toml').read_text(encoding='utf-8')
    assert HEAD not in (repo / 'pyproject.toml').read_text(encoding='utf-8')


def test_a_malformed_override_is_refused_by_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _member(tmp_path, 'app')
    monkeypatch.setenv(datadeps.OVERRIDE, 'recipes=not-a-sha')
    with pytest.raises(datadeps.DataRefused, match=datadeps.OVERRIDE):
        datadeps.declared(repo)
