"""PLATFORM PARTS: one declaration per marker, one assignment rule, a strict part from a run record."""

from __future__ import annotations

from pathlib import Path

import pytest
from _forge_fake import make_repo

from lab_commons.dev import localpart, platformparts
from lab_commons.dev.forgestatus import Status
from lab_commons.hpc.platforms import assign, cannot_run, host_platform, read_table, runnable
from lab_commons.hpc.records import write_record

SHA = 'a' * 40

PYPROJECT = """
[tool.lab_commons.platforms]
femm = ["windows"]
matlab = ["windows", "linux"]
"""


def _record(outcomes: dict[str, str], handed: dict[str, list[str]] | None = None) -> dict[str, object]:
    return {
        'sha': SHA,
        'platform': 'linux',
        'system': 'linux-x86_64/glibc2.28',
        'scope': 'full',
        'req': 't0',
        'cluster': 'login.ada',
        'python': '3.13.1',
        'plan': {},
        'outcomes': outcomes,
        'handed': handed or {},
    }


def test_the_table_is_one_declaration_per_marker() -> None:
    table = read_table(PYPROJECT)
    assert table == {'femm': ('windows',), 'matlab': ('windows', 'linux')}
    assert cannot_run(table, 'linux') == 'femm'
    assert cannot_run(table, 'macos') == 'femm or matlab'
    assert cannot_run(table, 'windows') == '', 'an unlisted marker runs everywhere'
    assert read_table('[project]\nname = "x"\n') == {}
    with pytest.raises(ValueError, match='platforms are a list'):
        read_table('[tool.lab_commons.platforms]\nfemm = ["win32"]\n')
    assert host_platform('win32') == 'windows'


def test_the_part_is_derived_strictly_from_the_run() -> None:
    passing = _record(
        {'t::a': 'passed', 't::b': 'skipped', 't::c': 'xfailed', 't::f': 'not-covered', 't::m': 'not-covered'},
        {'t::f': ['windows'], 't::m': ['windows', 'macos']},
    )
    part = platformparts.part_of(passing)
    assert (part.platform, part.scope, part.result, part.state) == ('linux', 'full', 'PASS', 'success'), (
        "platform and scope are the record's"
    )
    assert (part.ran, part.hands, part.nowhere) == (3, {'windows': 2}, 0)
    assert part.description() == 'scope=full ran=3 hands=windows:2 nowhere=0'
    for bad in ('failed', 'error'):
        failing = platformparts.part_of(_record({'t::a': 'passed', 't::x': bad}))
        assert (failing.result, failing.state) == ('FAIL', 'failure'), bad


@pytest.mark.parametrize('unrun', ['lost', 'missing'])
def test_a_part_whose_ids_never_reported_is_inconclusive_and_never_posted(unrun: str) -> None:
    """Measured 2026-10-09: 50349 lost ids from a build that never made a venv were written as a linux FAIL."""
    outcomes = {'t::a': 'passed', 't::e': 'error', 't::x': unrun}
    with pytest.raises(platformparts.PartRefusal, match=r'INCONCLUSIVE: 1 of 3 .*t::x'):
        platformparts.part_of(_record(outcomes))
    with pytest.raises(platformparts.PartRefusal, match='covers no test'):
        platformparts.part_of(_record({'t::f': 'not-covered'}))


def test_a_record_handing_off_its_own_ids_is_refused() -> None:
    """PLANTED CONTROL: linux handing off an id linux can run is a selection defect, not a part."""
    with pytest.raises(platformparts.PartRefusal, match='it is assigned: t::a'):
        platformparts.part_of(_record({'t::b': 'passed', 't::a': 'not-covered'}, {'t::a': ['linux', 'windows']}))


def test_the_description_round_trips_through_a_status() -> None:
    part = platformparts.Part('windows', 'full', 'FAIL', ran=7, hands={'macos': 1}, nowhere=2)
    status = Status(platformparts.part_context('windows'), part.state, part.description(), 'u')
    parts, problems = platformparts.parts_of([status, Status('ci/foreign', 'success', 'not a part', '')])
    assert parts == {'windows': part}
    assert problems == ()
    _, claimed = platformparts.parts_of([Status('tests/linux', 'pending', 'claim machine=G', '')])
    assert 'not a settled part' in claimed[0]


