"""THE HARNESS ENTRY: tick, produce or advance, publish -- a contract break fails loudly, a silent failure alarms."""

from __future__ import annotations

import dataclasses
import errno
import functools
import json
import os
import subprocess
import threading
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from _box_fake import ended, quiet, record
from _forge_fake import git_out, run_git
from lab_commons.box import GB, Capacity, Holding, ProcessEnd, Refused
from lab_commons.compute import learned
from lab_commons.compute.model import Candidate, Ranked, Resources, Supply
from lab_commons.compute.presence import Evidence, Presence
from lab_commons.config import CONFIG_ENV
from lab_commons.hpc.account import ClusterAccount
from lab_commons.hpc.shell import FULL

from dev_lab.dev import (
    forgehosts,
    forgeproduce,
    forgerounds,
    forgerun,
    forgerunstate,
    forgeserve,
    forgeservesteps,
    forgeship,
    prlanded,
)
from dev_lab.dev.forgealarm import AUTH, IDLE, INTEGRATION, PRUNED, RUN, STARVED, UNTAGGED, Alarm
from dev_lab.dev.forgeclaim import OPEN, Claim, Work
from dev_lab.dev.forgeintegration import Child, Feedback, Ticked
from dev_lab.dev.forgeproduce import Produced
from dev_lab.dev.forgeroute import Routed
from dev_lab.dev.forgetick import TickReport
from dev_lab.dev.forgetidy import Hygiene
from dev_lab.dev.forgework import ForgeCallFailed
from dev_lab.dev.netverb import Attempt, Diagnosis, Report
from dev_lab.dev.platformparts import ClusterPart
from dev_lab.dev.producer import PRODUCING_VAR, RETRYABLE, ProducerExit, release_reason
from dev_lab.dev.shatree import Tree, TreeFailed

SHA = 'a' * 40
BOX = Capacity(cpu=3.0, mem_bytes=24 * GB, seats={})
UNREACHABLE = 'forge unreachable'
NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
FORGE_NOW = NOW + timedelta(minutes=7)  # the forge's clock, deliberately not the host's
ME = Claim('G', 'alice', NOW + timedelta(hours=6))
SEAT = ClusterAccount('ada', 'alice')


class _Proc:
    """A fake producer: prints *lines*, outlives *beats* heartbeats, exits *code*; the box records *box*.

    *box* defaults to the child's own exit; a :class:`Refused`, a killed :class:`ProcessEnd` or ``None`` (a
    crashed box, no record) is what the box decided instead.
    """

    _OWN: object = object()

    def __init__(
        self,
        code: int,
        lines: tuple[str, ...] = (),
        beats: int = 0,
        pid: int | None = None,
        box: ProcessEnd | Refused | object | None = _OWN,
    ) -> None:
        self.code, self.beats, self.pid = code, beats, pid
        self.box = ended(code) if box is _Proc._OWN else box
        self.stdout = iter(f'{line}\n' for line in lines)

    def wait(self, timeout: float | None = None) -> int:
        if self.beats:
            self.beats -= 1
            cmd = 'fake'
            raise subprocess.TimeoutExpired(cmd, timeout or 0)
        return self.code

    def kill(self) -> None:
        self.beats = 0


class _Forge:
    """Records every status post; a part's producer may post its own verdict."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, str, str]] = []

    def post(self, _client, _sha, *, context, state, description) -> None:
        self.posts.append((context, state, description))

    def history(self, _client, _sha) -> tuple[SimpleNamespace, ...]:
        return tuple(SimpleNamespace(context=c, state=s, description=d) for c, s, d in self.posts)


class _Trees:
    """The producer's per-sha trees: which were opened and closed; *refuse* makes opening one fail."""

    def __init__(self, tmp_path: Path, refuse: str = '') -> None:
        self.base, self.refuse = tmp_path / 'trees', refuse
        self.opened: list[str] = []
        self.closed: list[str] = []
        self.logs: list[str] = []

    def open(self, _root: Path, sha: str, _context: str) -> Tree:
        self.opened.append(sha)
        if self.refuse:
            raise TreeFailed(self.refuse)
        return Tree(self.base / sha[:12], self.base / sha[:12] / 'python')

    def close(self, _root: Path, sha: str, _context: str, *, log: str = '') -> str:
        self.closed.append(sha)
        self.logs.append(log)
        return f'tree {sha[:12]}: removed'


@pytest.fixture(autouse=True)
def _a_checkout(tmp_path: Path) -> None:
    """Serve runs in a checkout: its run journal and outbox live in the main checkout git names."""
    run_git(tmp_path, 'init', '-q')


def _client(_root: Path) -> SimpleNamespace:
    return SimpleNamespace(answered=format_datetime(FORGE_NOW, usegmt=True), whoami=lambda: 'alice')


class _Issues:
    """The forge's open issues, shared by every host a test serves: ``reconcile``'s contract, by title."""

    def __init__(self) -> None:
        self.open: dict[str, str] = {}

    def reconcile(self, _client: object, prefix: str, wanted: dict[str, str]) -> tuple[Routed, ...]:
        done = []
        for title, body in sorted(wanted.items()):
            action = 'created' if title not in self.open else 'updated' if self.open[title] != body else 'unchanged'
            self.open[title] = body
            done.append(Routed(title, action, 1))
        for title in [t for t in self.open if t.startswith(prefix) and t not in wanted]:
            del self.open[title]
            done.append(Routed(title, 'closed', 1))
        return tuple(done)


def _serve(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    ticked: TickReport,
    procs: dict[str, _Proc] | None = None,
    forge: _Forge | None = None,
    *,
    seat: ClusterAccount | None = None,
    cluster=lambda: None,
    spawned: list[dict] | None = None,
    cards: list | None = None,
    host: str | None = None,
    tidy=lambda _root, _client, **_kw: (),
    trees: _Trees | None = None,
    seen: dict[str, object] | None = None,
    holding: tuple[Holding, ...] = (),
    later: tuple[TickReport, ...] = (),
    ticks: list[dict] | None = None,
    table: dict | None = None,
    retain=lambda _root, **_kw: None,
    observe=None,
    issues: _Issues | None = None,
    prune=lambda _root, _client, **_kw: (),
    close_landed=lambda *_a, **_k: None,
    records_prune=lambda _root, _client, **_kw: (),
    starving: tuple = (),
    issue_tidy=lambda _client, _hygiene: [],
    children: tuple = (),
    present=lambda _root: {},
    clock=lambda: NOW,
    reviewed: list | None = None,
) -> tuple[forgeserve.ServeReport, list[str], list]:
    """Serve once: the first round's tick answers *ticked*, each later one the next of *later*, then nothing.

    *seen* is what the FIRST tick was given; *ticks* collects what every tick was given.
    """
    said: list[str] = []
    alarms: list = []
    forge = forge or _Forge()
    seen = seen if seen is not None else {}
    cards = cards if cards is not None else []

    answers = iter((ticked, *later))
    given: list[dict] = ticks if ticks is not None else []

    def tick(*_a: object, **kwargs: object) -> TickReport:
        if not given:
            seen.update(kwargs)
        given.append(kwargs)
        return next(answers, TickReport((), (), ()))

    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    monkeypatch.setattr(forgerounds, 'tick', tick)
    monkeypatch.setattr(forgeserve, 'origin_url', lambda _root: 'https://f/o/r.git')
    monkeypatch.setattr(forgehosts, 'origin_url', lambda _root: 'https://f/o/r.git')
    monkeypatch.setattr(forgeproduce, 'origin_url', lambda _root: 'https://f/o/r.git')
    monkeypatch.setattr(forgeserve, 'flush', lambda _root, **_k: ['status: tests/windows=failure'])
    monkeypatch.setattr(forgeproduce, 'status_post', forge.post)
    monkeypatch.setattr(forgeproduce, 'status_history', forge.history)
    monkeypatch.setattr(forgehosts, 'publish', lambda _client, card: cards.append(card) or 'updated')
    monkeypatch.setattr(forgeship, 'tidy', tidy)
    trees = trees or _Trees(tmp_path)
    monkeypatch.setattr(forgeproduce, 'open_tree', trees.open)
    monkeypatch.setattr(forgeproduce, 'close_tree', trees.close)

    def spawn(argv: list[str], **kwargs: object) -> _Proc:
        (spawned if spawned is not None else []).append({'argv': argv, **kwargs})
        proc = (procs or {})[argv[argv.index('--') + 2]]  # boxed: after '--', the tree's own interpreter
        record(argv, proc.box)
        return proc

    monkeypatch.setattr(forgeservesteps, 'observe', observe or (lambda *_a, **_k: []))
    monkeypatch.setattr(forgeservesteps, 'integration_tick', lambda *_a, **_k: Ticked((), tuple(children)))
    monkeypatch.setattr(
        forgeservesteps,
        'review_step',
        lambda _root, _built, **kw: (reviewed if reviewed is not None else []).append(kw),
    )
    monkeypatch.setattr(forgeservesteps, 'reconcile', (issues or _Issues()).reconcile)
    monkeypatch.setattr(forgeserve, 'serve_close_landed', close_landed)
    monkeypatch.setattr(forgeserve, 'serve_prune', prune)
    monkeypatch.setattr(forgeserve, 'serve_records_prune', records_prune)
    monkeypatch.setattr(forgeservesteps, 'issue_tidy', issue_tidy)
    monkeypatch.setattr(forgeservesteps, 'forge_queue', lambda *_a, **_k: (list(starving), []))
    monkeypatch.setattr(forgeserve, 'read_cards', lambda _client: ())
    report = forgeserve.serve(
        tmp_path,
        client=_client,
        machine='G',
        seat=seat,
        cluster=cluster,
        spawn=spawn,
        clock=clock,
        say=said.append,
        alarm=alarms.append,
        renew_s=0.01,
        table=table or {},
        fetch=lambda _root: None,
        host=host,
        supplied=functools.partial(forgerounds.supply_now, capacity=lambda: BOX, read=quiet(BOX)),
        holding=lambda: holding,
        retain=retain,
        present=present,
    )
    said.append(f'running={seen.get("running")}')
    return report, said, alarms


