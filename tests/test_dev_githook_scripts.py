"""The four hook scripts R4 moved, driven for REAL: real bash, real git, real temp checkouts.

WHY NOT A TEXT ASSERTION. Every arm below could have been written as "the source contains this
line", and every one of them would have passed against a script whose logic had been inverted. So a
test here spawns the script the package ships, gives it an actual branch/environment state, and
reads what the CHILD received -- a shim interpreter that logs its own argv, or a marker file the
wrapped command writes. That is the same separation the ``netverb`` tests draw between "not retried"
and "retried and failed identically": only the child's side can tell them apart.

EVERY SCAN HAS A CONTROL IN BOTH DIRECTIONS. A wrapper that declines every push passes the
tag arm; a wrapper that declines nothing passes the branch arm. Each pair is written together, and
where a guard's silence is the interesting half -- ``git-env-repair`` leaving a COMPLETE
``GIT_CONFIG_*`` set alone, ``cz-push-range`` not invoking the checker on an empty range -- the
silent side is asserted from the child's side too.

THE SEAM THESE ARMS PIN. ``branch-push-only.sh`` and ``cz-push-range.sh`` each need one fact this
package cannot know -- which ref takes more than a branch push, and which ref an unpublished lane is
measured against. Both arrive as an environment variable with NO DEFAULT, and the arms that assert
the refusal when it is missing are the ones that keep it that way: a default would make every other
repo silently inherit the repo these scripts came from.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from lab_commons.dev import githooks

GIT = shutil.which('git')

# ASSERTED AT MODULE SCOPE RATHER THAN SKIPPED: this family's hooks all start with `bash`, so a box
# without bash or git runs no hooks at all -- a finding, not a reason to report green.
assert GIT is not None, 'no git on this box; nothing in this family can be verified here'
BASH = githooks.bash_executable()


#: A path as bash must see it. `dirname "C:\a\b"` eats the backslashes as escapes, and every script
#: here resolves its own directory through `BASH_SOURCE`, so the separator is load-bearing.
def sh(path: Path | str) -> str:
    """*path* with forward slashes -- the only spelling bash's word splitting survives."""
    return str(path).replace('\\', '/')


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        [GIT, '-c', 'user.email=t@example.invalid', '-c', 'user.name=t', *args],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return done.stdout.strip()


