"""``dev_lab.dev.liverun`` -- a checkout whose run is live refuses edits, merges and re-syncs; an idle one does not.

TWO KINDS OF CONTROL. The judgement (which process is a run of which tree, what is the tree) is driven over a
PLANTED census, both directions, at full speed. Then the whole chain is driven for real once: a real venv in
a throwaway checkout, a real sleeper executing from it, the real census, the real JS engine and the real
Edit hook -- refusing while the sleeper lives and naming its pid, silent for an idle checkout.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from lab_commons.census import Process, processes
from lab_commons.proc import kill_process_tree

from dev_lab.dev import agenthooks, dep, forgeserve, liverun
from dev_lab.dev.hook_adoption import HookAdoption, render
from dev_lab.dev.hooks import DENY_RULES, denies, rules_by_id

_SCRIPTS = 'Scripts' if os.name == 'nt' else 'bin'
_PYTHON = 'python.exe' if os.name == 'nt' else 'python'


def _checkout(path: Path) -> Path:
    (path / '.git').mkdir(parents=True)
    return path


def _proc(
    pid: int, exe: Path | str, *, ppid: int = 1, age: float | None = 600.0, cmd: str = '', cwd: Path | str | None = None
) -> Process:
    """A process; by default a sweep, whose cwd is the checkout its venv interpreter lives in."""
    where = str(Path(exe).parents[2]) if cwd is None and exe else str(cwd or '')
    return Process(pid, ppid, str(exe), cmd or f'{exe} -m motronics case sweep cases/x', age, where)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = _checkout(tmp_path / 'repo')
    _checkout(root / '.claude' / 'worktrees' / 'lane')
    return root


def _venv_python(root: Path) -> Path:
    return root / '.venv' / _SCRIPTS / _PYTHON


# ----------------------------------------------------------------------------------------- which process is a run


def test_a_sweep_reading_the_tree_locks_the_tree_and_its_venv(tree: Path) -> None:
    """PLANTED: the measured v3 shape -- venv interpreter, cwd in the tree (`-m` puts the cwd on sys.path)."""
    run = _proc(4242, _venv_python(tree))
    assert liverun.live_runs(tree, census=lambda: [run], me=1) == (run,)
    assert liverun.executing_from(tree / '.venv', census=lambda: [run], me=1) == (run,)


def test_a_serve_in_its_own_work_root_locks_the_venv_and_not_the_tree(tree: Path) -> None:
    """PLANTED: a forge serve executes from the venv and works in its own root, so the tree stays editable."""
    serve = _proc(5151, _venv_python(tree), cwd=tree / '.claude' / 'worktrees', cmd='python -m dev_lab.dev.forge serve')
    assert liverun.live_runs(tree, census=lambda: [serve], me=1) == ()
    assert liverun.executing_from(tree / '.venv', census=lambda: [serve], me=1) == (serve,)


def test_a_log_tail_in_the_tree_is_not_a_reader_and_a_script_it_names_is(tree: Path) -> None:
    """Measured: day-old `tail -F output/...` processes sit with cwd in the checkout; they read only output/."""
    (tree / 'scratch').mkdir()
    (tree / 'scratch' / 'v3_long_run.copy.sh').write_text('', encoding='utf-8')
    tail = _proc(61, '/usr/bin/tail', cwd=tree, cmd=f'tail -n 0 -F {(tree / "output" / "x.log").as_posix()}')
    chain = _proc(62, '/usr/bin/bash', cwd=tree, cmd='bash scratch/v3_long_run.copy.sh')
    assert liverun.live_runs(tree, census=lambda: [tail, chain], me=1) == (chain,)


def test_a_process_of_a_nested_worktree_or_of_no_checkout_is_not_the_mains_run(tree: Path, tmp_path: Path) -> None:
    lane = _proc(11, _venv_python(tree / '.claude' / 'worktrees' / 'lane'))
    elsewhere = _proc(12, tmp_path / 'other' / _PYTHON, cwd=tmp_path / 'other')
    unreadable = _proc(13, '', cwd='')
    census = [lane, elsewhere, unreadable]
    assert liverun.live_runs(tree, census=lambda: census, me=1) == ()
    assert liverun.live_runs(tree / '.claude' / 'worktrees' / 'lane', census=lambda: census, me=1) == (lane,)


def test_a_hook_young_process_is_not_a_run_and_an_old_one_is(tree: Path) -> None:
    """The floor: concurrent hooks start through the same interpreter and live for under a second."""
    young = _proc(21, _venv_python(tree), age=liverun.RUN_FLOOR_S / 2)
    old = _proc(22, _venv_python(tree), age=liverun.RUN_FLOOR_S * 2)
    assert liverun.live_runs(tree, census=lambda: [young, old], me=1) == (old,)


def test_the_asker_and_its_own_in_tree_family_are_not_runs(tree: Path) -> None:
    """The hook's launcher, a test's pytest workers: kin of an in-tree ancestor of the asker."""
    python = _venv_python(tree)
    launcher = _proc(30, python, ppid=2)
    me = _proc(31, '/usr/bin/python3', ppid=30, cwd=tree)
    worker = _proc(32, python, ppid=30)
    stranger = _proc(40, python, ppid=2)
    census = [launcher, me, worker, stranger]
    assert liverun.live_runs(tree, census=lambda: census, me=31) == (stranger,)


def _spawn_worker(pid: int, parent: int, tree: Path) -> Process:
    """A multiprocessing spawn child, as Windows launches it: `spawn_main(parent_pid=...)`, cwd inherited."""
    cmd = (
        '"python.exe" "-c" "from multiprocessing.spawn import spawn_main; '
        f'spawn_main(parent_pid={parent}, pipe_handle=1088)" "--multiprocessing-fork"'
    )
    return _proc(pid, _venv_python(tree), ppid=parent, cmd=cmd, cwd=tree, age=86_400.0)


def test_a_spawn_worker_whose_parent_is_gone_is_an_orphan_not_a_run(tree: Path) -> None:
    """MEASURED 2026-10-24 in a motronics worktree: two day-old spawn workers of a dead pid refused every mutation.

    A multiprocessing child serves its parent through a pipe; with the parent gone it can never advance, so it
    holds the tree's cwd and nothing else. PLANTED CONTROL: the same worker whose parent is alive is a run.
    """
    orphan = _spawn_worker(50, 45_560, tree)
    assert liverun.live_runs(tree, census=lambda: [orphan], me=1) == ()
    parent = _proc(60, _venv_python(tree))
    child = _spawn_worker(61, 60, tree)
    assert liverun.live_runs(tree, census=lambda: [parent, child], me=1) == (parent, child)


# ----------------------------------------------------------------------------------------------- what is the tree


def test_the_tree_is_the_checkout_minus_its_outputs_and_agent_state(tree: Path) -> None:
    assert liverun.in_tree(tree / 'src' / 'a.py', tree)
    assert liverun.in_tree(tree / 'pyproject.toml', tree)
    assert not liverun.in_tree(tree / 'output' / 'logs' / 'run.log', tree), 'a run writes its own logs there'
    assert not liverun.in_tree(tree / '.claude' / 'memory' / 'note.md', tree)
    assert not liverun.in_tree(tree / '.claude' / 'worktrees' / 'lane' / 'src' / 'a.py', tree), 'another checkout'


# ----------------------------------------------------------------------------------------------- the Edit hook


def _edit(path: Path, tool: str = 'Edit') -> io.StringIO:
    key = 'notebook_path' if tool == 'NotebookEdit' else 'file_path'
    return io.StringIO(json.dumps({'tool_name': tool, 'tool_input': {key: str(path)}, 'cwd': str(path.parent)}))


@pytest.mark.parametrize('tool', ['Edit', 'Write', 'MultiEdit', 'NotebookEdit'])
def test_the_hook_denies_an_edit_of_a_tree_with_a_live_run_and_names_it(
    tree: Path, tool: str, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _proc(4242, _venv_python(tree), cmd='python.exe -m motronics deck run cases/x')
    assert liverun.main(['hook'], stdin=_edit(tree / 'src' / 'a.py', tool), census=lambda: [run]) == 0
    decision = json.loads(capsys.readouterr().out)['hookSpecificOutput']
    assert decision['permissionDecision'] == 'deny'
    reason = decision['permissionDecisionReason']
    assert reason.startswith('TREE-HAS-A-LIVE-RUN:')
    assert 'pid 4242: python.exe -m motronics deck run cases/x' in reason
    assert 'another worktree' in reason


@pytest.mark.parametrize('target', ['output/logs/run.log', '.claude/memory/note.md'])
def test_the_hook_allows_writes_outside_the_tree_while_a_run_is_live(
    tree: Path, target: str, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _proc(4242, _venv_python(tree))
    assert liverun.main(['hook'], stdin=_edit(tree / target), census=lambda: [run]) == 0
    assert capsys.readouterr().out == ''


def test_the_hook_allows_an_edit_of_an_idle_tree(tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert liverun.main(['hook'], stdin=_edit(tree / 'src' / 'a.py'), census=list) == 0
    assert capsys.readouterr().out == ''


def test_the_hook_ignores_an_unreadable_payload_and_other_tools(tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run = _proc(4242, _venv_python(tree))
    assert liverun.main(['hook'], stdin=io.StringIO('not json'), census=lambda: [run]) == 0
    read = json.dumps({'tool_name': 'Read', 'tool_input': {'file_path': str(tree / 'src' / 'a.py')}})
    assert liverun.main(['hook'], stdin=io.StringIO(read), census=lambda: [run]) == 0
    assert capsys.readouterr().out == ''


def test_the_tree_mode_exits_one_naming_the_run_and_zero_when_idle(
    tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _proc(4242, _venv_python(tree))
    assert liverun.main(['--tree', str(tree / 'src')], census=lambda: [run]) == 1
    assert 'pid 4242' in capsys.readouterr().out
    assert liverun.main(['--tree', str(tree)], census=list) == 0


# --------------------------------------------------------------------------------------------- the deny row


def test_the_row_binds_only_while_a_run_is_live() -> None:
    """The registry's own text half: refused live, free idle; a read-only near-miss is free either way."""
    rule = rules_by_id(DENY_RULES)[liverun.RULE_ID]
    for command in rule.refuses:
        assert denies((rule,), command, live=True) == rule.id, command
        assert denies((rule,), command) is None, command
    for command in rule.permits:
        assert denies((rule,), command, live=True) is None, command


