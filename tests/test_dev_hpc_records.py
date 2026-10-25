"""dev_lab reads a ``lab_commons.hpc`` run record: its forge part, carried cells and refusals.

lab-commons tests ``lab_commons.hpc`` itself; this file keeps only what ``dev_lab.dev.platformparts``
and ``dev_lab.dev.forgestatus`` make of a record produced by that run against a fake cluster.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

import pytest
from lab_commons.hpc.builds import Builds
from lab_commons.hpc.config import Cost, Policy
from lab_commons.hpc.gather import gather_run
from lab_commons.hpc.grants import Grant, Machine, Session
from lab_commons.hpc.needsets import BASE, Vocabulary
from lab_commons.hpc.run import RETRIES, submit_run
from lab_commons.hpc.shell import FULL, RunSpec
from lab_commons.hpc.testcells import TestCell
from lab_commons.outcomes import Conclusion

from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.platformparts import PartRefusal, part_of, parts_of

FIXTURE = (Path(__file__).parent / '_hpc_fixtures' / 'cluster-2026-10-08.txt').read_text(encoding='utf-8')
IDLE = FIXTURE.split('@@@ running')[0] + '@@@ running\n'
GRANT = Grant(user='me', hosts=('login.example',), slurm_account='acct-free', partitions=('shortq', 'defq'))
SHA = 'a' * 40


# -- the stream ------------------------------------------------------------------------------------------


def _words(cells: dict[str, dict[str, object]]) -> dict[str, str]:
    """Each id's test cell as its word (``ok``, ``rejected/expected-rejected``, ...)."""
    return {node: TestCell.from_plain(plain).word() for node, plain in cells.items()}


# -- the item runner, for real ---------------------------------------------------------------------------


#: What xdist's ``--dist loadgroup`` does to a grouped test's id inside a worker.


# -- the measured plan -----------------------------------------------------------------------------------


# -- the run flow ------------------------------------------------------------------------------------


#: The resolved environment the fake build reports, as the facts line prints it (envkey.env_record).
RESOLVED: Final = json.dumps(['cpython-3.13.1-linux', 'lab-commons==0.3.0+g1234567', 'numpy==2.3.0'])


