"""The TOML hook table and its one runner -- driven through planted repositories, never a restatement.

Planted controls: a staged-file filter that must hand a hook exactly the staged paths it selects, a
pre-push refusal that must reach git's exit through the runner, and a ref filter that must skip a hook
whose refs were not pushed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from dev_lab.dev.githooks import main as githooks_main
from dev_lab.dev.githooks.runner import ZERO_SHA, parse_push_lines, resolve, run_stage
from dev_lab.dev.githooks.table import STAGES, Hook, HookTableError, base_rows, hook_table, merge
from dev_lab.dev.metrics import PUSH, REFUSAL, read

_GIT = shutil.which('git') or 'git'


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        [_GIT, '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8', check=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / 'repo'
    root.mkdir()
    _git(root, 'init', '-q', '-b', 'main')
    _git(root, 'config', 'user.email', 't@example.invalid')
    _git(root, 'config', 'user.name', 't')
    _git(root, 'config', 'core.autocrlf', 'false')
    (root / 'pyproject.toml').write_text('[tool.dev_lab.hooks]\n', encoding='utf-8')
    return root


class _Recorder:
    def __init__(self, code: int = 0) -> None:
        self.calls: list[tuple[list[str], str | None]] = []
        self.code = code

    def __call__(self, argv: list[str], cwd: Path, stdin: str | None, env: dict | None = None) -> tuple[int, str]:
        self.calls.append((argv, stdin))
        self.env = env
        return self.code, f'output of {argv[0]}\n'


# ------------------------------------------------------------------------------------------- table


def test_the_base_declares_the_family_stages_with_a_floor() -> None:
    table = merge(base_rows(), {})
    assert set(table) == {'pre-commit', 'commit-msg', 'pre-push', 'post-commit'}
    assert {hook.id for hook in table['post-commit']} == {'host-pressure', 'pr-notices', 'stray-files'}
    # LOCAL KEEPS IRREVERSIBLE HARM AND SECOND-SCALE CHECKS (toolchain plan P3): history that only grows,
    # the published ref. The lock pin and freshness, the branch set and PR admission are the forge's.
    assert {hook.id for hook in table['pre-push']} == {'session-branch', 'pr-notices'}
    assert {hook.id for hook in table['commit-msg']} == {
        'commitizen',
        'forge-host',
        'issue-ref',
        'lab-session',
        'merge-audit',
        'merge-resolution',
    }
    assert {hook.id for hook in table['pre-commit']} == {
        'check-added-large-files',
        'check-ast',
        'check-case-conflict',
        'check-json',
        'check-merge-conflict',
        'check-toml',
        'debug-statements',
        'end-of-file',
        'mixed-line-ending',
        'trailing-whitespace',
    }, 'the tracked-tree scans (ephemeral refs, scratch) are forge bodies, never a commit-time refusal'


def test_a_repo_row_merges_over_a_base_row_by_id_and_appends_a_new_one() -> None:
    layer = {
        'pre-commit': ({'id': 'trailing-whitespace', 'exclude': r'\.tsv$'}, {'id': 'ruff', 'run': ['ruff', 'check']}),
    }
    table = merge(base_rows(), layer)
    by_id = {hook.id: hook for hook in table['pre-commit']}
    assert by_id['trailing-whitespace'].exclude == r'\.tsv$'
    assert by_id['trailing-whitespace'].run[-1] == 'trailing-whitespace', 'the merge kept the base run'
    assert table['pre-commit'][-1].id == 'ruff'


@pytest.mark.parametrize(
    ('stage', 'row', 'needle'),
    [
        ('pre-commit', {'id': 'x', 'run': ['a'], 'stages': ['pre-push']}, 'unknown key'),
        ('pre-commit', {'id': 'x'}, 'needs `run`'),
        ('pre-commit', {'id': 'x', 'run': ['uv', 'run', 'ruff']}, 'interpreter of its own'),
        ('commit-msg', {'id': 'x', 'run': ['a'], 'files': 'y'}, 'selects paths'),
        ('pre-commit', {'id': 'x', 'run': ['a'], 'refs': 'y'}, 'only a push names refs'),
        ('pre-commit', {'id': 'x', 'run': ['a'], 'files': '('}, 'invalid `files` regex'),
    ],
)
def test_a_declaration_the_runner_cannot_honour_raises(stage: str, row: dict, needle: str) -> None:
    assert stage in STAGES
    with pytest.raises(HookTableError, match=needle):
        merge({}, {stage: (row,)})


def test_a_stage_git_runs_and_the_family_does_not_raises(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text(
        '[[tool.dev_lab.hooks.post-merge]]\nid = "x"\nrun = ["a"]\n', encoding='utf-8'
    )
    with pytest.raises(HookTableError, match='unknown hook stage'):
        hook_table(tmp_path)


def test_a_repo_layer_is_read_from_its_pyproject(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text(
        '[[tool.dev_lab.hooks.pre-push]]\nid = "pushgate"\nrun = ["python", "-m", "x"]\nalways_run = true\n',
        encoding='utf-8',
    )
    pre_push = [hook.id for hook in hook_table(tmp_path)['pre-push']]
    assert pre_push == ['session-branch', 'pr-notices', 'pushgate']


def test_a_repo_that_does_not_opt_in_runs_no_hook(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "x"\n', encoding='utf-8')
    assert hook_table(tmp_path) == {}


def test_python_resolves_to_this_interpreter_and_a_tool_beside_it_first() -> None:
    assert resolve(['python', '-m', 'x']) == [sys.executable, '-m', 'x']
    ruff = resolve(['ruff', 'check'])[0]
    assert Path(ruff).parent == Path(sys.executable).parent, 'the venv`s ruff, never one PATH offers first'


# ----------------------------------------------------------------------------------------- runner


def test_the_pre_commit_stage_hands_a_hook_only_the_staged_paths_it_selects(repo: Path) -> None:
    """PLANTED CONTROL: a staged .py, a staged .txt and an UNSTAGED .py -- only the first may arrive."""
    for name in ('a.py', 'b.txt', 'c.py'):
        (repo / name).write_text('x = 1\n', encoding='utf-8')
    _git(repo, 'add', 'a.py', 'b.txt')
    py = Hook(stage='pre-commit', id='py', run=('tool',), files=r'\.py$', pass_files=True)
    rust = Hook(stage='pre-commit', id='rs', run=('tool',), files=r'\.rs$', pass_files=True)
    always = Hook(stage='pre-commit', id='always', run=('tool',), files=r'\.rs$', always_run=True)
    seen = _Recorder()
    assert run_stage('pre-commit', root=repo, hooks=(py, rust, always), runner=seen) == 0
    assert [argv[1:] for argv, _ in seen.calls] == [['a.py'], []], 'rs is skipped; always runs with no paths'


def test_a_hook_that_rewrites_the_working_tree_fails_the_commit(repo: Path) -> None:
    (repo / 'a.py').write_text('x = 1\n', encoding='utf-8')
    _git(repo, 'add', 'a.py')
    _git(repo, 'commit', '-qm', 'init', '--no-verify')
    (repo / 'a.py').write_text('x = 2\n', encoding='utf-8')
    _git(repo, 'add', 'a.py')

    def rewrite(_argv: list[str], cwd: Path, _stdin: str | None, _env: object) -> tuple[int, str]:
        (cwd / 'a.py').write_text('x = 3\n', encoding='utf-8')
        return 0, ''

    fmt = Hook(stage='pre-commit', id='fmt', run=('tool',), pass_files=True)
    assert run_stage('pre-commit', root=repo, hooks=(fmt,), runner=rewrite) == 1


def test_the_commit_msg_stage_appends_the_message_file(repo: Path) -> None:
    seen = _Recorder()
    hook = Hook(stage='commit-msg', id='cz', run=('cz', 'check', '--commit-msg-file'))
    assert run_stage('commit-msg', ['.git/COMMIT_EDITMSG'], root=repo, hooks=(hook,), runner=seen) == 0
    assert seen.calls[0][0][-2:] == ['--commit-msg-file', '.git/COMMIT_EDITMSG']


def _push_line(repo: Path, remote_ref: str) -> str:
    (repo / 'a.py').write_text('x = 1\n', encoding='utf-8')
    _git(repo, 'add', 'a.py')
    _git(repo, 'commit', '-qm', 'init', '--no-verify')
    head = _git(repo, 'rev-parse', 'HEAD').strip()
    return f'refs/heads/main {head} {remote_ref} {ZERO_SHA}\n'


def test_a_pre_push_refusal_reaches_git_through_the_runner(repo: Path) -> None:
    """PLANTED CONTROL: a hook refusing a push to main must turn the stage's exit non-zero."""
    stdin = _push_line(repo, 'refs/heads/main')
    refuse = Hook(
        stage='pre-push',
        id='refuse-main',
        run=('python', '-c', 'import sys; sys.exit(1 if " refs/heads/main " in sys.stdin.read() else 0)'),
        always_run=True,
        refs='^refs/heads/',
    )
    assert run_stage('pre-push', ['origin', 'url'], root=repo, stdin=stdin, hooks=(refuse,)) == 1