class _Slurm:
    """The Slurm side as serve reads it before the tick: a standing, and jobs it may cancel."""

    def __init__(self) -> None:
        self.cancelled: list[str] = []
        self.withdrawn: list[str] = []
        self.started: list[str] = []

    def standing(self) -> forgerunstate.Standing:
        return forgerunstate.Standing(
            Supply('slurm:alice', Resources(cpu=64, mem_gb=128, submits=10)), {}, {'partitions': {'defq': 2880}}
        )

    def cancel(self, run: forgerunstate.Run) -> list[str]:
        self.cancelled += run.job_ids
        return list(run.job_ids)

    def withdraw(self, run: forgerunstate.Run) -> list[str]:
        self.withdrawn += run.job_ids
        return list(self.started)


def _claimed(*work: Work) -> TickReport:
    return TickReport(work, work, ('tick: one line',))


def test_the_producers_streamed_output_reaches_the_tree_closer(monkeypatch, tmp_path: Path) -> None:
    """The run's log reaches :func:`close_tree`, which keeps it in the serving checkout before removing the tree."""
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    trees = _Trees(tmp_path)
    _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(1, ('collected 9', '1 failed'))}, trees=trees)
    assert trees.closed == [SHA]
    assert trees.logs == ['collected 9\n1 failed\n']


def test_a_claimed_local_part_is_produced_inline_and_published(monkeypatch, tmp_path: Path) -> None:
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    report, said, _alarms = _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(1, ('collected 9',))})
    assert [(p.platform, p.returncode) for p in report.produced] == [('windows', 1)], 'a red part is not a failure'
    assert report.published == ('status: tests/windows=failure',)
    assert report.broken == ()
    assert 'tick: one line' in said
    assert f'[windows@{SHA[:8]}] collected 9' in said


def test_the_producer_is_spawned_holding_its_claim_and_nothing_else_is(monkeypatch, tmp_path: Path) -> None:
    """VERDICTS-FROM-THE-FORGE: serve is the one door to a full suite -- its producer carries the part it claimed."""
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    spawned: list[dict] = []
    monkeypatch.delenv(PRODUCING_VAR, raising=False)
    _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(0)}, spawned=spawned)
    assert [kwargs['env'][PRODUCING_VAR] for kwargs in spawned] == [f'tests/windows@{SHA}']
    assert PRODUCING_VAR not in os.environ, "the claim is the child's, never leaked into serve itself"


def test_the_producer_runs_in_the_box_at_the_demand_it_was_admitted_at(monkeypatch, tmp_path: Path) -> None:
    """Admission and enforcement are one number, held against the ONE capacity reading the producer sized it by.

    Unmeasured (no demand, nothing learned), a box part declares its selection -- here the per-task floor a
    worker, at as many workers as this 3-core box allows -- never the whole box
    (:func:`~lab_commons.compute.learned.selection_gb`).
    """
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    spawned: list[dict] = []
    monkeypatch.setattr(forgeproduce.Capacity, 'read', staticmethod(lambda: BOX))
    _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(0)}, spawned=spawned)
    (argv,) = [one['argv'] for one in spawned]
    assert argv[1:4] == ['-m', 'lab_commons.box', 'run']
    assert argv[argv.index('--cpu') + 1] == '3'
    assert argv[argv.index('--mem-gb') + 1] == '3'
    assert json.loads(argv[argv.index('--capacity') + 1]) == dataclasses.asdict(BOX), 'the child holds this size'
    assert argv[argv.index('--fingerprint') + 1] == SHA
    assert argv[argv.index('--') + 2 :] == ['verify']
    admitted = dataclasses.replace(local, demand={'cpu': 2.0, 'mem_gb': 5.5})
    spawned.clear()
    _serve(monkeypatch, tmp_path, _claimed(admitted), {'verify': _Proc(0)}, spawned=spawned)
    (argv,) = [one['argv'] for one in spawned]
    assert (argv[argv.index('--cpu') + 1], argv[argv.index('--mem-gb') + 1]) == ('2', '5.5'), 'what it was admitted at'


def test_a_producer_refusing_its_argv_is_a_broken_contract_not_a_skip(monkeypatch, tmp_path: Path) -> None:
    """PLANTED: a renamed flag makes argparse exit 2; that must surface as a failure with the argv shown."""
    stale = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify', '--install', 'x'))
    report, _said, _alarms = _serve(monkeypatch, tmp_path, _claimed(stale), {'verify': _Proc(ProducerExit.USAGE)})
    assert len(report.broken) == 1
    assert 'verify --install x' in report.broken[0]


def test_the_cli_exits_two_on_a_broken_contract(monkeypatch, tmp_path: Path, capsys) -> None:
    broken = forgeserve.ServeReport((), (), (), (), ('windows aaaa: the producer refused its argv: verify --x',))
    monkeypatch.setattr(forgeserve, 'serve', lambda *_a, **_k: broken)
    assert forgeserve.main([], cwd=tmp_path, seat_of=lambda: None) == ProducerExit.USAGE
    assert 'CONTRACT BROKEN' in capsys.readouterr().err
    with pytest.raises(SystemExit):
        forgeserve.main(['--nonsense'], cwd=tmp_path)


def test_any_host_prompts_the_integrator_and_n_hosts_page_once(monkeypatch, tmp_path: Path) -> None:
    """No owner: every host derives the queue; the forge keeps one issue per row, so only its writer pages.

    PLANTED CONTROLS: a second host deriving the same row pages nothing; a changed row pages again; a row
    no longer derived closes its issue.
    """
    prompt = Alarm(INTEGRATION, 'o/r', 'feat/a is READY', 'merge it', about='merge feat/a@abc')
    rows = [prompt]

    def observe(_root: Path, _repo: str, *, statuses: object) -> list[Alarm]:
        assert callable(statuses)
        return list(rows)

    forge = _Issues()
    first = _serve(monkeypatch, tmp_path, TickReport((), (), ()), observe=observe, issues=forge)[2]
    assert prompt in first
    assert forge.open == {'integration: feat/a is READY': 'merge it'}
    assert _serve(monkeypatch, tmp_path, TickReport((), (), ()), observe=observe, issues=forge)[2] == []
    rows[:] = [dataclasses.replace(prompt, body='merge it now')]
    assert _serve(monkeypatch, tmp_path, TickReport((), (), ()), observe=observe, issues=forge)[2] == rows
    rows[:] = []
    _serve(monkeypatch, tmp_path, TickReport((), (), ()), observe=observe, issues=forge)
    assert forge.open == {}


