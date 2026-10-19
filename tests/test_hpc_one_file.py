"""An HPC job ships ONE file and leaves a few: one artifact per sha, one results file per job, a file budget.

Plan 2026-10-17 (motronics ``PLAN-an-hpc-job-ships-one-file-not-a-checkout``): a campaign job reused the test
layout -- a full checkout plus an unpacked venv per sha, a log and a results file per task -- and cost ~46 k
files per sha against a 2 M file quota. Every rule here is checked against a planted control.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
from dataclasses import replace
from pathlib import Path

import pytest

from lab_commons.dev.githooks import bash_executable
from lab_commons.hpc import __main__ as cli
from lab_commons.hpc import shell
from lab_commons.hpc.artifact import (
    FORMATS,
    IMAGE,
    TARBALL,
    ArtifactRefused,
    artifact_script,
    build_artifact,
    enter_lines,
    require,
)
from lab_commons.hpc.builds import Builds, read_builds
from lab_commons.hpc.cluster import files_of, gather, render_script, run_home, submit
from lab_commons.hpc.config import Cluster, Config, Cost, JobSpec, Limits, Policy
from lab_commons.hpc.grants import Grant, Machine
from lab_commons.hpc.jobs import gather_job
from lab_commons.hpc.plan import make_plan
from lab_commons.hpc.shell import BUILD_FAILED, UV_PRUNE, RunSpec, build_script, cache_dir, facts
from lab_commons.hpc.slurm import parse_snapshot
from lab_commons.hpc.tree import NotSubmitted
from lab_commons.hpc.worker import RESULTS, TAIL_LINES, Rejected, append_event, close_shard, run_shard
from lab_commons.hpc.worker import main as worker_main
from lab_commons.outcomes import Reason, Status
from lab_commons.outcomes.jsonl import read_jsonl
from lab_commons.outcomes.record import OUTCOME, Event

FIXTURE = (Path(__file__).parent / '_hpc_fixtures' / 'cluster-2026-10-08.txt').read_text(encoding='utf-8')
IDLE = FIXTURE.split('@@@ running')[0] + '@@@ running\n'
SHA = 'c' * 40
NL = chr(10)
#: What the login node prints between the results file and an earlier worker's per-shard files.
EARLIER = NL + '@@@ earlier-layout' + NL
BUILDS = Builds(install='uv sync', source_roots=('src',), artifact_paths=('cases',), env_key='k1')


class Login:
    """A login node answering by the first key found in the command; every call kept."""

    def __init__(self, answers: dict[str, str]) -> None:
        """*answers* maps a substring of a command to its stdout."""
        self.answers, self.calls = answers, []

    def __call__(self, command: str, stdin: str | None = None) -> str:
        self.calls.append((command, stdin))
        return next((out for key, out in self.answers.items() if key in command), '')


def _manifest(tmp_path: Path, items: list[int], shards: list[list[int]]) -> Path:
    path = tmp_path / 'run' / 'manifest.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'entry': 'math:sqrt', 'items': items, 'shards': shards}), encoding='utf-8')
    return path


def _plan() -> object:
    return make_plan(
        10,
        Cost(seconds=60),
        parse_snapshot(IDLE),
        cluster=Cluster(partitions=('shortq', 'defq')),
        policy=Policy(),
        limits=Limits(),
    )


# -- phase 3: one results file per job ------------------------------------------------------------------


def test_every_shard_appends_to_the_one_results_file_and_an_item_failure_is_data(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, [4, 9, -1, 16], [[0, 2], [2, 4]])
    for shard in ('0', '1'):
        assert worker_main([str(manifest), shard]) == 0
    rows = read_jsonl(manifest.parent / RESULTS).rows
    events = [Event.from_plain(row) for row in rows]
    assert [(e.kind, e.key, e.cell.status) for e in events] == [
        (OUTCOME, '0', Status.OK),
        (OUTCOME, '1', Status.OK),
        (OUTCOME, '2', Status.ERROR),
        (OUTCOME, '3', Status.OK),
    ]
    assert events[0].data == {'shard': 0, 'value': 2.0}
    assert 'ValueError' in events[2].cell.reason.text
    assert sorted(p.name for p in manifest.parent.iterdir()) == ['manifest.json', RESULTS], 'no file per shard'


def _judge(item: int) -> int:
    if item < 0:
        raise Rejected(Reason('invalid', f'{item} is negative'))
    if item == 0:
        raise ZeroDivisionError(item)
    return item


def test_a_declared_rejection_is_rejected_and_any_other_exception_an_error(tmp_path: Path) -> None:
    """Control: only the declared :class:`Rejected` is a DECIDED no; a crash is RETRYABLE."""
    results = tmp_path / RESULTS
    run_shard({'items': [3, -1, 0], 'shards': [[0, 3]]}, 0, results, entry=_judge)
    cells = [Event.from_plain(row).cell for row in read_jsonl(results).rows]
    assert [c.status for c in cells] == [Status.OK, Status.REJECTED, Status.ERROR]
    assert cells[1].reason == Reason('invalid', '-1 is negative')
    assert cells[2].reason.kind == 'exception'
    assert 'ZeroDivisionError' in cells[2].reason.text
    gathered = gather(Login({RESULTS: results.read_text(encoding='utf-8') + _lines(_close(0)) + EARLIER}), '~/r')
    assert [(r['index'], r['ok'], r['status']) for r in gathered[0]] == [
        (0, True, 'ok'),
        (1, False, 'rejected'),
        (2, False, 'error'),
    ]
    assert gathered[0][1]['error'] == '-1 is negative'


def test_a_wide_run_still_writes_one_file(tmp_path: Path) -> None:
    """25 shards, as many writers: the run directory holds the manifest and ONE results file."""
    manifest = _manifest(tmp_path, list(range(50)), [[2 * i, 2 * i + 2] for i in range(25)])
    for shard in range(25):
        worker_main([str(manifest), str(shard)])
        log = tmp_path / f'task-{shard}.log'  # node-local $TMPDIR on the cluster, never the run directory
        log.write_text('out' + NL, encoding='utf-8')
        assert worker_main(['--close', str(manifest), str(shard), '0', str(log)]) == 0
    assert len(list(manifest.parent.iterdir())) == 2
    assert len(read_jsonl(manifest.parent / RESULTS).rows) == 50 + 25


def test_close_keeps_only_the_tail_of_the_tasks_output(tmp_path: Path) -> None:
    log = tmp_path / 'task.log'
    log.write_text(NL.join(f'line {n}' for n in range(TAIL_LINES + 25)) + NL, encoding='utf-8')
    close_shard(tmp_path / RESULTS, 3, 137, log)
    (row,) = read_jsonl(tmp_path / RESULTS).rows
    event = Event.from_plain(row)
    assert (event.kind, event.key, event.data['code']) == ('shard', '3', 137)
    assert event.data['tail'] == [f'line {n}' for n in range(25, TAIL_LINES + 25)]
    close_shard(tmp_path / RESULTS, 4, 1, tmp_path / 'absent.log')
    assert Event.from_plain(read_jsonl(tmp_path / RESULTS).rows[-1]).data['tail'] == [], 'no log: an empty tail'


def test_an_append_cuts_a_killed_writers_torn_tail(tmp_path: Path) -> None:
    path = tmp_path / RESULTS
    append_event(path, Event('item', '0', data={'shard': 0, 'ok': True, 'value': 1}))
    with path.open('ab') as handle:
        handle.write(b'{"schema":2,"kind":"item","key":"1","da')  # killed mid-line
    assert read_jsonl(path).torn, 'PLANTED CONTROL: the tail is torn before the append'
    append_event(path, Event('item', '2', data={'shard': 0, 'ok': True, 'value': 3}))
    read = read_jsonl(path)
    assert not read.torn
    assert [row['key'] for row in read.rows] == ['0', '2']


def _lines(*events: tuple[str, str, dict]) -> str:
    return ''.join(json.dumps(Event(kind, key, data=data).to_plain()) + NL for kind, key, data in events)


def _item(index: int, shard: int, value: object) -> tuple[str, str, dict]:
    return ('item', str(index), {'shard': shard, 'ok': True, 'value': value})


def _close(shard: int, code: int = 0) -> tuple[str, str, dict]:
    return ('shard', str(shard), {'code': code, 'tail': []})


def _ok(index: int, value: object) -> dict:
    return {'index': index, 'ok': True, 'status': 'ok', 'value': value}


def test_gather_derives_every_returned_shard_from_the_one_file() -> None:
    """FORMATS-UPGRADE-ON-READ: these are a pre-Cell worker's ``item`` lines, still read as OK items."""
    text = _lines(
        _item(0, 0, 'a'),
        _item(1, 0, 'b'),
        _close(0),
        _item(2, 1, 'killed'),  # shard 1 was killed: items, no close
        _item(4, 2, 'x'),
        _close(2, 1),  # shard 2's worker failed
        _item(2, 1, 'c'),  # the re-run of shard 1 supersedes its first attempt
        _item(3, 1, 'd'),
        _close(1),
    )
    login = Login({RESULTS: text + EARLIER})
    got = gather(login, '~/ci/jobs/s/sweep-t0')
    assert got == {
        0: [_ok(0, 'a'), _ok(1, 'b')],
        1: [_ok(2, 'c'), _ok(3, 'd')],
    }, 'shard 2 closed non-zero: not returned, so a retry re-runs it'
    assert gather(Login({RESULTS: text + '{"schema":2,"ki' + EARLIER}), '~/r') == got, 'a torn last line is cut'
    with pytest.raises(ValueError, match=r'Expecting|Unterminated'):
        gather(Login({RESULTS: '{"schema":2,"ki' + NL + text + EARLIER}), '~/r')


