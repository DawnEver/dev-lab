"""PARTS: one per need-set, derived from the suite; a strict part from a run record; one declared producer."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest
from _forge_fake import git_out, make_repo, run_git

from lab_commons.dev import localpart, platformparts
from lab_commons.dev.envkey import env_record
from lab_commons.dev.forgeoutbox import PostFailed
from lab_commons.dev.forgestatus import Status
from lab_commons.dev.producer import ProducerExit
from lab_commons.hpc import __main__ as hpc_cli
from lab_commons.hpc.grants import Machine
from lab_commons.hpc.needsets import BASE, Vocabulary, read_vocabulary
from lab_commons.hpc.records import write_record
from lab_commons.hpc.tree import NotSubmitted

SHA = 'a' * 40

PYPROJECT = """
[tool.lab_commons.tests]
resources = ["femm", "windows"]
"""


def _record(outcomes: dict[str, str], handed: dict[str, str] | None = None, part: str = BASE) -> dict[str, object]:
    return {
        'sha': SHA,
        'platform': part,
        'system': 'linux-x86_64/glibc2.28',
        'scope': 'full',
        'req': 't0',
        'cluster': 'login.ada',
        'python': '3.13.1',
        'plan': {},
        'outcomes': outcomes,
        'handed': handed or {},
    }


def test_the_part_is_derived_strictly_from_the_run() -> None:
    passing = _record(
        {'t::a': 'passed', 't::b': 'skipped', 't::c': 'xfailed', 't::f': 'not-covered', 't::m': 'not-covered'},
        {'t::f': 'femm', 't::m': 'femm+windows'},
    )
    part = platformparts.part_of(passing)
    assert (part.platform, part.scope, part.result, part.state) == (BASE, 'full', 'PASS', 'success'), (
        "part and scope are the record's"
    )
    assert (part.ran, part.hands) == (3, {'femm': 1, 'femm+windows': 1})
    assert part.description() == 'scope=full ran=3 hands=femm:1,femm+windows:1'
    for bad in ('failed', 'error'):
        failing = platformparts.part_of(_record({'t::a': 'passed', 't::x': bad}))
        assert (failing.result, failing.state) == ('FAIL', 'failure'), bad


@pytest.mark.parametrize('unrun', ['lost', 'missing'])
def test_a_part_whose_ids_never_reported_is_inconclusive_and_never_posted(unrun: str) -> None:
    """Measured 2026-10-09: 50349 lost ids from a build that never made a venv were written as a FAIL."""
    outcomes = {'t::a': 'passed', 't::e': 'error', 't::x': unrun}
    with pytest.raises(platformparts.PartRefusal, match=r'INCONCLUSIVE: 1 of 3 .*t::x'):
        platformparts.part_of(_record(outcomes))
    with pytest.raises(platformparts.PartRefusal, match='covers no test'):
        platformparts.part_of(_record({'t::f': 'not-covered'}))


def test_a_record_handing_off_its_own_ids_or_to_no_part_is_refused() -> None:
    """PLANTED CONTROL: base handing off a base id is a selection defect, not a part."""
    with pytest.raises(platformparts.PartRefusal, match='of its own part: t::a'):
        platformparts.part_of(_record({'t::b': 'passed', 't::a': 'not-covered'}, {'t::a': BASE}))
    with pytest.raises(platformparts.PartRefusal, match='to no part: t::a'):
        platformparts.part_of(_record({'t::b': 'passed', 't::a': 'not-covered'}, {'t::a': ''}))


def test_the_description_round_trips_through_a_status() -> None:
    part = platformparts.Part('femm+windows', 'full', 'FAIL', ran=7, hands={BASE: 1})
    status = Status(platformparts.part_context('femm+windows'), part.state, part.description(), 'u')
    parts, problems = platformparts.parts_of([status, Status('ci/foreign', 'success', 'not a part', '')])
    assert parts == {'femm+windows': part}
    assert problems == ()
    _, claimed = platformparts.parts_of([Status('tests/base', 'pending', 'claim machine=G', '')])
    assert 'not a settled part' in claimed[0]


def test_a_commits_parts_are_derived_from_what_its_parts_hand_to() -> None:
    """Nothing posted: base alone is known. A posted part names every part it handed ids to."""
    assert platformparts.derived([]) == (BASE,)
    base = platformparts.Part(BASE, 'full', 'PASS', ran=2, hands={'femm': 3, 'jmag': 1})
    posted = [Status('tests/base', base.state, base.description(), '')]
    assert platformparts.derived(posted) == (BASE, 'femm', 'jmag')


def test_every_id_belongs_to_exactly_one_part() -> None:
    owners = {'t::a': BASE, 't::f': 'femm', 't::w': 'windows'}
    for part in (BASE, 'femm', 'windows'):
        mine, handed = platformparts.split(owners, part)
        assert set(mine).isdisjoint(handed), part
        assert set(mine) | set(handed) == set(owners), part
    assert platformparts.split(owners, 'femm') == (['t::f'], {'t::a': BASE, 't::w': 'windows'})


def test_a_part_selects_from_its_own_collection_without_reading_any_ledger(tmp_path: Path, monkeypatch) -> None:
    """No part is recorded anywhere, and femm+windows still selects: it reads only the vocabulary and ids."""
    monkeypatch.setattr(platformparts, 'vocabulary_at', lambda _root, _sha: read_vocabulary(PYPROJECT))
    collected = {'': ['t::a', 't::f', 't::fw'], 'femm': ['t::f', 't::fw'], 'windows': ['t::fw']}
    mine, handed = platformparts.select(tmp_path, SHA, 'femm+windows', collect=collected.__getitem__)
    assert mine == ['t::fw']
    assert handed == {'t::a': BASE, 't::f': 'femm'}
    with pytest.raises(ValueError, match='not a part name'):
        platformparts.select(tmp_path, SHA, 'windows+femm', collect=collected.__getitem__)


def test_the_cli_queues_the_part_with_its_record_and_flushes(tmp_path: Path, monkeypatch, capsys) -> None:
    source = write_record(_record({'t::a': 'passed'}), tmp_path / 'runs')
    queued: list = []
    monkeypatch.setattr(platformparts, 'enqueue', lambda _root, post, *, record: queued.append((post, record)))
    monkeypatch.setattr(platformparts, 'flush', lambda _root: ['status: held tests/base'])
    assert platformparts.main(['post', str(source), '--root', str(tmp_path)]) == 0
    post, record = queued[0]
    assert (post.sha, post.context, post.state, post.description) == (
        SHA,
        'tests/base',
        'success',
        'scope=full ran=1 hands=-',
    )
    assert record == source
    assert 'status: held tests/base' in capsys.readouterr().out
    empty = write_record({**_record({}), 'req': 't1'}, tmp_path / 'runs')
    assert platformparts.main(['post', str(empty), '--root', str(tmp_path)]) == 1
    assert len(queued) == 1, 'a refused part is never queued'


DECLARED = """
[tool.lab_commons.hpc]
install = "uv sync --extra dev"
needs = ["cargo", "cc"]
collect = "tests"

