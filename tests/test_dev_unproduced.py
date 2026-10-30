"""UNPRODUCED: a resource a repo declares no part for is required by no reading; a declared one still is."""

from __future__ import annotations

from pathlib import Path

import pytest
from lab_commons.hpc.needsets import BASE
from lab_commons.outcomes import Conclusion

from dev_lab.dev import platformparts, unproduced
from dev_lab.dev.forgestatus import CommitStatus

SHA = 'a' * 40

PYPROJECT = """
[tool.lab_commons.tests]
resources = ["femm", "windows"]
"""


def _status(part: str, state: str = 'success', *, hands: str = '-') -> CommitStatus:
    return CommitStatus(f'tests/{part}', state, f'scope=full ran=2 hands={hands}', '')


UNPRODUCED = """
[tool.lab_commons.tests]
resources = ["workstation", "windows"]

[tool.dev_lab.parts]
unproduced = ["workstation"]
"""


def test_a_repo_declaring_no_workstation_part_never_requires_it_and_one_declaring_it_still_does() -> None:
    """User ruling 2026-10-30: a resource declared ``unproduced`` has no part, so no reading waits on one.

    PLANTED CONTROL: the same statuses under a repo that declares nothing unproduced still miss the part.
    """
    handed = [_status(BASE, hands='workstation:71,windows:2'), _status('windows')]
    names = platformparts.derived(handed)
    waived = unproduced.unproduced_parts(names, unproduced.unproduced(UNPRODUCED))
    assert waived == {'workstation'}
    assert platformparts.standing(handed, head=SHA, waived=waived).result is Conclusion.PASS
    declared = unproduced.unproduced_parts(names, unproduced.unproduced(PYPROJECT))
    assert declared == frozenset(), 'PLANTED CONTROL: a repo declaring nothing unproduced waives nothing'
    still = platformparts.standing(handed, head=SHA, waived=declared)
    assert still.result is Conclusion.INCONCLUSIVE
    assert any('missing the workstation part (base hands 71)' in problem for problem in still.problems)
    assert unproduced.unproduced_parts(['windows+workstation@linux'], {'workstation'}) == {'windows+workstation@linux'}


def test_an_unproduced_name_outside_the_vocabulary_is_refused_by_name() -> None:
    with pytest.raises(platformparts.UndeclaredPart, match=r'unproduced.*jmag'):
        unproduced.unproduced(UNPRODUCED.replace('unproduced = ["workstation"]', 'unproduced = ["jmag"]'))


def test_every_reading_waives_what_the_commit_declares_unproduced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Promote, the queue, the tick and the integration feedback read :func:`unproduced_waived` at the sha."""
    handed = [_status(BASE, hands='workstation:71')]
    texts = {'unproduced': UNPRODUCED, 'declared': PYPROJECT, 'broken': UNPRODUCED.replace('"workstation"]', '"x"]')}
    monkeypatch.setattr(unproduced, 'pyproject_at', lambda _root, sha: texts[sha])
    assert unproduced.unproduced_waived(Path(), 'unproduced', handed) == {'workstation'}
    assert unproduced.unproduced_waived(Path(), 'declared', handed) == frozenset(), 'PLANTED CONTROL'
    assert unproduced.unproduced_waived(Path(), 'broken', handed) == frozenset(), 'doubt waives nothing'