def test_any_host_runs_the_advisory_review_inside_its_integration_step(monkeypatch, tmp_path: Path) -> None:
    """The review host follows the integrator: no capability, the integration step's own policy.

    PLANTED CONTROL: a tick whose integration queue cannot be derived reviews nothing.
    """
    reviewed: list = []
    _serve(monkeypatch, tmp_path, TickReport((), (), ()), reviewed=reviewed)
    ((given,),) = [tuple(one['policy'] for one in reviewed)]
    assert given.integration == 'integrate/main'

    def unreachable(*_a: object, **_k: object) -> list[Alarm]:
        msg = 'the forge is down'
        raise OSError(msg)

    reviewed.clear()
    _serve(monkeypatch, tmp_path, TickReport((), (), ()), observe=unreachable, reviewed=reviewed)
    assert reviewed == []


def test_every_tick_reports_behind_and_conflicts_and_alarms_past_the_bound(monkeypatch, tmp_path: Path) -> None:
    """D12: the behind/conflict report runs each tick; a child past ``behind_max`` or conflicting is an issue.

    PLANTED CONTROL: a child at the bound and clean raises nothing; the same set with a conflicting and a
    far-behind child raises exactly those two, beside the integrator's prompts.
    """
    calm = (Child('lane/ok', 'a' * 40, None), Feedback('t', 'pending', 's', behind=20))
    forge = _Issues()
    _serve(monkeypatch, tmp_path, TickReport((), (), ()), issues=forge, children=(calm,))
    assert forge.open == {}
    far = (Child('lane/far', 'b' * 40, None), Feedback('t', 'pending', 's', behind=21))
    torn = (Child('lane/torn', 'c' * 40, None), Feedback('t', 'failure', 's', conflicts=('x.py',)))
    raised = _serve(monkeypatch, tmp_path, TickReport((), (), ()), issues=forge, children=(calm, far, torn))[2]
    assert sorted(forge.open) == [
        'integration: lane/far needs a sync with integrate/main',
        'integration: lane/torn needs a sync with integrate/main',
    ]
    assert {one.kind for one in raised} == {INTEGRATION}
    assert 'forge sync' in forge.open['integration: lane/far needs a sync with integrate/main']


def test_a_live_local_producer_renews_its_claim_on_the_forges_clock(monkeypatch, tmp_path: Path) -> None:
    forge = _Forge()
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(0, beats=2)}, forge)
    renewed = [d for c, s, d in forge.posts if c == 'tests/windows' and s == 'pending']
    assert len(renewed) == 2
    assert Claim.parse(renewed[0]) == dataclasses.replace(ME, until=FORGE_NOW + forgeserve.DEFAULT_LEASE)


def test_a_producing_host_keeps_publishing_its_card_while_the_producer_runs(monkeypatch, tmp_path: Path) -> None:
    """A part runs for hours inline; the card must tick at the tick period, holding the part, so STALE means down."""
    forge, cards = _Forge(), []
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(0, beats=3)}, forge, cards=cards)
    during = cards[:-1]  # the last card is the one published after the tick
    assert len(during) == 3, 'one card per heartbeat while producing'
    assert all(card.holds[0].startswith(f'{SHA[:12]} windows producing') for card in during)
    assert len([d for c, s, d in forge.posts if s == 'pending']) == 3, 'every beat inside the renew interval renews'


def test_a_beat_shorter_than_the_renewal_renews_only_when_the_renewal_is_due(monkeypatch, tmp_path: Path) -> None:
    """The card beats at the tick period; the claim is still renewed on its own, longer, cadence."""
    forge, beats = _Forge(), []
    item = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    monkeypatch.setattr(forgeproduce, 'status_post', forge.post)
    monkeypatch.setattr(forgeproduce, 'status_history', forge.history)
    monkeypatch.setattr(forgeproduce, 'open_tree', _Trees(tmp_path).open)
    monkeypatch.setattr(forgeproduce, 'close_tree', _Trees(tmp_path).close)
    monkeypatch.setattr(forgeproduce, 'origin_url', lambda _root: 'https://f/o/r.git')
    waits: list[float | None] = []
    proc = _Proc(0, beats=6)
    inner = proc.wait
    monkeypatch.setattr(proc, 'wait', lambda timeout=None: waits.append(timeout) or inner(timeout))
    forgeproduce.produce(
        tmp_path, item, client=_client, spawn=lambda *_a, **_k: proc, clock=lambda: NOW, say=lambda _l: None,
        lease=timedelta(hours=6), renew_s=30.0, beat_s=10.0, beat=beats.append, fetch=lambda _root: None,
    )  # fmt: skip
    assert waits[0] == 10.0, 'the loop wakes at the beat, not the lease third'
    assert len(beats) == 6
    assert len([d for c, s, d in forge.posts if s == 'pending']) == 2, 'renewed on beats 3 and 6 only'


def test_a_crashed_producer_releases_its_claim(monkeypatch, tmp_path: Path) -> None:
    """PLANTED: the producer dies without posting; its pending claim must not be left to age out."""
    forge = _Forge()
    forge.post(None, SHA, context='tests/windows', state='pending', description=ME.description())
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(-9)}, forge)
    assert forge.posts[-1] == ('tests/windows', 'error', 'released: producer crashed (exit -9)')


def test_a_local_part_is_judged_in_its_own_tree_at_the_claimed_sha(monkeypatch, tmp_path: Path) -> None:
    """PLANTED (live 2026-10-12, 4e394b6): the serving checkout sat at e9bc0d4 and verify judged THAT.

    The producer runs the declared argv with the interpreter of a tree AT the claimed sha, in that tree,
    and removes the tree afterwards -- the serving checkout (``tmp_path``) is never the cwd.
    """
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify', '--full'))
    trees, spawned = _Trees(tmp_path), []
    report, said, _alarms = _serve(
        monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(0)}, spawned=spawned, trees=trees
    )
    tree = tmp_path / 'trees' / SHA[:12]
    assert [(k['argv'][k['argv'].index('--') + 1 :], k['cwd']) for k in spawned] == [
        ([str(tree / 'python'), 'verify', '--full'], tree)
    ]
    assert (trees.opened, trees.closed) == ([SHA], [SHA])
    assert report.produced[0].argv == (str(tree / 'python'), 'verify', '--full')
    assert f'[windows@{SHA[:8]}] tree {SHA[:12]}: removed' in said


def test_a_tree_that_cannot_be_built_spawns_nothing_and_names_the_step(monkeypatch, tmp_path: Path) -> None:
    forge = _Forge()
    forge.post(None, SHA, context='tests/windows', state='pending', description=ME.description())
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    trees, spawned = _Trees(tmp_path, refuse='dep --bootstrap exited 1: no lock'), []
    report, _said, _alarms = _serve(
        monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(0)}, forge, spawned=spawned, trees=trees
    )
    assert spawned == []
    assert report.produced[0].returncode == ProducerExit.INCONCLUSIVE
    assert forge.posts[-1] == (
        'tests/windows',
        'error',
        f'released: no tree at {SHA[:12]} -- dep --bootstrap exited 1: no lock',
    )
    assert trees.closed == [SHA], 'a half-built tree is removed too'