# --------------------------------------------------------------------------------- dep refuses a venv in use


def test_dep_refuses_an_environment_a_live_process_executes_from(tmp_path: Path) -> None:
    prefix = tmp_path / 'env'
    user = _proc(5151, prefix / _SCRIPTS / _PYTHON, cmd='python -m motronics deck run cases/x')
    ran: list[object] = []
    port = dep.Port(name='repo', anchor_paths=lambda: (), key=lambda: 'k')
    with pytest.raises(dep.HeldEnvironmentError, match=r'pid 5151: python -m motronics deck run'):
        dep._change(
            ['uv', 'sync'], port=port, prefix=str(prefix), python=None, run=ran.append, dry_run=False,
            census=lambda: [user],
        )  # fmt: skip
    assert ran == [], 'the mutation ran under a live process'


def test_dep_mutates_an_environment_nothing_executes_from(tmp_path: Path) -> None:
    prefix = tmp_path / 'env'
    elsewhere = _proc(5151, tmp_path / 'other' / _SCRIPTS / _PYTHON)
    seen: list[list[str]] = []

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, '', '')

    port = dep.Port(name='repo', anchor_paths=lambda: (), key=lambda: 'k')
    report = dep._change(
        ['uv', 'sync'], port=port, prefix=str(prefix), python=None, run=run, dry_run=False, census=lambda: [elsewhere]
    )
    assert report.returncode == 0
    assert seen == [['uv', 'sync']]