def test_every_id_is_assigned_to_exactly_one_part_by_one_rule() -> None:
    """The rule: linux if it can run there, else windows, else macos; nowhere is ``None``."""
    assert assign(['linux', 'windows', 'macos']) == 'linux'
    assert assign(['macos', 'windows']) == 'windows', 'the rule reads PLATFORMS order, not the list order'
    assert assign(['macos']) == 'macos'
    assert assign([]) is None
    can = {'t::a': ['linux', 'windows', 'macos'], 't::f': ['windows'], 't::m': ['windows', 'macos'], 't::n': []}
    for platform in ('linux', 'windows', 'macos'):
        mine, handed = platformparts.split(can, platform)
        assert set(mine).isdisjoint(handed), platform
        assert set(mine) | set(handed) == set(can), platform
    assert platformparts.split(can, 'windows') == (['t::f', 't::m'], {'t::a': can['t::a'], 't::n': []})
    assert platformparts.split(can, 'linux')[0] == ['t::a']


def test_a_part_selects_from_its_own_collection_without_reading_any_ledger(tmp_path: Path, monkeypatch) -> None:
    """No part is recorded anywhere, and windows still selects: the selection reads only table and ids."""
    monkeypatch.setattr(platformparts, 'table_at', lambda _root, _sha: read_table(PYPROJECT))
    collected = {'': ['t::a', 't::f', 't::m'], 'femm': ['t::f'], 'femm or matlab': ['t::f', 't::m']}
    mine, handed = platformparts.select(tmp_path, SHA, 'windows', collect=collected.__getitem__)
    assert mine == ['t::f']
    assert handed == {'t::a': ['linux', 'windows', 'macos'], 't::m': ['linux', 'windows']}
    assert runnable(['t::f'], {'linux': {'t::f'}}) == {'t::f': ['windows', 'macos']}
    with pytest.raises(ValueError, match='one of'):
        platformparts.select(tmp_path, SHA, 'win32', collect=collected.__getitem__)


def test_the_cli_queues_the_part_with_its_record_and_flushes(tmp_path: Path, monkeypatch, capsys) -> None:
    source = write_record(_record({'t::a': 'passed'}), tmp_path / 'runs')
    queued: list = []
    monkeypatch.setattr(platformparts, 'enqueue', lambda _root, post, *, record: queued.append((post, record)))
    monkeypatch.setattr(platformparts, 'flush', lambda _root: ['status: held tests/linux'])
    assert platformparts.main(['post', str(source), '--root', str(tmp_path)]) == 0
    post, record = queued[0]
    assert (post.sha, post.context, post.state, post.description) == (
        SHA,
        'tests/linux',
        'success',
        'scope=full ran=1 hands=- nowhere=0',
    )
    assert record == source
    assert 'status: held tests/linux' in capsys.readouterr().out
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

