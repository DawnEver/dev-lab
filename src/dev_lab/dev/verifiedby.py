"""A DATA repo's ``tests/base`` is its CONSUMERS' tests, run against the head being verified.

A data repo (``[tool.dev_lab.integrator] test_roots = []``) has no tests of its own: what makes a recipe sound
is what its consumer's code does with it (user ruling 2026-11-11: a data repo is verified TOGETHER
WITH its consumer). Before this, a verify over the data repo selected nothing, so it was INCONCLUSIVE, no ``tests/base``
part was ever posted, and ``integrate promote`` refused every data commit.

ONE DECLARATION, in the DATA repo::

    [tool.dev_lab.verify]
    by = [{repo = "https://forge.example.org/team/app.git", part = "connection"}]

``part`` is a need-set of the CONSUMER's vocabulary -- its own declared selection of the tests that read the
data (:func:`dev_lab.dev.localpart.part_selection`); the consumer's ``[tool.dev_lab.data.<name>]`` row naming
this repo is the other half, and a consumer that does not name it is refused (a declaration that lies).

THE RUN (:func:`judge`): per consumer, its registered checkout on this machine (``[repos]``) is fetched and a
detached worktree is made at its integration line's head with its own environment (:func:`prepare`); its
data copy is synced to the head under :data:`~dev_lab.dev.datadeps.OVERRIDE` and its targeted verify of the
part runs there -- never as a producer, so it posts nothing on the consumer. Its per-test cells, named
``<member>:<node>``, become this repo's ``tests/base`` part on the DATA repo's head. Any consumer
INCONCLUSIVE, unreachable or undeclared makes the whole run INCONCLUSIVE; a data repo declaring no consumer
is untouched by this module and stays INCONCLUSIVE -- never a silent pass.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons import launch
from lab_commons.home import repos
from lab_commons.hpc.needsets import BASE
from lab_commons.hpc.shell import FULL
from lab_commons.log import emit
from lab_commons.outcomes import Conclusion

from dev_lab.dev import datadeps
from dev_lab.dev.dataconsumers import same_repo
from dev_lab.dev.datedlog import output_dir
from dev_lab.dev.forgestatus import head_sha, verdict_commit
from dev_lab.dev.gitenv import unlocated
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.localpart import local_record, part_selection, post_local
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.platformparts import UndeclaredPart, origin_url, record_directory
from dev_lab.dev.producer import PRODUCING_VAR, ProducerExit
from dev_lab.dev.test_outcomes import outcomes_dir, read_cells
from dev_lab.dev.treedirt import status_paths
from dev_lab.dev.venvpath import checkout_interpreter, current_os_name, running_interpreter

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from lab_commons.hpc.testcells import TestCell

__all__ = ['Consumer', 'Judged', 'VerifyByRefused', 'declared', 'judge', 'main', 'post', 'prepare', 'run_consumer']

#: Where a consumer's worktree is made, under the data repo's dated output.
WORKTREE_KIND: Final = 'consumer'
_EXIT: Final = {0: Conclusion.PASS, 1: Conclusion.FAIL}


class VerifyByRefused(RuntimeError):
    """A consumer cannot be judged here; the message names why and the remedy. The run is INCONCLUSIVE."""


@dataclass(frozen=True)
class Consumer:
    """One ``[tool.dev_lab.verify] by`` row: the consumer's url and the part of its tests that judges the data."""

    repo: str
    part: str


@dataclass(frozen=True)
class Judged:
    """The folded run: the conclusion, every consumer's cells keyed ``<member>:<node>``, and one line per consumer."""

    result: Conclusion
    cells: Mapping[str, TestCell]
    flaky: frozenset[str]
    lines: tuple[str, ...]