def test_dep_retries_a_transient_resolve_through_the_network_door(tmp_path: Path) -> None:
    """INCIDENT (1): `uv sync` failed once on forge auth and was not retried; through netverb it recovers."""
    answers = [
        subprocess.CompletedProcess([], 1, '', 'remote: Failed to authenticate user\n'),
        subprocess.CompletedProcess([], 0, '', ''),
    ]  # fmt: skip
    calls: list[list[str]] = []

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return answers[len(calls) - 1]

    port = dep.Port(name='repo', anchor_paths=lambda: (), key=lambda: 'k')
    report = dep._change(
        ['uv', 'sync', '--frozen'], port=port, prefix=str(tmp_path / 'env'), python=None, run=run, dry_run=False,
        census=list,
    )  # fmt: skip
    assert report.returncode == 0
    assert len(calls) == 2, 'the transient was not retried'


# ------------------------------------------------------------------------------------------- the real chain


@pytest.fixture(scope='module')
def live_tree(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Path, int]]:
    """A throwaway checkout with a REAL venv and a REAL sleeper executing from it, old enough to be a run."""
    root = _checkout(tmp_path_factory.mktemp('live') / 'repo')
    subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(root / '.venv')], check=True, timeout=300)
    sleeper = subprocess.Popen([str(_venv_python(root)), '-c', 'import time; time.sleep(300)'], cwd=root)
    try:
        deadline = time.monotonic() + 60
        while not liverun.live_runs(root) and time.monotonic() < deadline:
            time.sleep(0.5)
        yield root, sleeper.pid
    finally:
        kill_process_tree(sleeper.pid)
        sleeper.wait(timeout=30)