def test_a_tree_the_box_did_not_admit_is_released_retryable_never_an_error_verdict(monkeypatch, tmp_path: Path) -> None:
    """PLANTED (live 2026-10-17, 1d698d494d31): a full box queue refused the bootstrap; serve posted it as error."""
    forge = _Forge()
    forge.post(None, SHA, context='tests/windows', state='pending', description=ME.description())
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    refusal = (
        'dep --bootstrap exited 1: REFUSED: dep:x: not admitted -- no room within the queue limit -- '
        "queued behind 'verify:p8', which came first (strict FIFO)"
    )
    trees, spawned = _Trees(tmp_path, refuse=refusal), []
    report, _said, _alarms = _serve(
        monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(0)}, forge, spawned=spawned, trees=trees
    )
    assert spawned == []
    assert report.produced[0].returncode == ProducerExit.UNREACHABLE
    context, _state, description = forge.posts[-1]
    assert context == 'tests/windows'
    assert description.startswith(RETRYABLE), 'the next tick claims it again (forgeclaim.assess: OPEN)'
    assert "queued behind 'verify:p8'" in description
    assert trees.closed == [SHA]


def test_a_producer_that_posted_its_part_is_left_alone(monkeypatch, tmp_path: Path) -> None:
    forge = _Forge()
    forge.post(None, SHA, context='tests/windows', state='failure', description='FAIL')
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(1)}, forge)
    assert forge.posts == [('tests/windows', 'failure', 'FAIL')]


def test_inconclusive_and_unreachable_producers_are_released_never_red(monkeypatch, tmp_path: Path) -> None:
    """PLANTED (live 2026-10-11): a runner over its wall said INCONCLUSIVE; serve said "refused its argv"."""
    for proc, reason in (
        (_Proc(ProducerExit.INCONCLUSIVE), release_reason(ProducerExit.INCONCLUSIVE)),
        (_Proc(ProducerExit.UNREACHABLE), RETRYABLE),
        (_Proc(1, box=Refused('cpu: wants 4 of 3')), RETRYABLE),  # the box had no room in time: open, never red
        (_Proc(1, box=ended(-9, 'memory')), 'released: the box killed it past its declared memory'),
        (_Proc(1, box=None), 'released: the box crashed'),
    ):
        forge = _Forge()
        forge.post(None, SHA, context='tests/windows', state='pending', description=ME.description())
        local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
        report, _said, _alarms = _serve(monkeypatch, tmp_path, _claimed(local), {'verify': proc}, forge)
        assert report.broken == ()
        assert forge.posts[-1][1] == 'error'
        assert forge.posts[-1][2].startswith(reason)


@pytest.mark.parametrize('kept', [('', ()), ('output/26/10/20/parts/x', ())])
def test_an_inconclusive_part_without_its_record_names_the_missing_record(
    monkeypatch, tmp_path: Path, kept: tuple
) -> None:
    """W1.4 (live on Ada): a part ending ``inconclusive (exit 3) -- no part`` gave its author nothing to act on.

    PLANTED CONTROL: the same exit with its record written is released with the bare reason.
    """
    monkeypatch.setattr(forgeproduce, 'record_manifest', lambda _r, _s, _c: kept)
    forge = _Forge()
    forge.post(None, SHA, context='tests/windows', state='pending', description=ME.description())
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(ProducerExit.INCONCLUSIVE)}, forge)
    assert forge.posts[-1][1] == 'error'
    assert forge.posts[-1][2].startswith(release_reason(ProducerExit.INCONCLUSIVE))
    assert ('the run wrote no record' in forge.posts[-1][2]) is not kept[0]


@pytest.mark.parametrize('code', [69, 137])
def test_a_producer_exiting_a_former_box_sentinel_on_its_own_is_judged_by_its_code(
    monkeypatch, tmp_path: Path, code: int
) -> None:
    """PLANTED (SR-20261015-002): a producer exiting 69 was re-claimed every tick, read as "the box refused it".

    The box recorded the producer's OWN exit, so its code is judged as any other: a crash, never retryable.
    """
    forge = _Forge()
    forge.post(None, SHA, context='tests/windows', state='pending', description=ME.description())
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(code)}, forge)
    assert forge.posts[-1][1:] == ('error', release_reason(code))
    assert not forge.posts[-1][2].startswith(RETRYABLE)


def test_a_claimed_cluster_part_starts_a_run_and_is_advanced_never_spawned(monkeypatch, tmp_path: Path) -> None:
    cluster_claim = dataclasses.replace(ME, hpc='ada/alice')
    part = ClusterPart('https://f/o/r.git', 'tests', tmp_path / 'parts')
    work = Work('integrate/main', SHA, 'base', 'mine', cluster_claim, cluster=part)
    advanced: list[tuple[str, str]] = []

    def advance(_root: Path, run: forgerunstate.Run, **kwargs: object) -> forgerunstate.Run:
        me = kwargs['me']
        assert isinstance(me, Claim)
        advanced.append((run.phase, me.hpc))
        return run

    monkeypatch.setattr(forgerun, 'advance', advance)
    report, said, _alarms = _serve(monkeypatch, tmp_path, _claimed(work), seat=SEAT, cluster=_Slurm)
    assert report.produced == (), 'a cluster part is never a blocking process'
    assert advanced == [(forgerunstate.CLAIMED_PHASE, 'ada/alice')]
    assert report.in_flight == (SHA,)
    assert 'running=[]' in said
    report, said, _alarms = _serve(monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=_Slurm)
    (line,) = [one for one in said if one.startswith('running=')][-1:]
    assert line == "running=[Demand({'cpu': 1.0, 'mem_gb': 1.0, 'files': 50000.0})]", (
        'the next tick reads the run back from disk as running demand'
    )
    assert len(advanced) == 2


def test_a_run_with_no_cluster_to_advance_on_alarms_and_waits(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    part = ClusterPart('https://f/o/r.git', 'tests', tmp_path / 'parts')
    forgerun.start(Work('integrate/main', SHA, 'base', 'mine', ME, cluster=part), ME)

    def no_grant() -> None:
        msg = 'no [[hpc.grant]] has user = "alice"'
        raise ValueError(msg)

    report, _said, alarms = _serve(monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=no_grant)
    assert [a.kind for a in alarms] == [RUN]
    assert report.in_flight == (SHA,)
    assert len(forgerunstate.live('https://f/o/r.git')) == 1, 'the run is kept for the next tick'


def test_the_alarms_a_tick_raises_ride_on_its_host_card(monkeypatch, tmp_path: Path) -> None:
    """A stuck run is read from the forge, not from a cron log. PLANTED CONTROL: a calm tick's card is clean."""
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    cards: list = []
    _serve(monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=_Slurm, cards=cards, host='base')
    assert cards[-1].alarms == ()
    part = ClusterPart('https://f/o/r.git', 'tests', tmp_path / 'parts')
    forgerun.start(Work('integrate/main', SHA, 'base', 'mine', ME, cluster=part), ME)

    def no_grant() -> None:
        msg = 'no [[hpc.grant]] has user = "alice"'
        raise ValueError(msg)

    _serve(monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=no_grant, cards=cards, host='base')
    (raised,) = cards[-1].alarms
    assert raised['kind'] == RUN
    assert raised['subject'] == f'the cluster run of {SHA[:12]} cannot advance'
    assert 'no [[hpc.grant]]' in raised['body']


def test_an_account_idle_with_work_pending_alarms(monkeypatch, tmp_path: Path) -> None:
    """PLANTED CONTROL: the same pending request, claimed, raises nothing."""
    pending = Work('integrate/main', SHA, 'windows', OPEN)
    why = 'tests/windows: not claimed -- its declared outputs could exceed threshold_mb'
    idle = TickReport((pending,), (), ('tick',), (why,), pending=(pending,))
    _report, _said, alarms = _serve(monkeypatch, tmp_path, idle)
    assert [a.kind for a in alarms] == [IDLE]
    assert 'not claimed' in alarms[0].body
    claimed = dataclasses.replace(pending, state='mine', holder=ME, argv=('verify',))
    _report, _said, alarms = _serve(monkeypatch, tmp_path, _claimed(claimed), {'verify': _Proc(0)})
    assert alarms == []


def test_an_idle_alarm_names_the_account_not_the_login_node(monkeypatch, tmp_path: Path) -> None:
    """Accounts share a cluster's login nodes, so only the seat tells two idle hosts apart."""
    pending = Work('integrate/main', SHA, 'base', OPEN)
    idle = TickReport((pending,), (), ('tick',), (), pending=(pending,))
    _report, _said, alarms = _serve(monkeypatch, tmp_path, idle, seat=SEAT, cluster=_Slurm, host='base')
    (raised,) = [a for a in alarms if a.kind == IDLE]
    assert raised.subject == f'{SEAT} is idle with work pending'


def test_work_this_host_cannot_serve_never_makes_it_idle(monkeypatch, tmp_path: Path) -> None:
    """Another platform's open part is in every host's work; only the tick's servable *pending* alarms idle."""
    elsewhere = Work('integrate/main', SHA, 'linux', OPEN)
    _report, _said, alarms = _serve(monkeypatch, tmp_path, TickReport((elsewhere,), (), ('tick',)))
    assert alarms == []


def test_a_refused_credential_alarms_and_still_fails(monkeypatch, tmp_path: Path) -> None:
    refused = Report(('GET', '/api/v1/user'), (Attempt(1, 401, 'unauthorized', Diagnosis.FORGE_REFUSED),), 3)

    def tick(*_a: object, **_k: object) -> TickReport:
        raise ForgeCallFailed(refused)

    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))  # never this box's own machine file
    monkeypatch.setattr(forgerounds, 'tick', tick)
    monkeypatch.setattr(forgeserve, 'origin_url', lambda _root: 'https://f/o/r.git')
    monkeypatch.setattr(forgeserve, 'read_cards', lambda _client: ())
    alarms: list = []
    with pytest.raises(ForgeCallFailed):
        forgeserve.serve(
            tmp_path, client=_client, machine='G', seat=None, cluster=lambda: None, alarm=alarms.append,
            table={}, supplied=functools.partial(forgerounds.supply_now, capacity=lambda: BOX, read=quiet(BOX)),
            holding=tuple, retain=lambda _root, **_kw: None,
        )  # fmt: skip
    assert [a.kind for a in alarms] == [AUTH]


