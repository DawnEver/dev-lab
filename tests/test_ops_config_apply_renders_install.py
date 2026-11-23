"""An applied config is RENDERED in the same step: no separate ``ops install`` is ever owed after ``config apply``.

Measured 2026-11-22: a workstation's client key reached the issuer's ``[ops.clients]`` by a consented ``config apply``,
yet the issuer kept refusing it, because the consent/break-glass ``authorized_keys`` are written by ``install`` and
nothing ran it. The door now renders what the applied file declares (keys, sudoers, units) itself. The control: an
apply (or tick) that changes nothing renders nothing.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from dev_lab.ops import configverbs, upgrade
from dev_lab.ops.config import OpsConfig

LIVE = '[cycle]\ninterval_s = 60\n'


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> OpsConfig:
    live = tmp_path / 'supervise.toml'
    live.write_text(LIVE, encoding='utf-8')
    monkeypatch.setattr(configverbs, 'load', lambda _path, **_: None)
    monkeypatch.setattr(upgrade, 'checks', lambda _config: {})
    return cast('OpsConfig', SimpleNamespace(path=live, config_source=None, home=tmp_path))


def _apply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str) -> list[str]:
    config, rendered = _config(tmp_path, monkeypatch), []
    candidate = tmp_path / 'candidate.toml'
    candidate.write_text(text, encoding='utf-8')
    assert configverbs.apply(config, candidate, '', alert=lambda *_: None, redeemer=lambda: None,
                             render=lambda: rendered.append('install') or 0) == 0  # fmt: skip
    return rendered


def test_an_applied_change_is_rendered_in_the_same_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _apply(tmp_path, monkeypatch, LIVE.replace('60', '90')) == ['install']


def test_an_unchanged_apply_renders_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _apply(tmp_path, monkeypatch, LIVE) == []


def test_a_tick_that_applies_renders_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, rendered = _config(tmp_path, monkeypatch), []
    monkeypatch.setattr(configverbs, 'source_text', lambda *_: configverbs.configdoor.Fetched(LIVE.replace('60', '90')))
    assert configverbs.tick(config, alert=lambda *_: None, render=lambda: rendered.append('install') or 0) == 0
    assert rendered == ['install']
    assert configverbs.tick(config, alert=lambda *_: None, render=lambda: rendered.append('again') or 0) == 0
    assert rendered == ['install']
