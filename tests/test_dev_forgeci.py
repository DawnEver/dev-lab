"""``forge ci logs|artifact``: a CI run's job logs and artifacts, READ through the forge door and bounded on screen.

The forge is a duck-typed client answering from tables (no network): the evidence is what it was ASKED and what the
door printed and wrote. Every path the client is asked is GitHub's (``/repos/o/r/actions/...``).
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from _forge_fake import make_repo

from dev_lab.dev import forgeci
from dev_lab.dev.datedlog import FAMILY_KINDS
from dev_lab.dev.forge import Forge, NoCredential
from dev_lab.dev.forgecli import NOUNS
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgestatus import CI_LOGS_DOOR, status_show
from dev_lab.dev.forgework import GITHUB, Client
from dev_lab.dev.netverb import Attempt, Diagnosis, Report

SHA = 'c' * 40
HEAD = 'd' * 40
REPO = '/repos/o/r'
_PAGING = re.compile(r'[?&]per_page=\d+&page=(?P<page>\d+)$')
_LOG = '\n'.join([
    '2026-11-26T10:00:00.0000000Z ##[group]Run produce',
    *(f'2026-11-26T10:00:01.0000000Z line {n}' for n in range(1, 61)),
    '2026-11-26T10:00:02.0000000Z \x1b[31mFAILED tests/test_x.py::test_y - assert 1 == 2\x1b[0m',
    '2026-11-26T10:00:03.0000000Z ##[error]Process completed with exit code 1.',
    '2026-11-26T10:00:04.0000000Z Post job cleanup.',
    '2026-11-26T10:00:05.0000000Z Cleaning up orphan processes',
])  # fmt: skip


def _refused(path: str, status: int) -> ForgeCallFailed:
    attempt = Attempt(1, status, f'HTTP {status}', Diagnosis.FORGE_REFUSED)
    return ForgeCallFailed(Report(('GET', path), (attempt,), 1))


class _Forge:
    """GitHub's Actions API as tables: each listing by its path (paging cut off), each download by its path."""

    backend = GITHUB
    repo = REPO
    forge = Forge('github.com', 'o', 'r')

    def __init__(
        self, listings: dict[str, Any], files: dict[str, bytes], *, heads: dict[int, str] | None = None
    ) -> None:
        self.listings = listings
        self.files = files
        self.heads = heads or {}
        self.asked: list[str] = []

    def call(self, method: str, path: str) -> object:
        assert method == 'GET', 'the CI door only reads'
        self.asked.append(path)
        paged = _PAGING.search(path)
        base = path[: paged.start()] if paged else path
        if base not in self.listings:
            raise _refused(path, 404)
        answer = self.listings[base]
        return answer(int(paged['page'])) if callable(answer) and paged else answer

    def download(self, path: str) -> bytes:
        self.asked.append(path)
        if path not in self.files:
            raise _refused(path, 404)
        return self.files[path]

    def pr_view(self, number: int) -> SimpleNamespace:
        self.asked.append(f'pulls/{number}')
        return SimpleNamespace(head_sha=self.heads[number])


def _as_client(fake: object) -> Client:
    """*fake* where a door takes a forge client: it answers the calls the door makes."""
    return cast('Client', fake)


def _run(run: int, sha: str = SHA) -> dict[str, Any]:
    return {'id': run, 'name': 'ci', 'head_sha': sha}


def _job(job: int, name: str, conclusion: str | None) -> dict[str, Any]:
    status = 'completed' if conclusion else 'in_progress'
    return {'id': job, 'name': name, 'status': status, 'conclusion': conclusion, 'html_url': f'https://gh/j/{job}'}


def _listed(key: str, *items: dict[str, Any]) -> dict[str, Any]:
    return {key: list(items), 'total_count': len(items)}