def _waiting(kind: str, waited_h: float, blocked: str) -> Ranked:
    one = Candidate('o/r', 'feat/x', SHA, 'windows', kind, NOW - timedelta(hours=waited_h), FULL)
    return Ranked(one, 60.0, 4.0, 15.0, waited_h, blocked)


def test_any_host_raises_starved_for_a_part_no_host_admits_and_n_hosts_page_once(monkeypatch, tmp_path: Path) -> None:
    """Every host reads the queue ACROSS hosts; a part some host admits is no starvation, only a wait.

    PLANTED CONTROLS: a blocked wait under the bound and a wait one host only has to finish raise nothing,
    and a second host reading the same queue writes the same issue and pages nothing.
    """
    nobody = 'no host admits it -- G lacking cpu; ada/alice lacking mem_gb'
    queue = [_waiting('pr', 13, nobody), _waiting('pr', 11, nobody), _waiting('pr', 14, 'the tree is busy here')]

    forge = _Issues()
    _report, _said, alarms = _serve(
        monkeypatch, tmp_path, TickReport((), (), ('tick',)), issues=forge, starving=tuple(queue)
    )
    (alarm,) = alarms
    assert (alarm.kind, alarm.about) == (STARVED, f'feat/x@{SHA[:12]}:windows')
    assert 'waited 13.0 h, past its 12 h bound' in alarm.body
    assert nobody in alarm.body, 'the starved alarm names every host and what it lacks'
    assert len(forge.open) == 1
    again = _serve(
        monkeypatch, tmp_path, TickReport((), (), ('tick',)), issues=forge, host='other', starving=tuple(queue)
    )
    assert again[2] == []


def test_every_tick_publishes_the_host_card(monkeypatch, tmp_path: Path) -> None:
    """Who it is, what it serves, its supply and facts, and why each candidate waits."""
    cards: list = []
    ticked = TickReport((), (), ('tick',), (), (_waiting('pr', 1, 'not admitted: lacking cpu'),))
    _serve(monkeypatch, tmp_path, ticked, seat=SEAT, cluster=_Slurm, cards=cards, host='base')
    (card,) = cards
    assert (card.host, card.login, card.platform) == ('ada/alice', 'alice', 'base')
    assert card.supply == {'cpu': 64.0, 'mem_gb': 128.0, 'submits': 10.0}
    assert card.facts == {'partitions': {'defq': 2880}}
    assert card.ticked == FORGE_NOW.isoformat(), "the forge's clock, never the host's"
    assert card.waiting == {f'feat/x@{SHA[:12]}:windows': 'not admitted: lacking cpu'}


def test_the_card_carries_the_probed_tools_never_the_declarations(monkeypatch, tmp_path: Path) -> None:
    """D21: the tick re-probes its tools first, and its card shows each verdict with its evidence."""
    cards: list = []
    found = Presence('femm', present=False, evidence=(Evidence('find', 'not found', NOW.isoformat()),))
    _serve(monkeypatch, tmp_path, TickReport((), (), ()), cards=cards, present=lambda _root: {'femm': found})
    (card,) = cards
    assert card.tools == {'femm': found.row()}
    assert card.tools_present() == frozenset(), 'absent as probed, whatever a machine file declares'


def test_a_part_whose_infrastructure_did_not_answer_demotes_its_tools(monkeypatch) -> None:
    """D21 (4): exit 4 on a femm part demotes femm here; a red part (exit 1) is the code's, never the tool's."""
    demoted: list = []
    monkeypatch.setattr(forgeproduce, 'demote', lambda tools, why: demoted.append((tools, why)))
    monkeypatch.setattr(forgeproduce, 'needs_of', lambda _platform: frozenset({'femm', 'windows'}))
    red = Produced('r', 'a' * 40, 'femm', (), 1)
    forgeproduce.demote_unreachable([red])
    assert demoted == [], 'PLANTED CONTROL: a failed test is not a failed tool'
    forgeproduce.demote_unreachable([dataclasses.replace(red, returncode=ProducerExit.UNREACHABLE)])
    assert [tools for tools, _ in demoted] == [['femm']]


def test_a_box_admits_against_its_capacity_less_every_box_ledger_claim(monkeypatch, tmp_path: Path) -> None:
    """The box ledger is the ONE source: an interactive verify and a producer are claims on it alike.

    PLANTED CONTROL: no claim on the ledger, the whole capacity is admitted against.
    """
    seen: dict[str, object] = {}
    _serve(monkeypatch, tmp_path, TickReport((), (), ()), seen=seen)
    supply = seen['supply']
    assert isinstance(supply, Supply)
    assert (supply.scope, supply.resources['cpu'], supply.resources['mem_gb']) == ('G', 3.0, 24.0)
    verify = Holding('verify:r', 1, cpu=2, mem_bytes=4 * GB, seats={}, deadline=0.0)
    cards: list = []
    _serve(monkeypatch, tmp_path, TickReport((), (), ()), seen=seen, holding=(verify,), cards=cards)
    assert (seen['supply'].resources['cpu'], seen['supply'].resources['mem_gb']) == (1.0, 20.0)
    assert seen['running'] == [], 'a ledger claim is in the supply already, never counted twice'
    assert cards[-1].running == ('verify:r (pid 1)',)


class _Until(_Proc):
    """A producer that lives, beating, until *event* is set."""

    def __init__(self, event: threading.Event, code: int = 0, pid: int | None = None) -> None:
        super().__init__(code, pid=pid)
        self.event = event

    def wait(self, timeout: float | None = None) -> int:
        if self.event.wait(timeout=timeout):
            return self.code
        cmd = 'fake'
        raise subprocess.TimeoutExpired(cmd, timeout or 0)


class _Sets(_Proc):
    """A producer that beats *beats* times (a little apart), then sets *event* and exits."""

    def __init__(self, event: threading.Event, code: int = 0, beats: int = 0, pid: int | None = None) -> None:
        super().__init__(code, beats=beats, pid=pid)
        self.event = event

    def wait(self, timeout: float | None = None) -> int:
        if self.beats:
            self.event.wait(timeout=0.02)
        code = super().wait(timeout)
        self.event.set()
        return code


#: A tick period short enough that a second round comes while a producer runs.
QUICK = {'tick_minutes': 0.001}


