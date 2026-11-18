"""The TOML hook table and its one runner -- driven through planted repositories, never a restatement.

Planted controls: a staged-file filter that must hand a hook exactly the staged paths it selects, a
pre-push refusal that must reach git's exit through the runner, and a ref filter that must skip a hook
whose refs were not pushed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from dev_lab.dev import venvpointer, walls
from dev_lab.dev.githooks import main as githooks_main
from dev_lab.dev.githooks import runner
from dev_lab.dev.githooks.runner import (
    PUSH_URL_ENV,
    ZERO_SHA,
    borrowed_interpreter,
    parse_push_lines,
    resolve,
    run_stage,
)
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
    assert set(table) == {'pre-commit', 'commit-msg', 'pre-push', 'post-commit', 'post-merge', 'post-checkout'}
    assert {hook.id for hook in table['post-commit']} == {'host-pressure', 'stray-files'}
    # LOCAL KEEPS IRREVERSIBLE HARM AND SECOND-SCALE CHECKS (toolchain plan P3): history that only grows,
    # the published ref. The lock pin and freshness, the branch set and PR admission are the forge's.
    assert {hook.id for hook in table['pre-push']} == {
        'task-bound',
        'memory-adds',
        'session-branch',
        'milestone-base',
        'closed-pr',
        'lossless-delete',
        'pr-current',
        'pr-notices',
        'session-prs',
    }
    assert {hook.id for hook in table['commit-msg']} == {
        'conventional-commit',
        'forge-host',
        'issue-ref',
        'lab-session',
        'merge-audit',
        'merge-resolution',
    }
    assert {hook.id for hook in table['pre-commit']} == {
        'filechecks',
    }, 'the tracked-tree scans (ephemeral refs, scratch) are forge bodies, never a commit-time refusal'


def test_the_table_has_exactly_one_filechecks_row() -> None:
    """Ten per-check rows were ten interpreters per commit; one row runs them all over the staged set once."""
    rows = [
        (stage, hook.run)
        for stage, hooks in merge(base_rows(), {}).items()
        for hook in hooks
        if 'dev_lab.dev.filechecks' in hook.run
    ]
    assert rows == [('pre-commit', ('python', '-m', 'dev_lab.dev.filechecks', 'all'))]


def test_a_repo_row_merges_over_a_base_row_by_id_and_appends_a_new_one() -> None:
    layer = {
        'pre-commit': ({'id': 'filechecks', 'exclude': r'\.tsv$'}, {'id': 'ruff', 'run': ['ruff', 'check']}),
    }
    table = merge(base_rows(), layer)
    by_id = {hook.id: hook for hook in table['pre-commit']}
    assert by_id['filechecks'].exclude == r'\.tsv$'
    assert by_id['filechecks'].run[-1] == 'all', 'the merge kept the base run'
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


def test_a_repo_row_narrowing_a_retired_id_is_refused_naming_the_base_rows() -> None:
    """A consumer still narrowing a per-check id the one filechecks row replaced hears where it went."""
    with pytest.raises(HookTableError, match=r"'trailing-whitespace' names no base row.*'filechecks'"):
        merge(base_rows(), {'pre-commit': ({'id': 'trailing-whitespace', 'exclude': r'\.tsv$'},)})


def test_a_stage_git_runs_and_the_family_does_not_raises(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text(
        '[[tool.dev_lab.hooks.post-rewrite]]\nid = "x"\nrun = ["a"]\n', encoding='utf-8'
    )
    with pytest.raises(HookTableError, match='unknown hook stage'):
        hook_table(tmp_path)


def test_a_repo_layer_is_read_from_its_pyproject(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text(
        '[[tool.dev_lab.hooks.pre-push]]\nid = "pushgate"\nrun = ["python", "-m", "x"]\nalways_run = true\n',
        encoding='utf-8',
    )
    pre_push = [hook.id for hook in hook_table(tmp_path)['pre-push']]
    assert pre_push == [
        'task-bound',
        'memory-adds',
        'session-branch',
        'milestone-base',
        'closed-pr',
        'lossless-delete',
        'pr-current',
        'pr-notices',
        'session-prs',
        'pushgate',
    ]


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


def test_a_staged_file_failing_two_checks_reports_both_through_the_stage(repo: Path, capsys, monkeypatch) -> None:
    """The one filechecks row still names every check a file fails. PLANTED CONTROL: the clean file passes."""
    monkeypatch.delenv('LAB_HOOKS_VERBOSE', raising=False)
    (repo / 'bad.txt').write_bytes(b'trailing \nno newline')
    _git(repo, 'add', 'bad.txt')
    assert run_stage('pre-commit', root=repo) == 1
    said = capsys.readouterr().err
    assert '[trailing-whitespace] bad.txt:1: trailing whitespace' in said
    assert '[end-of-file] bad.txt: no newline at the end of the file' in said
    (repo / 'bad.txt').write_bytes(b'clean\n')
    _git(repo, 'add', 'bad.txt')
    assert run_stage('pre-commit', root=repo) == 0


def test_the_run_verb_runs_the_real_base_over_a_real_staged_file(repo: Path, monkeypatch) -> None:
    """End to end through the CLI: the base's trailing-whitespace check refuses, then passes."""
    monkeypatch.chdir(repo)
    monkeypatch.setattr(runner, 'borrowed_interpreter', lambda _root: False)  # it stands for a checkout's own venv
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


