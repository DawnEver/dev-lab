"""The seven shipped probes, and the distinctions each of them exists to make."""

from __future__ import annotations

import http.client
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from _box_fake import boxed_as_run

from dev_lab.supervise.alert import Transport
from dev_lab.supervise.component import CheckContext
from dev_lab.supervise.components import COMPONENTS, resources
from dev_lab.supervise.components.health import Heartbeat, HttpHealth, ShellProbe
from dev_lab.supervise.components.progress import ProgressTracker
from dev_lab.supervise.components.resources import RAM_CRITICAL, DiskUsage, LogScanner, _one_process
from dev_lab.supervise.process import SystemdProcessManager
from dev_lab.supervise.process.base import Ran
from dev_lab.supervise.transport import fetch_json
from dev_lab.supervise.verdict import Severity

_NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
_PROJECT = Path('/srv/target')


class _Reply:
    """A canned HTTP reply."""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body

    def read(self, amt: int | None = None) -> bytes:
        """Return the body."""
        return self._body.encode('utf-8')


class _Connection(http.client.HTTPConnection):
    """Answers with whatever it was built with.

    A real subclass so the transport it stands in for is satisfied by the type rather than by an
    annotation that says `Any`.
    """

    def __init__(self, status: int, body: str) -> None:
        super().__init__('fake.invalid', timeout=1)
        self._status = status
        self._body = body

    def request(self, method: str, url: str, headers: dict[str, str] | None = None) -> None:
        """Accept the request without inspecting it."""

    def getresponse(self) -> _Reply:
        """Return the canned reply."""
        return _Reply(self._status, self._body)

    def close(self) -> None:
        """Close, which for a fake is nothing."""


def _transport(status: int = 200, body: str = '{"status": "healthy"}') -> Transport:
    """Return a transport answering with one canned reply."""

    def make(_scheme: str, _host: str, _timeout: float) -> _Connection:
        return _Connection(status, body)

    return make


def _ctx(
    config: dict[str, Any] | None = None,
    *,
    state: dict[str, Any] | None = None,
    shared: dict[str, Any] | None = None,
    timeline: dict[str, Any] | None = None,
    ran: Ran | None = None,
    project: Path = _PROJECT,
) -> CheckContext:
    """Build a check context over a recording manager."""

    def run(argv: list[str], _timeout: int, _cwd: str | None) -> Ran:
        return boxed_as_run(argv, ran if ran is not None else Ran(code=0, out=''))

    return CheckContext(
        config=config or {},
        shared=shared or {},
        state=state if state is not None else {},
        project=project,
        manager=SystemdProcessManager(runner=run),
        timeline=timeline or {'now': _NOW.isoformat()},
    )


def test_the_roster_is_what_this_build_ships() -> None:
    """A roster, not a directory walk: what runs is what the file names."""
    assert [component.name for component in COMPONENTS] == [
        'http_health',
        'shell_probe',
        'heartbeat',
        'disk_usage',
        'process_monitor',
        'log_scanner',
        'progress_tracker',
        'deploy',
    ]


def test_a_healthy_endpoint_that_says_so_reports_nothing() -> None:
    """The ordinary case, and the expectation is what makes it more than a socket check."""
    probe = HttpHealth(transport=_transport())
    result = probe.check(
        _ctx({'endpoints': [{'name': 'api', 'url': 'http://x/health/', 'expect': {'status': 'healthy'}}]})
    )
    assert result.anomalies == []
    assert result.metrics['api_status'] == 200.0


def test_an_endpoint_that_answers_500_is_an_anomaly_even_with_a_json_body() -> None:
    """THE PREDECESSOR'S BLIND SPOT: it parsed the body and never looked at the status code."""
    probe = HttpHealth(transport=_transport(500, '{"error": "boom"}'))
    result = probe.check(_ctx({'endpoints': [{'name': 'api', 'url': 'http://x/health/'}]}))
    assert result.anomalies[0].kind == 'api_status'
    assert result.anomalies[0].severity is Severity.CRITICAL


def test_an_endpoint_whose_answer_says_the_wrong_thing_is_an_anomaly() -> None:
    """Reachable and degraded is not reachable and healthy."""
    probe = HttpHealth(transport=_transport(200, '{"status": "degraded"}'))
    result = probe.check(_ctx({'endpoints': [{'name': 'api', 'url': 'http://x/', 'expect': {'status': 'healthy'}}]}))
    assert result.anomalies[0].kind == 'api_unexpected'
    assert "'degraded'" in result.anomalies[0].message


def test_an_optional_endpoint_downgrades_to_a_warning() -> None:
    """A mirror being down is worth knowing and is not an outage."""
    probe = HttpHealth(transport=_transport(0, ''))
    result = probe.check(_ctx({'endpoints': [{'name': 'mirror', 'url': 'http://x/', 'optional': True}]}))
    assert result.anomalies[0].severity is Severity.WARNING