def _forge(sha: str = SHA, files: dict[str, bytes] | None = None) -> _Forge:
    """Run 7 at *sha*: ``tests/base`` failed, ``tests/base@windows`` timed out, ``parts`` succeeded; one artifact."""
    listings = {
        f'{REPO}/actions/runs?head_sha={sha}': _listed('workflow_runs', _run(7, sha), _run(8, 'e' * 40)),
        f'{REPO}/actions/runs/7': _run(7, sha),
        f'{REPO}/actions/runs/7/jobs': _listed(
            'jobs',
            _job(70, 'parts', 'success'),
            _job(71, 'tests/base', 'failure'),
            _job(72, 'tests/base@windows', 'timed_out'),
            _job(73, 'tests/gpu', None),
        ),
        f'{REPO}/actions/runs/7/artifacts': _listed(
            'artifacts',
            {'id': 90, 'name': 'verify-log-base-1', 'size_in_bytes': 4096, 'expired': False},
            {'id': 91, 'name': 'verify-log-old-1', 'size_in_bytes': 10, 'expired': True},
        ),
    }
    logs = {f'{REPO}/actions/jobs/{job}/logs': _LOG.encode() for job in (70, 71, 72)}
    return _Forge(listings, logs | {f'{REPO}/{path}': data for path, data in (files or {}).items()}, heads={60: sha})


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = make_repo(tmp_path, 'https://github.com/o/r.git')
    (root / 'pyproject.toml').write_text('[tool.dev_lab.parts]\noutput = "output/logs"\n', encoding='utf-8')
    monkeypatch.chdir(root)
    return root


def _main(client: object, monkeypatch: pytest.MonkeyPatch, root: Path, *argv: str) -> int:
    monkeypatch.setattr(forgeci, 'client_for', lambda *_a, **_k: client)
    return forgeci.main(list(argv), cwd=root)


def _printed(capsys: pytest.CaptureFixture[str]) -> tuple[str, str]:
    said = capsys.readouterr()
    return said.out, said.err


def test_the_forge_door_routes_ci_to_this_module() -> None:
    assert NOUNS['ci'] is forgeci.main


def test_a_pull_request_resolves_to_its_head_and_only_runs_of_that_head_are_read(checkout: Path) -> None:
    """``pr:60`` is its head sha; a forge that ignores ``head_sha`` answers run 8 too, and it is dropped."""
    client = _forge(HEAD)
    runs = forgeci.runs_of(_as_client(client), checkout, 'pr:60')
    assert [run.id for run in runs] == [7]
    assert client.asked[:2] == ['pulls/60', f'{REPO}/actions/runs?head_sha={HEAD}&per_page=100&page=1']


def test_a_run_id_reads_that_run_alone(checkout: Path) -> None:
    assert forgeci.runs_of(_as_client(_forge()), checkout, 'run:7') == (forgeci.Run(7, 'ci', SHA),)


def test_a_bare_number_is_refused_naming_both_spellings(checkout: Path) -> None:
    with pytest.raises(ValueError, match=r'pr:60 for a pull request or run:60 for an Actions run'):
        forgeci.runs_of(_as_client(_forge()), checkout, '60')


def test_a_listing_is_paged_to_its_total_count() -> None:
    """A forge serving one job per page (Gitea clamps its limit) is read on until ``total_count``."""
    pages = {1: _listed('jobs', _job(1, 'a', 'success')), 2: _listed('jobs', _job(2, 'b', 'failure'))}
    for page in pages.values():
        page['total_count'] = 2
    client = _Forge({f'{REPO}/actions/runs/7/jobs': pages.__getitem__}, {})
    jobs = forgeci.jobs_of(_as_client(client), [forgeci.Run(7, 'ci', SHA)])
    assert [job.name for job in jobs] == ['a', 'b']