def declared(root: Path) -> tuple[Consumer, ...]:
    """The consumers *root* declares; ``()`` when none. RAISES :class:`VerifyByRefused` on a malformed row."""
    manifest = root / 'pyproject.toml'
    text = manifest.read_text(encoding='utf-8') if manifest.is_file() else ''
    rows = tomllib.loads(text).get('tool', {}).get('dev_lab', {}).get('verify', {}).get('by', [])
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        msg = '[tool.dev_lab.verify] by must be a list of {repo = "<url>", part = "<consumer part>"} rows'
        raise VerifyByRefused(msg)
    consumers = []
    for row in rows:
        if set(row) != {'repo', 'part'} or not all(isinstance(v, str) and v for v in row.values()):
            msg = f'[tool.dev_lab.verify] by row {row!r} must carry exactly a non-empty repo and part'
            raise VerifyByRefused(msg)
        consumers.append(Consumer(row['repo'], row['part']))
    return tuple(consumers)


def _git(cwd: Path, *argv: str) -> str:
    done = launch.run(
        ['git', '-C', str(cwd), *argv], capture_output=True, text=True, encoding='utf-8', errors='replace',
        check=False, env=unlocated(),
    )  # fmt: skip
    if done.returncode != 0:
        msg = f'`git {" ".join(argv)}` in {cwd} failed: {done.stderr.strip()}'
        raise VerifyByRefused(msg)
    return done.stdout.strip()


def prepare(member: str, checkout: Path, data_root: Path) -> Path:
    """A detached worktree of *checkout* at its integration line's fetched head, with its own environment."""
    line = load_policy(checkout).integration
    report = run_network_verb(['git', 'fetch', '-q', 'origin', line], cwd=checkout, env=unlocated(), timeout=600)
    if not report.ok:
        msg = f'fetching {line} in {checkout} failed: {report.remedy}'
        raise VerifyByRefused(msg)
    sha = _git(checkout, 'rev-parse', f'origin/{line}')
    tree = output_dir(data_root, WORKTREE_KIND) / f'{member}-{sha[:12]}'
    if not tree.exists():
        _git(checkout, 'worktree', 'add', '-q', '--detach', str(tree), sha)
    boot = launch.run([running_interpreter(), '-m', 'dev_lab.dev.dep', '--bootstrap', str(tree)], check=False)
    if boot.returncode != 0:
        msg = f'bootstrapping {tree} exited {boot.returncode}'
        raise VerifyByRefused(msg)
    return tree


def run_consumer(tree: Path, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, Path | None]:
    """Sync *tree*'s data under *env*, run its verify *argv*; ``(exit code, the newest verify log or None)``."""
    python = str(checkout_interpreter(tree, os_name=current_os_name()))
    synced = launch.run([python, '-m', 'dev_lab.dev.datadeps', 'sync'], cwd=tree, env=dict(env), check=False)
    if synced.returncode != 0:
        msg = f'syncing the data copy of {tree} to the head exited {synced.returncode}'
        raise VerifyByRefused(msg)
    logs = output_dir(tree, 'verify')
    before = set(logs.glob('verify-*.log'))
    code = launch.run([python, *argv], cwd=tree, env=dict(env), check=False).returncode
    fresh = sorted(set(logs.glob('verify-*.log')) - before)
    return code, (fresh[-1] if fresh else None)


def judge(
    root: Path,
    head: str,
    consumers: Sequence[Consumer],
    *,
    url: str,
    members: Mapping[str, Path],
    make: Callable[[str, Path, Path], Path] = prepare,
    execute: Callable[[Path, Sequence[str], Mapping[str, str]], tuple[int, Path | None]] = run_consumer,
) -> Judged:
    """Run every *consumers* row against the data repo *root* (origin *url*) at *head*, folded into one answer."""
    results, cells, flaky, lines = [], {}, set(), []
    for consumer in consumers:
        try:
            outcome, mine, unsure, line = _one(
                root, head, consumer, url=url, members=members, make=make, execute=execute
            )
        except (VerifyByRefused, datadeps.DataRefused, ValueError, OSError) as why:
            outcome, mine, unsure, line = Conclusion.INCONCLUSIVE, {}, frozenset(), f'{consumer.repo}: {why}'
        results.append(outcome)
        cells.update(mine)
        flaky |= unsure
        lines.append(line)
    if not results or Conclusion.INCONCLUSIVE in results:
        result = Conclusion.INCONCLUSIVE
    else:
        result = Conclusion.FAIL if Conclusion.FAIL in results else Conclusion.PASS
    return Judged(result, cells, frozenset(flaky), tuple(lines))


