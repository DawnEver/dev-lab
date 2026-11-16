"""A repo raises (or lowers) one family row's severity; it never copies the row.

MEASURED 2026-11-16 in one consumer: BARE-NETWORK-GIT was a local copy of NETWORK-VERB kept only to make the
hint a refusal there, so two rows judged one shape with two reasons and two doors. ``HookAdoption.severities``
replaces the copy: the family row ships, at the severity the repo declares.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev_lab.dev import agenthooks
from dev_lab.dev.hook_adoption import HookAdoption, render
from dev_lab.dev.hooks import Remedy, UnremediedRule

_RETRY = Remedy('retry-wrapper', 'sh scripts/hooks/with-retry.sh <verb> <args>')


def _rows(adoption: HookAdoption) -> dict[str, dict[str, str]]:
    return {row['name']: row for row in json.loads(render(adoption))}


def test_a_declared_severity_is_the_shipped_rows_severity(tmp_path: Path) -> None:
    """The family row, its reason and door unchanged, refuses where the repo raised it. PLANTED CONTROL: unraised."""
    raised = HookAdoption('a', remedies={'NETWORK-VERB': _RETRY}, severities={'NETWORK-VERB': 'deny'})
    plain = HookAdoption('a', remedies={'NETWORK-VERB': _RETRY})
    assert _rows(raised)['NETWORK-VERB']['reason'] == _rows(plain)['NETWORK-VERB']['reason']
    assert _rows(raised)['NETWORK-VERB'].get('severity', 'deny') == 'deny'
    assert _rows(plain)['NETWORK-VERB']['severity'] == 'hint'
    for name, adoption, refused in (('raised', raised, True), ('plain', plain, False)):
        path = tmp_path / f'{name}.json'
        path.write_text(render(adoption), encoding='utf-8')
        assert (agenthooks.decide('git fetch origin', path) is not None) is refused, name


@pytest.mark.parametrize(
    ('severities', 'why'),
    [
        ({'NO-SUCH-ROW': 'deny'}, 'does not define'),
        ({'GIT-RESET': 'loud'}, 'not a severity'),
        ({'GIT-RESET': 'deny'}, 'already'),
    ],
)
def test_an_override_naming_no_row_no_severity_or_no_change_is_refused(severities: dict[str, str], why: str) -> None:
    """A typo raises nothing and says so nowhere; a no-op override reads as a decision and is none."""
    with pytest.raises(UnremediedRule, match=why):
        render(HookAdoption('a', severities=severities))