def test_the_base_runs_the_pr_notices_reader_before_a_pr_push_and_shows_it() -> None:
    """The push is where a session acts on its PR. ``advisory``: a notice exits 0, and the quiet runner shows it."""
    rows = [
        (stage, hook) for stage, hooks in merge(base_rows(), {}).items() for hook in hooks if hook.id == 'pr-notices'
    ]
    assert [(stage, hook.run) for stage, hook in rows] == [('pre-push', ('python', '-m', 'dev_lab.dev.branchnotices'))]
    assert rows[0][1].refs == '^refs/heads/pr/'
    assert rows[0][1].advisory


def test_the_pr_current_row_warns_and_never_refuses_a_push() -> None:
    """dev-lab #661: the forge's pr-current is an alarm, not a merge gate, so the local row may not be one."""
    [hook] = [hook for hook in merge(base_rows(), {})['pre-push'] if hook.id == 'pr-current']
    assert hook.advisory
    assert hook.refs == '^refs/heads/pr/'


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


def test_a_refusing_hook_is_a_wall_whose_remedy_is_read_off_its_own_output(repo: Path) -> None:
    """WALLS-ARE-RECORDED: a one-line failure names no door; one that says what to do does."""
    said = {'bare': 'no', 'told': 'cz: the subject is not conventional.\nWrite `feat(x): y`.'}

    def fail(argv: list[str], _cwd: Path, _stdin: str | None, _env: object) -> tuple[int, str]:
        return 1, said[argv[0]]

    hooks = (Hook(stage='commit-msg', id='bare', run=('bare',)), Hook(stage='commit-msg', id='told', run=('told',)))
    assert run_stage('commit-msg', ['.git/COMMIT_EDITMSG'], root=repo, hooks=hooks, runner=fail) == 1
    ledger = walls.ledger(repo).read_text(encoding='utf-8').splitlines()
    assert [(json.loads(one)['rule'], json.loads(one)['remedy_present']) for one in ledger] == [
        ('bare', False),
        ('told', True),
    ]


def test_a_push_names_the_branch_and_tip_it_pushes(repo: Path) -> None:
    """P0 metrics: a branch's first push is where its edit starts, so every push line names its branch."""
    sha = 'a' * 40
    pushed = f'refs/heads/pr/x {sha} refs/heads/pr/x {"0" * 40}\n'
    deleted = f'(delete) {"0" * 40} refs/heads/pr/old {"b" * 40}\n'  # PLANTED: a deletion names no edit
    assert run_stage('pre-push', ['origin', 'u'], root=repo, stdin=deleted + pushed, hooks=()) == 0
    [line] = read(PUSH, root=repo)
    assert (line['vcs.ref.head.name'], line['vcs.ref.head.revision']) == ('pr/x', sha)


