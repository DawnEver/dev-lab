"""THE RESUMABLE CLUSTER TICK: each serve call advances on-disk state; Slurm is the truth; only the owner renews.

The forge is a store of status posts answering the two calls a claim makes (post, list), with its own
clock; Slurm is a fake that counts submissions. A "crash" is a new tick reading the state back from disk.
"""

from __future__ import annotations

import dataclasses
import functools
import io
import json
import sys
import tarfile
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lab_commons.config import CONFIG_ENV
from lab_commons.dev import artefacts, forgecarry, forgerun, forgeship, forgeslurm
from lab_commons.dev.forgealarm import LEASE, Alarm
from lab_commons.dev.forgeclaim import DESCRIPTION_LIMIT, Claim, Work
from lab_commons.dev.forgework import GITEA, ForgeCallFailed
from lab_commons.dev.netverb import Attempt, Diagnosis, Report
from lab_commons.dev.platformparts import ClusterPart, PartRefusal
from lab_commons.dev.producer import ProducerExit, release_reason
from lab_commons.hpc import records
from lab_commons.hpc.progress import Progress
from lab_commons.hpc.run import NotSubmitted

SHA = 'c' * 40
NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
HOURS6 = timedelta(hours=6)
HERE = Claim('hpclogin02', 'alice', NOW + HOURS6, 'ada/alice')
OTHER_HOST = Claim('hpclogin01', 'alice', NOW + HOURS6, 'ada/alice')
BOB = Claim('hpclogin02', 'bob', NOW + HOURS6, 'ada/bob')


class _Store:
    """Every status post on one commit, ids ascending; the forge's clock is :attr:`now`."""

    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []
        self.now = NOW
        self.refuse = False

    def add(self, state: str, description: str) -> None:
        self.posts.append(
            {'id': len(self.posts) + 1, 'context': 'tests/linux', 'status': state, 'description': description}
        )


class _Client:
    """The forge as one login sees it -- only what a claim and a release call."""

    backend = GITEA
    repo = '/api/v1/repos/o/r'
    forge = SimpleNamespace(host='f', owner='o', repo='r')

    def __init__(self, store: _Store) -> None:
        self.store = store

    @property
    def answered(self) -> str:
        return format_datetime(self.store.now, usegmt=True)

    def call(self, method: str, _path: str, body: dict[str, str] | None = None) -> object:
        if method == 'POST':
            if self.store.refuse:
                attempt = Attempt(1, 403, 'forbidden', Diagnosis.FORGE_REFUSED)
                raise ForgeCallFailed(Report(('POST', _path), (attempt,), 3))
            assert body is not None
            self.store.add(body['state'], body['description'])
            return self.store.posts[-1]
        return list(self.store.posts)


class _Slurm:
    """Counts submissions; *state* is what ``hpc`` recorded on the cluster, *queue* what squeue holds."""

    def __init__(self, record: Path) -> None:
        self.recorded: list[str] = []
        self.queue: list[str] = []
        self.submits = 0
        self.done = False
        self.record = record
        self.phrase = 'queued 4/4'
        self.cancelled: list[str] = []

    def submitted(self, _run: forgerun.Run) -> list[str]:
        return list(self.recorded)

    def orphans(self, _run: forgerun.Run) -> list[str]:
        return list(self.queue)

    def submit(self, _run: forgerun.Run) -> list[str]:
        self.submits += 1
        self.recorded = ['4242']
        return ['4242']

    def gather(self, _run: forgerun.Run) -> Path | None:
        return self.record if self.done else None

    def progress(self, _run: forgerun.Run) -> str:
        return self.phrase

    def cancel(self, run: forgerun.Run) -> list[str]:
        self.cancelled += run.job_ids
        return list(run.job_ids)

    def tree(self, _run: forgerun.Run) -> Path:
        return self.record.parent / 'tree'


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    monkeypatch.setattr(forgerun, 'pyproject_at', lambda _root, _sha: '')
    monkeypatch.setattr(forgerun, 'route', lambda *_a: ())
    monkeypatch.setattr(forgerun, 'read_record', lambda _path: {'sha': SHA})
    return tmp_path


