"""The serve runs a data PR's consumer tests in the consumer's own checkout and posts them on the data PR."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import datadeps, forgedataruns, forgeoutbox
from dev_lab.dev._forge_records import PullRequest

URL = 'https://forge.example.org/team/recipes.git'
_GIT = shutil.which('git') or 'git'
PIN = 'a' * 40
PYTHON = Path('/venv/bin/python')
HEAD = 'b' * 40
PYPROJECT = (
    f'[tool.dev_lab.data.recipes]\nurl = "{URL}"\nline = "integrate/main"\nrev = "{PIN}"\npath = "recipes"\n'
    'tests = ["tests/test_recipes.py"]\n'
)


def _consumer(tmp_path: Path, pyproject: str = PYPROJECT) -> Path:
    root = tmp_path / 'app'
    root.mkdir()
    (root / 'pyproject.toml').write_text(pyproject, encoding='utf-8')
    subprocess.run([_GIT, 'init', '-q', str(root)], check=True)
    subprocess.run([_GIT, '-C', str(root), 'add', '-A'], check=True)
    subprocess.run(
        [_GIT, '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'init'], check=True
    )
    return root


def _pull(sha: str = HEAD) -> PullRequest:
    return PullRequest(7, 'recipe', 'open', '', f'{URL}/pulls/7', 'someone', 'pr/x', 'integrate/main', head_sha=sha)


class _Calls:
    def __init__(self, code: int = 0) -> None:
        self.code, self.ran, self.scanned = code, [], []

    def pulls(self, url: str) -> tuple[PullRequest, ...]:
        self.scanned.append(url)
        return (_pull(),)

    def execute(self, argv: list[str], cwd: Path, env: dict[str, str]) -> int:
        self.ran.append((argv, cwd, dict(env)))
        return self.code if argv[-1].endswith('.py') else 0


def _step(root: Path, calls: _Calls, decided: frozenset[str] = frozenset()) -> list[str]:
    said: list[str] = []
    forgedataruns.step(
        root, 'app', pulls=calls.pulls, decided=lambda _url, _sha: decided, execute=calls.execute,
        interpreter=lambda _root: PYTHON, say=said.append,
    )  # fmt: skip
    return said


def test_a_data_pr_runs_the_consumer_tests_and_queues_the_status_on_the_data_repo(tmp_path: Path) -> None:
    root = _consumer(tmp_path)
    calls = _Calls(code=1)
    _step(root, calls)
    verify = [argv for argv, _cwd, _env in calls.ran if 'dev_lab.dev.verify' in argv]
    assert verify == [[str(PYTHON), '-m', 'dev_lab.dev.verify', '--', 'tests/test_recipes.py']]
    assert all(cwd == root for _argv, cwd, _env in calls.ran)
    assert all(env[datadeps.OVERRIDE] == f'recipes={HEAD}' for argv, _cwd, env in calls.ran if argv[-1] != 'sync')
    (post,) = forgeoutbox.queued(root)
    assert (post.sha, post.context, post.state, post.repo) == (HEAD, 'tests/consumer:app', 'failure', URL)


def test_the_interpreter_is_the_consumers_own_never_a_bare_python(tmp_path: Path) -> None:
    root = _consumer(tmp_path)
    calls = _Calls()
    _step(root, calls)
    assert calls.ran
    assert all(argv[0] == str(PYTHON) for argv, _cwd, _env in calls.ran)


def test_the_run_never_edits_the_consumer_tree_or_moves_its_pin(tmp_path: Path) -> None:
    root = _consumer(tmp_path)
    _step(root, _Calls())
    assert (root / 'pyproject.toml').read_text(encoding='utf-8') == PYPROJECT  # PLANTED CONTROL: the pin stays
    status = subprocess.run([_GIT, '-C', str(root), 'status', '--porcelain', '--untracked-files=no'],
                            capture_output=True, text=True, encoding='utf-8', check=True).stdout  # fmt: skip
    assert status == ''
    restore = [env for argv, _cwd, env in calls_last(root) if argv[-1] == 'sync']
    assert restore, 'the copy is put back on the pin after the run'


def calls_last(root: Path) -> list[tuple[list[str], Path, dict[str, str]]]:
    calls = _Calls()
    _step(root, calls)
    return [(argv, cwd, env) for argv, cwd, env in calls.ran if datadeps.OVERRIDE not in env]


def test_a_consumer_with_no_data_row_scans_nothing(tmp_path: Path) -> None:
    root = _consumer(tmp_path, '[project]\nname = "plain"\n')
    calls = _Calls()
    assert _step(root, calls) == []
    assert calls.scanned == []  # PLANTED CONTROL: no data row, no scan
    assert calls.ran == []


def test_a_head_already_judged_is_not_run_again(tmp_path: Path) -> None:
    root = _consumer(tmp_path)
    calls = _Calls()
    _step(root, calls, decided=frozenset({'tests/consumer:app'}))
    assert calls.ran == []
    assert forgeoutbox.queued(root) == ()


def test_a_post_to_another_repository_is_keyed_apart_from_the_origins(tmp_path: Path) -> None:
    root = _consumer(tmp_path)
    forgeoutbox.enqueue(root, forgeoutbox.Post(HEAD, 'tests/consumer:app', 'success', 'v', repo=URL))
    forgeoutbox.enqueue(root, forgeoutbox.Post(HEAD, 'tests/consumer:app', 'success', 'v'))
    assert sorted(post.repo for post in forgeoutbox.queued(root)) == ['', URL]


@pytest.mark.parametrize('state', ['success', 'failure'])
def test_the_consumer_status_names_its_result(tmp_path: Path, state: str) -> None:
    root = _consumer(tmp_path)
    _step(root, _Calls(code=0 if state == 'success' else 1))
    (post,) = forgeoutbox.queued(root)
    assert post.state == state
