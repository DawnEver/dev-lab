"""FAMILY HEADS: a floating family package behind its forge head is STALE, offline is UNKNOWN, never fresh."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lab_commons.dev import familyheads, verify
from lab_commons.dev.familyheads import (
    CACHE_TTL_S,
    DEFAULT_DOOR,
    Freshness,
    Installed,
    check,
    installed_family,
    offline_line,
    refusal,
    sync_door,
)
from lab_commons.dev.platformparts import BASE, part_context
from lab_commons.dev.producer import PRODUCING_VAR
from lab_commons.outcomes import Conclusion

_OLD, _NEW = 'a' * 40, 'b' * 40
_URL = 'https://gitea.example.org/Team/lab-commons.git'


def _dist(name: str, direct_url: dict[str, object] | None) -> SimpleNamespace:
    text = None if direct_url is None else json.dumps(direct_url)
    return SimpleNamespace(metadata={'Name': name}, read_text=lambda _name: text)


def test_only_distributions_installed_from_git_are_read() -> None:
    vcs = {'url': _URL, 'vcs_info': {'vcs': 'git', 'commit_id': _OLD}}
    found = installed_family(
        lambda: [
            _dist('lab_commons', vcs),
            _dist('numpy', {'url': 'https://files/numpy.whl', 'archive_info': {}}),
            _dist('dep-b', {'url': 'file:///x', 'dir_info': {'editable': True}}),
            _dist('dep-c', None),
        ]
    )
    assert found == (Installed('lab-commons', _URL, 'HEAD', _OLD),)


def test_a_commit_behind_its_head_is_stale_and_the_refusal_names_the_door(tmp_path: Path) -> None:
    """PLANTED: the installed commit lags the forge head."""
    behind = Installed('lab-commons', _URL, 'HEAD', _OLD)
    freshness = check([behind], cache=tmp_path / 'heads.json', ls_remote=lambda _u, _r: _NEW)
    assert freshness.stale == ((behind, _NEW),)
    text = refusal(freshness, door='python scripts/gate/dep_sync.py --sync')
    assert text is not None
    assert 'STALE' in text
    assert 'python scripts/gate/dep_sync.py --sync' in text
    assert '--upgrade-package lab-commons' in text


def test_a_commit_at_its_head_or_pinned_is_fresh(tmp_path: Path) -> None:
    """THE OTHER SIDE: fresh is silent, and a pinned commit never floats."""
    at_head = Installed('lab-commons', _URL, 'HEAD', _NEW)
    pinned = Installed('dep-b', _URL, _OLD, _OLD)
    freshness = check(
        [at_head, pinned],
        cache=tmp_path / 'heads.json',
        ls_remote=lambda _u, ref: pytest.fail('a pinned commit asked the forge') if ref == _OLD else _NEW,
    )
    assert freshness == Freshness((), ())
    assert refusal(freshness, door='d') is None
    assert offline_line(freshness) is None


def test_offline_is_unknown_and_said_never_read_as_fresh(tmp_path: Path) -> None:
    one = Installed('dep-c', _URL, 'main', _OLD)
    freshness = check([one], cache=tmp_path / 'heads.json', ls_remote=lambda _u, _r: None)
    assert freshness.unknown == (one,)
    assert refusal(freshness, door='d') is None
    line = offline_line(freshness)
    assert line is not None
    assert 'UNKNOWN' in line
    assert 'dep-c' in line


def test_the_head_is_cached_briefly(tmp_path: Path) -> None:
    asked: list[str] = []

    def ls_remote(url: str, _ref: str) -> str:
        asked.append(url)
        return _NEW

    one = Installed('lab-commons', _URL, 'HEAD', _OLD)
    cache = tmp_path / 'heads.json'
    check([one], cache=cache, now=1000.0, ls_remote=ls_remote)
    check([one], cache=cache, now=1000.0 + CACHE_TTL_S / 2, ls_remote=ls_remote)
    assert asked == [_URL], 'a burst of runs asks the forge once'
    check([one], cache=cache, now=1000.0 + CACHE_TTL_S + 1, ls_remote=ls_remote)
    assert asked == [_URL, _URL], 'an expired head is asked again'


def test_the_sync_door_is_the_repos_declaration_else_the_shared_one(tmp_path: Path) -> None:
    assert sync_door(tmp_path) == DEFAULT_DOOR
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.lab_commons.doors]\nENV-MUTATION-THROUGH-THE-DOOR = "python scripts/gate/dep_sync.py --sync"\n',
        encoding='utf-8',
    )
    assert sync_door(tmp_path) == 'python scripts/gate/dep_sync.py --sync'


def test_verify_refuses_a_stale_environment_before_anything_runs(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv(PRODUCING_VAR, f'{part_context(BASE)}@planted')  # the full suite is the producer's
    monkeypatch.setattr(verify, 'project_root', lambda: tmp_path)
    monkeypatch.setattr(verify, 'run_verify', lambda *_a, **_k: pytest.fail('a stale environment ran'))
    monkeypatch.setattr(familyheads, 'installed_family', lambda: (Installed('lab-commons', _URL, 'HEAD', _OLD),))
    monkeypatch.setattr(familyheads, '_ls_remote', lambda _u, _r: _NEW)
    monkeypatch.setenv('LAB_COMMONS_RESOURCE_DIR', str(tmp_path))
    assert verify.main([]) == verify.EXIT_CODES[Conclusion.INCONCLUSIVE]
    assert 'STALE' in capsys.readouterr().err