def _start(tmp_path: Path, store: _Store, owner: Claim = HERE, outputs: tuple[str, ...] = ()) -> forgerun.Run:
    store.add('pending', owner.description())
    part = ClusterPart('https://f/o/r.git', 'tests', tmp_path / 'parts', outputs)
    return forgerun.start(Work('integrate/main', SHA, 'linux', 'mine', owner, cluster=part), owner)


def _tick(
    store: _Store, slurm: _Slurm, *, me: Claim = HERE, alarms: list[Alarm] | None = None, root: Path | None = None
) -> forgerun.Run | None:
    """One serve call: read the run back from disk (a fresh process) and advance it."""
    (run,) = forgerun.live('https://f/o/r.git')
    return forgerun.advance(
        root or Path(),
        run,
        client=_Client(store),
        me=me,
        lease=HOURS6,
        cluster=slurm,
        say=lambda _line: None,
        alarm=(alarms if alarms is not None else []).append,
    )


def test_each_tick_advances_the_run_and_a_restart_resumes_without_resubmitting(home: Path, monkeypatch) -> None:
    store, slurm = _Store(), _Slurm(home / 'run.json.gz')
    posted: list[Path] = []
    monkeypatch.setattr(forgecarry, 'post', lambda _root, path: posted.append(path) or 'posted')
    _start(home, store)
    after = _tick(store, slurm)
    assert after is not None
    assert (after.phase, after.job_ids, slurm.submits) == (forgerun.SUBMITTED, ('4242',), 1)
    assert _tick(store, slurm) is not None, 'still running: the tick returns, nothing waits'
    assert slurm.submits == 1, 'a restart (state re-read from disk) resumes; it never resubmits'
    slurm.done = True
    assert _tick(store, slurm) is None, 'gathered, published, released in one tick'
    assert posted == [home / 'run.json.gz']
    assert forgerun.live('https://f/o/r.git') == (), 'released: the state file is gone'


def test_a_retry_round_moves_the_runs_job_ids_to_the_round_in_flight(home: Path) -> None:
    """Each tick re-reads every round's job id from the cluster; the run file never keeps its submit's.

    Measured 2026-10-12 on Ada: r0 and r1 died OUT_OF_MEMORY, r2 ran, and every tick still said
    ``running (jobs 7667160)`` -- the r0 job squeue had long forgotten -- because the run file kept the
    ids of its SUBMIT. The retries are hpc's (one per gather); each tick re-reads them from the cluster.
    """
    store, slurm = _Store(), _Slurm(home / 'r')
    _start(home, store)
    _tick(store, slurm)
    slurm.recorded = ['7667160', '7667161', '7667163']
    said: list[str] = []
    (run,) = forgerun.live('https://f/o/r.git')
    after = forgerun.advance(
        Path(), run, client=_Client(store), me=HERE, lease=HOURS6, cluster=slurm, say=said.append, alarm=[].append
    )
    assert after is not None
    assert after.job_ids == ('7667160', '7667161', '7667163'), 'every round, so a cancel reaches them all'
    assert forgerun.live('https://f/o/r.git')[0].job_ids == after.job_ids, 'and the file carries them'
    assert any('job 7667163' in line and 'round 3' in line for line in said), said


def test_a_crash_after_sbatch_adopts_the_jobs_slurm_recorded(home: Path) -> None:
    """PLANTED CONTROL: phase still ``claimed`` on disk, but hpc recorded the run -- Slurm, not the file, decides."""
    store, slurm = _Store(), _Slurm(home / 'r')
    _start(home, store)
    slurm.recorded = ['777']
    after = _tick(store, slurm)
    assert after is not None
    assert (after.phase, after.job_ids, slurm.submits) == (forgerun.SUBMITTED, ('777',), 0)


def test_orphaned_jobs_raise_an_alarm_and_are_never_resubmitted(home: Path) -> None:
    store, slurm, alarms = _Store(), _Slurm(home / 'r'), []
    _start(home, store)
    slurm.queue = ['555']
    after = _tick(store, slurm, alarms=alarms)
    assert after is not None
    assert (after.phase, slurm.submits) == (forgerun.CLAIMED_PHASE, 0)
    assert [a.kind for a in alarms] == [LEASE]
    assert 'scancel' in alarms[0].body


