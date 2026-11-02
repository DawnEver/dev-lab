"""The RUN CACHE: this box's judged runs, keyed by (tree, env, selector), cited instead of re-run.

Driven over a real file, an :class:`lab_commons.outcomes.Record` (plan A1.5). The refusals that keep it
honest are planted: an INCONCLUSIVE is never cached, a key seen as both PASS and FAIL (flaky) is never
served and never overwritten, and a cache of the retired line shape is refused by name.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest

from dev_lab.dev.logref import LogRef
from dev_lab.dev.reports import StepReport
from dev_lab.dev.runcache import CACHE_REL, CachedRun, RetiredCache, cache_path, cached, record, remember, runs
from dev_lab.dev.verdict import Verdict
from dev_lab.dev.verifysteps import build_verdict

GIT = shutil.which('git') or 'git'


def _verdict(tmp_path: Path, *, truncated: tuple[str, ...] = ()) -> Verdict:
    log = tmp_path / 'run.log'
    log.write_text('ran\n', encoding='utf-8')
    report = StepReport(name='hooks', reported=() if truncated else ('hooks',), failures=(), truncated=truncated)
    return build_verdict((report,), tree='T', env='E', spec='verify', log=LogRef.of(log))


def _run(result: str) -> CachedRun:
    return CachedRun('T', 'E', 'verify', result, '', 'x.log')


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
    for result in ('PASS', 'FAIL', 'PASS'):
        record(cache, _run(result))
    assert cached(cache, tree='T', env='E', selector='verify') is None
    kinds = [json.loads(line)['kind'] for line in cache.read_text(encoding='utf-8').splitlines()]
    assert kinds == ['outcome', 'flaky'], 'the first decision stands; the opposite one is a flaky event'
    assert [run.result for run in runs(cache)] == ['PASS']


def test_the_cache_is_an_outcomes_record_keyed_by_tree_env_and_selector(tmp_path: Path) -> None:
    cache = tmp_path / 'runs.jsonl'
    record(cache, _run('FAIL'))
    (line,) = cache.read_text(encoding='utf-8').splitlines()
    event = json.loads(line)
    assert (event['kind'], event['cell']['status']) == ('outcome', 'rejected')
    assert (event['data']['tree'], event['data']['env'], event['data']['selector']) == ('T', 'E', 'verify')


def test_a_cache_of_the_retired_line_shape_is_refused_by_name(tmp_path: Path) -> None:
    """Regenerable: no dual-format reading -- the cache is deleted and re-filled by re-running."""
    cache = tmp_path / 'runs.jsonl'
    cache.write_text(json.dumps(asdict(_run('PASS'))) + '\n', encoding='utf-8')
    with pytest.raises(RetiredCache, match='retired line shape'):
        runs(cache)


def test_an_absent_cache_or_a_torn_last_line_serves_nothing_extra(tmp_path: Path) -> None:
    assert cached(tmp_path / 'absent.jsonl', tree='T', env='E', selector='verify') is None
    cache = tmp_path / 'runs.jsonl'
    record(cache, _run('FAIL'))
    with cache.open('a', encoding='utf-8') as handle:
        handle.write('{"torn')
    assert [run.result for run in runs(cache)] == ['FAIL'], 'a torn LAST line is a kill mid-append, dropped'


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
