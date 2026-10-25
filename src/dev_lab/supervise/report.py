"""What a cycle leaves behind, and what a day of them adds up to.

Two readers, two shapes. A PERSON wants one line that says whether anything is wrong and what is
being done about it. A DIGEST wants the same facts as data, because the daily roll-up is built from
a day of them and a roll-up parsed out of prose breaks the first time the prose is reworded.

THE DIGEST IS WHY A CYCLE WRITES A RECORD AT ALL. Every cycle appends one compact line; the daily
summary reads them back. Both halves live here so the writer and the reader cannot drift into
disagreeing about a field name -- the defect the predecessor had in its state, where two writers
used two spellings of the same counter.

WHAT IS REDACTED AND WHY. A delivery's detail is whatever a channel said back, and a channel that
refuses an address tends to refuse it BY NAME. A report is the most-copied artefact a supervisor
produces -- into a log, a chat, a ticket -- so an address or a bearer token is masked on the way in
rather than trusted not to travel.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Final

from dev_lab.supervise.loop import CycleResult

__all__ = ['digest', 'record', 'redact', 'summary']

#: Anything shaped like an address, and anything shaped like a bearer token. Deliberately crude:
#: a redactor that tries to be precise about what a secret looks like is a redactor with misses.
_ADDRESS: Final = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
_TOKEN: Final = re.compile(r'\b(?:Bearer\s+)?[A-Za-z0-9_-]{24,}\b')


def redact(text: str) -> str:
    """Mask addresses and token-shaped runs in *text*.

    Args:
        text: whatever a channel said.

    Returns:
        The same text with anything that looks like a credential or an address replaced by a
        fixed marker.

    """
    return _TOKEN.sub('<redacted>', _ADDRESS.sub('<address>', text))


def summary(result: CycleResult) -> str:
    """Return the one line a person reads.

    Args:
        result: what a cycle found.

    Returns:
        A sentence naming the status, what is wrong, and what was done about it.

    """
    if result.status == 'healthy' and not result.completions:
        return 'HEALTHY -- every check passed'
    parts: list[str] = []
    if result.anomalies:
        parts.append(f'{len(result.anomalies)} anomalous: ' + ', '.join(sorted({a.source for a in result.anomalies})))
    if result.completions:
        parts.append(f'{len(result.completions)} complete: ' + ', '.join(sorted({c.kind for c in result.completions})))
    if result.attempts:
        ran = sum(1 for attempt in result.attempts if attempt.ran)
        held = len(result.attempts) - ran
        noun = 'remedy' if ran == 1 else 'remedies'
        parts.append(f'{ran} {noun} ran, {held} held by a gate')
    if result.deliveries:
        told = sum(1 for delivery in result.deliveries if delivery.ok)
        parts.append(f'{told}/{len(result.deliveries)} channels reached')
    label = 'DEGRADED' if result.anomalies else 'COMPLETE'
    return f'{label} -- ' + '; '.join(parts)


def record(result: CycleResult, at: datetime) -> dict[str, Any]:
    """Return the compact line a digest reads back.

    Kept to scalars and sorted lists: a digest sums a day of these, and a field whose shape drifts
    is a roll-up that silently stops counting.

    Args:
        result: what the cycle found.
        at: when it ran.

    Returns:
        A mapping of scalars, safe to serialise.

    """
    return {
        'at': at.isoformat(),
        'status': result.status,
        'anomalies': sorted({anomaly.source for anomaly in result.anomalies}),
        'completions': sorted({completion.kind for completion in result.completions}),
        'remedies_ran': sum(1 for attempt in result.attempts if attempt.ran),
        'remedies_held': sum(1 for attempt in result.attempts if attempt.skipped),
        'channels_reached': sum(1 for delivery in result.deliveries if delivery.ok),
        'channels_failed': [
            f'{delivery.channel}: {redact(delivery.detail)}' for delivery in result.deliveries if not delivery.ok
        ],
    }


def digest(records: Sequence[Mapping[str, Any]], *, since: str = '') -> str:
    """Add up a run of cycle records into the one message a day sends.

    Args:
        records: the records, oldest first, as :func:`record` produced them.
        since: what the window was, for the first line.

    Returns:
        A plain-text summary. A day with nothing in it says so rather than saying nothing: silence
        from a supervisor is indistinguishable from a supervisor that is not running.

    """
    if not records:
        return f'No supervision cycles recorded{f" since {since}" if since else ""}.'
    failed = [entry for entry in records if entry.get('status') != 'healthy']
    sources: dict[str, int] = {}
    for entry in failed:
        for source in entry.get('anomalies', []):
            sources[str(source)] = sources.get(str(source), 0) + 1
    ran = sum(int(entry.get('remedies_ran', 0)) for entry in records)
    held = sum(int(entry.get('remedies_held', 0)) for entry in records)
    lines = [
        f'{len(records)} cycles{f" since {since}" if since else ""}, {len(failed)} degraded.',
        f'Remedies run: {ran}; held by a gate: {held}.',
    ]
    dropped = [note for entry in records for note in entry.get('channels_failed', [])]
    if dropped:
        lines.append('Channels that did not take a notice: ' + '; '.join(sorted(set(dropped))))
    if sources:
        worst = sorted(sources.items(), key=lambda pair: (-pair[1], pair[0]))[:5]
        lines.append('Most persistent: ' + ', '.join(f'{name} x{count}' for name, count in worst))
    return '\n'.join(lines)
