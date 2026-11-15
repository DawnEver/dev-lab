"""Retention keeps a rust toolchain only while something pins it, and drops extracted crate sources (2026-11-14).

A cluster account held 135 k files in rustup toolchains no commit asked for; each is 45-65 k files.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dev_lab.dev.retentionplan import Plan, Policy, cluster_plan
from dev_lab.dev.retentionrust import RULE_REGISTRY, RULE_TOOLCHAIN

NOW = datetime(2026, 11, 14, 12, tzinfo=UTC)
OLD = (NOW - timedelta(days=3)).timestamp()
TRIPLE = 'x86_64-unknown-linux-gnu'


def _file(path: Path, text: str = 'x') -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    os.utime(path, (OLD, OLD))
    return path


def _toolchain(home: Path, name: str) -> Path:
    _file(home / '.rustup' / 'toolchains' / name / 'bin' / 'rustc')
    _file(home / '.rustup' / 'update-hashes' / name)
    os.utime(home / '.rustup' / 'toolchains' / name, (OLD, OLD))
    return home / '.rustup' / 'toolchains' / name


def _account(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / 'home'
    _file(home / '.rustup' / 'settings.toml', f'default_toolchain = "stable-{TRIPLE}"\n')
    for name in (f'stable-{TRIPLE}', f'1.83.0-{TRIPLE}', f'1.80.0-{TRIPLE}', f'nightly-2026-01-01-{TRIPLE}'):
        _toolchain(home, name)
    checkout = tmp_path / 'repos' / 'served'
    _file(checkout / 'rust-toolchain.toml', '[toolchain]\nchannel = "1.83.0"\n')
    return home, checkout


def _rule(plan: Plan, rule: str) -> set[str]:
    return {d.path.name for d in plan.doomed if d.rule == rule}


def _plan(home: Path, checkout: Path, *, occupied: set[str] | None = frozenset(), live: set[str] = frozenset()) -> Plan:
    return cluster_plan(
        home, Policy(), now=NOW, live=live, repo='r', sources=(), occupied=occupied, checkouts=[checkout]
    )


def test_a_toolchain_nothing_pins_goes_with_its_update_hash(tmp_path: Path) -> None:
    home, checkout = _account(tmp_path)
    gone = _rule(_plan(home, checkout), RULE_TOOLCHAIN)
    assert f'1.80.0-{TRIPLE}' in gone
    assert f'nightly-2026-01-01-{TRIPLE}' in gone
    hashes = {d.path.parent.name for d in _plan(home, checkout).doomed if d.rule == RULE_TOOLCHAIN}
    assert hashes == {'toolchains', 'update-hashes'}


def test_the_pinned_channel_and_the_default_are_kept(tmp_path: Path) -> None:
    """Planted control: the served checkout's 1.83.0 and rustup's default stable survive."""
    home, checkout = _account(tmp_path)
    gone = _rule(_plan(home, checkout), RULE_TOOLCHAIN)
    assert f'1.83.0-{TRIPLE}' not in gone
    assert f'stable-{TRIPLE}' not in gone


def test_an_in_flight_tree_keeps_its_own_pin(tmp_path: Path) -> None:
    home, checkout = _account(tmp_path)
    tree = home / 'ci' / 'trees' / 'abc123'
    _file(tree / 'rust-toolchain.toml', '[toolchain]\nchannel = "1.80.0"\n')
    gone = _rule(_plan(home, checkout, live={'abc123'}), RULE_TOOLCHAIN)
    assert f'1.80.0-{TRIPLE}' not in gone
    assert f'nightly-2026-01-01-{TRIPLE}' in gone


def test_an_unreadable_queue_keeps_every_toolchain(tmp_path: Path) -> None:
    home, checkout = _account(tmp_path)
    assert not _rule(_plan(home, checkout, occupied=None), RULE_TOOLCHAIN)


def test_extracted_sources_go_and_the_crate_cache_stays(tmp_path: Path) -> None:
    home, checkout = _account(tmp_path)
    src = home / '.cargo' / 'registry' / 'src' / 'index-1' / 'serde-1.0.0'
    _file(src / 'lib.rs')
    os.utime(src, (OLD, OLD))
    crate = _file(home / '.cargo' / 'registry' / 'cache' / 'index-1' / 'serde-1.0.0.crate')
    fresh = home / '.cargo' / 'registry' / 'src' / 'index-1' / 'being-built-0.1.0'
    _file(fresh / 'lib.rs')
    now = NOW.timestamp()
    os.utime(fresh, (now, now))
    plan = _plan(home, checkout)
    gone = {d.path for d in plan.doomed if d.rule == RULE_REGISTRY}
    assert gone == {src}
    assert all(d.path != crate for d in plan.doomed)