def test_a_probe_that_cannot_run_is_an_anomaly_not_a_healthy_value() -> None:
    """The failure that looks like success: no reading at all is not a good reading."""
    probe = ShellProbe()
    ctx = _ctx({'probes': [{'name': 'q', 'command': 'false'}]}, ran=Ran(code=1, err='not found'))
    assert probe.check(ctx).anomalies[0].kind == 'q_failed'


def test_two_probe_failures_that_exit_alike_are_not_the_same_condition() -> None:
    """THE EXIT CODE IS A CONTAINER, and -1 is the coarsest of them.

    A timeout, a command that could not be run at all and an OSError all carry it. The policy writes
    a condition off by signature, so a signature of `{name}:{code}` made the second failure inherit
    the first one's silence -- and `Ran.detail()`, which names the actual condition, was already
    computed for the message beside it.
    """
    probe = ShellProbe()

    def failed(err: str) -> str:
        ctx = _ctx({'probes': [{'name': 'q', 'command': 'x'}]}, ran=Ran(code=-1, err=err))
        return str(probe.check(ctx).anomalies[0].signature)

    timed_out = failed('timed out after 30')
    missing = failed('could not run x: No such file or directory')
    assert timed_out != missing, 'a timeout and a missing binary are not one condition'

    # The SAME failure re-reported: the timeout's number moved, and that is not a new condition.
    assert failed('timed out after 45') == timed_out, 'a re-measured timeout is the same condition'


def test_a_probe_that_says_to_ignore_errors_still_reads_its_output() -> None:
    """Some commands report through their exit code and some only through their output."""
    probe = ShellProbe()
    ctx = _ctx({'probes': [{'name': 'q', 'command': 'x', 'ignore_errors': True}]}, ran=Ran(code=1, out='7'))
    result = probe.check(ctx)
    assert result.anomalies == []
    assert result.metrics['q'] == 7.0


def test_a_value_past_its_threshold_is_an_anomaly_at_the_right_severity() -> None:
    """Warning and critical are different answers, and both are worth having."""
    probe = ShellProbe()
    ctx = _ctx({'probes': [{'name': 'q', 'command': 'x', 'warning': 5, 'critical': 50}]}, ran=Ran(code=0, out='9'))
    assert probe.check(ctx).anomalies[0].severity is Severity.WARNING


def test_a_stalled_value_is_an_anomaly_only_after_the_configured_rounds() -> None:
    """A value that has not moved is the signal; one that has not moved ONCE is a coincidence.

    ``stale_rounds = N`` means N rounds of observed non-movement, which takes N+1 sightings: the
    first has nothing to compare against.
    """
    probe = ShellProbe()
    config = {'probes': [{'name': 'q', 'command': 'x', 'check': 'delta', 'stale_rounds': 2}]}
    state: dict[str, Any] = {}
    for _round in range(2):
        assert probe.check(_ctx(config, state=state, ran=Ran(code=0, out='3'))).anomalies == []
    stalled = probe.check(_ctx(config, state=state, ran=Ran(code=0, out='3')))
    assert stalled.anomalies[0].kind == 'q_stale'


def test_a_value_that_moved_is_not_stalled_however_long_it_ran() -> None:
    """A slow job that is still reporting progress is not a stuck one."""
    probe = ShellProbe()
    state: dict[str, Any] = {'q_last': 3.0, 'q_unchanged': 9}
    ctx = _ctx({'probes': [{'name': 'q', 'command': 'x', 'check': 'delta'}]}, state=state, ran=Ran(code=0, out='4'))
    assert probe.check(ctx).anomalies == []


def test_a_fresh_heartbeat_reports_nothing() -> None:
    """The supervisor cycled recently, which is all this probe has an opinion about."""
    ctx = _ctx(
        {'max_age': 900}, timeline={'now': _NOW.isoformat(), 'last_cycle': (_NOW - timedelta(minutes=1)).isoformat()}
    )
    assert Heartbeat().check(ctx).anomalies == []


def test_a_supervisor_that_stopped_cycling_is_reported() -> None:
    """Silence from a supervisor and a quiet target must not read the same."""
    ctx = _ctx(
        {'max_age': 60}, timeline={'now': _NOW.isoformat(), 'last_cycle': (_NOW - timedelta(hours=2)).isoformat()}
    )
    result = Heartbeat().check(ctx)
    assert result.anomalies[0].kind == 'supervisor_stale'
    assert result.anomalies[0].severity is Severity.WARNING


