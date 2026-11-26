"""The per-owner complexity report: its three readings on a planted tree, the dated record, and the trend view.

Not a gate: nothing here refuses a value. What is pinned is that each reading measures what it names -- a planted
import chain has its length, a planted fan-out its count, a declared ``__all__`` its size -- so a trend over the
records is a trend in the code and not in the reader.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from dev_lab.dev import complexity
from dev_lab.dev.complexity import Owner

if TYPE_CHECKING:
    from pathlib import Path


def _write(root: Path, rel: str, text: str = '') -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding='utf-8')


_TREE = {
    'src/pkg/__init__.py': '',
    'src/pkg/a.py': "from pkg import b\nimport pkg.c\n__all__ = ['f', 'g']\ndef f(): ...\ndef g(): ...\n"
    'def _h(): ...\n',
    'src/pkg/b.py': 'from pkg.c import x\nimport json\ndef one(): ...\nclass Two: ...\n_private = 1\n',
    'src/pkg/c.py': 'x = 1\n',
    'src/pkg/loop1.py': 'from pkg import loop2\n',
    'src/pkg/loop2.py': 'from pkg import loop1\nfrom pkg import c\n',
    'tests/test_a.py': 'from pkg import a\n',
}


def _owners(tmp_path: Path) -> dict[str, Owner]:
    for rel, text in _TREE.items():
        _write(tmp_path, rel, text)
    return {owner.name: owner for owner in complexity.owners(tmp_path, _TREE)}


def test_fan_out_counts_distinct_in_repo_modules_only(tmp_path: Path) -> None:
    """PLANTED: a imports b and c (2); b imports c and the stdlib json, which is not the repo's (1)."""
    found = _owners(tmp_path)
    assert found['pkg.a'].fan_out == 2
    assert found['pkg.b'].fan_out == 1
    assert found['pkg.c'].fan_out == 0


def test_call_path_is_the_longest_import_chain_with_a_cycle_as_one_hop(tmp_path: Path) -> None:
    """A -> b -> c is two hops; loop1 <-> loop2 is one strongly connected owner set, then one hop to c."""
    found = _owners(tmp_path)
    assert found['pkg.a'].call_path == 2
    assert found['pkg.b'].call_path == 1
    assert found['pkg.c'].call_path == 0
    assert found['pkg.loop1'].call_path == found['pkg.loop2'].call_path == 1


def test_public_surface_is_all_else_the_public_top_level_names(tmp_path: Path) -> None:
    found = _owners(tmp_path)
    assert found['pkg.a'].surface == 2, 'a declared __all__ is the surface'
    assert found['pkg.b'].surface == 2, 'without __all__: the public top-level def and class, never _private'
    assert found['pkg.c'].surface == 1


def test_tests_are_not_owners(tmp_path: Path) -> None:
    assert not any(name.startswith('tests') for name in _owners(tmp_path))


def test_record_appends_one_dated_line_per_owner_and_trend_reads_them_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _owners(tmp_path)
    monkeypatch.setattr(complexity, '_tracked', lambda _root: tuple(_TREE))
    monkeypatch.setattr(complexity, '_revision', lambda _root: 'a' * 40)
    path = complexity.record(tmp_path, repo='repo')
    assert path.parent.name == complexity.KIND
    assert path.parent.parent.parent.parent.parent.name == 'logs'
    lines = [json.loads(raw) for raw in path.read_text(encoding='utf-8').splitlines()]
    assert len(lines) == len(_TREE) - 1, 'one line per owner, the test file is no owner'
    assert {line['code.namespace'] for line in lines} >= {'pkg.a', 'pkg.b', 'pkg.c'}
    assert all(line['event.name'] == 'lab.complexity' for line in lines)
    _write(tmp_path, 'src/pkg/c.py', 'from pkg import b\nx = 1\n')  # a cycle b <-> c: c now fans out
    complexity.record(tmp_path, repo='repo')
    view = complexity.trend(complexity.read(tmp_path), top=len(_TREE))
    assert len([line for line in view if line.startswith('run ')]) == 2
    assert any('pkg.c' in line and 'fan_out 0 -> 1' in line for line in view)


def test_the_cli_records_and_shows_the_trend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _owners(tmp_path)
    monkeypatch.setattr(complexity, '_tracked', lambda _root: tuple(_TREE))
    monkeypatch.setattr(complexity, '_revision', lambda _root: 'b' * 40)
    monkeypatch.setattr(complexity, 'repo_of', lambda _root: 'repo')
    assert complexity.main(['record'], cwd=tmp_path) == 0
    assert complexity.main(['trend', '--top', '2'], cwd=tmp_path) == 0
    out = capsys.readouterr().out
    assert 'owners.jsonl' in out
    assert 'run ' in out