def test_the_real_census_sees_a_real_run_and_the_hook_names_its_pid(live_tree: tuple[Path, int]) -> None:
    root, pid = live_tree
    runs = liverun.live_runs(root, census=processes)
    assert pid in {one.pid for one in runs}
    out = io.StringIO()
    sys_stdout, sys.stdout = sys.stdout, out
    try:
        liverun.main(['hook'], stdin=_edit(root / 'src' / 'a.py'))
    finally:
        sys.stdout = sys_stdout
    assert f'pid {pid}' in json.loads(out.getvalue())['hookSpecificOutput']['permissionDecisionReason']


def _junction(link: Path, target: Path) -> None:
    if os.name == 'nt':
        shell = os.environ.get('COMSPEC', 'cmd.exe')
        subprocess.run([shell, '/c', 'mklink', '/J', str(link), str(target)], check=True, capture_output=True)
    else:
        link.symlink_to(target, target_is_directory=True)


@pytest.mark.workstation
def test_the_real_engine_refuses_a_merge_into_a_live_tree_and_allows_an_idle_one(
    live_tree: tuple[Path, int], tmp_path: Path
) -> None:
    """PLANTED BOTH WAYS through `node`: the same `git -C <tree> merge` is refused live and free idle."""
    root, pid = live_tree
    session = _checkout(tmp_path / 'session')
    _junction(session / '.venv', Path(sys.prefix))
    hooks = session / '.claude' / 'hooks'
    hooks.mkdir(parents=True)
    rules = hooks / 'deny-rules.json'
    rules.write_text(render(HookAdoption(app_name='s', declared_absent=frozenset(_NEEDING))), encoding='utf-8')
    idle = _checkout(tmp_path / 'idle')
    live = agenthooks.decide(f'git -C {root.as_posix()} merge origin/integrate/main', rules, cwd=session)
    assert live is not None
    assert live.startswith('TREE-HAS-A-LIVE-RUN:'), live
    assert f'pid {pid}' in live
    assert agenthooks.decide(f'git -C {idle.as_posix()} merge origin/integrate/main', rules, cwd=session) is None
    assert agenthooks.decide(f'git -C {root.as_posix()} status', rules, cwd=session) is None


#: Every row needing a repo artefact, declared absent so the planted adoption renders without remedies.
_NEEDING = {rule.id for rule in DENY_RULES if rule.needs is not None}


def _session_whose_interpreter_cannot_answer(root: Path) -> Path:
    """A session checkout whose ``.venv`` python is NOT Python (a copy of ``node``): every probe crashes."""
    session = _checkout(root)
    node = shutil.which('node')
    assert node, 'the engine runs under node, so node is on PATH'
    python = session / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    python.parent.mkdir(parents=True)
    try:
        os.link(node, python)
    except OSError:
        shutil.copy2(node, python)
    hooks = session / '.claude' / 'hooks'
    hooks.mkdir(parents=True)
    (hooks / 'deny-rules.json').write_text(
        render(HookAdoption(app_name='s', declared_absent=frozenset(_NEEDING))), encoding='utf-8'
    )
    return session


