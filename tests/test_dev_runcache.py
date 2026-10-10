"""The RUN CACHE: this box's judged runs, keyed by (tree, env, selector), cited instead of re-run.

Driven over a real file. The two refusals that keep it honest are planted: an INCONCLUSIVE is never
cached, and a key seen as both PASS and FAIL (flaky) is never served.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

from lab_commons.dev.logref import LogRef
from lab_commons.dev.reports import StepReport
from lab_commons.dev.runcache import CACHE_REL, CachedRun, cache_path, cached, remember, runs
from lab_commons.dev.verdict import Verdict
from lab_commons.dev.verify import build_verdict

GIT = shutil.which('git') or 'git'


def _verdict(tmp_path: Path, *, truncated: tuple[str, ...] = ()) -> Verdict:
    log = tmp_path / 'run.log'
    log.write_text('ran\n', encoding='utf-8')
    report = StepReport(name='hooks', reported=() if truncated else ('hooks',), failures=(), truncated=truncated)
    return build_verdict((report,), tree='T', env='E', spec='verify', log=LogRef.of(log))


def _line(result: str) -> str:
    return json.dumps(asdict(CachedRun('T', 'E', 'verify', result, '', 'x.log'))) + '\n'


def test_a_remembered_pass_is_cited_for_its_key_only(tmp_path: Path) -> None:
    cache = tmp_path / 'runs.jsonl'
    run = remember(cache, _verdict(tmp_path), tree='T', env='E', selector='verify', commit='c' * 40)
    assert run is not None
    assert cached(cache, tree='T', env='E', selector='verify') == run
    assert cached(cache, tree='other', env='E', selector='verify') is None
    assert cached(cache, tree='T', env='E', selector='verify tests/a.py') is None


def test_an_inconclusive_run_is_not_remembered(tmp_path: Path) -> None:
    cache = tmp_path / 'runs.jsonl'
    verdict = _verdict(tmp_path, truncated=('the wall fired',))
    assert remember(cache, verdict, tree='T', env='E', selector='verify', commit='') is None
    assert runs(cache) == ()


def test_a_key_seen_both_ways_is_flaky_and_never_served(tmp_path: Path) -> None:
    cache = tmp_path / 'runs.jsonl'
    cache.write_text(_line('PASS') + _line('FAIL') + _line('PASS'), encoding='utf-8')
    assert cached(cache, tree='T', env='E', selector='verify') is None


def test_an_absent_cache_or_a_torn_line_serves_nothing_extra(tmp_path: Path) -> None:
    assert cached(tmp_path / 'absent.jsonl', tree='T', env='E', selector='verify') is None
    cache = tmp_path / 'runs.jsonl'
    cache.write_text('{"torn\n' + _line('FAIL'), encoding='utf-8')
    assert [run.result for run in runs(cache)] == ['FAIL']


def test_the_cache_lives_in_the_main_checkout_even_from_a_worktree(tmp_path: Path) -> None:
    """ONE file per repository: a lane resolves the main checkout's path, never its own copy."""
    main = tmp_path / 'main'
    main.mkdir()

    def git(*args: str, cwd: Path = main) -> None:
        subprocess.run([GIT, *args], cwd=cwd, check=True, capture_output=True, text=True, encoding='utf-8')

    git('init', '-q')
    git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'root')
    lane = main / '.claude' / 'worktrees' / 'lane'
    git('worktree', 'add', '-q', '--detach', str(lane), 'HEAD')
    expected = main.resolve() / CACHE_REL
    assert cache_path(lane).resolve() == expected
    assert cache_path(main).resolve() == expected