def test_a_heartbeat_that_cannot_measure_says_so() -> None:
    """THE REGRESSION. A watchdog that cannot see the clock is not a watchdog with nothing to say.

    This is the one component whose job is noticing that the supervisor stopped, and it answered
    "no cycle recorded" with silence -- which is exactly what it says when the supervisor is
    perfectly healthy. Every other probe here treats unmeasurable as an anomaly: an endpoint that
    answers nothing is CRITICAL, an unreadable disk is `disk_check_failed`, a process table without
    psutil says so. The state carries no `last_cycle` on a first run AND whenever `StateStore.read`
    discards a file it could not use, and that second case is the one that matters.

    A WARNING rather than a page, so a fresh install reports it once and it clears by itself.
    """
    result = Heartbeat().check(_ctx({'max_age': 60}, timeline={'now': _NOW.isoformat()}))
    assert [one.kind for one in result.anomalies] == ['heartbeat_unmeasurable']
    assert result.anomalies[0].severity is Severity.WARNING


def test_disk_usage_measures_and_convicts_on_the_ceiling() -> None:
    """The reading is recorded either way, so a report can show it climbing before it convicts."""
    probe = DiskUsage()
    lenient = probe.check(_ctx({'paths': [{'path': '/', 'name': 'root', 'critical': 100}]}))
    assert lenient.anomalies == []
    assert 'root_percent' in lenient.metrics
    strict = probe.check(_ctx({'paths': [{'path': '/', 'name': 'root', 'warning': 0}]}))
    assert strict.anomalies[0].kind == 'root_warning'


def test_a_missing_process_is_an_anomaly() -> None:
    """The first thing anyone wants a supervisor to notice."""
    found = {'python -m webapp': (1, 120.0)}
    assert _one_process({'name': 'webapp', 'match': 'webapp'}, found) == []
    missing = _one_process({'name': 'webapp', 'match': 'webapp'}, {})
    assert missing[0].kind == 'webapp_missing'


def test_a_process_past_its_memory_ceiling_is_an_anomaly() -> None:
    """The number that matters on a box where memory is the constraint."""
    found = {'python -m webapp': (1, 700.0)}
    large = _one_process({'name': 'webapp', 'match': 'webapp', 'max_rss_mb': 400}, found)
    assert large[0].kind == 'webapp_large'
    assert '700MB' in large[0].message


def test_the_system_ceiling_is_a_named_number() -> None:
    """A bare 95 in a comparison is a number; a ceiling someone can find is a policy."""
    assert RAM_CRITICAL == 95


def test_a_log_scan_finds_errors_and_says_which_file(tmp_path: Path) -> None:
    """A count with no file named sends a reader looking through all of them."""
    logs = tmp_path / 'logs'
    logs.mkdir()
    (logs / 'run.log').write_text('all good\nERROR: it broke\n', encoding='utf-8')
    result = LogScanner().check(_ctx({'log_dir': str(logs)}, project=tmp_path))
    assert result.anomalies[0].kind == 'errors_in_log'
    assert result.data['hits'][0]['file'] == 'run.log'


def test_a_new_error_in_a_log_that_already_had_one_is_a_new_condition(tmp_path: Path) -> None:
    """THE CONTAINER IS NOT THE CONDITION, and the write-off is why the difference is load-bearing.

    The signature used to be the set of file NAMES, so a fresh failure landing in a log that already
    held an old one carried that old one's signature. The policy counts cycles per signature and
    writes a condition off once the count passes its threshold -- so the new failure was absorbed
    into the old one's silence, which is the one outcome a scanner watching for an unhandled
    exception must not have.
    """
    logs = tmp_path / 'logs'
    logs.mkdir()
    log = logs / 'run.log'
    log.write_text('10/03/2026 19:58:20 ERROR Failed to open file /a/b.toml! [Errno 2]\n', encoding='utf-8')
    first = LogScanner().check(_ctx({'log_dir': str(logs)}, project=tmp_path)).anomalies[0]

    # The SAME failure written again later: the date, the clock and the errno all moved.
    log.write_text('10/04/2026 02:14:02 ERROR Failed to open file /a/b.toml! [Errno 2]\n', encoding='utf-8')
    again = LogScanner().check(_ctx({'log_dir': str(logs)}, project=tmp_path)).anomalies[0]
    assert again.signature == first.signature, 'a re-dated line is the same condition, not a new one'

    # A DIFFERENT failure in the SAME file, which is the case that used to go silent.
    log.write_text('10/04/2026 02:14:02 ERROR Failed to open file /c/d.toml! [Errno 2]\n', encoding='utf-8')
    other = LogScanner().check(_ctx({'log_dir': str(logs)}, project=tmp_path)).anomalies[0]
    assert other.signature != first.signature, 'a new failure must not inherit the old one signature'