def test_two_admitted_local_parts_are_produced_at_once(monkeypatch, tmp_path: Path) -> None:
    """Each part runs in its own thread with its own claim: the first producer waits until the second started.

    Sequential production would deadlock the first on that wait (bounded: it then fails the assertion).
    """
    other = 'b' * 40
    first = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('first',))
    second = Work('feat/a', other, 'windows', 'mine', ME, argv=('second',))
    started = threading.Event()

    class _Waits(_Proc):
        def wait(self, timeout: float | None = None) -> int:
            assert started.wait(timeout=10), 'the second producer never started while the first ran'
            return super().wait(timeout)

    class _Starts(_Proc):
        def wait(self, timeout: float | None = None) -> int:
            started.set()
            return super().wait(timeout)

    procs = {'first': _Waits(0), 'second': _Starts(1)}
    spawned: list[dict] = []
    trees = _Trees(tmp_path)
    report, _said, _alarms = _serve(monkeypatch, tmp_path, _claimed(first, second), procs, spawned=spawned, trees=trees)
    assert [(p.sha, p.returncode) for p in report.produced] == [(SHA, 0), (other, 1)], 'reported in claim order'
    assert sorted(trees.closed) == sorted([SHA, other]), 'each part in its own tree'


def _moved_on(tmp_path: Path) -> str:
    """*tmp_path* as a checkout whose origin integrate/main moved past :data:`SHA`; the new tip."""
    run_git(tmp_path, 'init', '-q')
    run_git(tmp_path, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'x')
    tip = git_out(tmp_path, 'rev-parse', 'HEAD')
    run_git(tmp_path, 'update-ref', 'refs/remotes/origin/integrate/main', tip)
    return tip


def test_a_cluster_run_whose_ref_moved_on_is_kept_and_advanced(monkeypatch, tmp_path: Path) -> None:
    """A PART UNDER TEST IS NOT SUPERSEDED (design item 9): a push to B never cancels A's cluster run."""
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    forge = _Forge()
    monkeypatch.setattr(forgerun, 'status_post', forge.post)
    monkeypatch.setattr(forgerun, 'advance', lambda _root, run, **_k: run)
    run = forgerunstate.Run('https://f/o/r.git', SHA, 'integrate/main', 'tests', str(tmp_path), ME.description(),
                       phase=forgerunstate.SUBMITTED, job_ids=('77',))  # fmt: skip
    forgerunstate.save(run)
    kept, _said, _alarms = _serve(monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=_Slurm)
    assert kept.in_flight == (SHA,)
    tip = _moved_on(tmp_path)
    slurm = _Slurm()
    report, said, _alarms = _serve(
        monkeypatch, tmp_path, TickReport((), (), ()), forge, seat=SEAT, cluster=lambda: slurm
    )
    assert report.in_flight == (SHA,), f'A runs on after the ref moved to {tip[:12]}'
    assert slurm.cancelled == []
    assert not [post for post in forge.posts if 'superseded' in post[2]]
    assert [one.sha for one in forgerunstate.live('https://f/o/r.git')] == [SHA]
    assert not any('superseded' in line for line in said)


def test_a_local_producer_whose_ref_moved_on_runs_to_its_end(monkeypatch, tmp_path: Path) -> None:
    """A PART UNDER TEST IS NOT SUPERSEDED (design item 9): every heartbeat after the push only renews."""
    _moved_on(tmp_path)
    forge = _Forge()
    item = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    proc = _Proc(0, beats=5)
    report, _said, _alarms = _serve(monkeypatch, tmp_path, _claimed(item), {'verify': proc}, forge)
    assert report.produced[0].returncode == 0
    assert proc.beats == 0
    renewed = [d for c, s, d in forge.posts if c == 'tests/windows' and s == 'pending']
    assert len(renewed) == 5, 'renewed at every heartbeat, never stopped'
    assert not [post for post in forge.posts if 'superseded' in post[2]]


def test_only_a_cluster_host_cleans_the_artefact_stores_and_a_failed_cleanup_alarms(
    monkeypatch, tmp_path: Path
) -> None:
    """PLANTED CONTROL: the same serve off a cluster (no seat) never cleans -- a workstation only reads."""
    cleaned: list[tuple[Path, str]] = []

    def tidy(root: Path, _client: object, *, account: str, say: object) -> tuple[str, ...]:
        del say
        cleaned.append((root, account))
        return ()

    _serve(monkeypatch, tmp_path, TickReport((), (), ()), seat=None, tidy=tidy)
    assert cleaned == []
    _serve(monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=_Slurm, tidy=tidy)
    assert cleaned == [(tmp_path, SEAT.account)], "it cleans its own account's runs only"

    def broken(_root: Path, _client: object, **_kw: object) -> tuple[str, ...]:
        msg = 'rclone lsjson exited 1'
        raise OSError(msg)

    _report, _said, alarms = _serve(
        monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=_Slurm, tidy=broken
    )
    assert [a.kind for a in alarms] == [RUN]


def test_every_tick_runs_the_branch_prune_on_any_host(monkeypatch, tmp_path: Path) -> None:
    """No owner: the prune is idempotent, so every host's tick runs it (a raced delete is a no-op)."""
    offered: list[Path] = []

    def prune(root: Path, _client: object, **kwargs: object) -> tuple[()]:
        assert 'host' not in kwargs
        offered.append(root)
        return ()

    _serve(monkeypatch, tmp_path, TickReport((), (), ()), prune=prune)
    assert offered == [tmp_path]


def test_every_tick_closes_landed_prs_before_the_prune_and_a_failure_only_alarms(monkeypatch, tmp_path: Path) -> None:
    """A landed PR is closed before its branch is pruned; a failed close alarms and the tick still prunes."""
    order: list[str] = []

    def failing(*_a: object, **_k: object) -> int:
        order.append('close')
        raise ConnectionError(errno.ECONNREFUSED, UNREACHABLE)

    monkeypatch.setattr(prlanded, 'close_landed', failing)
    forge_client = SimpleNamespace(forge=SimpleNamespace(repo='o/r'))

    def close(root: Path, _client: object, **kwargs: object) -> None:
        prlanded.serve_close_landed(root, forge_client, **kwargs)

    _report, _said, alarms = _serve(
        monkeypatch,
        tmp_path,
        TickReport((), (), ()),
        close_landed=close,
        prune=lambda _root, _c, **_k: order.append('prune') or (),
    )
    assert order == ['close', 'prune']
    (raised,) = alarms
    assert (raised.kind, raised.repo) == (PRUNED, 'o/r')
    assert UNREACHABLE in raised.body


def test_every_tick_offers_the_records_prune_its_rate_limit_decides(monkeypatch, tmp_path: Path) -> None:
    """A retention rule nobody runs is not a rule: the tick offers the records/unit-result prune."""
    offered: list[Path] = []
    _serve(monkeypatch, tmp_path, TickReport((), (), ()), records_prune=lambda root, _c, **_k: offered.append(root))
    assert offered == [tmp_path]


def test_every_tick_tidies_the_repos_issues_on_any_host(monkeypatch, tmp_path: Path) -> None:
    """Issues never rot: every served repo is tidied each tick, by its defaults when it declares nothing."""
    given: list[Hygiene] = []

    def issue_tidy(_client: object, hygiene: Hygiene) -> list[str]:
        given.append(hygiene)
        return ['#7: closed']

    _report, said, _alarms = _serve(monkeypatch, tmp_path, TickReport((), (), ()), issue_tidy=issue_tidy)
    assert given == [Hygiene()]
    assert '[serve] tidy: #7: closed' in said


def test_a_failed_tidy_is_said_and_the_tick_goes_on(monkeypatch, tmp_path: Path) -> None:
    def issue_tidy(_client: object, _hygiene: Hygiene) -> list[str]:
        msg = 'bad table'
        raise ValueError(msg)

    report, said, _alarms = _serve(monkeypatch, tmp_path, TickReport((), (), ()), issue_tidy=issue_tidy)
    assert '[serve] the issue hygiene did not run: bad table' in said
    assert report.published, 'the outbox is still flushed'