def test_a_push_that_publishes_nothing_runs_no_pre_push_hook(repo: Path) -> None:
    """Git runs pre-push with NO ref line when every ref is already up to date (``test_dev_netverb``).

    Netverb's retry after an attempt that landed hit exactly that, and admission refused the
    empty input "no ref to judge". PLANTED CONTROL: the same always-run hook runs on a pushed ref.
    """
    seen = _Recorder(code=2)
    admission = Hook(stage='pre-push', id='pushgate', run=('tool',), always_run=True)
    assert run_stage('pre-push', ['origin', 'url'], root=repo, stdin='', hooks=(admission,), runner=seen) == 0
    assert seen.calls == [], 'nothing pushed, nothing judged'
    stdin = _push_line(repo, 'refs/heads/main')
    assert run_stage('pre-push', ['origin', 'url'], root=repo, stdin=stdin, hooks=(admission,), runner=seen) == 1


def test_a_ref_filter_skips_a_hook_whose_refs_were_not_pushed(repo: Path) -> None:
    stdin = _push_line(repo, 'refs/tags/v1')
    seen = _Recorder(code=1)
    branch_only = Hook(stage='pre-push', id='b', run=('tool',), always_run=True, refs='^refs/heads/')
    assert run_stage('pre-push', ['origin', 'url'], root=repo, stdin=stdin, hooks=(branch_only,), runner=seen) == 0
    assert seen.calls == []