def test_a_clean_log_reports_nothing_and_says_it_looked(tmp_path: Path) -> None:
    """`CLEAN` and `NO_LOG_DIR` are different facts, and only one of them is reassuring."""
    logs = tmp_path / 'logs'
    logs.mkdir()
    (logs / 'run.log').write_text('all good\n', encoding='utf-8')
    result = LogScanner().check(_ctx({'log_dir': str(logs)}, project=tmp_path))
    assert result.anomalies == []
    assert result.data['status'] == 'CLEAN'


def test_a_missing_log_directory_is_not_an_error(tmp_path: Path) -> None:
    """Nothing to read yet is the ordinary state of a fresh install."""
    result = LogScanner().check(_ctx({'log_dir': str(tmp_path / 'absent')}, project=tmp_path))
    assert result.anomalies == []
    assert result.data['status'] == 'NO_LOG_DIR'


def test_a_finished_job_is_a_completion_and_not_an_anomaly(tmp_path: Path) -> None:
    """THE PREDECESSOR'S SCAR: modelling completion as a warning made every success read degraded."""
    progress = tmp_path / 'progress.json'
    progress.write_text(json.dumps({'ops': 10, 'total_ops': 10}), encoding='utf-8')
    result = ProgressTracker().check(_ctx({'progress_file': str(progress), 'count_path': 'ops'}, project=tmp_path))
    assert result.anomalies == []
    assert len(result.completions) == 1
    assert result.data['status'] == 'COMPLETE'


def test_a_stalled_job_is_an_anomaly(tmp_path: Path) -> None:
    """The other half: a job that has stopped moving is exactly what this is for."""
    progress = tmp_path / 'progress.json'
    progress.write_text(json.dumps({'ops': 3, 'total_ops': 10}), encoding='utf-8')
    config = {'progress_file': str(progress), 'count_path': 'ops', 'stale_rounds': 2}
    state: dict[str, Any] = {}
    for _round in range(2):
        assert ProgressTracker().check(_ctx(config, state=state, project=tmp_path)).anomalies == []
    result = ProgressTracker().check(_ctx(config, state=state, project=tmp_path))
    assert result.anomalies[0].kind == 'stalled'


def test_a_job_with_no_progress_file_claims_no_percentage(tmp_path: Path) -> None:
    """NO READING IS NOT NO PROGRESS, and this test used to assert the opposite of its own name.

    The docstring said the right thing and the assertions recorded `ops_done = 0.0` with no
    anomaly, which is a percentage of nothing presented as a reading. A progress file that vanished
    or became unreadable -- the job died, a cleanup removed it, permissions changed -- turned the
    one component that would have noticed the job stopped into a silent no-op.
    """
    result = ProgressTracker().check(_ctx({'progress_file': str(tmp_path / 'absent.json')}, project=tmp_path))
    assert [one.kind for one in result.anomalies] == ['progress_unreadable']
    assert 'ops_done' not in result.metrics, 'a count of nothing was reported as a count'


def test_a_fetch_reports_an_unreachable_endpoint_without_raising() -> None:
    """An endpoint being down is the ordinary case this module exists to report."""

    def refuse(_scheme: str, _host: str, _timeout: float) -> _Connection:
        msg = 'connection refused'
        raise OSError(msg)

    status, body, detail = fetch_json(refuse, 'https://x/health/', 5)
    assert (status, body) == (0, None)
    assert 'connection refused' in detail


def test_a_log_that_cannot_be_read_is_not_a_clean_log(tmp_path: Path) -> None:
    """THE REGRESSION. An unreadable file contributed zero lines and was still counted as scanned.

    `_tail` answered `[]` both for "this file is empty" and for "this file could not be read", so a
    log the scanner could not open -- permissions, an I/O error, or a DIRECTORY matching the glob --
    made the scan report CLEAN. That is the one answer a scanner must never invent, and it is the
    same conflation as `_remote`'s None: two different facts sharing one return value.
    """
    logs = tmp_path / 'logs'
    (logs / 'a.log').mkdir(parents=True)  # a DIRECTORY that matches the glob
    result = LogScanner().check(_ctx({'log_dir': str(logs), 'glob': '*.log'}))
    assert [one.kind for one in result.anomalies] == ['logs_unreadable']
    assert result.metrics['files_scanned'] == 0.0, 'an unreadable file was counted as read'


def test_a_filesystem_reporting_no_size_is_not_an_empty_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """`used / total` with a zero total is unanswerable, not 0% -- and 0% never convicts."""
    report = SimpleNamespace(total=0, used=0, free=0)
    monkeypatch.setattr(resources.shutil, 'disk_usage', lambda _path: report)
    result = DiskUsage().check(_ctx({'paths': [{'path': '/', 'name': 'x'}]}))
    assert 'disk_unmeasurable' in [one.kind for one in result.anomalies]
    assert 'x_percent' not in result.metrics, 'a size nobody could read was reported as zero'