[tool.lab_commons.parts.produce.windows]
full = ["scripts/gate/runner.py", "gate", "--platform", "windows", "--full"]
incremental = ["scripts/gate/runner.py", "gate", "--platform", "windows"]
"""


def _checkout(tmp_path: Path, pyproject: str, remote: str = 'git@forge.example.org:o/r.git') -> tuple[Path, str]:
    repo = make_repo(tmp_path, remote)
    (repo / 'pyproject.toml').write_text(pyproject, encoding='utf-8')
    python = repo / '.venv' / 'Scripts' / 'python.exe'
    python.parent.mkdir(parents=True)
    python.write_text('', encoding='utf-8')
    return repo, str(python)


def test_the_cluster_argv_is_filled_from_the_declarations_alone(tmp_path: Path) -> None:
    """The build (install, needs) is NOT in the argv: hpc run submit reads it from the commit itself."""
    repo, python = _checkout(tmp_path, DECLARED)
    argv = platformparts.part_argv(repo, 'linux', SHA, scope='full', os_name='nt')
    output = Path(argv[-1])
    assert argv == [
        python, '-m', 'lab_commons.dev.platformparts', 'cluster', '--sha', SHA,
        '--repo-url', 'https://forge.example.org/o/r.git',
        '--collect', 'tests', '-o', str(output),
    ]  # fmt: skip
    assert output.relative_to(repo).parts[:2] == ('output', 'logs')
    assert output.relative_to(repo).parts[-2:] == ('parts', SHA)
    assert not any('<' in item for item in argv), 'no placeholder survives'


def test_a_local_part_runs_the_declared_producer_per_scope(tmp_path: Path) -> None:
    repo, python = _checkout(tmp_path, DECLARED)
    full = platformparts.part_argv(repo, 'windows', SHA, scope='full', os_name='nt')
    assert full == [python, 'scripts/gate/runner.py', 'gate', '--platform', 'windows', '--full']
    incremental = platformparts.part_argv(repo, 'windows', SHA, scope='incremental', os_name='nt')
    assert incremental[-1] == 'windows'


@pytest.mark.parametrize(
    ('drop', 'platform', 'named'),
    [
        ('install = "uv sync --extra dev"\n', 'linux', r'\[tool\.lab_commons\.hpc\] install'),
        ('output = "output/logs"\n', 'linux', r'\[tool\.lab_commons\.parts\] output'),
        ('full = ["scripts/gate/runner.py", "gate", "--platform", "windows", "--full"]\n', 'windows',
         r'\[tool\.lab_commons\.parts\.produce\.windows\] full'),
    ],
)  # fmt: skip
def test_a_missing_declaration_is_refused_naming_its_key(tmp_path: Path, drop: str, platform: str, named: str) -> None:
    """PLANTED CONTROL: the full declaration produces an argv; removing one key refuses by that key."""
    assert DECLARED.count(drop) == 1
    repo, _python = _checkout(tmp_path, DECLARED.replace(drop, ''))
    with pytest.raises(platformparts.UndeclaredPart, match=named):
        platformparts.part_argv(repo, platform, SHA, scope='full', os_name='nt')


def test_a_cluster_part_is_full_and_macos_needs_its_own_declaration(tmp_path: Path) -> None:
    repo, _python = _checkout(tmp_path, DECLARED)
    with pytest.raises(ValueError, match='scope full'):
        platformparts.part_argv(repo, 'linux', SHA, scope='incremental', os_name='nt')
    with pytest.raises(platformparts.UndeclaredPart, match=r'produce\.macos\] full'):
        platformparts.part_argv(repo, 'macos', SHA, scope='full', os_name='nt')


def test_cluster_submits_gathers_and_posts_the_record(tmp_path: Path, monkeypatch) -> None:
    calls: list[list[str]] = []
    output = tmp_path / 'records'

    def hpc(argv: list[str]) -> int:
        calls.append(argv)
        if argv[1] == 'gather':
            write_record(_record({'t::a': 'failed'}), output)
            return 1
        return 0

    posted: list[Path] = []
    monkeypatch.setattr(platformparts, 'post', lambda _root, path: posted.append(path) or 'posted')
    flags = ['--repo-url', 'https://f/o/r.git', '--collect', 'tests']
    assert platformparts.cluster(tmp_path, sha=SHA, hpc_args=flags, output=output, hpc=hpc) == 'posted'
    assert calls[0] == ['run', 'submit', '--sha', SHA, '--scope', 'full', '--repo', str(tmp_path), *flags]
    assert calls[1] == ['run', 'gather', '--sha', SHA, '-o', str(output), '--wait']
    assert posted == [output / f'run-{SHA}-linux-t0.json.gz'], 'a red run is still posted as a FAIL part'


def test_cluster_refuses_a_failed_submit_and_a_gather_without_a_record(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same verb with the run absent posts nothing."""
    seen: list[str] = []
    with pytest.raises(platformparts.PartRefusal, match='run submit'):
        platformparts.cluster(tmp_path, sha=SHA, hpc_args=[], output=tmp_path, hpc=lambda a: seen.append(a[1]) or 2)
    assert seen == ['submit'], 'nothing is gathered after a failed submit'
    with pytest.raises(platformparts.PartRefusal, match='no linux record'):
        platformparts.cluster(tmp_path, sha=SHA, hpc_args=[], output=tmp_path / 'none', hpc=lambda _a: 0)