def test_another_login_host_of_this_account_holding_it_live_is_left_alone(home: Path) -> None:
    """ONE HOST PER ACCOUNT: flock on GPFS is not cross-host, so the idempotent state is the guard."""
    store, slurm = _Store(), _Slurm(home / 'r')
    _start(home, store, owner=OTHER_HOST)
    before = list(store.posts)
    after = _tick(store, slurm, me=HERE)
    assert after is not None
    assert after.owner == OTHER_HOST.description()
    assert (store.posts, slurm.submits) == (before, 0), 'nothing posted, nothing submitted'


def test_a_lapsed_owner_on_another_host_is_adopted_and_slurm_says_where_the_run_is(home: Path) -> None:
    """PLANTED CONTROL: the same foreign owner, its lease past by the FORGE's clock."""
    store, slurm = _Store(), _Slurm(home / 'r')
    _start(home, store, owner=OTHER_HOST)
    slurm.recorded = ['777']
    store.now = NOW + HOURS6 + timedelta(minutes=1)
    after = _tick(store, slurm, me=HERE)
    assert after is not None
    assert Claim.parse(after.owner) == dataclasses.replace(HERE, until=store.now + HOURS6)
    assert (after.job_ids, slurm.submits) == (('777',), 0)


def test_a_claim_another_owner_won_stands_the_run_down(home: Path) -> None:
    store, slurm, alarms = _Store(), _Slurm(home / 'r'), []
    _start(home, store)
    store.now = NOW + HOURS6 + timedelta(minutes=1)
    store.add('pending', dataclasses.replace(BOB, until=store.now + HOURS6).description())
    assert _tick(store, slurm, alarms=alarms) is None
    assert forgerun.live('https://f/o/r.git') == ()
    assert [a.kind for a in alarms] == [LEASE]
    assert slurm.submits == 0, 'a loser never produces'


def test_only_the_owner_renews_and_only_once_a_third_of_the_lease_has_passed(home: Path) -> None:
    store, slurm = _Store(), _Slurm(home / 'r')
    _start(home, store)
    _tick(store, slurm)
    posted = len(store.posts)  # the claim, then its progress: building, queued 4/4
    _tick(store, slurm)
    assert len(store.posts) == posted, 'a fresh claim with unchanged progress is not re-posted every five minutes'
    store.now = NOW + timedelta(hours=2, minutes=1)
    _tick(store, slurm)
    assert len(store.posts) == posted + 1
    renewed = dataclasses.replace(HERE, until=store.now + HOURS6, progress='queued 4/4')
    assert Claim.parse(store.posts[-1]['description']) == renewed, 'the renewal still shows the progress'


def test_a_lease_that_cannot_be_renewed_alarms_and_keeps_the_run(home: Path) -> None:
    store, slurm, alarms = _Store(), _Slurm(home / 'r'), []
    _start(home, store)
    store.now, store.refuse = NOW + timedelta(hours=3), True
    after = _tick(store, slurm, alarms=alarms)
    assert after is not None
    assert after.phase == forgerun.CLAIMED_PHASE
    assert [a.kind for a in alarms] == [LEASE]
    assert slurm.submits == 0


def test_an_inconclusive_record_is_released_never_posted(home: Path, monkeypatch) -> None:
    store, slurm = _Store(), _Slurm(home / 'r')
    slurm.done = True

    def refuse(_root: Path, _path: Path) -> str:
        msg = 'INCONCLUSIVE: 3 lost'
        raise PartRefusal(msg)

    monkeypatch.setattr(forgecarry, 'post', refuse)
    _start(home, store)
    assert _tick(store, slurm) is None
    assert (store.posts[-1]['status'], store.posts[-1]['description']) == (
        'error',
        release_reason(ProducerExit.INCONCLUSIVE),
    )