def test_every_pre_push_hook_is_told_the_url_git_pushes_to(repo: Path) -> None:
    """The private-markers message scan judges by the PUSHED-TO repo's visibility; git names it only as an argument."""
    seen = _Recorder()
    hook = Hook(stage='pre-push', id='h', run=('tool',), always_run=True)
    stdin = _push_line(repo, 'refs/heads/x')
    url = 'https://example.com/o/r.git'
    assert run_stage('pre-push', ['origin', url], root=repo, stdin=stdin, hooks=(hook,), runner=seen) == 0
    assert seen.env == {PUSH_URL_ENV: url}


def _merge_in_flight(repo: Path) -> None:
    """``lane`` merging ``main``: upstream brings ``up.py``; ``both.py`` conflicts and is resolved by hand."""
    for name in ('both.py', 'mine.py'):
        (repo / name).write_text('x = 0\n', encoding='utf-8')
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-qm', 'seed', '--no-verify')
    _git(repo, 'checkout', '-qb', 'lane')
    (repo / 'both.py').write_text('x = 1\n', encoding='utf-8')
    (repo / 'mine.py').write_text('x = 1\n', encoding='utf-8')
    _git(repo, 'commit', '-qam', 'lane', '--no-verify')
    _git(repo, 'checkout', '-q', 'main')
    (repo / 'both.py').write_text('x = 2\n', encoding='utf-8')
    (repo / 'up.py').write_text('x = 2  \n', encoding='utf-8')  # upstream's own business, not the merge's
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-qm', 'upstream', '--no-verify')
    _git(repo, 'checkout', '-q', 'lane')
    done = subprocess.run([_GIT, '-C', str(repo), 'merge', '--no-edit', 'main'], capture_output=True, check=False)
    assert done.returncode, 'the planted conflict'
    (repo / 'both.py').write_text('x = 3\n', encoding='utf-8')
    _git(repo, 'add', 'both.py')


def test_a_merge_commit_hands_a_hook_only_the_paths_the_merge_itself_changes(repo: Path) -> None:
    """User ruling 2026-11-13: never the files the merge only brings in. PLANTED CONTROL: the resolution arrives."""
    _merge_in_flight(repo)
    seen = _Recorder()
    py = Hook(stage='pre-commit', id='py', run=('tool',), files=r'\.py$', pass_files=True)
    assert run_stage('pre-commit', root=repo, hooks=(py,), runner=seen) == 0
    assert [argv[1:] for argv, _ in seen.calls] == [['both.py']]


def test_a_merge_with_no_content_of_its_own_runs_no_path_hook(repo: Path) -> None:
    _merge_in_flight(repo)
    _git(repo, 'checkout', '-q', 'lane', '--', 'both.py')  # resolve to the lane's side: the merge adds nothing
    seen = _Recorder()
    py = Hook(stage='pre-commit', id='py', run=('tool',), files=r'\.py$', pass_files=True)
    assert run_stage('pre-commit', root=repo, hooks=(py,), runner=seen) == 0
    assert seen.calls == []


def test_a_pushed_merge_hands_a_pre_push_hook_only_its_own_and_the_lanes_paths(repo: Path) -> None:
    """The upstream commit is already on the remote: its ``up.py`` is not the push's. PLANTED CONTROL: lane paths."""
    _merge_in_flight(repo)
    _git(repo, 'commit', '-qm', 'merge', '--no-verify')
    tip = _git(repo, 'rev-parse', 'HEAD').strip()
    seed = _git(repo, 'rev-parse', 'main~1').strip()
    _git(repo, 'update-ref', 'refs/remotes/origin/main', 'main')
    _git(repo, 'update-ref', 'refs/remotes/origin/lane', seed)
    line = f'refs/heads/lane {tip} refs/heads/lane {seed}\n'
    seen = _Recorder()
    py = Hook(stage='pre-push', id='py', run=('tool',), files=r'\.py$', pass_files=True)
    assert run_stage('pre-push', ('origin', 'url'), root=repo, stdin=line, hooks=(py,), runner=seen) == 0
    assert sorted(seen.calls[0][0][1:]) == ['both.py', 'mine.py']