def test_a_run_an_earlier_worker_wrote_still_gathers() -> None:
    """FORMATS-UPGRADE-ON-READ: jobs on the cluster across the change wrote one ``results/<shard>.json`` each."""
    old = NL.join(
        json.dumps({'shard': shard, 'results': [{'index': shard, 'ok': True, 'value': shard * 10}]}) for shard in (0, 1)
    )
    login = Login({RESULTS: EARLIER + old + NL, 'find ': '57\n', '-d ': ''})
    assert gather(login, '~/p/.lab-hpc/sweep-t0') == {
        0: [_ok(0, 0)],
        1: [_ok(1, 10)],
    }
    assert files_of(Login({'find ': '57\nearlier\n'}), '~/r') == (57, True)
    assert files_of(Login({'find ': '3\n'}), '~/r') == (3, False)


# -- phase 6: the file budget is data, judged at gather ---------------------------------------------------

NEAR = Grant(user='me', hosts=('near',), slurm_account='acct-free')
RECORD = {
    'placements': [
        {
            'grant': NEAR.name,
            'account': list(NEAR.account),
            'targets': ['me@near'],
            'job_ids': ['1'],
            'shards': 1,
            'items': [0, 1],
            'run_dir': '~/ci/jobs/s/sweep-t0',
        }
    ]
}