def test_failed_picks_every_job_that_concluded_failed_and_no_other(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = _forge()
    assert _main(client, monkeypatch, checkout, 'logs', SHA, '--failed') == 0
    read = [path for path in client.asked if path.endswith('/logs')]
    assert read == [f'{REPO}/actions/jobs/71/logs', f'{REPO}/actions/jobs/72/logs']
    out, _ = _printed(capsys)
    assert '  failure    tests/base  (run 7 ci)  https://gh/j/71' in out
    assert '  in_progress tests/gpu' in out  # an unconcluded job is listed by its status


def test_a_log_is_printed_bounded_and_written_whole(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The screen shows the last --tail lines up to the failed step, stamps and colors dropped; the file holds all."""
    assert _main(_forge(), monkeypatch, checkout, 'logs', SHA, '--job', 'tests/base', '--tail', '2') == 0
    out, _ = _printed(capsys)
    written = list((checkout / 'output' / 'logs').rglob(f'{SHA[:12]}-tests_base-71.log'))
    assert len(written) == 1
    assert written[0].parent.name == forgeci.KIND
    assert written[0].read_text(encoding='utf-8') == _LOG
    said = '65 lines; the last 2 up to its first ##[error] (line 63)'
    shown = out.split(f'--- tests/base (failure): {written[0]} ({said})\n')[1].splitlines()
    assert shown == ['FAILED tests/test_x.py::test_y - assert 1 == 2', '##[error]Process completed with exit code 1.']


def test_the_excerpt_ends_at_the_failed_step_not_in_the_post_job_cleanup() -> None:
    """PLANTED: two cleanup lines follow the error; ``--until end`` is the plain tail that shows only them."""
    assert forgeci.excerpt(_LOG, tail=2, grep=None, until='end') == (
        ['Post job cleanup.', 'Cleaning up orphan processes'],
        '65 lines; the last 2 up to its last line',
    )
    unmarked = '\n'.join(_LOG.splitlines()[:5])
    assert forgeci.excerpt(unmarked, tail=1, grep=None, until='error') == (
        ['line 4'],
        '5 lines; the last 1 up to its last line',
    )


def test_a_running_job_is_named_not_fetched_and_a_failed_download_prints_no_url(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A running job's log is not published yet; a download's URL (a redirect's is signed) never reaches the screen."""
    client = _forge()
    del client.files[f'{REPO}/actions/jobs/71/logs']
    assert _main(client, monkeypatch, checkout, 'logs', SHA, '--job', 'tests/gpu', '--job', 'tests/base') == 1
    out, _ = _printed(capsys)
    assert f'{REPO}/actions/jobs/73/logs' not in client.asked
    assert '--- tests/gpu (in_progress): its log is published once it concludes; read it again then' in out
    assert '--- tests/base: its log could not be read (HTTP 404)' in out
    assert '/actions/jobs/71/logs' not in out


def test_grep_keeps_the_matching_lines_before_the_tail() -> None:
    lines, said = forgeci.excerpt(_LOG, tail=5, grep=re.compile(r'FAILED|error|cleanup'), until='error')
    assert lines == ['FAILED tests/test_x.py::test_y - assert 1 == 2', '##[error]Process completed with exit code 1.']
    assert said == "65 lines; the last 2 matching 'FAILED|error|cleanup' up to its first ##[error] (line 63)"
    assert forgeci.excerpt(_LOG, tail=0, grep=None, until='end') == ([], '65 lines; the last 0 up to its last line')


def test_a_job_glob_selects_by_name_and_one_matching_nothing_is_refused_naming_the_jobs(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = _forge()
    assert _main(client, monkeypatch, checkout, 'logs', SHA, '--job', 'tests/base*', '--tail', '0') == 0
    assert [p for p in client.asked if p.endswith('/logs')] == [f'{REPO}/actions/jobs/{j}/logs' for j in (71, 72)]
    capsys.readouterr()
    assert _main(_forge(), monkeypatch, checkout, 'logs', SHA, '--job', 'tests/nope') == 2
    _, err = _printed(capsys)
    assert 'no job matches tests/nope; the jobs here: parts, tests/base, tests/base@windows, tests/gpu' in err


def test_no_selection_lists_jobs_and_artifacts_and_says_how_to_select(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = _forge()
    assert _main(client, monkeypatch, checkout, 'logs', 'pr:60') == 0
    out, _ = _printed(capsys)
    assert not [path for path in client.asked if path.endswith('/logs')]
    assert '[ci] artifacts: verify-log-base-1 (4 KiB)' in out
    assert '--failed, or --job <name|glob>' in out
    assert 'forge ci artifact pr:60 --name <name|glob>' in out
    assert not (checkout / 'output').exists()  # nothing selected, nothing written


def test_an_artifact_is_unpacked_under_output_and_its_logs_tailed(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The verify log a part's job uploaded holds the real failure; its zip is unpacked, its ``.log`` tailed."""
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, 'w') as archive:
        archive.writestr('output/verify/verify-base.log', 'collected 9\nE   assert 1 == 2\n1 failed, 8 passed\n')
        archive.writestr('output/verify/verify-base.outcomes/a.json', '{}')
        archive.writestr('../escape.log', 'a member naming a parent directory lands inside')
    client = _forge(files={'actions/artifacts/90/zip': packed.getvalue()})
    assert _main(client, monkeypatch, checkout, 'artifact', SHA, '--name', 'verify-log-*', '--tail', '2') == 1
    out, _ = _printed(capsys)
    where = next((checkout / 'output' / 'logs').rglob(f'{SHA[:12]}-verify-log-base-1-90'))
    assert (where / 'output' / 'verify' / 'verify-base.log').is_file()
    assert (where / 'escape.log').is_file()  # zipfile drops the `..`: the member lands inside
    assert not (where.parent / 'escape.log').exists()
    assert 'E   assert 1 == 2\n1 failed, 8 passed' in out
    assert f'--- verify-log-base-1: 3 file(s) under {where}, 2 log(s) shown' in out
    assert '--- verify-log-old-1: expired, the forge no longer holds it' in out  # matched, but gone: exit 1


def test_out_outside_the_output_directory_is_refused(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _main(_forge(), monkeypatch, checkout, 'logs', SHA, '--failed', '--out', 'src') == 2
    _, err = _printed(capsys)
    assert "--out src is outside this checkout's output directory" in err
    assert _main(_forge(), monkeypatch, checkout, 'logs', SHA, '--failed', '--out', 'output/logs/mine') == 0
    assert list((checkout / 'output' / 'logs' / 'mine').glob('*.log'))


def test_no_credential_is_refused_naming_auth_login(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def none(*_a: object, **_k: object) -> object:
        msg = 'git holds no credential for github.com'
        raise NoCredential(msg)

    monkeypatch.setattr(forgeci, 'client_for', none)
    assert forgeci.main(['logs', SHA, '--failed'], cwd=checkout) == 2
    _, err = _printed(capsys)
    assert 'no forge credential is stored' in err
    assert '-m dev_lab.dev.forge auth login --host github.com' in err


def test_a_refused_read_names_the_actions_permission_and_auth_login(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = _forge()
    monkeypatch.setattr(client, 'call', lambda _m, path: (_ for _ in ()).throw(_refused(path, 403)))
    assert _main(client, monkeypatch, checkout, 'logs', SHA, '--failed') == 1
    _, err = _printed(capsys)
    assert 'needs a token that may read Actions' in err
    assert 'auth login --host github.com' in err


def test_a_commit_with_no_run_is_refused_naming_the_serve_door(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = _Forge({f'{REPO}/actions/runs?head_sha={SHA}': _listed('workflow_runs')}, {})
    assert _main(client, monkeypatch, checkout, 'logs', SHA) == 2
    _, err = _printed(capsys)
    assert f'{SHA} has no Actions run on github.com' in err


def test_status_show_names_the_ci_door_for_a_red_part_a_ci_job_produced() -> None:
    """The wall an agent met: a red part whose target is a job page. It now names the door, and the door parses."""
    target = 'https://github.com/o/r/actions/runs/7/job/71'
    statuses = [{'context': 'tests/base', 'state': 'error', 'description': 'producer exited 1', 'target_url': target}]
    client = SimpleNamespace(backend=GITHUB, repo=REPO, call=lambda *_a, **_k: statuses)
    lines = status_show(_as_client(client), SHA)
    door = CI_LOGS_DOOR.format(sha=SHA)
    assert f'  its job log (a CI job produced it): {door}' in lines
    argv = door.split(' -m dev_lab.dev.forge ', 1)[1].split()
    assert argv[0] == 'ci'
    assert forgeci._parser().parse_args(argv[1:]).failed


def test_the_kind_it_writes_is_a_family_kind_every_repo_admits() -> None:
    """Its logs land in every family repo, so DECLARED-LAYOUT admits them without a repo row."""
    assert forgeci.KIND in FAMILY_KINDS