def _status(platform: str, state: str = 'success', *, scope: str = 'full', hands: str = '-') -> Status:
    return Status(f'tests/{platform}', state, f'scope={scope} ran=2 hands={hands} nowhere=0', '')


def test_the_standing_is_the_one_reading_of_a_platform_result() -> None:
    """PASS only when nothing is missing; a FAIL part is FAIL whatever else; unsettled otherwise."""
    assert platformparts.standing([_status('linux')], head=SHA).result == 'PASS'
    assert platformparts.standing([], head=SHA).result == ''
    assert platformparts.standing([_status('linux', hands='windows:1')], head=SHA).result == ''
    both = [_status('linux', hands='windows:1'), _status('windows')]
    assert platformparts.standing(both, head=SHA).result == 'PASS'
    red = [_status('linux', 'failure'), _status('windows', 'pending')]
    assert platformparts.standing(red, head=SHA).result == 'FAIL'
    incremental = [_status('linux', scope='incremental')]
    assert platformparts.standing(incremental, head=SHA).result == 'PASS'
    full = platformparts.standing(incremental, head=SHA, scope='full')
    assert full.result == ''
    assert any('scope incremental' in problem for problem in full.problems)


def test_a_local_run_becomes_a_record_of_the_cluster_shape(tmp_path: Path, monkeypatch) -> None:
    """A windows verify keeps the ids assigned to windows and hands every other id off, not-covered."""
    monkeypatch.setattr(localpart, 'table_at', lambda _root, _sha: read_table(PYPROJECT))
    outcomes = {'t::a': 'passed', 't::f': 'failed', 't::m': 'skipped'}
    collected = {'femm': ['t::f'], 'femm or matlab': ['t::f', 't::m']}
    record = localpart.local_record(
        tmp_path,
        sha=SHA,
        platform='windows',
        scope='full',
        req='verify-x',
        outcomes=outcomes,
        reasons={'t::m': 'no matlab here', 't::a': 'not mine'},
        collect=collected.__getitem__,
    )
    assert record['outcomes'] == {'t::f': 'failed', 't::a': 'not-covered', 't::m': 'not-covered'}
    assert record['handed'] == {'t::a': ['linux', 'windows', 'macos'], 't::m': ['linux', 'windows']}
    assert record['reasons'] == {}
    part = platformparts.part_of(record)
    assert (part.platform, part.result, part.ran, part.hands) == ('windows', 'FAIL', 1, {'linux': 2})


def test_a_local_record_with_no_table_assigns_every_id_to_linux(tmp_path: Path, monkeypatch) -> None:
    """No table: every id runs everywhere, so the one rule assigns it to linux -- a windows run covers nothing."""
    monkeypatch.setattr(localpart, 'table_at', lambda _root, _sha: {})

    def local(platform: str) -> dict[str, object]:
        return localpart.local_record(
            tmp_path,
            sha=SHA,
            platform=platform,
            scope='incremental',
            req='r',
            outcomes={'t::a': 'passed', 't::s': 'skipped'},
            reasons={'t::s': 'why'},
            collect=lambda _expr: pytest.fail('no marker is declared, so nothing is collected'),
        )

    on_linux = local('linux')
    assert on_linux['outcomes'] == {'t::a': 'passed', 't::s': 'skipped'}
    assert on_linux['reasons'] == {'t::s': 'why'}
    assert platformparts.part_of(on_linux).hands == {}
    on_windows = local('windows')
    assert set(on_windows['outcomes'].values()) == {'not-covered'}
    with pytest.raises(platformparts.PartRefusal, match='covers no test'):
        platformparts.part_of(on_windows)