def _gathered(files: str, *, budget: int = Policy().file_budget) -> object:
    login = Login({RESULTS: _lines(_item(0, 0, 'v'), _close(0)) + EARLIER, 'find ': files})
    return gather_job(RECORD, Machine(session=None, grants=(NEAR,)), lambda _g: login, budget=budget)


def test_a_planted_eleven_file_job_reds_and_ten_does_not(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Policy().file_budget == 10, 'the declared default (plan: <= 10 files on the shared home)'
    over = _gathered('11\n')
    assert over.over == [f'{NEAR.name}: ~/ci/jobs/s/sweep-t0 holds 11 files, over file_budget = 10']
    assert _gathered('10\n').over == [], 'PLANTED CONTROL: at the budget is within it'
    assert _gathered('11\n', budget=12).over == [], 'the budget is data: [policy] file_budget moves it'
    earlier = _gathered('57\nearlier\n')
    assert (earlier.over, earlier.earlier) == ([], [f'{NEAR.name}: ~/ci/jobs/s/sweep-t0'])
    out: list[str] = []
    monkeypatch.setattr(cli, '_out', out.append)
    monkeypatch.setattr(cli, 'gather_job', lambda *_a, **_k: over)
    assert cli._gather(RECORD, Machine(session=None, grants=(NEAR,)), None, None, 10) == 1, 'over budget FAILS'
    assert any('OVER FILE BUDGET' in line for line in out)
    monkeypatch.setattr(cli, 'gather_job', lambda *_a, **_k: _gathered('3\n'))
    assert cli._gather(RECORD, Machine(session=None, grants=(NEAR,)), None, None, 10) == 0


def test_a_budget_below_one_file_is_refused() -> None:
    with pytest.raises(ValueError, match='unusable policy'):
        Policy(file_budget=0)


# -- phase 2/3: the task script -- no checkout, no file per task --------------------------------------------


def test_the_task_script_keeps_its_output_node_local_and_closes_its_shard() -> None:
    config = Config(job=JobSpec(name='sweep', entry='m:f', sha=SHA, repo_url='https://x/r.git'))
    script = render_script(_plan(), cli.built_config(config), f'~/ci/jobs/{SHA}/sweep-t0')
    assert '#SBATCH --output=/dev/null' in script
    assert 'logs/' not in script, 'Slurm writes no per-task file on the shared home'
    assert 'LOG="${TMPDIR:-/tmp}/' in script
    assert 'lab_commons.hpc.worker "$M" "$SLURM_ARRAY_TASK_ID" > "$LOG" 2>&1 || code=$?' in script
    assert '--close "$M" "$SLURM_ARRAY_TASK_ID" "$code" "$LOG"' in script
    assert script.rstrip().endswith('exit "$code"')
    unpack = script.index('tar -xzf')
    assert unpack < script.index('lab_commons.hpc.worker'), 'the artifact is entered before the worker runs'
    assert 'ci/trees' not in script, 'a job never checks out the repository'
    assert 'git ' not in script


def test_a_commits_runs_live_under_its_sha_and_hold_three_files(tmp_path: Path) -> None:
    job = JobSpec(name='sweep', entry='m:f', sha=SHA, repo_url='https://x/r.git')
    assert run_home(job) == f'~/ci/jobs/{SHA}'
    assert run_home(JobSpec(workdir='~/p')) == '~/p/.lab-hpc', 'PLANTED CONTROL: a job at no commit'
    login = Login({'sbatch': '42\n'})
    sub = submit(login, _plan(), Config(job=job, source=tmp_path / 'j.toml'), list(range(10)), stamp='t0')
    assert sub.run_dir == f'~/ci/jobs/{SHA}/sweep-t0'
    made = login.calls[0][0]
    assert made.startswith('mkdir -p ')
    assert 'logs' not in made
    assert 'results' not in made


# -- phase 1: one artifact per sha ---------------------------------------------------------------------------


def test_the_artifact_format_is_a_declared_choice_and_the_image_is_refused_for_good() -> None:
    assert set(FORMATS) == {TARBALL, IMAGE}
    require(TARBALL)
    with pytest.raises(ArtifactRefused, match='phase 6 closed') as refused:
        require(IMAGE)
    assert 'uv sync --frozen' in str(refused.value), 'the refusal names why the phase closed'
    with pytest.raises(ArtifactRefused, match='not a format'):
        require('zip')
    with pytest.raises(ArtifactRefused):
        cli.built_config(Config(job=JobSpec(sha=SHA, repo_url='https://x/r.git', artifact=IMAGE)))


def test_the_artifact_build_leaves_one_file_and_no_resident_cache() -> None:
    script = artifact_script(RunSpec(sha=SHA, repo_url='https://x/r.git', builds=BUILDS))
    assert f'A="$HOME"/ci/artifacts/{SHA}.tar.gz' in script
    assert 'if [ ! -s "$A" ]' in script, 'an artifact that exists is reused'
    assert 'mktemp -d "${TMPDIR:-/tmp}/' in script
    assert 'EXIT' in script
    assert f'archive {SHA} | tar -x' in script, 'exported, never a worktree'
    assert 'UV_CACHE_DIR="$S/uv-cache"' in script, 'phase 4: the uv cache dies with the scratch'
    for gone in ('worktree add', 'ci/envs', 'ci/trees', 'ci/uv-cache'):
        assert gone not in script, gone
    assert 'for p in src cases;' in script, 'the source roots and the declared paths, nothing else'
    assert 'PYTHONPATH="$ART/tree/src${PYTHONPATH' in script
    assert 'tar -czf "$A.part" -C "$S/pack" . && mv "$A.part" "$A"' in script, 'one file, atomically'
    native = artifact_script(RunSpec(sha=SHA, repo_url='u', builds=replace(BUILDS, native_key='n9', native_build='b')))
    assert 'ci/native/n9' in native, 'a native build stays keyed'
    assert '$ART/native' in native, 'and is packed'


def test_the_task_enters_the_unpacked_artifact() -> None:
    lines = enter_lines(SHA)
    assert lines[0] == 'ART="${TMPDIR:-/tmp}/lab-artifact-${SLURM_JOB_ID}"'
    assert f'tar -xzf "$HOME"/ci/artifacts/{SHA}.tar.gz -C "$ART"' in lines[2]
    assert lines[-2:] == ('. "$ART/activate.sh"', 'cd "$ART/tree"')


def test_build_artifact_answers_the_path_or_refuses_with_the_log() -> None:
    spec = RunSpec(sha=SHA, repo_url='https://x/r.git', builds=BUILDS)
    ok = Login(
        {'command -v': '', 'cat-file': 'have\n', 'mktemp': f'@@@ facts{NL}artifact=/h/ci/artifacts/{SHA}.tar.gz'}
    )
    assert build_artifact(spec, ok, 'login1') == f'/h/ci/artifacts/{SHA}.tar.gz'
    failed = Login({'command -v': '', 'cat-file': 'have\n', 'mktemp': f'{BUILD_FAILED} env{NL}no wheel'})
    with pytest.raises(NotSubmitted, match='no wheel'):
        build_artifact(spec, failed, 'login1')
    lacking = Login({'command -v': '@@@ missing uv\n'})
    with pytest.raises(NotSubmitted, match='lacks uv'):
        build_artifact(spec, lacking, 'login1')


def test_the_declaration_names_what_the_artifact_carries() -> None:
    text = '[tool.lab_commons.hpc]\ninstall = "uv sync"\nsource_roots = ["src"]\nartifact_paths = ["cases"]\n'
    assert read_builds(text).artifact_paths == ('cases',)


def test_a_test_runs_env_build_prunes_the_shared_uv_cache() -> None:
    script = build_script(RunSpec(sha=SHA, repo_url='u', builds=BUILDS))
    assert UV_PRUNE in script
    assert script.index(UV_PRUNE) > script.index('uv sync'), 'after the install it served'


def _git(*args: str | Path, cwd: Path | None = None) -> str:
    done = subprocess.run(
        [shell._GIT, *map(str, args)], cwd=cwd, capture_output=True, text=True, encoding='utf-8', check=True
    )
    return done.stdout.strip()


def _commit(work: Path, files: dict[str, str]) -> str:
    for name, text in files.items():
        (work / name).parent.mkdir(parents=True, exist_ok=True)
        (work / name).write_text(text, encoding='utf-8')
    _git('add', '.', cwd=work)
    _git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'c', '--allow-empty', cwd=work)
    return _git('rev-parse', 'HEAD', cwd=work)


