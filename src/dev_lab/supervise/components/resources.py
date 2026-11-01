"""Is the box running out of anything: disk, memory, or room in a log before anyone reads it.

These report; none of them acts. A disk filling up has no remedy this kit can honestly apply on its
own -- deleting somebody's files to make a number go down is not a repair -- so a target that wants
one declares a chain in its own config, where the choice is visible.

``psutil`` IS IMPORTED LAZILY. It is an optional extra, not a tier-1 dependency, and a target that
wants only the HTTP probes must not need it installed to import this module. Its absence is
reported as an anomaly rather than raised, because a monitor that cannot measure is a fact about
the deployment worth knowing.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from dev_lab.supervise.component import CheckContext, Component
from dev_lab.supervise.pressure import RAM_CRITICAL
from dev_lab.supervise.verdict import Anomaly, CheckResult, Severity, condition_digest

__all__ = ['RAM_CRITICAL', 'DiskUsage', 'LogScanner', 'ProcessMonitor', 'psutil_module']

#: How much of a matched log line is kept. A line long enough to be interesting is usually JSON,
#: and the first two hundred characters of it name the failure.
LINE_KEPT: Final = 200

#: The default patterns a log scan convicts on. Deliberately few and blunt: a scanner tuned to
#: somebody's log format is a scanner that stops matching the day the format changes.
ERROR_PATTERNS: Final = ('FAIL', 'ERROR', 'Traceback')


class DiskUsage(Component):
    """Check filesystem usage against thresholds.

    Config::

        [components.disk_usage]
        enabled = true
        [[components.disk_usage.paths]]
        path = "/"
        name = "root"
        warning = 85
        critical = 95

    """

    name = 'disk_usage'
    description = 'Check filesystem usage against thresholds'

    def check(self, ctx: CheckContext) -> CheckResult:
        """Measure every configured path.

        Args:
            ctx: the component's config.

        Returns:
            Usage percentages, and an anomaly per path past a threshold.

        """
        result = CheckResult()
        paths = ctx.config.get('paths') or [{'path': '/', 'name': 'root'}]
        for entry in paths:
            name = str(entry.get('name', 'disk'))
            try:
                usage = shutil.disk_usage(str(entry.get('path', '/')))
            except OSError as exc:
                result.anomalies.append(
                    Anomaly(
                        kind='disk_check_failed',
                        severity=Severity.WARNING,
                        message=f'{name} could not be measured: {exc}',
                        signature=f'{name}:unmeasurable',
                    )
                )
                continue
            if not usage.total:
                # A FILESYSTEM THAT REPORTS NO SIZE IS NOT AN EMPTY ONE. `used / total` with a zero
                # total is not 0% full, it is unanswerable -- and answering it 0.0 is the reading
                # that never convicts. The same distinction this loop already draws for an OSError
                # a few lines up; zero is simply the other way a total can fail to be a number.
                result.anomalies.append(
                    Anomaly(
                        kind='disk_unmeasurable',
                        severity=Severity.WARNING,
                        message=f'{name} reports no size, so how full it is cannot be said',
                        signature=f'{name}:no-size',
                    )
                )
                continue
            percent = usage.used / usage.total * 100
            result.metrics[f'{name}_percent'] = round(percent, 1)
            result.metrics[f'{name}_free_gb'] = round(usage.free / 1024**3, 2)
            for label, severity in (('critical', Severity.CRITICAL), ('warning', Severity.WARNING)):
                limit = entry.get(label)
                if limit is not None and percent > float(limit):
                    result.anomalies.append(
                        Anomaly(
                            kind=f'{name}_{label}',
                            severity=severity,
                            message=f'{name} is {percent:.1f}% full, past its {label} of {limit}%',
                            value=round(percent, 1),
                            threshold=float(limit),
                            signature=f'{name}:{label}',
                        )
                    )
                    break
        return result


class ProcessMonitor(Component):
    """Watch processes by name: are they there, and how much are they using.

    Config::

        [components.process_monitor]
        enabled = true
        track_system = true
        [[components.process_monitor.processes]]
        name = "webapp"
        match = "webapp"
        min_count = 1
        max_rss_mb = 400

    """

    name = 'process_monitor'
    description = 'Watch processes by name -- presence, resident size, and the box they are on'

    def check(self, ctx: CheckContext) -> CheckResult:
        """Look for every configured process, and optionally at the box.

        Args:
            ctx: the component's config and its own state slice.

        Returns:
            Counts and sizes, and an anomaly per process missing or too large.

        """
        result = CheckResult()
        psutil = psutil_module()
        if psutil is None:
            result.anomalies.append(
                Anomaly(
                    kind='no_psutil',
                    severity=Severity.WARNING,
                    message='psutil is not installed, so no process is being watched',
                    signature='no_psutil',
                )
            )
            return result
        found = _running(psutil)
        for wanted in ctx.config.get('processes', []):
            result.anomalies.extend(_one_process(wanted, found))
        return result if not ctx.config.get('track_system') else _with_system(psutil, result)


def psutil_module() -> ModuleType | None:
    """The ``psutil`` module, or ``None`` where the optional extra is not installed -- the one lazy import."""
    try:
        import psutil  # noqa: PLC0415
    except ImportError:
        return None
    return psutil


def _running(psutil: ModuleType) -> dict[str, tuple[int, float]]:
    """Sample every process once, keyed by the command line it was started with.

    One pass rather than one per configured process: a supervisor that walks the process table once
    per entry is competing with the box it is watching.

    Args:
        psutil: the module, injected so this function is testable without it.

    Returns:
        Command line to (count, total resident megabytes).

    """
    found: dict[str, tuple[int, float]] = {}
    for process in psutil.process_iter(['cmdline', 'memory_info']):
        sample = _sample(process)
        if sample is None:
            continue
        line, megabytes = sample
        count, total = found.get(line, (0, 0.0))
        found[line] = (count + 1, total + megabytes)
    return found


def _sample(process: object) -> tuple[str, float] | None:
    """Read one process's command line and resident size.

    A process that exits between the table being read and this call is ordinary rather than
    exceptional -- the box is running -- so it is skipped rather than reported. Returning None
    rather than `continue`-ing inside the except keeps the loop's shape honest about that.

    Args:
        process: a psutil process handle.

    Returns:
        The command line and its resident megabytes, or None when the process has gone.

    """
    try:
        info = process.info
        memory = info.get('memory_info')
        return ' '.join(info.get('cmdline') or []), (memory.rss if memory else 0) / 1024**2
    except Exception:  # noqa: BLE001
        return None


def _one_process(wanted: dict[str, Any], found: dict[str, tuple[int, float]]) -> list[Anomaly]:
    """Judge one configured process against what was sampled.

    Args:
        wanted: the process's table.
        found: what the sample found, keyed by command line.

    Returns:
        The anomalies this process produced.

    """
    name = str(wanted.get('name', 'process'))
    match = str(wanted.get('match', name))
    count = 0
    resident = 0.0
    for line, (seen, megabytes) in found.items():
        if match in line:
            count += seen
            resident += megabytes
    anomalies: list[Anomaly] = []
    if count < int(wanted.get('min_count', 1)):
        anomalies.append(
            Anomaly(
                kind=f'{name}_missing',
                severity=Severity.CRITICAL,
                message=f'{name} is not running: {count} matched {match!r}',
                value=float(count),
                signature=f'{name}:missing',
            )
        )
    limit = wanted.get('max_rss_mb')
    if limit is not None and resident > float(limit):
        anomalies.append(
            Anomaly(
                kind=f'{name}_large',
                severity=Severity.CRITICAL,
                message=f'{name} is using {resident:.0f}MB, past its {limit}MB ceiling',
                value=round(resident, 1),
                threshold=float(limit),
                signature=f'{name}:large',
            )
        )
    return anomalies


def _with_system(psutil: ModuleType, result: CheckResult) -> CheckResult:
    """Add the box's own memory reading to a result.

    Args:
        psutil: the module.
        result: the result to extend.

    Returns:
        The same result.

    """
    memory = psutil.virtual_memory()
    result.metrics['system_ram_percent'] = round(memory.percent, 1)
    result.metrics['system_ram_available_mb'] = round(memory.available / 1024**2, 1)
    if memory.percent > RAM_CRITICAL:
        result.anomalies.append(
            Anomaly(
                kind='system_ram_critical',
                severity=Severity.CRITICAL,
                message=f'the box is {memory.percent:.0f}% full',
                value=round(memory.percent, 1),
                signature='system:ram',
            )
        )
    return result


class LogScanner(Component):
    """Read the newest files in a directory and convict on the patterns in their tails.

    Config::

        [components.log_scanner]
        enabled = true
        log_dir = "output/logs"
        glob = "*.log"
        tail_lines = 5
        error_patterns = ["FAIL", "ERROR", "Traceback"]

    """

    name = 'log_scanner'
    description = 'Read the newest logs and convict on the patterns in their tails'

    def check(self, ctx: CheckContext) -> CheckResult:
        """Scan the newest logs under the configured directory.

        Args:
            ctx: the component's config and the target directory.

        Returns:
            How many files were read and what was found in them.

        """
        result = CheckResult()
        directory = Path(str(ctx.config.get('log_dir', 'output/logs')))
        if not directory.is_absolute():
            directory = ctx.project / directory
        if not directory.is_dir():
            result.data['status'] = 'NO_LOG_DIR'
            return result
        patterns = tuple(ctx.config.get('error_patterns') or ERROR_PATTERNS)
        newest = sorted(directory.rglob(str(ctx.config.get('glob', '*.log'))), key=_modified, reverse=True)
        kept = newest[: int(ctx.config.get('max_files', 10))]
        tail = int(ctx.config.get('tail_lines', 5))
        hits: list[dict[str, str]] = []
        unreadable: list[str] = []
        for path in kept:
            lines_read = _tail(path, tail)
            if lines_read is None:
                # A FILE THAT COULD NOT BE READ IS NOT A FILE WITH NOTHING IN IT. It used to
                # contribute zero lines and still be counted in `files_scanned`, so a log the
                # scanner could not open -- permissions, an I/O error, or a DIRECTORY matching
                # `*.log` -- made the scan report CLEAN, which is the one answer it must never
                # invent. `_tail` now answers None for "could not read" and [] for "empty".
                unreadable.append(path.name)
                continue
            for line in lines_read:
                keyword = next((pattern for pattern in patterns if pattern in line), '')
                if keyword:
                    hits.append({'file': path.name, 'keyword': keyword, 'line': line[:LINE_KEPT]})
        if unreadable:
            result.anomalies.append(
                Anomaly(
                    kind='logs_unreadable',
                    severity=Severity.WARNING,
                    message=f'{len(unreadable)} log(s) could not be read: {", ".join(sorted(unreadable)[:3])}',
                    signature=f'logs-unreadable:{"|".join(sorted(unreadable))[:80]}',
                )
            )
        result.metrics['files_scanned'] = float(len(kept) - len(unreadable))
        result.metrics['error_count'] = float(len(hits))
        result.data['hits'] = hits
        result.data['status'] = 'CLEAN' if not hits else 'ERRORS'
        if hits:
            result.anomalies.append(
                Anomaly(
                    kind='errors_in_log',
                    severity=Severity.CRITICAL,
                    message=f'{len(hits)} error line(s) in {len({hit["file"] for hit in hits})} log(s)',
                    value=float(len(hits)),
                    threshold=0.0,
                    signature=_error_signature(hits),
                )
            )
        return result


def _error_signature(hits: list[dict[str, str]]) -> str:
    """Identify WHICH errors are in the logs, and not merely which files hold them.

    THE CONTAINER IS NOT THE CONDITION. This signature used to be the sorted set of file names, and
    a file name is stable while its contents are not -- so an entirely new failure landing in a log
    that already had an old one was indistinguishable from that old one. The policy counts
    consecutive cycles PER SIGNATURE and writes a condition off once the count passes its threshold,
    after which it is reported as "the same condition has held for N cycles" and never again. So the
    scanner had exactly two outcomes for a fresh exception: if no log held an error yet, it was
    reported; if one did, the new failure was absorbed into the write-off of the old one and the
    channel went quiet.

    That is the failure this component exists to catch. It watches for an unhandled exception landing
    outside a request -- the shape that leaves `/health/` answering 200 while something is wrong --
    and it was blind precisely when something was already wrong.

    The digest is taken over the matched lines with their NUMBERS FOLDED, because a log line's date,
    clock and errno change on every write: hashing them would make one condition a new signature
    every cycle. Folding keeps what names the failure -- the message, the path, the frames -- and
    drops what only dates it.

    Args:
        hits: the matched lines, as ``{'file', 'keyword', 'line'}``.

    Returns:
        A signature, bounded and stable for one condition.

    """
    files = sorted({hit['file'] for hit in hits})
    return f'logs:{files}:{condition_digest(*(hit["line"] for hit in hits))}'


def _modified(path: Path) -> float:
    """Return a file's modification time, or 0 when it cannot be read.

    Args:
        path: the file.

    Returns:
        Seconds since the epoch, or 0.

    """
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _tail(path: Path, lines: int) -> list[str] | None:
    """Return the last *lines* lines of a file.

    None AND [] ARE DIFFERENT ANSWERS. `None` is "this file could not be read"; `[]` is "this file
    is empty". Collapsing them is what let an unreadable log be reported as a clean one.

    Args:
        path: the file.
        lines: how many to keep.

    Returns:
        The lines, or None when the file cannot be read.

    """
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None
    return text.splitlines()[-lines:]