def test_a_failed_build_is_released_inconclusive_naming_its_log(home: Path) -> None:
    """Live 2026-10-11 (a consumer's part): a native build lacking cmake submitted nothing and was released FAIL.

    PLANTED CONTROL: the same tick with a build that succeeds submits and keeps the run.
    """
    log = 'log=/ci/native/k.log'

    class _Unbuilt(_Slurm):
        def submit(self, _run: forgerun.Run) -> list[str]:
            msg = f'the build for {SHA[:12]} failed on h, nothing was submitted; {log}\ncmake not found'
            raise NotSubmitted(msg)

    store = _Store()
    _start(home, store)
    assert _tick(store, _Unbuilt(home / 'r')) is None, 'released and dropped'
    assert (store.posts[-1]['status'], store.posts[-1]['description']) == (
        'error',
        f'{release_reason(ProducerExit.INCONCLUSIVE)} {log}',
    )
    assert forgerun.live('https://f/o/r.git') == ()
    _start(home, store)
    assert _tick(store, _Slurm(home / 'r')).phase == forgerun.SUBMITTED


def test_a_live_run_of_another_schema_is_refused_with_the_remedy(home: Path) -> None:
    """PLANTED CONTROL: the same file at this schema is read."""
    store = _Store()
    run = _start(home, store)
    assert forgerun.live(run.repo_url) == (run,)
    (path,) = forgerun.directory().glob('*.json')
    path.write_text(json.dumps({**json.loads(path.read_text(encoding='utf-8')), 'schema': 0}), encoding='utf-8')
    with pytest.raises(forgerun.ForeignSchema, match=r'schema 0.*squeue --me'):
        forgerun.live(run.repo_url)


def test_the_state_is_keyed_by_repo_sha_platform_and_scope(home: Path) -> None:
    store = _Store()
    run = _start(home, store)
    other = dataclasses.replace(run, repo_url='https://f/o/other.git')
    forgerun.save(other)
    assert forgerun.live(run.repo_url) == (run,)
    assert forgerun.live(other.repo_url) == (other,)
    assert len(list(forgerun.directory().glob('*.json'))) == 2


def _progress(store: _Store) -> list[str]:
    return [found.progress for post in store.posts if (found := Claim.parse(post['description'])) and found.progress]


def test_a_run_in_flight_shows_its_progress_on_the_forge_and_a_repeat_posts_nothing(home: Path) -> None:
    """Any machine reading the claim sees where the run is. PLANTED CONTROL: an unchanged phrase is not re-posted."""
    store, slurm = _Store(), _Slurm(home / 'r')
    _start(home, store)
    _tick(store, slurm)
    assert _progress(store) == ['building', 'queued 4/4']
    _tick(store, slurm)
    assert _progress(store) == ['building', 'queued 4/4'], 'the same progress is not posted twice'
    slurm.phrase = 'running 3/4 done 1/4'
    _tick(store, slurm)
    assert _progress(store)[-1] == 'running 3/4 done 1/4'
    latest = Claim.parse(store.posts[-1]['description'])
    assert latest is not None
    assert latest.same_owner(HERE), 'progress never changes who owns the claim'


def test_progress_text_reads_the_slurm_counts() -> None:
    assert forgeslurm.progress_text(Progress('s', '1', 4, pending=4)) == 'queued 4/4'
    assert forgeslurm.progress_text(Progress('s', '1', 4, pending=1, running=2)) == 'running 2/4 done 1/4'
    assert forgeslurm.progress_text(Progress('s', '1', 4, finished=True)) == 'gathering'


def test_a_long_progress_is_cut_to_what_every_forge_stores() -> None:
    long = dataclasses.replace(HERE, progress='x' * 300)
    assert len(long.description()) == DESCRIPTION_LIMIT
    assert Claim.parse(long.description()) is not None


def test_a_superseded_run_is_cancelled_released_and_dropped(home: Path) -> None:
    store, slurm = _Store(), _Slurm(home / 'r')
    _start(home, store)
    run = _tick(store, slurm)
    assert run is not None
    forgerun.supersede(run, 'd' * 40, client=_Client(store), cluster=slurm, say=lambda _line: None)
    assert slurm.cancelled == ['4242']
    assert store.posts[-1]['description'] == f'superseded by {"d" * 12}'
    assert store.posts[-1]['status'] == 'error'
    assert forgerun.live('https://f/o/r.git') == ()