@pytest.mark.workstation  # the engine runs under node, workstation kit
@pytest.mark.parametrize(
    'spelling',
    [
        'git -C {tree} merge origin/integrate/main',
        'git -c core.autocrlf=false -C {tree} merge origin/integrate/main',
        'uv --directory {tree} sync',
        'uv --project={tree} run pytest',
    ],
)
def test_a_live_run_probe_that_cannot_answer_refuses_and_names_the_target(tmp_path: Path, spelling: str) -> None:
    """The harm is irreversible, so a crashed probe is not "no live run"; the target is the tree the call names."""
    session = _session_whose_interpreter_cannot_answer(tmp_path / 'session')
    tree = _checkout(tmp_path / 'tree')
    rules = session / '.claude' / 'hooks' / 'deny-rules.json'
    said = agenthooks.decide(spelling.format(tree=tree.as_posix()), rules, cwd=session)
    assert said is not None
    assert said.startswith('TREE-HAS-A-LIVE-RUN: could not confirm'), said
    assert str(tree) in said or tree.as_posix() in said


@pytest.mark.workstation  # the engine runs under node, workstation kit
@pytest.mark.parametrize(
    'spelling',
    [
        'git -C {other} status && git -C {tree} merge origin/integrate/main',
        'cd {tree} && git merge origin/integrate/main && cd {other}',
        'git -C {other} log -1; cd {tree} && uv sync',
        'python -m dev_lab.dev.dep --bootstrap {tree}',
    ],
)
def test_the_live_run_target_is_the_tree_the_matching_segment_acts_in(tmp_path: Path, spelling: str) -> None:
    """INCIDENT: the target was the first dir ANY segment named (or the last `cd`), not the mutating one's."""
    session = _session_whose_interpreter_cannot_answer(tmp_path / 'session')
    tree, other = _checkout(tmp_path / 'tree'), _checkout(tmp_path / 'other')
    rules = session / '.claude' / 'hooks' / 'deny-rules.json'
    said = agenthooks.decide(spelling.format(tree=tree.as_posix(), other=other.as_posix()), rules, cwd=session)
    assert said is not None
    assert said.startswith('TREE-HAS-A-LIVE-RUN: could not confirm'), said
    assert str(tree) in said or tree.as_posix() in said, said


@pytest.mark.workstation  # the engine runs under node, workstation kit
def test_a_session_venv_without_the_kit_is_no_refusal(tmp_path: Path) -> None:
    """A checkout mid-adoption has a real interpreter that cannot import dev_lab: nobody to ask, not a crash."""
    session = _session_whose_interpreter_cannot_answer(tmp_path / 'session')
    python = session / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    shutil.rmtree(session / '.venv')
    subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(session / '.venv')], check=True, timeout=120)
    assert python.exists()
    tree = _checkout(tmp_path / 'tree')
    rules = session / '.claude' / 'hooks' / 'deny-rules.json'
    assert agenthooks.decide(f'git -C {tree.as_posix()} merge origin/integrate/main', rules, cwd=session) is None


@pytest.mark.workstation  # the engine runs under node, workstation kit
def test_a_command_the_row_does_not_match_never_asks_the_probe(tmp_path: Path) -> None:
    """PLANTED CONTROL for the test above: the same broken probe, a read-only command, nothing refused."""
    session = _session_whose_interpreter_cannot_answer(tmp_path / 'session')
    tree = _checkout(tmp_path / 'tree')
    rules = session / '.claude' / 'hooks' / 'deny-rules.json'
    assert agenthooks.decide(f'git -C {tree.as_posix()} status', rules, cwd=session) is None


def test_a_serve_works_in_a_root_that_is_not_the_tree(tree: Path) -> None:
    """By construction: `forge serve` chdirs to its work root, where its cwd reads no tree."""
    work = forgeserve.work_root(tree)
    assert work.is_dir()
    assert not liverun.in_tree(work, tree)
    serve = _proc(7, _venv_python(tree), cwd=work, cmd='python -m dev_lab.dev.forge serve')
    assert not liverun.reads_tree(serve, tree)


def test_an_argument_whose_stat_raises_is_no_path_and_the_census_survives(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MEASURED 2026-10-21: an argument naming a busy named pipe made ``Path.exists`` raise WinError 231."""
    pipe = 'C:/pipe/busy'
    real = Path.exists

    def exists(self: Path, *args: object, **kwargs: object) -> bool:
        if self.as_posix() == pipe:
            raise OSError(231, 'All pipe instances are busy')
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'exists', exists)
    reader = _proc(9, 'C:/bin/node.exe', cmd=f'node.exe {pipe} {tree / "src"}', cwd='C:/')
    (tree / 'src').mkdir()
    assert liverun.live_runs(tree, census=lambda: (reader,), me=1) == (reader,)