class FakeRunCluster:
    """A cluster answering the run flow; an item of a file in *dies* is killed in its first *kills* rounds.

    A killed item streams the first half of its ids (rounded down) and never closes.
    """

    def __init__(
        self,
        *,
        have: bool = True,
        dies: frozenset[str] = frozenset(),
        kills: int = 1,
        oom: bool = False,
        build_fails: bool = False,
        lacking: tuple[str, ...] = (),
        active: int = 0,
        env: str = 'e0ffee0123456789',
        collected: str | None = None,
        hog: str = '',
        mem_ceiling: str = '360G',
        held: str = '',
        peak_mb: float = 2048.0,
    ) -> None:
        """*have*: the cache holds the commit; *oom*: round 0 is OUT_OF_MEMORY; *active*: sacct polls RUNNING.

        *hog*: an id whose item is OOM-killed in every round it runs in; *mem_ceiling*: the account's quota
        memory; *closed* (set later): every grant refuses the next round; *peak_mb*: what a finished item peaks at.
        """
        self.have, self.dies, self.kills, self.oom = have, dies, kills, oom
        self.hog, self.mem_ceiling, self.closed = hog, mem_ceiling, False
        self.peak_mb = peak_mb
        self.held = held  # the account's OTHER running jobs, ``squeue`` lines of the probe's ``running`` section
        self.build_fails, self.lacking, self.active = build_fails, lacking, active
        self.env, self.collected = env, collected
        self.state = ''  # the state last written
        self.states: dict[str, str] = {}  # every state written, by its path
        self.queue = ''
        self.calls: list[tuple[str, str | None]] = []
        self.manifests: list[dict] = []
        self.scripts: list[str] = []

    def __call__(self, command: str, stdin: str | None = None) -> str:  # noqa: C901, PLR0911, PLR0912 -- one answer per verb
        self.calls.append((command, stdin))
        if command.endswith('state.json') and 'cat >' in command:
            self.state = self.states[command.rsplit('cat > ', maxsplit=1)[-1]] = stdin or ''
            return ''
        if 'squeue -h -r -j' in command:
            if isinstance(self.queue, Exception):
                raise self.queue
            return self.queue
        if 'state.json' in command:
            return self.states.get(command.split()[1], '')
        if command.startswith('for c in'):
            return ''.join(f'@@@ missing {c}\n' for c in self.lacking)
        if command.startswith('echo "@@@ nodes"'):
            quota = 'cpu=0' if self.closed else 'cpu=96'
            probed = IDLE.replace('|free|cpu=96,', f'|free|{quota},').replace('mem=360G', f'mem={self.mem_ceiling}')
            return probed + self.held + '@@@ shared\n8|1G|1|lc:session=other\n'
        if 'cat-file' in command:
            return 'have\n' if self.have else 'missing\n'
        if '@@@ facts' in command and self.build_fails:
            return '@@@ build-failed exit 101\nerror: could not find `cargo`\n'
        if '@@@ facts' in command:
            return (
                f'@@@ time env=12s\n@@@ facts\nplatform=linux-x86_64/glibc2.28\npython=3.13.1\nenv={self.env}\n'
                f'resolved={RESOLVED}\n'
            )
        if '--collect-only' in command or 'lab_ci_collect.py --cache' in command:
            if '(win)' in command:
                return 'tests/w.py::t\n'
            if self.collected is not None:
                return self.collected
            return (
                '@@@ time collect=3s\n'
                'tests/a.py::t1\ntests/a.py::t2\ntests/w.py::t\ntests/b.py::t3\ntests/b.py::t4\ntests/b.py::t5\n'
            )
        if command.endswith('manifest.json'):
            self.manifests.append(json.loads(stdin or ''))
        if command.endswith('job.sh') and 'cat >' in command:
            self.scripts.append(stdin or '')
        if 'sbatch' in command:
            return f'{4242 + len(self.manifests)}\n'
        if 'sacct' in command and self.active:
            self.active -= 1
            return '\n'.join(f'1_{i}|RUNNING' for i in range(9)) + '\n'
        if 'sacct' in command:
            state = 'OUT_OF_MEMORY' if (self.oom and len(self.manifests) == 1) or self.hog else 'TIMEOUT'
            hour = 1 + len(self.manifests)
            rows = (
                f'1_{i}|{state if i == 0 else "COMPLETED"}|2026-10-11T0{hour}:00:00|2026-10-11T0{hour}:01:00'
                f'|2026-10-11T0{hour}:{2 + i:02d}:00|{60 + 60 * i}|1'
                for i in range(9)
            )
            return '\n'.join(rows) + '\n'
        if '*.jsonl' in command:
            return self._streams()
        return ''

    def _streams(self) -> str:
        out = []
        dying = len(self.manifests) <= self.kills
        for index, item in enumerate(self.manifests[-1]['items']):
            killed = dying and item['ids'][0].split('::')[0] in self.dies
            ran = item['ids'][: len(item['ids']) // 2] if killed else item['ids']
            out.append(f'@@@ {index}.jsonl')
            if self.hog in item['ids']:
                ran = item['ids'][: item['ids'].index(self.hog)]
                out += [json.dumps({'id': n, 'status': 'ok', 's': 1.0}) for n in ran]
                out.append(json.dumps({'done': -9, 'wall': 5.0, 'peak_mb': 1024.0}))
                continue
            out += [json.dumps({'id': n, 'status': 'ok', 's': 1.0}) for n in ran]
            if not killed:
                out.append(json.dumps({'done': 0, 'wall': 5.0 + len(ran), 'peak_mb': self.peak_mb}))
        return '\n'.join(out) + '\n'


MACHINE = Machine(session=Session(name='ws-a', tasks=1000, cpus=100_000, mem_gb=1_000_000), grants=(GRANT,))
COST, POLICY = Cost(seconds=600), Policy(shard_minutes_min=1, shard_minutes_max=15)


def _submit(fake: FakeRunCluster, **kw: object) -> str:
    spec = RunSpec(
        sha=SHA,
        repo_url='https://g/r.git',
        builds=Builds(install='true', env_key='k1'),
        vocabulary=Vocabulary(('win',)),
    )
    return submit_run(spec, MACHINE, lambda _g: fake, cost=COST, policy=POLICY, stamp='t0', **kw)


def _gather(fake: FakeRunCluster) -> dict | None:
    return gather_run(SHA, BASE, MACHINE, lambda _g: fake, cost=COST, policy=POLICY)


def _run(fake: FakeRunCluster, **kw: object) -> dict:
    """Submit, then gather until the record comes back -- each gather one short call, as a caller makes them."""
    _submit(fake, **kw)
    for _ in range(2 + RETRIES):
        record = _gather(fake)
        if record is not None:
            return record
    pytest.fail('the gathers never returned a record')


def test_what_is_still_unfinished_after_the_retries_is_infra() -> None:
    record = _run(FakeRunCluster(dies=frozenset({'tests/b.py'}), kills=1 + RETRIES))
    assert len(record['rounds']) == 1 + RETRIES
    words = _words(record['cells'])
    assert words['tests/b.py::t3'] == 'ok', 'what a killed shard finished is kept'
    assert [words[f'tests/b.py::t{n}'] for n in (4, 5)] == ['infra', 'infra'], 'the machine, not the test, said no'
    with pytest.raises(PartRefusal, match='INCONCLUSIVE'):
        part_of(record)


#: The measured shape, 2026-10-16: 29 one-core 8 GB tasks of other campaigns held 232 GB of a 360 GB ceiling.


# -- an id that dies is priced from its death ------------------------------------------------------------


# -- where a run is, and when it stalls ------------------------------------------------------------------


# -- gather and gather --wait share one path, on this login node's shell ---------------------------------


# -- efficiency: measured phases, carried measurements, balanced shards (census 2026-10-11) ----------------


# -- carried cells (dev_lab.dev.forgecarry) ------------------------------------------------------

A_SHA = 'a' * 40
OK_CELL: dict[str, object] = {'status': 'ok', 'evidence': 'observed'}
RED_CELL: dict[str, object] = {
    'status': 'rejected',
    'evidence': 'observed',
    'reason': {'kind': 'assertion', 'text': 'x'},
}


def test_carried_ids_are_never_submitted_and_the_record_names_their_origin() -> None:
    fake, envs = FakeRunCluster(), []

    def carry(env: str) -> dict[str, tuple[dict[str, object], str, str]]:
        envs.append(env)
        return {
            'tests/a.py::t1': (OK_CELL, A_SHA, A_SHA),
            'tests/a.py::t2': (RED_CELL, A_SHA, A_SHA),
            'x::y': (OK_CELL, A_SHA, A_SHA),
        }

    record = _run(fake, carry=carry)
    assert envs == ['e0ffee0123456789'], 'the carry is asked for the env the build reported'
    submitted = {node for item in fake.manifests[0]['items'] for node in item['ids']}
    assert submitted == {'tests/b.py::t3', 'tests/b.py::t4', 'tests/b.py::t5'}
    assert record['carried'] == {'tests/a.py::t1': A_SHA, 'tests/a.py::t2': A_SHA}, 'an id not collected is not taken'
    assert _words(record['cells'])['tests/a.py::t2'] == 'rejected', 'a carried red stays red'
    assert record['scope'] == FULL, 'a carried run is still the full suite'
    part = part_of(record)
    assert (part.ran, part.kept, part.result) == (3, {A_SHA[:12]: 2}, Conclusion.FAIL), (
        'carried is never counted as run'
    )
    assert part.description().endswith(f'kept={A_SHA[:12]}:2')
    assert (
        parts_of([CommitStatus(f'tests/{part.platform}', 'failure', part.description(), '')])[0][part.platform] == part
    )


def test_a_run_whose_every_id_is_carried_writes_its_record_without_a_job() -> None:
    fake = FakeRunCluster()
    ids = ['tests/a.py::t1', 'tests/a.py::t2', 'tests/b.py::t3', 'tests/b.py::t4', 'tests/b.py::t5']
    state = _submit(fake, carry=lambda _env: dict.fromkeys(ids, (OK_CELL, A_SHA, A_SHA)))
    assert not fake.manifests, 'nothing was submitted'
    assert state['rounds'] == []
    assert _gather(fake) == state['record']
    assert part_of(state['record']).ran == 0