def test_only_a_declared_issue_kind_is_kept_as_an_issue() -> None:
    """``forge tidy`` exempts exactly ISSUE_KINDS as machine-kept, so raise_once may keep no other kind."""
    with pytest.raises(ValueError, match='ISSUE_KINDS'):
        forgeservesteps.raise_once(SimpleNamespace(), RUN, [], alarm=lambda _a: None)


def test_a_producer_stopped_on_purpose_releases_its_claim_as_stopped(monkeypatch, tmp_path: Path) -> None:
    """A stop door notes a serve's producer before it kills it; the serve names the release ``stopped``, not a crash."""
    forge = _Forge()
    forge.post(None, SHA, context='tests/windows', state='pending', description=ME.description())
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    proc = _Proc(1, pid=77)
    monkeypatch.setattr(forgeproduce, 'was_stopped', lambda pid: pid == 77)
    _serve(monkeypatch, tmp_path, _claimed(local), {'verify': proc}, forge)
    assert forge.posts[-1] == ('tests/windows', 'error', 'stopped')


def _produce_one(monkeypatch, tmp_path: Path, proc: _Proc, **kwargs: object) -> forgeproduce.Produced:
    """One local part through :func:`forgeproduce.produce`, every forge and tree seam faked."""
    forge = _Forge()
    item = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    monkeypatch.setattr(forgeproduce, 'status_post', forge.post)
    monkeypatch.setattr(forgeproduce, 'status_history', forge.history)
    monkeypatch.setattr(forgeproduce, 'open_tree', _Trees(tmp_path).open)
    monkeypatch.setattr(forgeproduce, 'close_tree', _Trees(tmp_path).close)
    monkeypatch.setattr(forgeproduce, 'was_stopped', lambda _pid: False)
    monkeypatch.setattr(forgeproduce, 'origin_url', lambda _root: 'https://f/o/r.git')
    kwargs.setdefault('spawn', lambda *_a, **_k: proc)
    return forgeproduce.produce(
        tmp_path, item, client=_client, say=lambda _l: None,
        lease=timedelta(hours=6), renew_s=30.0, fetch=lambda _root: None, **kwargs,
    )  # fmt: skip


def test_a_finished_box_run_learns_its_peak_wall_and_measured_cpu(monkeypatch, tmp_path: Path) -> None:
    """The box half of the one demand table: the tree's peak and its MEASURED cpu-seconds, never wall x cores."""
    learnt: list = []
    gb, cpu = iter([2.0, None, 3.5, 1.0]), iter([10.0, None, 30.0, 45.0])
    ticks = iter(NOW + timedelta(seconds=s) for s in range(0, 1000, 10))
    _produce_one(
        monkeypatch, tmp_path, _Proc(0, beats=4, pid=4242), clock=lambda: next(ticks),
        sample=lambda _pid: next(gb), meter=lambda _pid: lambda: next(cpu),
        learn=lambda *a, **k: learnt.append((a, k)),
    )  # fmt: skip
    ((root, done, run), how) = learnt[0]
    assert (root, done.platform, run.peak_mem_gb, run.cpu_s, how) == (tmp_path, 'windows', 3.5, 45.0, {'killed': False})
    assert run.wall_s > 0


def test_a_run_never_sampled_learns_nothing(monkeypatch, tmp_path: Path) -> None:
    """PLANTED CONTROL: no wake, no reading -- nothing is learned."""
    learnt: list = []
    _produce_one(
        monkeypatch, tmp_path, _Proc(0, beats=0, pid=4242), clock=lambda: NOW,
        sample=lambda _pid: 1.0, meter=lambda _pid: lambda: 5.0, learn=lambda *a, **_k: learnt.append(a),
    )  # fmt: skip
    assert learnt == []


#: Windows' STATUS_NO_MEMORY: what a Job Object's memory limit leaves as the killed tree's exit code.
_NO_MEMORY = 0xC0000017


def _killed_for_memory(monkeypatch, tmp_path: Path, **kwargs: object) -> None:
    """One part the box killed for memory before serve's first sample: the box's record is all that measured it."""
    proc = _Proc(_NO_MEMORY, beats=0, pid=4242, box=ended(_NO_MEMORY, 'memory'))
    _produce_one(
        monkeypatch, tmp_path, proc, clock=lambda: NOW, spawn=lambda argv, **_k: record(argv, proc.box) or proc,
        sample=lambda _pid: None, meter=lambda _pid: lambda: None, capacity=lambda: BOX, **kwargs,
    )  # fmt: skip


def test_a_part_the_box_killed_for_memory_learns_the_limit_it_died_at(monkeypatch, tmp_path: Path) -> None:
    """A memory kill is a floor at the DECLARED limit, read from the box's record, never nothing.

    THE INCIDENT: a part killed past its declared memory before serve's first sample learned NOTHING, so the
    next tick claimed it at the same figure and the box killed it again. ``record_run`` grows the floor.
    """
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    learnt: list = []
    _killed_for_memory(monkeypatch, tmp_path, learn=lambda *a, **k: learnt.append((a, k)))
    declared = forgeproduce.box_claim(Work('integrate/main', SHA, 'windows', 'mine', ME), BOX, root=tmp_path)
    ((_root, _item, run), how) = learnt[0]
    assert (run.peak_mem_gb, how) == (declared.mem_gb, {'killed': True})


def test_a_killed_part_is_reclaimed_at_a_grown_figure(monkeypatch, tmp_path: Path) -> None:
    """End to end on the real learn path: claimed, killed for memory, re-claimed at OOM_GROWTH x the limit."""
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    monkeypatch.setattr(forgeproduce, 'origin_url', lambda _root: 'https://f/o/r.git')
    item = Work('integrate/main', SHA, 'windows', 'mine', ME)
    first = forgeproduce.box_claim(item, BOX, root=tmp_path).mem_gb
    _killed_for_memory(monkeypatch, tmp_path)
    again = forgeproduce.box_claim(item, BOX, root=tmp_path).mem_gb
    assert again == min(first * learned.OOM_GROWTH * learned.BOX_HEADROOM, BOX.mem_bytes / GB) > first


def test_a_part_the_box_refused_learns_nothing(monkeypatch, tmp_path: Path) -> None:
    """A refusal ran nothing: serve's samples are the box CLI waiting in the queue, never the part's need.

    Measured on the real box: a refusal after a kill replaced the grown 6.03 GB floor with the waiting
    wrapper's 0.03 GB, and the next claim shrank back to the figure the box had killed.
    """
    learnt: list = []
    proc = _Proc(1, beats=2, pid=4242, box=Refused('no room'))
    _produce_one(
        monkeypatch, tmp_path, proc, clock=lambda: NOW, spawn=lambda argv, **_k: record(argv, proc.box) or proc,
        sample=lambda _pid: 0.03, meter=lambda _pid: lambda: 0.4, learn=lambda *a, **_k: learnt.append(a),
    )  # fmt: skip
    assert learnt == []


def test_a_box_record_with_no_peak_and_no_sample_learns_nothing(monkeypatch, tmp_path: Path) -> None:
    """PLANTED CONTROL: an exit the box measured nothing of, and serve never sampled, invents no peak."""
    learnt: list = []
    proc = _Proc(0, beats=0, pid=4242)
    _produce_one(
        monkeypatch, tmp_path, proc, clock=lambda: NOW, spawn=lambda argv, **_k: record(argv, proc.box) or proc,
        sample=lambda _pid: None, meter=lambda _pid: lambda: None, learn=lambda *a, **_k: learnt.append(a),
    )  # fmt: skip
    assert learnt == []


def test_a_run_with_no_cpu_reading_learns_nothing(monkeypatch, tmp_path: Path) -> None:
    """A tree whose cpu cannot be read records no demand: an unmeasured cpu is never invented."""
    learnt: list = []
    _produce_one(
        monkeypatch, tmp_path, _Proc(0, beats=2, pid=4242), clock=lambda: NOW,
        sample=lambda _pid: 1.0, meter=lambda _pid: lambda: None, learn=lambda *a, **_k: learnt.append(a),
    )  # fmt: skip
    assert learnt == []