def test_the_pre_push_stage_selects_among_the_paths_the_push_changes(repo: Path) -> None:
    stdin = _push_line(repo, 'refs/heads/main')
    seen = _Recorder()
    py = Hook(stage='pre-push', id='py', run=('tool',), files=r'\.py$', pass_files=True)
    assert run_stage('pre-push', ['origin', 'url'], root=repo, stdin=stdin, hooks=(py,), runner=seen) == 0
    assert seen.calls[0][0][1:] == ['a.py']
    assert seen.calls[0][1] == stdin, "the hook reads git's own ref lines"


def test_push_lines_are_git_s_four_fields_and_a_deletion_is_recognised() -> None:
    lines = parse_push_lines(f'(delete) {ZERO_SHA} refs/heads/x {"a" * 40}\nnoise\n')
    assert len(lines) == 1
    assert lines[0].deleted


def test_the_run_verb_runs_the_real_base_over_a_real_staged_file(repo: Path, monkeypatch) -> None:
    """End to end through the CLI: the base's trailing-whitespace check refuses, then passes."""
    monkeypatch.chdir(repo)
    (repo / 'notes.txt').write_text('trailing \n', encoding='utf-8')
    _git(repo, 'add', 'notes.txt')
    assert githooks_main(['run', 'pre-commit']) == 1
    (repo / 'notes.txt').write_text('clean\n', encoding='utf-8')
    _git(repo, 'add', 'notes.txt')
    assert githooks_main(['run', 'pre-commit']) == 0


def test_a_hook_s_env_table_reaches_its_command(repo: Path) -> None:
    hook = Hook(stage='commit-msg', id='e', run=('tool',), env={'LAB_CZ_BASE_REF': 'origin/main'})
    seen = _Recorder()
    run_stage('commit-msg', ['m'], root=repo, hooks=(hook,), runner=seen)
    assert seen.env == {'LAB_CZ_BASE_REF': 'origin/main'}


def test_a_post_commit_hook_never_changes_the_commits_exit_status(repo: Path) -> None:
    """post-commit is ADVISORY: the commit exists already, so a failing row still exits 0.

    PLANTED CONTROL: the same failing row at pre-push turns that stage's exit non-zero.
    """
    seen = _Recorder(code=3)
    loud = Hook(stage='post-commit', id='pr-notices', run=('tool',), always_run=True)
    assert run_stage('post-commit', root=repo, hooks=(loud,), runner=seen) == 0
    assert seen.calls, 'the row ran'
    stdin = _push_line(repo, 'refs/heads/main')
    gate = Hook(stage='pre-push', id='pr-notices', run=('tool',), always_run=True)
    assert run_stage('pre-push', ['origin', 'url'], root=repo, stdin=stdin, hooks=(gate,), runner=seen) == 1


