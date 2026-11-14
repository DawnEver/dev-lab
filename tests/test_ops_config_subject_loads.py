"""``config apply --subject`` loads the candidate with the host's CURRENT code (#555).

A preflight asks the host for this subject before any code is spent; a candidate the host cannot load must answer
non-zero here, naming "upgrade first", so the plan is BLOCKED instead of spending a credential at run. The control: a
candidate the code loads prints its digest and exits 0.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from dev_lab.ops import configdoor, configverbs


def _subject(tmp_path: Path, *, loads_ok: bool, monkeypatch: pytest.MonkeyPatch) -> int:
    candidate = tmp_path / 'candidate.toml'
    candidate.write_text('[ops]\nstatus = {}\n', encoding='utf-8')

    def load(_path: Path, **_: object) -> object:
        if not loads_ok:
            msg = "[ops] has unknown keys ['status']"
            raise ValueError(msg)
        return None

    monkeypatch.setattr(configverbs, 'load', load)
    config = SimpleNamespace(path=tmp_path / 'supervise.toml', config_source=None)
    return configverbs.apply(
        cast('Any', config), candidate, '', alert=lambda *_: None, redeemer=lambda: None, subject=True
    )


def test_a_candidate_the_host_cannot_load_has_no_subject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                         capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    assert _subject(tmp_path, loads_ok=False, monkeypatch=monkeypatch) == 2
    said = capsys.readouterr()
    assert 'upgrade first' in said.err
    assert configdoor.digest('[ops]\nstatus = {}\n') not in said.out


def test_a_candidate_the_host_loads_prints_its_subject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                       capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    assert _subject(tmp_path, loads_ok=True, monkeypatch=monkeypatch) == 0
    assert configdoor.digest('[ops]\nstatus = {}\n') in capsys.readouterr().out
