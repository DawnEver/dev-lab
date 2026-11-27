"""#987: a measured run in a worktree writes nothing outside it, and never the retired ``.verify/``.

``.verify/`` was retired on 2026-11-05 (verify logs and the durations ledger moved to the dated output tree).
64 empty ``.verify/`` directories were still seen in a consumer's MAIN checkout while a worktree verified; the
consumer's main venv held a dev-lab pinned before the retirement, whose durations ledger wrote ``.verify/``.
This pins the current kit: the recorder every verify loads into each pytest worker, run in a real git worktree,
leaves the main checkout exactly as it was.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_GIT = shutil.which('git') or 'git'
_DECLARED = '[tool.dev_lab.parts]\noutput = "out/logs"\n[tool.pytest.ini_options]\n'
_TESTS = 'def test_one() -> None:\n    pass\n\n\ndef test_two() -> None:\n    pass\n'


def _git(*argv: str, cwd: Path) -> None:
    subprocess.run([_GIT, *argv], cwd=cwd, check=True, capture_output=True, timeout=60)


def _main_with_a_worktree(tmp_path: Path) -> tuple[Path, Path]:
    main = tmp_path / 'main'
    main.mkdir()
    (main / 'pyproject.toml').write_text(_DECLARED, encoding='utf-8')
    (main / 'test_probe.py').write_text(_TESTS, encoding='utf-8')
    _git('init', '-q', cwd=main)
    _git('add', '.', cwd=main)
    _git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--no-verify', '-m', 'probe', cwd=main)
    tree = main / '.claude' / 'worktrees' / 'probe'
    _git('worktree', 'add', '-q', str(tree), cwd=main)
    return main, tree


def _outside(main: Path, tree: Path) -> set[str]:
    """Every path in *main* that is neither git's own nor inside the worktree *tree*."""
    return {
        path.relative_to(main).as_posix()
        for path in main.rglob('*')
        if '.git' not in path.relative_to(main).parts and not path.is_relative_to(tree)
    }


def _measured(tree: Path) -> subprocess.CompletedProcess[str]:
    argv = [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-p', 'dev_lab.dev.durations', '-n', '2']
    return subprocess.run(argv, cwd=tree, capture_output=True, text=True, encoding='utf-8', timeout=180, check=False)


def test_a_measured_run_in_a_worktree_leaves_the_main_checkout_untouched(tmp_path: Path) -> None:
    main, tree = _main_with_a_worktree(tmp_path)
    before = _outside(main, tree)
    run = _measured(tree)
    assert run.returncode == 0, run.stdout + run.stderr
    assert list(tree.glob('out/logs/*/*/*/durations/durations-gw*.json')), 'the recorder wrote nothing: no reading'
    assert _outside(main, tree) == before
    assert not list(tmp_path.rglob('.verify')), 'the retired .verify/ was created'


def test_planted_the_snapshot_sees_a_dot_verify_created_in_the_main_checkout(tmp_path: Path) -> None:
    """PLANTED CONTROL: the probe above can say no -- an empty ``.verify/`` in main changes the snapshot."""
    main, tree = _main_with_a_worktree(tmp_path)
    before = _outside(main, tree)
    (main / 'sub' / '.verify').mkdir(parents=True)
    assert _outside(main, tree) - before == {'sub', 'sub/.verify'}