def test_a_host_producing_one_part_claims_another_that_fits_while_it_runs(monkeypatch, tmp_path: Path) -> None:
    """Serve keeps ticking while a producer lives: the next round sees it RUNNING, and claims more.

    The first producer lives until the second ends, so the second can only have been claimed while it ran.
    """
    other = 'b' * 40
    first = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('first',))
    second = Work('feat/a', other, 'windows', 'mine', ME, argv=('second',))
    second_done = threading.Event()
    procs = {'first': _Until(second_done), 'second': _Sets(second_done, code=1, beats=3)}
    ticks: list[dict] = []
    cards: list = []
    report, _said, _alarms = _serve(
        monkeypatch, tmp_path, _claimed(first), procs, ticks=ticks, later=(_claimed(second),), table=QUICK, cards=cards,
    )  # fmt: skip
    assert [(p.sha, p.returncode) for p in report.produced] == [(SHA, 0), (other, 1)], 'in start order'
    assert ticks[1]['running'] == ticks[0]['running'], (
        'a live producer is a box ledger claim: in the supply, never twice'
    )
    assert any(len(card.holds) == 2 for card in cards), 'a card while both run names both'
    assert report.tick == ('tick: one line', 'tick: one line'), 'every round says what it claimed'


def test_a_producer_stopped_on_purpose_ends_the_claiming(monkeypatch, tmp_path: Path) -> None:
    """A stop (stoprun) means serve exits: no round after it, the live producer is waited for, nothing new starts.

    PLANTED CONTROL: the same two producers, neither stopped, and a later round runs.
    """
    other, third = 'b' * 40, 'c' * 40
    claims = (
        Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('stopped',)),
        Work('feat/a', other, 'windows', 'mine', ME, argv=('lives',)),
    )
    later = (_claimed(Work('feat/b', third, 'windows', 'mine', ME, argv=('never',))),)

    def run(stopped_pid: int) -> tuple[list[dict], list[dict]]:
        ended = threading.Event()
        procs = {
            'stopped': _Sets(ended, code=-9, pid=77),
            'lives': _Sets(threading.Event(), beats=10),
            'never': _Proc(0),
        }
        monkeypatch.setattr(forgeproduce, 'was_stopped', lambda pid: pid == stopped_pid)
        ticks: list[dict] = []
        spawned: list[dict] = []
        _serve(
            monkeypatch, tmp_path, _claimed(*claims), procs, ticks=ticks, later=later, table=QUICK, spawned=spawned,
        )  # fmt: skip
        return ticks, spawned

    ticks, spawned = run(77)
    assert len(ticks) == 1
    assert sorted(one['argv'][one['argv'].index('--') + 2] for one in spawned) == ['lives', 'stopped']
    ticks, _spawned = run(0)
    assert len(ticks) >= 2, 'PLANTED CONTROL: a crash is not a stop; the host claims on'


def test_a_round_that_raises_joins_every_producer_first(monkeypatch, tmp_path: Path) -> None:
    """No producer thread outlives serve: a later round failing waits for the live producer before it raises."""
    ended = threading.Event()
    first = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('first',))
    procs = {'first': _Sets(ended, beats=20)}
    failed = ForgeCallFailed(Report(('GET', '/x'), (Attempt(1, 128, 'boom', Diagnosis.TRANSIENT),), 3))
    calls: list[int] = []

    def tick(*_a: object, **_k: object) -> TickReport:
        calls.append(1)
        if len(calls) > 1:
            raise failed
        return _claimed(first)

    monkeypatch.setattr(forgerounds, '_tick', lambda *_a, **kw: tick(**kw))
    with pytest.raises(ForgeCallFailed):
        _serve(monkeypatch, tmp_path, _claimed(first), procs, table=QUICK)
    assert ended.is_set(), 'the producer ended before serve raised'
    assert not [t for t in threading.enumerate() if t.name.startswith('produce-')]


def _runs_on_disk(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, count: int) -> list[str]:
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    part = ClusterPart('https://f/o/r.git', 'tests', tmp_path / 'parts')
    shas = [str(n) * 40 for n in range(1, count + 1)]
    for sha in shas:
        forgerun.start(Work('integrate/main', sha, 'base', 'mine', ME, cluster=part), ME)
    return shas


def test_a_cluster_host_publishes_its_card_before_each_run_it_advances(monkeypatch, tmp_path: Path) -> None:
    """A run's gather, route, post or submit is slow; the card goes out before each, so a live host is never STALE.

    Ada 2026-10-17: one tick spent 47 min advancing runs with the card published only at its end, and
    ``forge queue`` called the live host down. PLANTED CONTROL: a tick with no run publishes one card.
    """
    cards: list = []
    _serve(monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=_Slurm, cards=cards, host='base')
    assert len(cards) == 1
    shas = _runs_on_disk(monkeypatch, tmp_path, 2)
    published_before: list[int] = []

    def advance(_root: Path, run: forgerunstate.Run, **_kw: object) -> forgerunstate.Run:
        published_before.append(len(cards))
        return run

    monkeypatch.setattr(forgerun, 'advance', advance)
    cards.clear()
    report, _said, _alarms = _serve(
        monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=_Slurm, cards=cards, host='base'
    )
    assert published_before == [1, 2], 'a fresh card before every run'
    assert len(cards) == 3, 'and the tick card at its end'
    assert sorted(report.in_flight) == shas


def test_a_tick_past_its_period_leaves_the_runs_it_did_not_reach_for_the_next(monkeypatch, tmp_path: Path) -> None:
    """A tick is bounded: once its period is spent it advances no further run; the rest stay in flight.

    PLANTED CONTROL: the same runs advanced in no time are all advanced; and a tick always advances one.
    """
    shas = _runs_on_disk(monkeypatch, tmp_path, 3)
    now = [NOW]
    advanced: list[str] = []

    def slow(_root: Path, run: forgerunstate.Run, **_kw: object) -> forgerunstate.Run:
        advanced.append(run.sha)
        now[0] += timedelta(minutes=4)
        return run

    monkeypatch.setattr(forgerun, 'advance', slow)
    report, said, _alarms = _serve(
        monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=_Slurm,
        table={'tick_minutes': 5}, clock=lambda: now[0],
    )  # fmt: skip
    assert advanced == shas[:2], 'the third would start past the 5 min period'
    assert sorted(report.in_flight) == shas, 'a run not reached is still in flight, untouched'
    assert any(line == f'[serve] the tick ran past its period: {shas[2][:12]} wait for the next' for line in said), said
    advanced.clear()
    _serve(monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=_Slurm, table={'tick_minutes': 5})
    assert advanced == shas, 'PLANTED: a quick tick advances every run'
    advanced.clear()
    now[:] = [NOW, NOW + timedelta(hours=1)]  # the tick started at NOW; its rounds took an hour
    monkeypatch.setattr(forgerun, 'advance', lambda _r, run, **_k: advanced.append(run.sha) or run)
    _serve(
        monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=_Slurm,
        table={'tick_minutes': 5}, clock=lambda: now.pop(0) if len(now) > 1 else now[0],
    )  # fmt: skip
    assert advanced == shas[:1], 'a tick whose rounds ran long still advances one run: no run starves'


class _Untagged(_Slurm):
    """Slurm holding jobs that carry no session tag."""

    def standing(self) -> forgerunstate.Standing:
        held = super().standing()
        return dataclasses.replace(held, facts={**held.facts, 'untagged': 3})


def test_jobs_without_a_session_tag_alarm(monkeypatch, tmp_path: Path) -> None:
    """Untagged jobs are one more stream in the max-min share (lab_commons.hpc.allocation); the forge says so."""
    quiet = TickReport((), (), ('tick',))
    _report, _said, alarms = _serve(monkeypatch, tmp_path, quiet, seat=SEAT, cluster=_Untagged, host='base')
    (raised,) = [a for a in alarms if a.kind == UNTAGGED]
    assert '3' in raised.subject
    assert 'LC_HPC_SESSION' in raised.body
    # Planted control: every job tagged, nothing is raised.
    _report, _said, alarms = _serve(monkeypatch, tmp_path, quiet, seat=SEAT, cluster=_Slurm, host='base')
    assert [a for a in alarms if a.kind == UNTAGGED] == []
