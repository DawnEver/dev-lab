"""Is a long job still moving, and has it finished.

A FINISHED JOB IS NOT AN ANOMALY, and the predecessor learned that the hard way: it modelled
completion as a warning, so a run that had succeeded reported `degraded` forever, stayed on the
anomaly cadence, and could trip escalation on its own success. Completion is a first-class outcome
here -- it makes the run `complete` rather than `degraded`, and it enters no remedy chain.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dev_lab.supervise.component import CheckContext, Component
from dev_lab.supervise.verdict import Anomaly, CheckResult, Completion, Severity

__all__ = ['ProgressTracker']


class ProgressTracker(Component):
    """Read a job's progress file and report a stall or a finish.

    Config::

        [components.progress_tracker]
        enabled = true
        progress_file = "output/run/progress.json"
        count_path = "ops"          # the key whose counters are summed
        count_field = "count"
        total_ops = 72
        stale_rounds = 3

    """

    name = 'progress_tracker'
    description = 'Read a job progress file, and report a stall or a finish'

    def check(self, ctx: CheckContext) -> CheckResult:
        """Read the progress file and judge how far the job has got.

        Args:
            ctx: the component's config, its own state slice, and the target directory.

        Returns:
            The counts read, a completion when the job is done, and a stall if it has stopped.

        """
        result = CheckResult()
        path = Path(str(ctx.config.get('progress_file', 'progress.json')))
        if not path.is_absolute():
            path = ctx.project / path
        payload = _read(path)
        if payload is None:
            # NO READING IS NOT NO PROGRESS. `_read` answers None for a missing file and for an
            # unparseable one, and its own docstring says so -- "both mean 'no reading', which is
            # not the same as 'no progress'". The caller then asserted `ops_done = 0.0` and said
            # nothing, and `data['status']` reaches no report: `report.summary` and `report.record`
            # read anomalies, completions, attempts and deliveries, and nothing else.
            #
            # So a progress file that vanished or became unreadable -- the job died, a cleanup
            # removed it, permissions changed -- turned the one component that would have noticed
            # the job stopped into a silent no-op, with a zero recorded that looks like a reading.
            result.anomalies.append(
                Anomaly(
                    kind='progress_unreadable',
                    severity=Severity.WARNING,
                    message=f'{path.name} could not be read, so progress cannot be judged',
                    signature='progress:unreadable',
                )
            )
            return result
        done = _count(payload, str(ctx.config.get('count_path', '')), str(ctx.config.get('count_field', 'count')))
        total = float(_total(payload, ctx.config))
        result.metrics['ops_done'] = done
        result.metrics['total_ops'] = total
        result.metrics['percent'] = round(min(100.0, done / total * 100), 1) if total > 0 else 0.0
        unchanged = int(ctx.state.get('unchanged', 0))
        unchanged = unchanged + 1 if ctx.state.get('last') == done else 0
        ctx.state['last'] = done
        ctx.state['unchanged'] = unchanged
        result.metrics['stale_cycles'] = float(unchanged)
        if total > 0 and done >= total:
            result.data['status'] = 'COMPLETE'
            result.completions.append(
                Completion(kind=f'{self.name}_finished', message=f'{done:.0f} of {total:.0f} done')
            )
            ctx.state['unchanged'] = 0
            return result
        limit = int(ctx.config.get('stale_rounds', 3))
        if unchanged >= limit:
            result.data['status'] = 'STALLED'
            result.anomalies.append(
                Anomaly(
                    kind='stalled',
                    severity=Severity.CRITICAL,
                    message=f'the job has not moved from {done:.0f} in {unchanged} cycles',
                    value=done,
                    threshold=total,
                    signature=f'stalled:{done}',
                )
            )
        else:
            result.data['status'] = 'RUNNING'
        return result


def _read(path: Path) -> dict[str, Any] | None:
    """Read a progress file.

    Args:
        path: the file.

    Returns:
        The parsed object, or None when it is missing or unparseable -- both mean "no reading",
        which is not the same as "no progress".

    """
    try:
        parsed = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _count(payload: dict[str, Any], at: str, field: str) -> float:
    """Sum the counters under a key, or the whole document when no key is named.

    Args:
        payload: the parsed progress document.
        at: the key the counters live under, or an empty string for the top level.
        field: the name of each counter.

    Returns:
        The sum, counting anything numeric that is not a named counter as itself.

    """
    node: Any = payload
    if at:
        for piece in at.split('.'):
            node = node.get(piece) if isinstance(node, dict) else None
    if isinstance(node, dict):
        total = 0.0
        for key, value in node.items():
            if key == field and isinstance(value, (int, float)):
                total += float(value)
            elif isinstance(value, dict):
                inner = value.get(field)
                if isinstance(inner, (int, float)):
                    total += float(inner)
        return total
    return float(node) if isinstance(node, (int, float)) else 0.0


def _total(payload: dict[str, Any], config: dict[str, Any]) -> float:
    """Return the job's expected total, from the config or the document.

    Args:
        payload: the parsed progress document.
        config: the component's configuration.

    Returns:
        The total, or 0 when neither source names one -- which means no percentage is claimed
        rather than a percentage of nothing.

    """
    declared = config.get('total_ops')
    if declared:
        return float(declared)
    key = str(config.get('total_ops_key', 'total_ops'))
    found = payload.get(key)
    return float(found) if isinstance(found, (int, float)) else 0.0