def _one(
    root: Path,
    head: str,
    consumer: Consumer,
    *,
    url: str,
    members: Mapping[str, Path],
    make: Callable[[str, Path, Path], Path],
    execute: Callable[[Path, Sequence[str], Mapping[str, str]], tuple[int, Path | None]],
) -> tuple[Conclusion, dict[str, TestCell], frozenset[str], str]:
    named = [(name, path) for name, path in sorted(members.items()) if _origin(path, consumer.repo)]
    if not named:
        msg = f"no checkout of {consumer.repo} is registered in this machine's [repos]; register and bootstrap one"
        raise VerifyByRefused(msg)
    member, checkout = named[0]
    tree = make(member, checkout, root)
    rows = [dep for dep in datadeps.declared(tree, overridden=False) if same_repo(dep.url, url)]
    if not rows:
        msg = f'{member} declares no [tool.dev_lab.data.<name>] row naming {url}: the [tool.dev_lab.verify] by row lies'
        raise VerifyByRefused(msg)
    env = {key: value for key, value in os.environ.items() if key != PRODUCING_VAR}  # never a producer there
    env[datadeps.OVERRIDE] = ','.join(f'{dep.name}={head}' for dep in rows)
    roots = [r for r in load_policy(tree).test_roots if (tree / r).exists()] or ['tests']
    argv = ['-m', 'dev_lab.dev.verify', '--', *roots, *part_selection(tree, consumer.part)]
    code, log = execute(tree, argv, env)
    outcome = _EXIT.get(code, Conclusion.INCONCLUSIVE)
    found, unsure = read_cells(outcomes_dir(log)) if log is not None else ({}, frozenset())
    if outcome is not Conclusion.INCONCLUSIVE and not found:
        outcome = Conclusion.INCONCLUSIVE  # an exit code over no recorded test proves nothing
    cells = {f'{member}:{node}': cell for node, cell in found.items()}
    line = f'{member} part {consumer.part} at data {head[:12]}: {outcome.name} (exit {code}, {len(cells)} tests)'
    return outcome, cells, frozenset(f'{member}:{node}' for node in unsure), line


def _origin(checkout: Path, repo: str) -> bool:
    try:
        return same_repo(_git(checkout, 'remote', 'get-url', 'origin'), repo)
    except VerifyByRefused:
        return False


def post(root: Path, commit: str | None, judged: Judged) -> str:
    """Post *judged* as the ``tests/base`` part of *commit* on the data repo *root*; one line, never a raise."""
    if commit is None:
        return 'part: not posted -- the tree was dirty or moved, so this run is about no commit'
    if judged.result is Conclusion.INCONCLUSIVE:
        return 'part: not posted -- an INCONCLUSIVE run is no part'
    try:
        directory = record_directory(root, commit)
    except UndeclaredPart as why:
        return f'part: not posted -- {why}'
    owned = dict.fromkeys(judged.cells, BASE)
    record = local_record(
        root, sha=commit, part=BASE, scope=FULL, req='verify-by', cells=judged.cells, owned=owned, flaky=judged.flaky
    )
    return post_local(root, record, directory)


def main(root: Path, *, producer: bool) -> int:
    """*root*'s verify when it declares consumers: judge them, print, post when *producer*; the exit code."""
    head, start = head_sha(root), status_paths(root)
    try:
        judged = judge(root, head or '', declared(root), url=origin_url(root), members=repos())
    except (VerifyByRefused, ValueError, OSError) as why:
        judged = Judged(Conclusion.INCONCLUSIVE, {}, frozenset(), (str(why),))
    for line in judged.lines:
        emit(f'verify-by: {line}')
    emit(f"verify: {judged.result.name} -- this data repo is judged by its consumers' tests")
    if producer:
        emit(post(root, verdict_commit(head, head_sha(root), start, status_paths(root)), judged))
    return int(ProducerExit[judged.result.name])