_FAKE_ZSTD = (
    'import shutil, sys\n'
    "with open(sys.argv[sys.argv.index('-o') + 1], 'wb') as f:\n"
    '    shutil.copyfileobj(sys.stdin.buffer, f)\n'
)


def _shipping(home: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, _Slurm]:
    """A real record and work tree, a ``folder`` large store, and the archive just over its 1 MB threshold."""
    zstd = home / 'zstd.py'
    zstd.write_text(_FAKE_ZSTD, encoding='utf-8')
    monkeypatch.setattr(forgeship, 'pack', functools.partial(artefacts.pack, zstd=(sys.executable, str(zstd))))
    monkeypatch.setattr(forgerun, 'read_record', records.read_record)
    monkeypatch.setattr(forgeship, 'forge_from_remote', lambda _root: SimpleNamespace(repo='r'))
    big, root = home / 'big', home / 'repo'
    root.mkdir()
    table = f'[tool.lab_commons.artefacts]\nbackend = "folder"\nremote = "{big.as_posix()}"\nthreshold_mb = 1\n'
    (root / 'pyproject.toml').write_text(table, encoding='utf-8')
    record = records.write_record({'sha': SHA, 'platform': 'linux', 'req': 'r1'}, home / 'gathered')
    tree = record.parent / 'tree'
    (tree / 'fields').mkdir(parents=True)
    (tree / 'fields' / 'b.h5').write_bytes(bytes(range(256)) * 8192)  # 2 MB: over the threshold
    (tree / 'undeclared.log').write_bytes(b'never uploaded')
    slurm = _Slurm(record)
    slurm.done = True
    return root, big, slurm


def test_declared_outputs_are_stored_and_named_in_the_record_before_it_is_posted(home: Path, monkeypatch) -> None:
    root, big, slurm = _shipping(home, monkeypatch)
    posted: list[Path] = []
    monkeypatch.setattr(forgecarry, 'post', lambda _root, path: posted.append(path) or 'posted')
    store = _Store()
    _start(home, store, outputs=('fields/*.h5',))
    assert _tick(store, slurm, root=root) is None
    (entry,) = records.read_record(posted[0])['artefacts']
    (ref,) = artefacts.FolderStore(big, 'r').list(None)
    assert entry == ref.manifest()
    assert ref.backend == 'folder'
    assert artefacts.parsed_run_id(ref.run_id)['account'] == 'alice', "the claim owner's cluster account writes it"
    fetched = artefacts.FolderStore(big, 'r').get(ref, home / 'fetched')
    with tarfile.open(fileobj=io.BytesIO(fetched.read_bytes())) as tar:
        assert tar.getnames() == ['fields/b.h5'], 'only the declared output; undeclared.log stays on the cluster'


def test_planted_control_nothing_declared_stores_nothing(home: Path, monkeypatch) -> None:
    root, big, slurm = _shipping(home, monkeypatch)
    posted: list[Path] = []
    monkeypatch.setattr(forgecarry, 'post', lambda _root, path: posted.append(path) or 'posted')
    store = _Store()
    _start(home, store)
    assert _tick(store, slurm, root=root) is None
    assert 'artefacts' not in records.read_record(posted[0])
    assert not big.exists()


def test_a_missing_declared_output_fails_the_run_loudly(home: Path, monkeypatch) -> None:
    root, _big, slurm = _shipping(home, monkeypatch)
    posted: list[Path] = []
    monkeypatch.setattr(forgecarry, 'post', lambda _root, path: posted.append(path) or 'posted')
    store, alarms = _Store(), []
    _start(home, store, outputs=('fields/*.h5', 'fields/*.vtu'))
    assert _tick(store, slurm, root=root, alarms=alarms) is None
    assert posted == [], 'a run missing a declared output never posts a part'
    assert store.posts[-1]['status'] == 'error'
    assert 'fields/*.vtu' in store.posts[-1]['description']
    assert [a.kind for a in alarms] == [forgerun.RUN]
    assert forgerun.live('https://f/o/r.git') == ()