def _run(script: str, args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [BASH, sh(githooks.hook_path(script)), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        # THE TIMEOUT IS AN ASSERTION: a hook that waits on a prompt must fail rather than take the
        # worker down with it.
        timeout=180,
        env={**os.environ, **env},
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real single-commit git repo on ``main``."""
    root = tmp_path / 'r'
    root.mkdir()
    _git(root, 'init', '-b', 'main')
    (root / 'f.txt').write_text('x', encoding='utf-8')
    _git(root, 'add', '-A')
    _git(root, 'commit', '-m', 'feat: seed')
    return root


def _plant_venv(root: Path, *, distributions: bool = True, pythonpath: Path | None = None) -> Path:
    """A venv whose interpreter is a SHIM: it logs its own argv, then execs the real one.

    The shim is what makes "which venv won" and "what the child received" readable at all. A real
    ``python -m venv`` would answer neither, and would cost a second of wall clock per arm.
    """
    venv = root / '.venv'
    (venv / 'bin').mkdir(parents=True)
    if distributions:
        (venv / 'lib' / 'python3.12' / 'site-packages' / 'planted-1.0.dist-info').mkdir(parents=True)
    log = venv / 'calls.log'
    extra = f'export PYTHONPATH="{sh(pythonpath)}"\n' if pythonpath is not None else ''
    shim = venv / 'bin' / 'python'
    shim.write_text(
        f'#!/usr/bin/env bash\necho "{sh(venv)} $*" >> "{sh(log)}"\n{extra}exec "{sh(sys.executable)}" "$@"\n',
        encoding='utf-8',
    )
    shim.chmod(0o755)
    return venv


def _calls(venv: Path) -> list[str]:
    log = venv / 'calls.log'
    return log.read_text(encoding='utf-8').splitlines() if log.is_file() else []


@pytest.fixture
def module_dir(tmp_path: Path) -> Path:
    """A directory holding one importable module, planted on a chosen venv's ``PYTHONPATH``."""
    where = tmp_path / 'planted'
    where.mkdir()
    (where / 'labtest_planted_tool.py').write_text('VALUE = 1\n', encoding='utf-8')
    return where


# ---------------------------------------------------------------- the registry over what is shipped


def test_every_shipped_script_declares_what_it_is() -> None:
    """A script is a HOOK, a WRAPPER or a FRAGMENT, and the directory and the registry must agree."""
    floor = 5
    assert len(githooks.SCRIPTS) >= floor, (
        f'the payload scan reached {githooks.SCRIPTS}; an unread tree is not a clean one'
    )
    assert githooks.undeclared() == (), githooks.undeclared()
    assert set(githooks.HOOKS) == {'bump-version', 'cz-push-range'}, githooks.HOOKS
    assert set(githooks.scripts_of_kind(githooks.WRAPPER)) == {'branch-push-only', 'with-venv'}


def test_a_planted_registry_reds_on_every_side() -> None:
    """THE PLANTED CONTROL, through the REAL function, one side at a time."""
    problems = githooks.undeclared(['here', 'orphan'], {'here': githooks.HOOK, 'ghost': githooks.WRAPPER})
    assert problems == (
        'orphan: shipped with no row in KINDS',
        'ghost: declared in KINDS, and no such script is shipped',
    ), problems
    assert githooks.undeclared(['here'], {'here': 'somethingelse'}) == (
        "here: declared as 'somethingelse', which is not one of 'hook', 'wrapper', 'fragment'",
    )
    assert githooks.undeclared(['here'], {'here': githooks.HOOK}) == ()


def test_a_fragment_refuses_to_be_run_and_a_wrapper_does_not(repo: Path) -> None:
    """The reason the kinds exist: running a sourced fragment exits 0 having done nothing."""
    with pytest.raises(githooks.NotRunnable) as caught:
        githooks.run_hook('git-env-repair')
    assert 'SOURCED' in str(caught.value)
    # THE OTHER DIRECTION, so the refusal is not simply "run_hook refuses": a wrapper really runs,
    # and reaches its own exit code (1 -- this repo has no .venv planted under the temp checkout).
    assert githooks.run_hook('with-venv', ['labtest_absent_module'], cwd=repo) == 1


def test_the_script_set_is_listable_by_kind() -> None:
    """A consumer wiring a hook must be able to ask which scripts are hooks at all."""
    listed = subprocess.run(
        [sys.executable, '-m', 'lab_commons.dev.githooks', '--list', '--kind', 'fragment'],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    ).stdout.split()
    assert listed == ['git-env-repair'], listed


# ------------------------------------------------------------------------------- git-env-repair.sh


def _probe(tmp_path: Path, body: str) -> Path:
    probe = tmp_path / 'probe.sh'
    probe.write_text(f'#!/usr/bin/env bash\nset -u\n{body}\n', encoding='utf-8')
    probe.chmod(0o755)
    return probe


def _source_line() -> str:
    return f'. "{sh(githooks.hook_path("git-env-repair"))}"'


_POISON = {'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'credential.helper'}


def test_an_incomplete_git_config_set_really_does_break_git(repo: Path, tmp_path: Path) -> None:
    """THE FLOOR. Without this arm the repair arm proves nothing -- it could be repairing nothing."""
    probe = _probe(tmp_path, 'git rev-parse --show-toplevel')
    done = subprocess.run(
        [BASH, sh(probe)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env={**os.environ, **_POISON},
    )
    assert done.returncode != 0, 'the planted environment is not actually poisonous, so nothing below is a repair'
    assert 'missing config value' in done.stderr, done.stderr


def test_the_fragment_drops_an_incomplete_set_and_git_runs(repo: Path, tmp_path: Path) -> None:
    """The repair, measured by the git call that FOLLOWS it rather than by the notice it prints."""
    probe = _probe(tmp_path, f'{_source_line()}\ngit rev-parse --show-toplevel')
    done = subprocess.run(
        [BASH, sh(probe)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env={**os.environ, **_POISON},
    )
    assert done.returncode == 0, done.stderr
    assert sh(repo) in done.stdout.replace('\\', '/'), done.stdout
    assert 'DROPPING' in done.stderr, 'a silent repair is indistinguishable from an environment that was fine'
    assert 'GIT_CONFIG_VALUE_0' in done.stderr, 'the notice must name what was unset'


def test_a_COMPLETE_git_config_set_reaches_git_untouched(repo: Path, tmp_path: Path) -> None:
    """The silent side. A caller passing config through the environment on purpose must keep it."""
    probe = _probe(tmp_path, f'{_source_line()}\ngit config user.name')
    done = subprocess.run(
        [BASH, sh(probe)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env={
            **os.environ,
            'GIT_CONFIG_COUNT': '1',
            'GIT_CONFIG_KEY_0': 'user.name',
            'GIT_CONFIG_VALUE_0': 'planted-name',
        },
    )
    assert done.stdout.strip() == 'planted-name', done.stdout + done.stderr
    assert '[git-env]' not in done.stderr, 'a complete set must be left alone, and silently'


def test_no_git_config_in_the_environment_is_silent(repo: Path, tmp_path: Path) -> None:
    """The other silent side: the common case must not print a repair notice."""
    probe = _probe(tmp_path, f'{_source_line()}\necho ok')
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_CONFIG_')}
    done = subprocess.run(
        [BASH, sh(probe)], cwd=repo, capture_output=True, text=True, check=False, timeout=120, env=env
    )
    assert done.stdout.strip() == 'ok'
    assert '[git-env]' not in done.stderr


# ------------------------------------------------------------------------------------ with-venv.sh


@pytest.fixture
def worktree(repo: Path, tmp_path: Path) -> Path:
    """A real git worktree of *repo*, so THIS_ROOT and MAIN_ROOT are genuinely different paths."""
    lane = tmp_path / 'lane'
    _git(repo, 'worktree', 'add', '-b', 'feat/lane', str(lane))
    return lane


def test_a_lane_venv_that_CAN_run_the_tool_wins(repo: Path, worktree: Path, module_dir: Path) -> None:
    """The isolation rule: a lane's own environment beats MAIN's when it can serve the call."""
    lane_venv = _plant_venv(worktree, pythonpath=module_dir)
    main_venv = _plant_venv(repo, pythonpath=module_dir)
    done = _run('with-venv', ['labtest_planted_tool'], cwd=worktree, env={})
    assert done.returncode == 0, done.stdout + done.stderr
    assert any('-m labtest_planted_tool' in line for line in _calls(lane_venv)), _calls(lane_venv)
    assert all('-m labtest_planted_tool' not in line for line in _calls(main_venv)), _calls(main_venv)


def test_a_lane_venv_that_CANNOT_yields_to_MAINs(repo: Path, worktree: Path, module_dir: Path) -> None:
    """The same probe planted the other way round -- the control that makes the arm above mean something."""
    lane_venv = _plant_venv(worktree)
    main_venv = _plant_venv(repo, pythonpath=module_dir)
    done = _run('with-venv', ['labtest_planted_tool'], cwd=worktree, env={})
    assert done.returncode == 0, done.stdout + done.stderr
    assert any('-m labtest_planted_tool' in line for line in _calls(main_venv)), _calls(main_venv)
    assert all('-m labtest_planted_tool' not in line for line in _calls(lane_venv)), (
        'the lane venv could not provide the tool and still ran it'
    )


def test_a_STUB_venv_is_not_an_environment(repo: Path) -> None:
    """An interpreter that exists is not an environment that works: no dist-info, no candidate."""
    _plant_venv(repo, distributions=False, pythonpath=None)
    done = _run('with-venv', ['labtest_planted_tool'], cwd=repo, env={})
    assert done.returncode == 1
    assert 'no .venv under' in done.stderr, done.stderr
    assert 'missing TOOL' not in done.stderr, 'a placeholder venv must not be reported as a missing tool'


def test_a_REAL_venv_without_the_tool_names_the_TOOL(repo: Path) -> None:
    """The other half of that pair, and the whole reason the two messages differ."""
    _plant_venv(repo)
    done = _run('with-venv', ['labtest_planted_tool'], cwd=repo, env={})
    assert done.returncode == 1
    assert 'missing TOOL' in done.stderr, done.stderr
    assert 'labtest_planted_tool' in done.stderr, 'the refusal must name what was missing'


def test_a_script_path_is_run_as_a_SCRIPT_and_not_as_a_module(repo: Path) -> None:
    """The measured defect: ``-m "$@"`` turned a path into ``-m python <path>`` and ran no tests."""
    venv = _plant_venv(repo)
    script = repo / 'tool.py'
    script.write_text('print("ran-the-script")\n', encoding='utf-8')
    done = _run('with-venv', [sh(script)], cwd=repo, env={})
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'ran-the-script' in done.stdout
    calls = _calls(venv)
    assert all(' -m ' not in line for line in calls), f'a path reached the interpreter as a module: {calls}'


# -------------------------------------------------------------------------------- cz-push-range.sh


def _plant_commitizen(root: Path, tmp_path: Path) -> tuple[Path, Path]:
    """A venv whose ``commitizen`` is a planted package recording the argv it was handed."""
    where = tmp_path / 'czsrc'
    (where / 'commitizen').mkdir(parents=True)
    argv_log = tmp_path / 'cz-argv.log'
    (where / 'commitizen' / '__init__.py').write_text('', encoding='utf-8')
    (where / 'commitizen' / '__main__.py').write_text(
        f'import sys\nopen(r"{argv_log}", "a").write(" ".join(sys.argv[1:]) + "\\n")\n',
        encoding='utf-8',
    )
    _plant_venv(root, pythonpath=where)
    return where, argv_log


def _cz(repo: Path, **env: str) -> subprocess.CompletedProcess[str]:
    return _run('cz-push-range', [], cwd=repo, env=env)


def test_the_base_ref_has_NO_DEFAULT_and_its_absence_refuses(repo: Path, tmp_path: Path) -> None:
    """THE SEAM. A default here would judge every other repo's lane against this repo's trunk."""
    _, argv_log = _plant_commitizen(repo, tmp_path)
    done = _cz(repo)
    assert done.returncode == 1, done.stdout + done.stderr
    assert 'LAB_CZ_BASE_REF' in done.stderr, done.stderr
    assert not argv_log.is_file(), 'the checker ran despite an unanswerable range'


def test_the_increment_is_the_range_the_checker_receives(repo: Path, tmp_path: Path) -> None:
    """The defect this script exists for: judge what is being PUBLISHED, not the whole lane."""
    _, argv_log = _plant_commitizen(repo, tmp_path)
    first = _git(repo, 'rev-parse', 'HEAD')
    (repo / 'g.txt').write_text('y', encoding='utf-8')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-m', 'feat: second')
    head = _git(repo, 'rev-parse', 'HEAD')
    done = _cz(repo, LAB_CZ_BASE_REF='origin/main', PRE_COMMIT_FROM_REF=first, PRE_COMMIT_TO_REF=head)
    assert done.returncode == 0, done.stdout + done.stderr
    assert argv_log.read_text(encoding='utf-8').strip() == f'check --rev-range {first}..{head}', argv_log.read_text(
        encoding='utf-8'
    )
    assert 'as pre-commit computed it' in done.stdout


def test_an_all_zero_remote_side_falls_back_to_the_declared_base(repo: Path, tmp_path: Path) -> None:
    """A brand-new branch has no remote object to start a range at, and says which range it used."""
    _, argv_log = _plant_commitizen(repo, tmp_path)
    _git(repo, 'branch', 'base-for-test')
    (repo / 'g.txt').write_text('y', encoding='utf-8')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-m', 'feat: second')
    done = _cz(
        repo,
        LAB_CZ_BASE_REF='base-for-test',
        PRE_COMMIT_FROM_REF='0' * 40,
        PRE_COMMIT_TO_REF=_git(repo, 'rev-parse', 'HEAD'),
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'new branch' in done.stdout, done.stdout
    assert argv_log.read_text(encoding='utf-8').strip() == 'check --rev-range base-for-test..HEAD'


def test_a_sha_this_checkout_does_not_have_falls_back_and_SAYS_SO(repo: Path, tmp_path: Path) -> None:
    """A fallback that does not announce itself makes a legacy refusal look like a fresh one."""
    _, argv_log = _plant_commitizen(repo, tmp_path)
    _git(repo, 'branch', 'base-for-test')
    (repo / 'g.txt').write_text('y', encoding='utf-8')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-m', 'feat: second')
    done = _cz(
        repo,
        LAB_CZ_BASE_REF='base-for-test',
        PRE_COMMIT_FROM_REF='b' * 40,
        PRE_COMMIT_TO_REF='c' * 40,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'does not have' in done.stdout, done.stdout
    assert argv_log.read_text(encoding='utf-8').strip() == 'check --rev-range base-for-test..HEAD'


def test_an_EMPTY_increment_is_nothing_to_judge(repo: Path, tmp_path: Path) -> None:
    """Measured: ``commitizen check`` exits 3 on an empty range, which made an up-to-date branch unpushable."""
    _, argv_log = _plant_commitizen(repo, tmp_path)
    head = _git(repo, 'rev-parse', 'HEAD')
    done = _cz(repo, LAB_CZ_BASE_REF='origin/main', PRE_COMMIT_FROM_REF=head, PRE_COMMIT_TO_REF=head)
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'nothing to check' in done.stdout
    assert not argv_log.is_file(), 'the checker was invoked on an empty range'


# ----------------------------------------------------------------------------- branch-push-only.sh


def _wrapped(tmp_path: Path) -> tuple[list[str], Path]:
    """A wrapped command that leaves a marker -- the only way to tell "ran" from "declined"."""
    marker = tmp_path / 'wrapped-ran'
    return [BASH, '-c', f'echo yes > "{sh(marker)}"'], marker


def _bpo(repo: Path, tmp_path: Path, **env: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    command, marker = _wrapped(tmp_path)
    return _run('branch-push-only', ['probe', *command], cwd=repo, env=env), marker


DECLARED_NONE = {'LAB_PUSH_PROTECTED_REF': 'none'}


def test_a_branch_push_RUNS_the_wrapped_command(repo: Path, tmp_path: Path) -> None:
    """The accepting side. Without it every arm below passes for a wrapper that declines everything."""
    done, marker = _bpo(repo, tmp_path, PRE_COMMIT_REMOTE_BRANCH='refs/heads/feat/x', **DECLARED_NONE)
    assert done.returncode == 0, done.stdout + done.stderr
    assert marker.is_file(), done.stdout + done.stderr


@pytest.mark.parametrize('ref', ['refs/tags/v1.2.3', 'refs/notes/commits', 'refs/ci/heartbeat/box/1'])
def test_a_push_that_updates_no_branch_DECLINES(repo: Path, tmp_path: Path, ref: str) -> None:
    """The axis: decided on the REMOTE ref, which is the only one that differs between these pushes."""
    done, marker = _bpo(repo, tmp_path, PRE_COMMIT_REMOTE_BRANCH=ref, **DECLARED_NONE)
    assert done.returncode == 0, 'declining is not refusing: a tag push must still succeed'
    assert not marker.is_file(), f'{ref} reached the wrapped command'
    assert 'DECLINED' in done.stdout, done.stdout
    assert ref in done.stdout, done.stdout


def test_no_remote_ref_in_the_environment_RUNS(repo: Path, tmp_path: Path) -> None:
    """A manual invocation carries no pre-commit environment, and must not silently check nothing."""
    env = {k: v for k, v in os.environ.items() if k != 'PRE_COMMIT_REMOTE_BRANCH'}
    command, marker = _wrapped(tmp_path)
    done = subprocess.run(
        [BASH, sh(githooks.hook_path('branch-push-only')), 'probe', *command],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
        env={**env, **DECLARED_NONE},
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert marker.is_file(), done.stdout


def test_the_protected_ref_RUNS_ITS_GUARD_and_a_refusal_stops_the_push(repo: Path, tmp_path: Path) -> None:
    """The repo-shaped half, supplied from outside: a failing tier must fail the push."""
    done, marker = _bpo(
        repo,
        tmp_path,
        PRE_COMMIT_REMOTE_BRANCH='refs/heads/main',
        LAB_PUSH_PROTECTED_REF='refs/heads/main',
        LAB_PUSH_PROTECTED_CMD='echo no-verdict-for-this-tree; exit 1',
        LAB_PUSH_PROTECTED_NAME='heavy',
    )
    assert done.returncode == 1, done.stdout + done.stderr
    assert not marker.is_file(), 'the wrapped command ran despite the guard refusing'
    assert 'heavy' in done.stdout, f'the refusal must NAME the tier that declined: {done.stdout!r}'
    assert 'no-verdict-for-this-tree' in done.stdout, "the guard's own reason must reach the reader"


def test_a_PASSING_guard_lets_the_protected_push_through(repo: Path, tmp_path: Path) -> None:
    """The accepting side of the same pair: the guard is consulted, not a gate that always shuts."""
    done, marker = _bpo(
        repo,
        tmp_path,
        PRE_COMMIT_REMOTE_BRANCH='refs/heads/main',
        LAB_PUSH_PROTECTED_REF='refs/heads/main',
        LAB_PUSH_PROTECTED_CMD='echo verdict=PASS',
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert marker.is_file(), done.stdout + done.stderr


def test_an_UNPROTECTED_branch_does_not_run_the_guard(repo: Path, tmp_path: Path) -> None:
    """Scope: the guard belongs to ONE ref, and a lane push must not pay for it."""
    done, marker = _bpo(
        repo,
        tmp_path,
        PRE_COMMIT_REMOTE_BRANCH='refs/heads/feat/x',
        LAB_PUSH_PROTECTED_REF='refs/heads/main',
        LAB_PUSH_PROTECTED_CMD='exit 1',
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert marker.is_file(), "a lane push was judged by the protected ref's guard"


def test_a_repo_that_DECLARES_no_protected_ref_pushes_its_trunk_normally(repo: Path, tmp_path: Path) -> None:
    """``none`` is a declaration, not a default: the trunk becomes an ordinary branch push."""
    done, marker = _bpo(repo, tmp_path, PRE_COMMIT_REMOTE_BRANCH='refs/heads/main', **DECLARED_NONE)
    assert done.returncode == 0, done.stdout + done.stderr
    assert marker.is_file()


@pytest.mark.parametrize(
    ('env', 'named'),
    [
        ({}, 'LAB_PUSH_PROTECTED_REF'),
        ({'LAB_PUSH_PROTECTED_REF': 'refs/heads/main'}, 'LAB_PUSH_PROTECTED_CMD'),
    ],
)
def test_an_UNANSWERED_repo_fact_refuses_and_names_it(
    repo: Path, tmp_path: Path, env: dict[str, str], named: str
) -> None:
    """THE NO-DEFAULT ARM, both halves: a protection nothing enforces is a declaration that lies."""
    ambient = {k: v for k, v in os.environ.items() if not k.startswith('LAB_PUSH_')}
    command, marker = _wrapped(tmp_path)
    done = subprocess.run(
        [BASH, sh(githooks.hook_path('branch-push-only')), 'probe', *command],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
        env={**ambient, 'PRE_COMMIT_REMOTE_BRANCH': 'refs/heads/main', **env},
    )
    assert done.returncode == 1, done.stdout + done.stderr
    assert named in done.stderr, done.stderr
    assert not marker.is_file(), 'a misconfigured hook ran the command it could not judge'