def test_the_base_runs_the_pr_notices_reader_after_a_commit_and_before_a_pr_push() -> None:
    rows = {stage: [r for r in base_rows()[stage] if r['id'] == 'pr-notices'] for stage in ('post-commit', 'pre-push')}
    assert [r['run'] for r in rows['post-commit']] == [['python', '-m', 'dev_lab.dev.branchnotices']]
    assert [r['run'] for r in rows['pre-push']] == [['python', '-m', 'dev_lab.dev.branchnotices', '--push']]
    assert rows['pre-push'][0]['refs'] == '^refs/heads/pr/'


# ------------------------------------------------------------------------------------------- quiet


def test_a_stage_whose_every_hook_passes_or_skips_prints_nothing(repo: Path, capsys, monkeypatch) -> None:
    """A passing hook's own output and every pass/skip line stay off the agent's screen."""
    monkeypatch.delenv('LAB_HOOKS_VERBOSE', raising=False)
    (repo / 'a.py').write_text('x = 1\n', encoding='utf-8')
    _git(repo, 'add', 'a.py')
    ran = Hook(stage='pre-commit', id='ran', run=('tool',), pass_files=True)
    skipped = Hook(stage='pre-commit', id='skipped', run=('tool',), files=r'\.rs$', pass_files=True)
    assert run_stage('pre-commit', root=repo, hooks=(ran, skipped), runner=_Recorder()) == 0
    out = capsys.readouterr()
    assert out.out + out.err == ''


def test_a_failing_hook_prints_only_its_own_output_and_one_summary(repo: Path, capsys, monkeypatch) -> None:
    """PLANTED CONTROL: the quiet runner must still show a refusal -- its text, then one summary line."""
    monkeypatch.delenv('LAB_HOOKS_VERBOSE', raising=False)
    quiet = Hook(stage='commit-msg', id='quiet', run=('ok',))
    loud = Hook(stage='commit-msg', id='loud', run=('refuser',))

    def runner(argv: list[str], _cwd: Path, _stdin: str | None, _env: object) -> tuple[int, str]:
        return (1, 'REFUSED: planted\nRemedy: fix it\n') if argv[0].endswith('refuser') else (0, 'noise\n')

    assert run_stage('commit-msg', ['m'], root=repo, hooks=(quiet, loud), runner=runner) == 1
    out = capsys.readouterr()
    assert out.out == ''
    summary = '[githooks] commit-msg: 1 hook(s) failed: loud'
    assert out.err.splitlines() == ['REFUSED: planted', 'Remedy: fix it', summary]


def test_the_verbose_env_shows_the_passes(repo: Path, capsys, monkeypatch) -> None:
    monkeypatch.setenv('LAB_HOOKS_VERBOSE', '1')
    hook = Hook(stage='commit-msg', id='cz', run=('tool',))
    assert run_stage('commit-msg', ['m'], root=repo, hooks=(hook,), runner=_Recorder()) == 0
    assert '[githooks] commit-msg cz: passed' in capsys.readouterr().out


def test_a_refusing_stage_logs_one_refusal_per_hook_and_a_push_is_counted(repo: Path) -> None:
    """P0 metrics: a refusal names its hook and stage; an advisory stage refuses nothing; every pre-push counts."""

    def fail(_argv: list[str], _cwd: Path, _stdin: str | None, _env: object) -> tuple[int, str]:
        return 1, 'no'

    bad = Hook(stage='commit-msg', id='cz', run=('cz',))
    assert run_stage('commit-msg', ['.git/COMMIT_EDITMSG'], root=repo, hooks=(bad,), runner=fail) == 1
    late = Hook(stage='post-commit', id='notes', run=('n',), always_run=True)
    assert run_stage('post-commit', root=repo, hooks=(late,), runner=fail) == 0
    assert run_stage('pre-push', ['origin', 'u'], root=repo, hooks=(), runner=fail) == 0
    assert [(line['lab.rule.id'], line['error.type']) for line in read(REFUSAL, root=repo)] == [('cz', 'commit-msg')]
    assert len(read(PUSH, root=repo)) == 1


def test_a_push_names_the_branch_and_tip_it_pushes(repo: Path) -> None:
    """P0 metrics: a branch's first push is where its edit starts, so every push line names its branch."""
    sha = 'a' * 40
    pushed = f'refs/heads/pr/x {sha} refs/heads/pr/x {"0" * 40}\n'
    deleted = f'(delete) {"0" * 40} refs/heads/pr/old {"b" * 40}\n'  # PLANTED: a deletion names no edit
    assert run_stage('pre-push', ['origin', 'u'], root=repo, stdin=deleted + pushed, hooks=()) == 0
    [line] = read(PUSH, root=repo)
    assert (line['vcs.ref.head.name'], line['vcs.ref.head.revision']) == ('pr/x', sha)