[tool.lab_commons.parts]
output = "output/logs"

[tool.lab_commons.tests]
resources = ["femm", "jmag"]
produce = ["scripts/gate/runner.py", "part", "{part}", "--full"]
"""


def _checkout(tmp_path: Path, pyproject: str, remote: str = 'git@forge.example.org:o/r.git') -> tuple[Path, str]:
    """A repo whose COMMIT carries *pyproject*, and that commit; the working tree then declares nothing."""
    repo = make_repo(tmp_path, remote)
    (repo / 'pyproject.toml').write_text(pyproject, encoding='utf-8')
    run_git(repo, 'add', 'pyproject.toml')
    run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'declare')
    (repo / 'pyproject.toml').write_text('', encoding='utf-8')
    return repo, git_out(repo, 'rev-parse', 'HEAD')


def test_the_cluster_part_is_filled_from_the_declarations_alone(tmp_path: Path) -> None:
    """The build (install, needs) is NOT in it: hpc reads it from the commit itself."""
    repo, sha = _checkout(tmp_path, DECLARED)
    part = platformparts.cluster_part(repo, sha)
    assert (part.repo_url, part.collect) == ('https://forge.example.org/o/r.git', 'tests')
    assert part.output.relative_to(repo).parts[:2] == ('output', 'logs')
    assert part.output.relative_to(repo).parts[-2:] == ('parts', sha)
    assert part.outputs == (), 'nothing is uploaded by default'


def test_the_cluster_part_carries_the_declared_outputs_and_a_malformed_list_is_refused(tmp_path: Path) -> None:
    declared = DECLARED.replace(
        'install = "uv sync --extra dev"\n', 'install = "uv sync --extra dev"\noutputs = ["f/*.h5"]\n'
    )
    for name in ('ok', 'bad'):
        (tmp_path / name).mkdir()
    repo, sha = _checkout(tmp_path / 'ok', declared)
    assert platformparts.cluster_part(repo, sha).outputs == ('f/*.h5',)
    repo, sha = _checkout(tmp_path / 'bad', declared.replace('["f/*.h5"]', '"f/*.h5"'))
    with pytest.raises(platformparts.UndeclaredPart, match=r'\[tool\.lab_commons\.hpc\] outputs'):
        platformparts.cluster_part(repo, sha)


@pytest.mark.parametrize('part', [BASE, 'jmag', 'femm+jmag'])
def test_every_part_runs_the_one_declared_producer_told_its_part(tmp_path: Path, part: str) -> None:
    """The argv is the one the CLAIMED COMMIT declares (the working tree is emptied), {part} filled."""
    repo, sha = _checkout(tmp_path, DECLARED)
    assert platformparts.producer_argv(repo, part, sha=sha) == ['scripts/gate/runner.py', 'part', part, '--full']


@pytest.mark.parametrize(
    ('produce', 'named'),
    [
        ('', r'\[tool\.lab_commons\.tests\] produce as a non-empty array'),
        ('produce = ["-m", "lab_commons.dev.verify"]\n', r'must carry \{part\}'),
    ],
)
def test_a_producer_never_told_its_part_is_refused(tmp_path: Path, produce: str, named: str) -> None:
    """PLANTED CONTROL: the full declaration fills the argv; dropping {part} or the producer refuses by key."""
    line = 'produce = ["scripts/gate/runner.py", "part", "{part}", "--full"]\n'
    repo, sha = _checkout(tmp_path, DECLARED.replace(line, produce))
    with pytest.raises(platformparts.UndeclaredPart, match=named):
        platformparts.producer_argv(repo, BASE, sha=sha)


@pytest.mark.parametrize(
    ('drop', 'named'),
    [
        ('install = "uv sync --extra dev"\n', r'\[tool\.lab_commons\.hpc\] install'),
        ('output = "output/logs"\n', r'\[tool\.lab_commons\.parts\] output'),
    ],
)
def test_a_missing_cluster_declaration_is_refused_naming_its_key(tmp_path: Path, drop: str, named: str) -> None:
    """PLANTED CONTROL: the full declaration fills the part; removing one key refuses by that key."""
    assert DECLARED.count(drop) == 1
    repo, sha = _checkout(tmp_path, DECLARED.replace(drop, ''))
    with pytest.raises(platformparts.UndeclaredPart, match=named):
        platformparts.cluster_part(repo, sha)


def test_a_hand_run_submit_whose_build_failed_exits_inconclusive_naming_its_log(monkeypatch, capsys) -> None:
    """``hpc run submit`` by hand: a build that submitted nothing exits 3 (INCONCLUSIVE) and names its log.

    The tick's half is ``test_dev_forgerun::test_a_failed_build_is_released_inconclusive_naming_its_log``.
    """
    log = '/ci/native/k.log'

    def failed_build(*_a: object, **_k: object) -> NoReturn:
        msg = f'the build for {SHA[:12]} failed on h, nothing was submitted; log={log}'
        raise NotSubmitted(msg)

    monkeypatch.setattr(hpc_cli, 'load_grants', lambda: Machine(session=None, grants=()))
    monkeypatch.setattr(hpc_cli, 'builds_at', lambda *_a, **_k: ())
    monkeypatch.setattr(hpc_cli, 'vocabulary_at', lambda *_a: Vocabulary())
    monkeypatch.setattr(hpc_cli, 'submitter', lambda: None)
    monkeypatch.setattr(hpc_cli, 'submit_run', failed_build)
    flags = ['--repo-url', 'u', '--collect', 't']
    assert hpc_cli.main(['run', 'submit', '--sha', SHA, '--scope', 'full', *flags]) == ProducerExit.INCONCLUSIVE
    assert log in capsys.readouterr().err


def _status(part: str, state: str = 'success', *, scope: str = 'full', hands: str = '-') -> Status:
    return Status(f'tests/{part}', state, f'scope={scope} ran=2 hands={hands}', '')


def test_the_standing_requires_base_and_every_part_handed_to() -> None:
    """PASS only when base and every derived part stand; a FAIL part is FAIL whatever else; unsettled otherwise."""
    assert platformparts.standing([_status(BASE)], head=SHA).result == 'PASS'
    assert platformparts.standing([], head=SHA).result == ''
    assert platformparts.standing([_status('jmag')], head=SHA).result == '', 'no base: nothing proves the rest'
    assert platformparts.standing([_status(BASE, hands='femm+windows:1')], head=SHA).result == ''
    both = [_status(BASE, hands='femm+windows:1'), _status('femm+windows')]
    assert platformparts.standing(both, head=SHA).result == 'PASS'
    red = [_status(BASE, 'failure'), _status('femm', 'pending')]
    assert platformparts.standing(red, head=SHA).result == 'FAIL'
    incremental = [_status(BASE, scope='incremental')]
    assert platformparts.standing(incremental, head=SHA).result == 'PASS'
    full = platformparts.standing(incremental, head=SHA, scope='full')
    assert full.result == ''
    assert any('scope incremental' in problem for problem in full.problems)


def test_a_local_run_becomes_one_record_per_part_of_the_cluster_shape(tmp_path: Path, monkeypatch) -> None:
    """A local run covers the ids of the part it records and hands every other id to its own part."""
    monkeypatch.setattr(localpart, 'vocabulary_at', lambda _root, _sha: read_vocabulary(PYPROJECT))
    outcomes = {'t::a': 'passed', 't::f': 'failed', 't::w': 'skipped'}
    collected = {'': ['t::a', 't::f', 't::w', 't::fw'], 'femm': ['t::f', 't::fw'], 'windows': ['t::w', 't::fw']}
    owned = localpart.owners(tmp_path, SHA, list(outcomes), collected.__getitem__)
    assert owned == {'t::a': BASE, 't::f': 'femm', 't::w': 'windows', 't::fw': 'femm+windows'}

    def local(part: str) -> dict[str, object]:
        reasons = {'t::w': 'skipped here', 't::f': 'red'}
        fields = {'sha': SHA, 'scope': 'full', 'req': 'verify-x', 'outcomes': outcomes, 'reasons': reasons}
        return localpart.local_record(part=part, owned=owned, **fields)

    base = local(BASE)
    assert base['outcomes'] == {'t::a': 'passed', **dict.fromkeys(['t::f', 't::w', 't::fw'], 'not-covered')}
    assert base['handed'] == {'t::f': 'femm', 't::w': 'windows', 't::fw': 'femm+windows'}
    assert base['reasons'] == {}
    part = platformparts.part_of(base)
    assert (part.platform, part.result, part.ran) == (BASE, 'PASS', 1)
    assert part.hands == {'femm': 1, 'windows': 1, 'femm+windows': 1}, 'the parts this commit needs, discovered'
    femm = platformparts.part_of(local('femm'))
    assert (femm.result, femm.ran, femm.hands) == ('FAIL', 1, {BASE: 1, 'windows': 1, 'femm+windows': 1})


def test_a_repo_declaring_no_resource_is_all_base_and_collects_nothing(tmp_path: Path, monkeypatch) -> None:
    """Live 2026-10-11 (lab-commons ff3106e): a windows verify of a repo with no table covered nothing.

    PLANTED CONTROL: a run that judged no test is still refused, so an empty part is never a pass.
    """
    monkeypatch.setattr(localpart, 'vocabulary_at', lambda _root, _sha: Vocabulary())
    reported = {'t::a': 'passed', 't::s': 'skipped'}
    owned = localpart.owners(tmp_path, SHA, list(reported), lambda _e: pytest.fail('nothing is declared'))
    assert owned == dict.fromkeys(reported, BASE)

    def local(outcomes: dict[str, str]) -> dict[str, object]:
        fields = {'sha': SHA, 'scope': 'full', 'req': 'r', 'reasons': {'t::s': 'why'}}
        return localpart.local_record(part=BASE, outcomes=outcomes, owned=owned, **fields)

    record = local(reported)
    assert record['outcomes'] == reported
    assert {key: record[key] for key in ('env', 'resolved')} == env_record(), 'it names what it ran against'
    assert record['reasons'] == {'t::s': 'why'}
    assert platformparts.part_of(record).hands == {}
    with pytest.raises(platformparts.PartRefusal, match='covers no test'):
        platformparts.part_of(
            localpart.local_record(part=BASE, outcomes={}, owned={}, sha=SHA, scope='full', req='r', reasons={})
        )


def test_a_forge_outage_on_post_is_unreachable_not_a_refusal(tmp_path: Path, monkeypatch) -> None:
    """PLANTED CONTROL: the same green record posts (0) when the forge answers."""
    source = write_record(_record({'t::a': 'passed'}), tmp_path / 'runs')
    monkeypatch.setattr(platformparts, 'enqueue', lambda *_a, **_k: None)
    monkeypatch.setattr(platformparts, 'flush', lambda _root: [])
    assert platformparts.main(['post', str(source), '--root', str(tmp_path)]) == 0

    def down(_root: Path) -> list[str]:
        msg = 'forge did not answer'
        raise PostFailed(msg)

    monkeypatch.setattr(platformparts, 'flush', down)
    assert platformparts.main(['post', str(source), '--root', str(tmp_path)]) == ProducerExit.UNREACHABLE