def test_under_a_borrowed_interpreter_a_bootstrapping_row_runs_and_names_the_door(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """2026-11-13: a new worktree had no venv, every row skipped, and the venv never came.

    PLANTED control: beside it a row needing the checkout's own venv does not run on the borrowed one.
    """
    seen = _Recorder()
    follow = Hook(
        stage='post-checkout', id='venv-follows-lock', run=('python', '-m', 'x'), always_run=True, bootstraps=True
    )
    other = Hook(stage='post-checkout', id='reclaim', run=('python', '-m', 'y'), always_run=True)
    assert run_stage('post-checkout', root=repo, hooks=(follow, other), runner=seen, borrowed=True) == 0
    assert [argv[-1] for argv, _ in seen.calls] == ['x']
    said = capsys.readouterr().err
    assert 'this checkout has no venv -- venv-follows-lock bootstraps it' in said
    assert f'-m dev_lab.dev.dep --bootstrap {repo.as_posix()}' in said


def test_under_a_borrowed_interpreter_a_judged_stage_is_refused_naming_the_door(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """dev-lab #639: no venv of its own (or a half one) is a refusal with its door, never a silent skip."""
    seen = _Recorder()
    row = Hook(stage='pre-commit', id='task-bound', run=('python', '-m', 'x'), always_run=True)
    assert run_stage('pre-commit', root=repo, hooks=(row,), runner=seen, borrowed=True) == 1
    assert seen.calls == []
    said = capsys.readouterr().err
    assert 'refused' in said
    assert f'-m dev_lab.dev.dep --bootstrap {repo.as_posix()}' in said
    assert run_stage('pre-commit', root=repo, hooks=(row,), runner=seen) == 0, 'PLANTED CONTROL: its own venv runs it'
    assert len(seen.calls) == 1


def test_the_running_interpreter_is_borrowed_unless_it_is_the_checkouts_own(repo: Path) -> None:
    assert borrowed_interpreter(repo)
    # The checkout these tests run from runs them in its own environment, `.venv` or a published `.venvs/<id>`: the
    # interpreter's parent is the checkout only in the first layout, so the control names the checkout, not the prefix.
    checkout = Path(__file__).resolve().parents[1]
    assert not borrowed_interpreter(checkout), 'PLANTED CONTROL: the checkout whose own environment runs this'


def test_a_legacy_venv_the_pointer_passed_over_is_not_the_checkouts_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One rule names a checkout's environment (``venvpointer.current``): no second ``.venv`` spelling beside it."""
    root = tmp_path / 'main'
    legacy, current = root / venvpointer.ALIAS, root / venvpointer.HOME / 'x'
    legacy.mkdir(parents=True)
    current.mkdir(parents=True)
    (root / venvpointer.POINTER).write_text('x\n', encoding='utf-8')
    monkeypatch.setattr(sys, 'prefix', str(legacy))
    assert borrowed_interpreter(root), 'the pointer names .venvs/x: the legacy directory is not current'
    monkeypatch.setattr(sys, 'prefix', str(current))
    assert not borrowed_interpreter(root)
    (root / venvpointer.POINTER).unlink()
    monkeypatch.setattr(sys, 'prefix', str(legacy))
    assert not borrowed_interpreter(root), 'PLANTED CONTROL: no pointer: .venv is the checkout own'


@pytest.mark.parametrize(
    ('stage', 'row'),
    [
        ('pre-push', 'task-bound'),
        ('commit-msg', 'merge-audit'),
        ('commit-msg', 'merge-resolution'),
    ],
)
def test_every_named_base_row_actually_runs(repo: Path, stage: str, row: str) -> None:
    """dev-lab #639: a filter on ``python -m lab_commons`` skipped every one of these since the rename."""
    seen = _Recorder()
    args = {'commit-msg': ['.git/COMMIT_EDITMSG'], 'pre-push': ['origin', 'url']}.get(stage, [])
    stdin = _push_line(repo, 'refs/heads/main') if stage == 'pre-push' else ''
    run_stage(stage, args, root=repo, stdin=stdin, runner=seen)
    ran = {' '.join(argv) for argv, _ in seen.calls}
    [hook] = [hook for hook in hook_table(repo)[stage] if hook.id == row]
    assert any(' '.join(hook.run[1:]) in line for line in ran), (row, ran)


def test_the_base_venv_follow_row_bootstraps_a_checkout_with_no_venv() -> None:
    [hook] = [hook for hook in merge(base_rows(), {})['post-checkout'] if hook.id == 'venv-follows-lock']
    assert hook.bootstraps


# ------------------------------------------------------------------------------------- in process

#: A planted module: it records what it was started with, then exits with the code its first argument names.
_PLANTED = """
import json, os, sys
from pathlib import Path
try:
    stdin = sys.stdin.read()
except OSError:  # an inherited stdin a test runner will not let be read
    stdin = None
Path(os.environ['PLANTED_OUT']).write_text(json.dumps({
    'argv': sys.argv[1:], 'cwd': os.getcwd(), 'stdin': stdin, 'env': os.environ.get('PLANTED_ENV'),
    'pid': os.getpid(),
}), encoding='utf-8')
print('planted says hello')
raise SystemExit(int(sys.argv[1]))
"""


def _planted(repo: Path, tmp_path: Path, name: str) -> tuple[str, Path]:
    """A module importable from *repo* (``python -m`` puts the cwd first), and where it writes what it saw."""
    (repo / f'{name}.py').write_text(_PLANTED, encoding='utf-8')
    return name, tmp_path / f'{name}.json'


def test_a_python_m_row_runs_in_process_with_its_argv_cwd_stdin_and_env(
    repo: Path, tmp_path: Path, monkeypatch
) -> None:
    """One interpreter serves the stage: the row sees what a subprocess would, and its exit is the hook's."""
    module, out = _planted(repo, tmp_path, 'planted_in_process')
    monkeypatch.setenv('PLANTED_OUT', str(out))
    stdin = _push_line(repo, 'refs/heads/main')
    hook = Hook(
        stage='pre-push', id='p', run=('python', '-m', module, '0', 'x y'), always_run=True, env={'PLANTED_ENV': 'e'}
    )
    assert runner.in_process(hook)
    cwd, argv = Path.cwd(), sys.argv[:]
    assert run_stage('pre-push', ['origin', 'url'], root=repo, stdin=stdin, hooks=(hook,)) == 0
    seen = json.loads(out.read_text(encoding='utf-8'))
    assert Path(seen.pop('cwd')) == repo
    assert seen == {'argv': ['0', 'x y'], 'stdin': stdin, 'env': 'e', 'pid': os.getpid()}
    assert (Path.cwd(), sys.argv, os.environ.get('PLANTED_ENV')) == (cwd, argv, None), 'the process state restored'


def test_an_in_process_row_s_nonzero_exit_fails_the_stage_with_its_output(
    repo: Path, tmp_path: Path, capsys, monkeypatch
) -> None:
    monkeypatch.delenv('LAB_HOOKS_VERBOSE', raising=False)
    module, out = _planted(repo, tmp_path, 'planted_refuses')
    monkeypatch.setenv('PLANTED_OUT', str(out))
    hook = Hook(stage='commit-msg', id='refuses', run=('python', '-m', module, '3'))
    assert run_stage('commit-msg', ['MSG'], root=repo, hooks=(hook,)) == 1
    said = capsys.readouterr().err
    assert 'planted says hello' in said, 'its captured output is replayed'
    assert said.rstrip().endswith('[githooks] commit-msg: 1 hook(s) failed: refuses')


def test_an_in_process_row_that_raises_fails_the_stage(repo: Path) -> None:
    """An uncaught exception is the interpreter's exit 1, traceback in the output -- never the runner's crash."""
    (repo / 'planted_raises.py').write_text('raise RuntimeError("planted")\n', encoding='utf-8')
    code, output = runner._in_process_runner([sys.executable, '-m', 'planted_raises'], repo, None, {})
    assert code == 1
    assert 'RuntimeError: planted' in output
    boom = Hook(stage='commit-msg', id='boom', run=('python', '-m', 'planted_raises'))
    assert run_stage('commit-msg', ['MSG'], root=repo, hooks=(boom,)) == 1


def test_an_isolate_row_still_runs_as_a_subprocess(repo: Path, tmp_path: Path, monkeypatch) -> None:
    """PLANTED CONTROL for the in-process row: the same module, declared ``isolate``, runs in another process."""
    module, out = _planted(repo, tmp_path, 'planted_isolated')
    monkeypatch.setenv('PLANTED_OUT', str(out))
    stdin = _push_line(repo, 'refs/heads/main')
    hook = Hook(stage='pre-push', id='iso', run=('python', '-m', module, '0'), always_run=True, isolate=True)
    assert not runner.in_process(hook)
    assert run_stage('pre-push', ['origin', 'url'], root=repo, stdin=stdin, hooks=(hook,)) == 0
    seen = json.loads(out.read_text(encoding='utf-8'))
    assert seen['pid'] != os.getpid()
    assert (seen['argv'], Path(seen['cwd']), seen['stdin']) == (['0'], repo, stdin)


def test_only_a_python_m_row_runs_in_process() -> None:
    assert runner.in_process(Hook(stage='pre-commit', id='a', run=('python', '-m', 'dev_lab.dev.filechecks', 'all')))
    assert not runner.in_process(Hook(stage='pre-commit', id='b', run=('ruff', 'check')))
    assert not runner.in_process(Hook(stage='pre-commit', id='c', run=('python', 'scripts/x.py')))


# -------------------------------------------------------------------------------------- advisory


def test_an_advisory_row_speaks_and_never_fails_the_stage(repo: Path, capsys, monkeypatch) -> None:
    """A warning or a notice is SHOWN, and is no refusal. PLANTED CONTROL: the same row unmarked fails the push."""
    monkeypatch.delenv('LAB_HOOKS_VERBOSE', raising=False)
    stdin = _push_line(repo, 'refs/heads/pr/x')

    def warn(_argv: list[str], _cwd: Path, _stdin: str | None, _env: object) -> tuple[int, str]:
        return 1, 'WARNING: behind; run forge sync\n'

    def notice(_argv: list[str], _cwd: Path, _stdin: str | None, _env: object) -> tuple[int, str]:
        return 0, '[pr-notices] a notice\n'

    advisory = Hook(stage='pre-push', id='pr-current', run=('t',), always_run=True, advisory=True)
    assert run_stage('pre-push', ['origin', 'u'], root=repo, stdin=stdin, hooks=(advisory,), runner=warn) == 0
    said = capsys.readouterr().err
    assert 'WARNING: behind; run forge sync' in said
    assert 'advisory (exit 1); not a refusal' in said
    assert run_stage('pre-push', ['origin', 'u'], root=repo, stdin=stdin, hooks=(advisory,), runner=notice) == 0
    assert '[pr-notices] a notice' in capsys.readouterr().err, 'a passing advisory row is shown too'
    assert read(REFUSAL, root=repo) == [], 'an advisory row is never a wall'
    gate = Hook(stage='pre-push', id='pr-current', run=('t',), always_run=True)
    assert run_stage('pre-push', ['origin', 'u'], root=repo, stdin=stdin, hooks=(gate,), runner=warn) == 1


# ------------------------------------------------------------------------------- one stage a check


#: Owned by the task-gating lane, which judges a commit and a push apart; not this table test's to fold.
_TWO_STAGES_OWNED_ELSEWHERE = frozenset({'dev_lab.dev.taskgate'})
#: A tree moves by a merge OR a checkout (a rebase checks out); the check keeping untracked-now-ignored files
#: must hear both, and git offers no one stage for the two.
_TWO_STAGES_BY_NATURE = frozenset({'dev_lab.dev.keepignored'})


def _modules_at_two_stages(table: dict[str, tuple[Hook, ...]]) -> dict[str, list[str]]:
    stages: dict[str, list[str]] = {}
    for stage, hooks in table.items():
        for hook in hooks:
            if (
                hook.run[:2] == ('python', '-m')
                and hook.run[2] not in _TWO_STAGES_OWNED_ELSEWHERE | _TWO_STAGES_BY_NATURE
            ):
                stages.setdefault(hook.run[2], []).append(stage)
    return {module: found for module, found in stages.items() if len(found) > 1}


def test_no_base_module_runs_at_two_stages() -> None:
    """Each check runs once, at the one stage its nature needs. PLANTED CONTROL: a duplicate row is found."""
    assert _modules_at_two_stages(merge(base_rows(), {})) == {}
    planted = {
        'post-commit': ({'id': 'again', 'run': ['python', '-m', 'dev_lab.dev.filechecks', 'all']},),
    }
    assert _modules_at_two_stages(merge(base_rows(), planted)) == {
        'dev_lab.dev.filechecks': ['pre-commit', 'post-commit']
    }