def _project(name: str, deps: str = '') -> str:
    return f'[project]\nname = "{name}"\nversion = "0"\nrequires-python = ">=3.9"\ndependencies = [{deps}]\n'


def test_the_artifact_exports_every_submodule_at_its_pinned_commit_before_the_install(tmp_path: Path) -> None:
    """A submodule that is a path dependency reaches the install at the commit the exported sha pins.

    PLANTED CONTROL: ``top`` pins ``components/dep`` -- a submodule that is ``top``'s uv PATH dependency, and
    itself pins ``leaf``. A bare ``git archive`` leaves ``components/dep`` empty and ``uv sync --frozen`` fails.

    The submodule moves on after the pin: the artifact must carry the PINNED commit, not its branch head.
    """
    remotes, work = tmp_path / 'remotes', tmp_path / 'work'
    urls = {n: (remotes / f'{n}.git').as_posix() for n in ('leaf', 'dep', 'top')}
    for name in ('leaf', 'dep', 'top'):
        _git('init', '-q', '-b', 'main', work / name)
        _git('remote', 'add', 'origin', urls[name], cwd=work / name)
    allow = ('-c', 'protocol.file.allow=always')
    _commit(work / 'leaf', {'leaf.txt': 'leaf'})
    _git('clone', '-q', '--bare', work / 'leaf', urls['leaf'])
    _commit(work / 'dep', {'pyproject.toml': _project('dep'), 'dep/__init__.py': 'PINNED = True\n'})
    _git(*allow, 'submodule', 'add', '-q', '../leaf.git', 'leaf', cwd=work / 'dep')
    _commit(work / 'dep', {})
    _git('clone', '-q', '--bare', work / 'dep', urls['dep'])
    top = work / 'top'
    _commit(
        top, {'pyproject.toml': _project('top', '"dep"') + '[tool.uv.sources]\ndep = { path = "components/dep" }\n'}
    )
    _git(*allow, 'submodule', 'add', '-q', '../dep.git', 'components/dep', cwd=top)
    subprocess.run([shutil.which('uv') or 'uv', 'lock', '-q', '--offline'], cwd=top, check=True)
    sha = _commit(top, {})
    _git('clone', '-q', '--bare', top, urls['top'])
    moved = work / 'dep'
    _commit(moved, {'dep/__init__.py': 'PINNED = False\n'})
    _git('push', '-q', 'origin', 'main', cwd=moved)  # the pin is now behind the branch head

    home = tmp_path / 'home'
    builds = Builds(install='uv sync -q --frozen --offline', source_roots=('components',), env_key='k1')
    spec = RunSpec(sha=sha, repo_url=urls['top'], builds=builds, python=Path(sys.executable).as_posix())
    cache = Path(cache_dir(spec.repo_url).replace('"$HOME"', home.as_posix()))
    _git('clone', '-q', '--bare', urls['top'], cache)
    env = {**os.environ, 'HOME': home.as_posix(), 'GIT_CONFIG_PARAMETERS': "'protocol.file.allow=always'"}
    done = subprocess.run(
        [bash_executable(), '-c', artifact_script(spec)],
        capture_output=True,
        text=True,
        encoding='utf-8',
        env=env,
        check=False,
    )
    assert BUILD_FAILED not in done.stdout, done.stdout
    assert done.returncode == 0, (done.stdout, done.stderr)
    with tarfile.open(facts(done.stdout)['artifact'].replace('"$HOME"', home.as_posix())) as tar:
        names = set(tar.getnames())
        pinned = tar.extractfile('./tree/components/dep/dep/__init__.py')
        assert pinned is not None
        assert pinned.read() == b'PINNED = True\n', 'the commit the sha pins, not the branch head'
    assert './tree/components/dep/leaf/leaf.txt' in names, 'recursively'
    assert not (Path(urls['top']) / 'modules').exists(), "nothing written into the repository's cache"


def test_the_artifact_exports_submodules_between_the_archive_and_the_install() -> None:
    script = artifact_script(RunSpec(sha=SHA, repo_url='https://x/r.git', builds=BUILDS))
    assert 'git submodule update' not in script
    archive, subs, venv = (script.index(s) for s in (f'archive {SHA} |', 'lc_export ', 'uv venv'))
    assert archive < subs < venv
