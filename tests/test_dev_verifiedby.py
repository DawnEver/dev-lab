"""A data repo's tests/base is its consumers' tests at its head: a broken rev fails, a good one passes."""

from __future__ import annotations

import shutil
import subprocess
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from lab_commons.outcomes import Conclusion

from dev_lab.dev import datadeps, verifiedby
from dev_lab.dev.gitenv import unlocated
from dev_lab.dev.test_outcomes import CellRecorder, outcomes_dir

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    Execute = Callable[[Path, Sequence[str], Mapping[str, str]], tuple[int, Path | None]]

_GIT_EXE = shutil.which('git') or 'git'
APP = 'https://forge.example.org/team/app.git'


def _git(cwd: Path, *argv: str) -> str:
    done = subprocess.run(
        [_GIT_EXE, '-C', str(cwd), '-c', 'user.name=t', '-c', 'user.email=t@t', *argv],
        capture_output=True, text=True, encoding='utf-8', check=True, env=unlocated(),
    )  # fmt: skip
    return done.stdout.strip()


def _commit(repo: Path, text: str) -> str:
    (repo / 'recipe.toml').write_text(text, encoding='utf-8')
    _git(repo, 'add', 'recipe.toml')
    _git(repo, 'commit', '-q', '-m', 'data: recipe')
    return _git(repo, 'rev-parse', 'HEAD')


@pytest.fixture
def world(tmp_path: Path) -> SimpleNamespace:
    """A data repo with a GOOD then a BROKEN recipe, and a consumer whose data row pins the good one."""
    data = tmp_path / 'library'
    data.mkdir()
    _git(data, 'init', '-q', '-b', 'integrate/main')
    good = _commit(data, 'sound = true\n')
    bad = _commit(data, 'sound = false\n')
    app = tmp_path / 'app'
    app.mkdir()
    _git(app, 'init', '-q', '-b', 'integrate/main')
    _git(app, 'remote', 'add', 'origin', APP)
    (app / 'tests').mkdir()
    (app / 'pyproject.toml').write_text(
        f'[tool.dev_lab.integrator]\nintegration = "integrate/main"\n\n'
        f'[tool.lab_commons.tests]\nresources = ["connection"]\n\n'
        f'[tool.dev_lab.data.recipes]\nurl = "{data.as_posix()}"\nline = "integrate/main"\n'
        f'rev = "{good}"\npath = "recipes"\n',
        encoding='utf-8',
    )
    return SimpleNamespace(data=data, url=data.as_posix(), good=good, bad=bad, app=app)


def _consumer_suite(monkeypatch: pytest.MonkeyPatch, seen: list[Sequence[str]]) -> Execute:
    """The consumer's connection test, for real: sync the data copy under the run's env, judge the recipe it reads."""

    def execute(tree: Path, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, Path | None]:
        seen.append(argv)
        monkeypatch.setenv(datadeps.OVERRIDE, env[datadeps.OVERRIDE])
        for dep in datadeps.declared(tree):
            datadeps.sync(tree, dep)
        sound = (tree / 'recipes' / 'recipe.toml').read_text(encoding='utf-8') == 'sound = true\n'
        log = tree / 'verify-1.log'
        recorder = CellRecorder(outcomes_dir(log) / 'cells-0.jsonl')
        node = 'tests/test_recipes.py::test_every_recipe_is_sound'
        for when in ('setup', 'call', 'teardown'):
            outcome = 'passed' if sound or when != 'call' else 'failed'
            recorder.pytest_runtest_logreport(
                SimpleNamespace(nodeid=node, when=when, outcome=outcome, duration=0.1, longrepr=None, keywords={})
            )
        return (0 if sound else 1), log

    return execute


def _judge(world: SimpleNamespace, head: str, execute: Execute) -> verifiedby.Judged:
    return verifiedby.judge(
        world.data, head, (verifiedby.Consumer(APP, 'connection'),), url=world.url,
        members={'app': world.app}, make=lambda _member, checkout, _root: checkout, execute=execute,
    )  # fmt: skip


def test_a_data_rev_that_breaks_the_consumer_fails(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Sequence[str]] = []
    judged = _judge(world, world.bad, _consumer_suite(monkeypatch, seen))
    assert judged.result is Conclusion.FAIL
    assert list(judged.cells) == ['app:tests/test_recipes.py::test_every_recipe_is_sound']
    assert seen == [['-m', 'dev_lab.dev.verify', '--', 'tests', '-m', 'connection']]


def test_the_same_consumer_with_a_good_rev_passes(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    judged = _judge(world, world.good, _consumer_suite(monkeypatch, []))
    assert judged.result is Conclusion.PASS


def test_a_data_repo_with_no_consumer_is_inconclusive(world: SimpleNamespace) -> None:
    assert verifiedby.declared(world.data) == ()
    judged = verifiedby.judge(world.data, world.good, (), url=world.url, members={'app': world.app})
    assert judged.result is Conclusion.INCONCLUSIVE


def test_an_exit_code_over_no_recorded_test_is_inconclusive(world: SimpleNamespace) -> None:
    judged = _judge(world, world.good, lambda _tree, _argv, _env: (0, None))
    assert judged.result is Conclusion.INCONCLUSIVE


def test_an_unregistered_or_lying_consumer_is_inconclusive(world: SimpleNamespace) -> None:
    unregistered = verifiedby.judge(
        world.data, world.good, (verifiedby.Consumer('https://forge.example.org/team/other.git', 'connection'),),
        url=world.url, members={'app': world.app},
    )  # fmt: skip
    assert unregistered.result is Conclusion.INCONCLUSIVE
    assert '[repos]' in unregistered.lines[0]
    lying = verifiedby.judge(
        world.data, world.good, (verifiedby.Consumer(APP, 'connection'),), url='https://forge.example.org/x.git',
        members={'app': world.app}, make=lambda _m, checkout, _r: checkout,
    )  # fmt: skip
    assert lying.result is Conclusion.INCONCLUSIVE
    assert 'lies' in lying.lines[0]


def test_the_declaration_is_read_and_a_malformed_row_refused(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text(
        f'[tool.dev_lab.verify]\nby = [{{repo = "{APP}", part = "connection"}}]\n', encoding='utf-8'
    )
    assert verifiedby.declared(tmp_path) == (verifiedby.Consumer(APP, 'connection'),)
    (tmp_path / 'pyproject.toml').write_text(f'[tool.dev_lab.verify]\nby = [{{repo = "{APP}"}}]\n', encoding='utf-8')
    with pytest.raises(verifiedby.VerifyByRefused, match='exactly'):
        verifiedby.declared(tmp_path)


def test_the_judged_run_posts_as_the_data_heads_base_part(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    posted: list[dict[str, Any]] = []
    monkeypatch.setattr(verifiedby, 'record_directory', lambda _root, _commit: world.data / 'records')
    monkeypatch.setattr(verifiedby, 'post_local', lambda _root, record, _d: posted.append(record) or 'posted')
    judged = _judge(world, world.bad, _consumer_suite(monkeypatch, []))
    assert verifiedby.post(world.data, world.bad, judged) == 'posted'
    (record,) = posted
    assert (record['sha'], record['platform'], record['scope']) == (world.bad, 'base', 'full')
    assert list(record['cells']) == list(judged.cells)
    inconclusive = verifiedby.Judged(Conclusion.INCONCLUSIVE, {}, frozenset(), ())
    assert 'INCONCLUSIVE' in verifiedby.post(world.data, world.bad, inconclusive)
    assert len(posted) == 1
