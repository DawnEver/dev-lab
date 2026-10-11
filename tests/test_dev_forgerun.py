"""THE RESUMABLE CLUSTER TICK: each serve call advances on-disk state; Slurm is the truth; only the owner renews.

The forge is a store of status posts answering the two calls a claim makes (post, list), with its own
clock; Slurm is a fake that counts submissions. A "crash" is a new tick reading the state back from disk.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lab_commons.config import CONFIG_ENV
from lab_commons.dev import forgerun
from lab_commons.dev.forgealarm import LEASE, Alarm
from lab_commons.dev.forgetick import Claim, Work
from lab_commons.dev.forgework import GITEA, ForgeCallFailed
from lab_commons.dev.netverb import Attempt, Diagnosis, Report
from lab_commons.dev.platformparts import ClusterPart, PartRefusal
from lab_commons.dev.producer import ProducerExit, release_reason

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

    def forge_now(self) -> datetime:
        return self.store.now

    def call(self, method: str, _path: str, body: dict[str, str] | None = None) -> Any:  # noqa: ANN401 -- JSON
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


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    monkeypatch.setattr(forgerun, 'pyproject_at', lambda _root, _sha: '')
    monkeypatch.setattr(forgerun, 'route', lambda *_a: ())
    monkeypatch.setattr(forgerun, 'read_record', lambda _path: {'sha': SHA})
    return tmp_path


def _start(tmp_path: Path, store: _Store, owner: Claim = HERE) -> forgerun.Run:
    store.add('pending', owner.description())
    part = ClusterPart('https://f/o/r.git', 'tests', tmp_path / 'parts')
    return forgerun.start(Work('integrate/main', SHA, 'linux', 'mine', owner, cluster=part), owner)


def _tick(store: _Store, slurm: _Slurm, *, me: Claim = HERE, alarms: list[Alarm] | None = None) -> forgerun.Run | None:
    """One serve call: read the run back from disk (a fresh process) and advance it."""
    (run,) = forgerun.live('https://f/o/r.git')
    return forgerun.advance(
        Path(),
        run,
        client=_Client(store),  # type: ignore[arg-type]
        me=me,
        lease=HOURS6,
        cluster=slurm,
        say=lambda _line: None,
        alarm=(alarms if alarms is not None else []).append,
    )


def test_each_tick_advances_the_run_and_a_restart_resumes_without_resubmitting(home: Path, monkeypatch) -> None:
    store, slurm = _Store(), _Slurm(home / 'run.json.gz')
    posted: list[Path] = []
    monkeypatch.setattr(forgerun, 'post', lambda _root, path: posted.append(path) or 'posted')
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
    assert len(store.posts) == 1, 'a fresh claim is not re-posted every five minutes'
    store.now = NOW + timedelta(hours=2, minutes=1)
    _tick(store, slurm)
    assert len(store.posts) == 2
    assert Claim.parse(store.posts[-1]['description']) == dataclasses.replace(HERE, until=store.now + HOURS6)


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

    monkeypatch.setattr(forgerun, 'post', refuse)
    _start(home, store)
    assert _tick(store, slurm) is None
    assert (store.posts[-1]['status'], store.posts[-1]['description']) == (
        'error',
        release_reason(ProducerExit.INCONCLUSIVE),
    )


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
