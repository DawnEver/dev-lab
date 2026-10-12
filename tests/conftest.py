"""Every test reserves on a box of its own: the broker's record root is the test's ``tmp_path``.

A test that falls through to the default root shares the HOST's live seats (a sibling's verdict, a
stranger's directory on a cluster node) and its result then depends on who else is on the box. A
test that means the default root says so with ``monkeypatch.delenv``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.resources import RESOURCE_DIR_ENV


@pytest.fixture(autouse=True)
def _a_box_of_its_own(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(RESOURCE_DIR_ENV, str(tmp_path / 'lab-commons-resources'))
