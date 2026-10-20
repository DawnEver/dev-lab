"""THE RESUMABLE CLUSTER TICK: each serve call advances on-disk state; Slurm is the truth; only the owner renews.

The forge is a store of status posts answering the two calls a claim makes (post, list), with its own
clock; Slurm is a fake that counts submissions. A "crash" is a new tick reading the state back from disk.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import os
import tarfile
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from lab_commons.compute import learned
from lab_commons.config import CONFIG_ENV
from lab_commons.dev import artefacts, forgecarry, forgerun, forgerunstate, forgeship, forgeslurm
from lab_commons.dev.forgealarm import LEASE, RUN, Alarm
from lab_commons.dev.forgeclaim import DESCRIPTION_LIMIT, OPEN, Claim, Work, assess
from lab_commons.dev.forgestatus import CommitStatus
from lab_commons.dev.forgework import GITEA, ForgeCallFailed
from lab_commons.dev.netverb import Attempt, Diagnosis, Report
from lab_commons.dev.platformparts import ClusterPart, PartRefusal, part_context
from lab_commons.dev.producer import RETRYABLE, ProducerExit, release_reason
from lab_commons.hpc import records
from lab_commons.hpc import run as hpc_run
from lab_commons.hpc.account import ClusterAccount
from lab_commons.hpc.cluster import Unreachable
from lab_commons.hpc.config import Config
from lab_commons.hpc.grants import SESSION_ENV, Grant, Machine, Session
from lab_commons.hpc.progress import Progress
from lab_commons.hpc.run import NoRoom
from lab_commons.hpc.slurm import FORGE_SESSION, Node, Quota, Snapshot, parse_usage
from lab_commons.hpc.tree import NotSubmitted

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

    def call(self, method: str, _path: str, body: dict[str, str] | None = None, durable: object = None) -> object:
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
        self.began = True

    def started(self, _run: forgerunstate.Run) -> bool:
        return self.began

    def submitted(self, _run: forgerunstate.Run) -> list[str]:
        return list(self.recorded)

    def orphans(self, _run: forgerunstate.Run) -> list[str]:
        return list(self.queue)

    def submit(self, _run: forgerunstate.Run) -> list[str]:
        self.submits += 1
        self.recorded = ['4242']
        return ['4242']

    def gather(self, _run: forgerunstate.Run) -> Path | None:
        return self.record if self.done else None

    def progress(self, _run: forgerunstate.Run) -> str:
        return self.phrase

    def cancel(self, run: forgerunstate.Run) -> list[str]:
        self.cancelled += run.job_ids
        return list(run.job_ids)

    def tree(self, _run: forgerunstate.Run) -> Path:
        return self.record.parent / 'tree'


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    monkeypatch.setattr(forgerun, 'pyproject_at', lambda _root, _sha: '')
    monkeypatch.setattr(forgerun, 'route', lambda *_a: ())
    monkeypatch.setattr(forgerun, 'read_record', lambda _path: {'sha': SHA})
    monkeypatch.setattr(forgerun, 'tip_of', lambda _root, _ref: SHA)  # the run's sha is its ref's tip
    monkeypatch.setattr(forgerun, 'coalesced', lambda _root, _ref: True)
    return tmp_path


def _start(tmp_path: Path, store: _Store, owner: Claim = HERE, outputs: tuple[str, ...] = ()) -> forgerunstate.Run:
    store.add('pending', owner.description())
    part = ClusterPart('https://f/o/r.git', 'tests', tmp_path / 'parts', outputs)
    return forgerun.start(Work('integrate/main', SHA, 'linux', 'mine', owner, cluster=part), owner)


def _tick(
    store: _Store, slurm: _Slurm, *, me: Claim = HERE, alarms: list[Alarm] | None = None, root: Path | None = None
) -> forgerunstate.Run | None:
    """One serve call: read the run back from disk (a fresh process) and advance it."""
    (run,) = forgerunstate.live('https://f/o/r.git')
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
    assert (after.phase, after.job_ids, slurm.submits) == (forgerunstate.SUBMITTED, ('4242',), 1)
    assert _tick(store, slurm) is not None, 'still running: the tick returns, nothing waits'
    assert slurm.submits == 1, 'a restart (state re-read from disk) resumes; it never resubmits'
    slurm.done = True
    assert _tick(store, slurm) is None, 'gathered, published, released in one tick'
    assert posted == [home / 'run.json.gz']
    assert forgerunstate.live('https://f/o/r.git') == (), 'released: the state file is gone'


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
    (run,) = forgerunstate.live('https://f/o/r.git')
    after = forgerun.advance(
        Path(), run, client=_Client(store), me=HERE, lease=HOURS6, cluster=slurm, say=said.append, alarm=[].append
    )
    assert after is not None
    assert after.job_ids == ('7667160', '7667161', '7667163'), 'every round, so a cancel reaches them all'
    assert forgerunstate.live('https://f/o/r.git')[0].job_ids == after.job_ids, 'and the file carries them'
    assert any('job 7667163' in line and 'round 3' in line for line in said), said


def test_a_crash_after_sbatch_adopts_the_jobs_slurm_recorded(home: Path) -> None:
    """PLANTED CONTROL: phase still ``claimed`` on disk, but hpc recorded the run -- Slurm, not the file, decides."""
    store, slurm = _Store(), _Slurm(home / 'r')
    _start(home, store)
    slurm.recorded = ['777']
    after = _tick(store, slurm)
    assert after is not None
    assert (after.phase, after.job_ids, slurm.submits) == (forgerunstate.SUBMITTED, ('777',), 0)


def test_orphaned_jobs_raise_an_alarm_and_are_never_resubmitted(home: Path) -> None:
    store, slurm, alarms = _Store(), _Slurm(home / 'r'), []
    _start(home, store)
    slurm.queue = ['555']
    after = _tick(store, slurm, alarms=alarms)
    assert after is not None
    assert (after.phase, slurm.submits) == (forgerunstate.CLAIMED_PHASE, 0)
    assert [a.kind for a in alarms] == [LEASE]
    assert 'scancel' in alarms[0].body


class _CrashAtSbatch(_Slurm):
    """``sbatch`` queued the jobs, then the login node died before ``hpc`` wrote the run state."""

    def submit(self, _run: forgerunstate.Run) -> list[str]:
        self.queue = ['555']
        msg = 'the login node went down mid-submit'
        raise ConnectionResetError(msg)


def test_the_submit_is_journaled_before_sbatch_so_a_crash_mid_submit_is_resumed_not_orphaned(home: Path) -> None:
    """D19: the run file says ``submitting`` BEFORE sbatch; jobs found under it are ours, cancelled and resubmitted.

    PLANTED CONTROL: :func:`test_orphaned_jobs_raise_an_alarm_and_are_never_resubmitted` -- the same jobs under a
    run never journaled as submitting still alarm and wait for a human.
    """
    store, crashing, alarms = _Store(), _CrashAtSbatch(home / 'r'), []
    _start(home, store)
    with pytest.raises(ConnectionResetError):
        _tick(store, crashing)
    (journaled,) = forgerunstate.live('https://f/o/r.git')
    assert journaled.phase == forgerunstate.SUBMITTING, 'the intent was on disk before sbatch was called'
    slurm = _Slurm(home / 'r')
    slurm.queue = list(crashing.queue)
    after = _tick(store, slurm, alarms=alarms)
    assert after is not None
    assert (after.phase, after.job_ids, slurm.submits) == (forgerunstate.SUBMITTED, ('4242',), 1)
    assert slurm.cancelled == ['555'], 'the interrupted submit is cancelled, never left running twice'
    assert alarms == [], 'no human is needed: the journal says the jobs were ours'


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
    assert forgerunstate.live('https://f/o/r.git') == ()
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
    assert after.phase == forgerunstate.CLAIMED_PHASE
    assert [a.kind for a in alarms] == [LEASE]
    assert slurm.submits == 0


def test_an_inconclusive_record_is_released_never_posted(home: Path, monkeypatch) -> None:
    store, slurm = _Store(), _Slurm(home / 'r')
    slurm.done = True

    def refuse(_root: Path, _path: Path) -> str:
        msg = 'INCONCLUSIVE: 3 lost'
        raise PartRefusal(msg)

    routed: list[object] = []
    monkeypatch.setattr(forgecarry, 'post', refuse)
    monkeypatch.setattr(forgerun, 'route', lambda _client, record, _areas: routed.append(record) or ())
    _start(home, store)
    assert _tick(store, slurm) is None
    assert (store.posts[-1]['status'], store.posts[-1]['description']) == (
        'error',
        release_reason(ProducerExit.INCONCLUSIVE),
    )
    assert routed == [{'sha': SHA}], 'its reported reds are real reds: an inconclusive record is still routed'


def test_a_failed_build_is_released_inconclusive_naming_its_log(home: Path) -> None:
    """Live 2026-10-11 (a consumer's part): a native build lacking cmake submitted nothing and was released FAIL.

    PLANTED CONTROL: the same tick with a build that succeeds submits and keeps the run.
    """
    log = 'log=/ci/native/k.log'

    class _Unbuilt(_Slurm):
        def submit(self, _run: forgerunstate.Run) -> list[str]:
            msg = f'the build for {SHA[:12]} failed on h, nothing was submitted; {log}\ncmake not found'
            raise NotSubmitted(msg)

    store = _Store()
    _start(home, store)
    assert _tick(store, _Unbuilt(home / 'r')) is None, 'released and dropped'
    assert (store.posts[-1]['status'], store.posts[-1]['description']) == (
        'error',
        f'{release_reason(ProducerExit.INCONCLUSIVE)} {log}',
    )
    assert forgerunstate.live('https://f/o/r.git') == ()
    _start(home, store)
    assert _tick(store, _Slurm(home / 'r')).phase == forgerunstate.SUBMITTED


def test_a_host_with_no_room_releases_the_part_open_never_inconclusive(home: Path) -> None:
    """A host with no room releases its part RETRYABLE: no room is a fact about the HOST, not the sha.

    Live 2026-10-16 (a consumer's base part): the release read ``released: inconclusive``, the part was
    never claimed again, and the sha got no verdict.

    PLANTED CONTROL: :func:`test_a_failed_build_is_released_inconclusive_naming_its_log` -- a run that
    built nothing for its own reasons is still released inconclusive.
    """

    class _Full(_Slurm):
        def submit(self, _run: forgerunstate.Run) -> list[str]:
            msg = 'h has no headroom now for one task of 1 CPU and 352.2 GB'
            raise NoRoom(msg)

    store = _Store()
    _start(home, store)
    assert _tick(store, _Full(home / 'r')) is None, 'released and dropped'
    post = store.posts[-1]
    assert post['status'] == 'error'
    assert post['description'].startswith(RETRYABLE), post['description']
    assert 'inconclusive' not in post['description']
    assert forgerunstate.live('https://f/o/r.git') == ()
    released = CommitStatus(context=part_context('tests'), state='error', description=post['description'], url='')
    assert assess([released], part_context('tests'), me=HERE, now=NOW)[0] == OPEN, 'claimable by any host again'


SCHEMA_1 = Path(__file__).parent / '_hpc_fixtures' / 'forge-run-schema1-2026-10-17.json'


def _plant_schema_1() -> dict[str, Any]:
    """A live schema-1 run as Ada held it (2026-10-17, account sanitised), planted in this home's forge-runs/."""
    raw = json.loads(SCHEMA_1.read_text(encoding='utf-8'))
    forgerunstate.directory().mkdir(parents=True, exist_ok=True)
    repo = hashlib.sha256(raw['repo_url'].encode('utf-8')).hexdigest()[:12]
    name = f'{repo}-{raw["sha"]}-{raw["platform"]}-{raw["scope"]}.json'
    (forgerunstate.directory() / name).write_text(json.dumps(raw, indent=2), encoding='utf-8')
    return raw


@pytest.mark.usefixtures('home')
def test_a_live_schema_1_run_is_adopted_losslessly_and_written_back_at_this_schema() -> None:
    """A tool redeployed under a live run adopts it: every field carried, the old job name kept as an alias."""
    raw = _plant_schema_1()
    (run,) = forgerunstate.live(raw['repo_url'])
    carried = {key: value for key, value in dataclasses.asdict(run).items() if key in raw and key != 'schema'}
    as_read = {k: tuple(v) if isinstance(v, list) else v for k, v in raw.items() if k != 'schema'}
    assert carried == as_read
    assert run.schema == forgerunstate.SCHEMA
    assert run.job_aliases == (f'run-{raw["sha"][:12]}',), 'jobs sbatched under schema 1 bear the sha-only name'
    (path,) = forgerunstate.directory().glob('*.json')
    assert json.loads(path.read_text(encoding='utf-8'))['schema'] == forgerunstate.SCHEMA, 'written back'
    assert forgerunstate.live(raw['repo_url']) == (run,), 'deterministic: a second read of the upgraded file agrees'


def test_a_new_run_has_no_job_alias(home: Path) -> None:
    """PLANTED CONTROL for the alias: only an upgraded run's jobs may bear the old name."""
    assert _start(home, _Store()).job_aliases == ()


def test_a_live_run_of_an_unknown_schema_is_refused_with_the_remedy(home: Path) -> None:
    """PLANTED CONTROL: the same file at this schema is read."""
    store = _Store()
    run = _start(home, store)
    assert forgerunstate.live(run.repo_url) == (run,)
    (path,) = forgerunstate.directory().glob('*.json')
    path.write_text(json.dumps({**json.loads(path.read_text(encoding='utf-8')), 'schema': 0}), encoding='utf-8')
    with pytest.raises(forgerunstate.ForeignSchema, match=r'schema 0.*squeue --me'):
        forgerunstate.live(run.repo_url)


def test_one_refused_run_is_skipped_and_named_the_rest_are_read(home: Path) -> None:
    """A tick must not die on one bad file: with *refused* given, it hears the refusal and gets the other runs."""
    store = _Store()
    run = _start(home, store)
    bad = forgerunstate.save(dataclasses.replace(run, sha='d' * 40))
    bad.write_text(json.dumps({**json.loads(bad.read_text(encoding='utf-8')), 'schema': 99}), encoding='utf-8')
    heard: list[str] = []
    assert forgerunstate.live(run.repo_url, refused=heard.append) == (run,)
    assert len(heard) == 1
    assert 'schema 99' in heard[0]


def test_the_state_is_keyed_by_repo_sha_platform_and_scope(home: Path) -> None:
    store = _Store()
    run = _start(home, store)
    other = dataclasses.replace(run, repo_url='https://f/o/other.git')
    forgerunstate.save(other)
    assert forgerunstate.live(run.repo_url) == (run,)
    assert forgerunstate.live(other.repo_url) == (other,)
    assert len(list(forgerunstate.directory().glob('*.json'))) == 2


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


def _shipping(home: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, _Slurm]:
    """A real record and work tree, a ``folder`` large store, and the archive just over its 1 MB threshold."""
    monkeypatch.setattr(forgerun, 'read_record', records.read_record)
    monkeypatch.setattr(forgeship, 'forge_from_remote', lambda _root: SimpleNamespace(repo='r'))
    big, root = home / 'big', home / 'repo'
    root.mkdir()
    table = f'[tool.lab_commons.artefacts]\nbackend = "folder"\nremote = "{big.as_posix()}"\nthreshold_mb = 1\n'
    (root / 'pyproject.toml').write_text(table, encoding='utf-8')
    record = records.write_record({'sha': SHA, 'platform': 'linux', 'req': 'r1', 'cells': {}}, home / 'gathered')
    tree = record.parent / 'tree'
    (tree / 'fields').mkdir(parents=True)
    (tree / 'fields' / 'b.h5').write_bytes(os.urandom(2 << 20))  # 2 MB incompressible
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
    assert forgerunstate.live('https://f/o/r.git') == ()


def test_a_started_run_produces_the_part_it_claimed(home: Path) -> None:
    """A cluster claims any need-set it has (base, linux, ...); its run posts THAT part, never a fixed one."""
    part = ClusterPart('https://f/o/r.git', 'tests', home / 'parts')
    run = forgerun.start(Work('integrate/main', SHA, 'linux+matlab', 'mine', HERE, cluster=part), HERE)
    assert run.platform == 'linux+matlab'
    assert forgerun.start(Work('integrate/main', SHA, 'base', 'mine', HERE, cluster=part), HERE).platform == 'base'


def test_an_orphan_array_is_named_by_its_own_job_id_never_its_pending_range(tmp_path: Path) -> None:
    """``squeue -o %i`` spells a pending array ``7683032_[12-68%1]``; scancel refuses it and the tick died.

    PLANTED CONTROL: the runner answers only the ``%F`` query; a ``%i`` query would get the range back.
    """
    asked: list[str] = []

    def runner(command: str, _stdin: object) -> str:
        asked.append(command)
        return '7683032 7683032 7683040' if command.endswith('-o %F') else '7683032_[12-68%1]'

    machine: Any = SimpleNamespace(grants=[object()])
    cluster = forgeslurm.SlurmCluster(tmp_path, machine, cast('Any', None), lambda _grant: runner)
    run: Any = SimpleNamespace(sha='a' * 40, platform='base', job_aliases=())
    assert cluster.orphans(run) == ['7683032', '7683040']
    assert asked == [f'squeue -h --me -n run-{"a" * 12}-base -o %F']


def test_an_upgraded_runs_jobs_are_found_under_their_old_name_too(tmp_path: Path) -> None:
    """Jobs a schema-1 tool sbatched are named ``run-<sha12>``: squeue asks for both names."""
    asked: list[str] = []

    def runner(command: str, _stdin: object) -> str:
        asked.append(command)
        return '7716448'

    machine: Any = SimpleNamespace(grants=[object()])
    cluster = forgeslurm.SlurmCluster(tmp_path, machine, cast('Any', None), lambda _grant: runner)
    run: Any = SimpleNamespace(sha='a' * 40, platform='base', job_aliases=(f'run-{"a" * 12}',))
    assert cluster.orphans(run) == ['7716448']
    assert asked == [f'squeue -h --me -n run-{"a" * 12}-base,run-{"a" * 12} -o %F']


def test_a_run_held_by_an_account_limit_is_cancelled_returned_and_its_ask_learned(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Measured 2026-10-16: 52 tasks of 352 GB pended an hour on ``AssocGrpMemLimit``, 0 running, on one host.

    The gather cancels the array, learns the 352 GB ask so this host stops admitting the part at its old
    size, and raises :class:`NoRoom` -- the retryable release path -- so a host with headroom takes it.
    PLANTED CONTROL: the same job pending for priority is kept and gathered on.
    """
    asked: list[str] = []

    def runner(command: str, _stdin: object) -> str:
        asked.append(command)
        return ''

    held = Progress('a' * 40, '7', 52, pending=52, reasons=('AssocGrpMemLimit',), pending_minutes=59.0)
    monkeypatch.setattr(forgeslurm, 'settle', lambda *_a, **_k: forgeslurm.PENDING)
    monkeypatch.setattr(forgeslurm, 'where', lambda *_a, **_k: held)
    state = {'rounds': [{'job_ids': ['7'], 'mem_mb': 360658}]}
    monkeypatch.setattr(forgeslurm, 'load_state', lambda *_a: (state, runner))
    monkeypatch.setattr(hpc_run, 'load_state', lambda *_a: (state, runner))  # the one cancel path reads it there
    machine: Any = SimpleNamespace(grants=[SimpleNamespace(account=('h', 'u'))])
    cluster = forgeslurm.SlurmCluster(home, machine, Config(), lambda _grant: runner)
    run: Any = SimpleNamespace(
        job_aliases=(), sha='a' * 40, output=str(home), repo_url='https://f/o/r.git', platform='base', job_ids=()
    )
    with pytest.raises(NoRoom, match='AssocGrpMemLimit'):
        cluster.gather(run)
    assert any(command.startswith('scancel 7') for command in asked), asked
    assert learned.cluster_demand('https://f/o/r.git')(frozenset())['mem_gb'] == pytest.approx(
        360658 / 1024, rel=1e-12, abs=0.0
    )
    monkeypatch.setattr(forgeslurm, 'where', lambda *_a, **_k: dataclasses.replace(held, reasons=('Priority',)))
    assert cluster.gather(run) is None


class _Unrecorded(_Slurm):
    """Its jobs ended without writing a record: every gather says so."""

    def gather(self, run: forgerunstate.Run) -> Path | None:
        msg = f'the run of {run.sha[:12]} ended without a record in /out'
        raise forgerunstate.Unrecorded(msg)


def _submitted_run(home: Path, store: _Store, slurm: _Slurm) -> None:
    _start(home, store)
    assert _tick(store, slurm).phase == forgerunstate.SUBMITTED


def test_a_run_that_ended_without_a_record_settles_once_and_never_re_alarms(home: Path) -> None:
    """Ada 2026-10-17: femm of 59ad34a6657d alarmed "ended without a record" every tick, forever.

    The run settles: released with the reason on record, its file dropped, ONE alarm. PLANTED CONTROL: a
    run still running is kept and raises nothing.
    """
    store, alarms = _Store(), []
    _submitted_run(home, store, _Slurm(home / 'r'))
    running = _Slurm(home / 'r')
    running.recorded = ['4242']
    assert _tick(store, running, alarms=alarms) is not None
    assert alarms == []
    ended = _Unrecorded(home / 'r')
    ended.recorded = ['4242']
    assert _tick(store, ended, alarms=alarms) is None
    assert forgerunstate.live('https://f/o/r.git') == (), 'settled: the next tick has nothing to re-alarm'
    assert [a.kind for a in alarms] == [RUN]
    post = store.posts[-1]
    assert post['status'] == 'error'
    assert post['description'].startswith(release_reason(ProducerExit.INCONCLUSIVE)), post['description']


def test_a_run_whose_part_was_never_submitted_is_released_claimable_while_its_sha_is_the_tip(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pre-fix femm run read base's state as its own: phase ``submitted``, no state and no job of its part.

    Still the ref's tip, it is released RETRYABLE -- any host claims it afresh. PLANTED CONTROL: the same
    run once the ref moved on is settled as superseded, which no host claims again.
    """
    for tip, open_again in ((SHA, True), ('d' * 40, False)):
        monkeypatch.setattr(forgerun, 'tip_of', lambda _root, _ref, tip=tip: tip)
        store, alarms, slurm = _Store(), [], _Slurm(home / 'r')
        _submitted_run(home, store, slurm)
        slurm.recorded = []  # the part's state.json never existed: the ids were another part's
        assert _tick(store, slurm, alarms=alarms) is None
        assert forgerunstate.live('https://f/o/r.git') == ()
        assert [a.kind for a in alarms] == [RUN]
        post = store.posts[-1]
        assert post['status'] == 'error'
        released = CommitStatus(context=part_context('tests'), state='error', description=post['description'], url='')
        state = assess([released], part_context('tests'), me=HERE, now=NOW)[0]
        assert (state == OPEN) is open_again, post['description']
        assert ('superseded' in post['description']) is not open_again


@pytest.mark.parametrize(
    'case',
    [
        ('d' * 40, False, True, True),  # a newer sha queued, nothing of this run started: its slot goes to the tip
        ('d' * 40, True, True, False),  # PLANTED CONTROL: a run already executing finishes; its verdict counts
        (SHA, False, True, False),  # PLANTED CONTROL: still the tip, nothing supersedes it
        ('d' * 40, False, False, False),  # PLANTED CONTROL: a lane is tested at every pushed sha
    ],
)
def test_a_run_not_started_when_its_ref_moves_on_is_cancelled_for_the_tip(
    home: Path, monkeypatch: pytest.MonkeyPatch, case: tuple[str, bool, bool, bool]
) -> None:
    """SUPERSEDE (user ruling 2026-10-19): a coalesced ref's run of an older sha that has NOT STARTED is cancelled.

    Measured 2026-10-19 (Ada): integrate/main's newest tip waited hours behind an older sha's array that
    was still pending. Released as superseded (DONE: the tip no longer waits behind it), one alarm saying so.
    """
    tip, began, coalesced, superseded = case
    store, alarms, slurm = _Store(), [], _Slurm(home / 'r')
    _submitted_run(home, store, slurm)
    monkeypatch.setattr(forgerun, 'tip_of', lambda _root, _ref: tip)
    monkeypatch.setattr(forgerun, 'coalesced', lambda _root, _ref: coalesced)
    slurm.began = began
    after = _tick(store, slurm, alarms=alarms)
    if not superseded:
        assert after is not None
        assert (slurm.cancelled, alarms) == ([], [])
        return
    assert after is None
    assert slurm.cancelled == ['4242']
    assert forgerunstate.live('https://f/o/r.git') == ()
    post = store.posts[-1]
    assert post['status'] == 'error'
    assert 'superseded' in post['description']
    assert tip[:12] in post['description'], 'it names the tip that takes its slot'
    released = CommitStatus(context=part_context('tests'), state='error', description=post['description'], url='')
    assert assess([released], part_context('tests'), me=HERE, now=NOW)[0] != OPEN
    [alarm] = alarms
    assert alarm.kind == RUN
    assert 'superseded before it started' in alarm.subject


def test_a_submitted_run_with_jobs_of_its_name_still_queued_is_kept(home: Path) -> None:
    """PLANTED CONTROL: no state yet but squeue holds jobs of the run's name -- not "never submitted"."""
    store, slurm = _Store(), _Slurm(home / 'r')
    _submitted_run(home, store, slurm)
    slurm.recorded, slurm.queue = [], ['4242']
    assert _tick(store, slurm) is not None


def test_an_unreachable_cluster_is_never_read_as_nothing_submitted(tmp_path: Path) -> None:
    """``load_state`` raises :class:`Unreachable` (a RuntimeError) when no login host answered; that is not ``[]``."""

    def down(_command: str, _stdin: object) -> str:
        msg = 'no host answered'
        raise Unreachable(msg)

    machine: Any = SimpleNamespace(grants=[SimpleNamespace(account=('h', 'u'))])
    cluster = forgeslurm.SlurmCluster(tmp_path, machine, cast('Any', None), lambda _grant: down)
    run: Any = SimpleNamespace(sha='a' * 40, platform='base')
    with pytest.raises(Unreachable):
        cluster.submitted(run)
    empty = forgeslurm.SlurmCluster(tmp_path, machine, cast('Any', None), lambda _grant: lambda *_a: '')
    assert empty.submitted(run) == [], 'PLANTED CONTROL: a host that answered with no state is nothing submitted'


def _built(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> forgeslurm.SlurmCluster:
    grant = Grant('alice', ('login1',), 'acct')
    monkeypatch.setattr(forgeslurm, 'load_grants', lambda: Machine(session=_session_from_env(), grants=(grant,)))
    monkeypatch.setattr(forgeslurm, 'with_allocation', lambda machine, _read: machine)
    monkeypatch.setattr(forgeslurm, 'submitter', lambda: lambda _grant: None)
    return forgeslurm.slurm_cluster(tmp_path, ClusterAccount('ada', 'alice'))


def _session_from_env() -> Session | None:
    name = os.environ.get(SESSION_ENV, '')
    return Session(name) if name else None


def test_the_forge_serve_tags_its_own_submissions_without_a_session_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ada 2026-10-17: cron sets no ``$LC_HPC_SESSION``, so every forge array was untagged and alarmed on.

    The forge is a known stream and names itself. PLANTED CONTROL: an explicit ``$LC_HPC_SESSION`` still wins.
    """
    monkeypatch.delenv(SESSION_ENV, raising=False)
    assert _built(monkeypatch, tmp_path).machine.comment == f'lc:session={FORGE_SESSION}'
    monkeypatch.setenv(SESSION_ENV, 'campaign')
    assert _built(monkeypatch, tmp_path).machine.comment == 'lc:session=campaign'


def test_untagged_counts_only_jobs_that_are_not_the_forges_own(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Arrays the forge sbatched before it tagged itself bear its job names (``run-<sha12>[-<part>]``): not alarmed.

    PLANTED CONTROL: another session's untagged job (``wdg-design``) is still counted, and a tagged one never is.
    """
    squeue = (
        '1|1G|1|(null)|run-89f11a39d6fe\n'
        '1|1G|1|(null)|run-89f11a39d6fe\n'
        '1|1G|1|(null)|run-4ad64054bba3-base\n'
        '1|1G|1|(null)|wdg-design\n'
        '1|1G|1|lc:session=campaign|campaign-7\n'
        '1|1G|1|(null)|run-notasha12xyz\n'
    )
    snapshot = dataclasses.replace(_snapshot_untagged(), usage=parse_usage(squeue))
    monkeypatch.setattr(forgeslurm, 'probe', lambda *_a: snapshot)
    machine: Any = SimpleNamespace(grants=[SimpleNamespace(user='alice', slurm_account='a')])
    cluster = forgeslurm.SlurmCluster(tmp_path, machine, cast('Any', None), lambda _g: lambda *_a: '', lambda: None)
    assert cluster.standing().facts['untagged'] == 2


def _snapshot_untagged() -> Snapshot:
    quota = Quota(account='a', cpus=8, mem_mb=None, gpus=None, default_qos='q', qos_max_submit={}, queued={})
    return Snapshot(nodes=(Node('n1', ('defq',), 8, 8192, 0, schedulable=True),), partitions={}, quota=quota)
