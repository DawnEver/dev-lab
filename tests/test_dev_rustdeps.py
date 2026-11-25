"""OWNER-DAG over Rust: the crate graph, external crates by kind and feature, restricted std paths and tokens."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dev_lab.dev import deptable, rustdeps

if TYPE_CHECKING:
    from pathlib import Path

DECLARED = """
[rust.crates]
base = []
middle = ["base"]
binding = [{ name = "*", adds = "translation" }]

[rust.external]
rayon = { crates = ["middle"], reason = "data parallelism" }
cc = { crates = ["middle"], kind = "build", reason = "the shim" }
serde_json = { crates = ["*"], kind = "dev", features = ["float_roundtrip"], reason = "goldens" }

[rust.std]
"std::sync::Arc" = { crates = ["*"], reason = "shared read-only data" }
"std::sync" = { crates = ["middle"], reason = "no shared mutable state elsewhere" }
"std::env" = { crates = [], reason = "explicit configuration only" }
unsafe = { crates = ["middle"], reason = "the FFI" }
"""
WORKSPACE = '[workspace]\nmembers = ["crates/*"]\n[workspace.dependencies]\nserde_json = { version = "1" }\n'


def _crate(name: str, deps: str = '', dev: str = '', build: str = '') -> str:
    sections = f'[dependencies]\n{deps}\n[dev-dependencies]\n{dev}\n[build-dependencies]\n{build}\n'
    return f'[package]\nname = "{name}"\n{sections}'


#: The tree every case starts from; each case overwrites one file.
BASE = {
    'rust/Cargo.toml': WORKSPACE,
    'rust/crates/base/Cargo.toml': _crate(
        'base', dev='serde_json = { workspace = true, features = ["float_roundtrip"] }\nmiddle = { path = "../middle" }'
    ),
    'rust/crates/base/src/lib.rs': 'use std::sync::Arc;\npub fn f() {}\n#[cfg(test)]\nmod t { use std::env; }\n',
    'rust/crates/base/build.rs': 'fn main() { std::env::var("OUT_DIR").unwrap(); }\n',
    'rust/crates/middle/Cargo.toml': _crate(
        'middle', deps='base = { path = "../base" }\nrayon = "1"', build='cc = "1"'
    ),
    'rust/crates/middle/src/lib.rs': 'use std::sync::{Arc, Mutex};\npub fn g() { unsafe { h() } }\n',
    'rust/pybind/binding/Cargo.toml': _crate('binding', deps='base = { path = "../../crates/base" }'),
    'rust/pybind/binding/src/lib.rs': '',
}


def _problems(root: Path, extra: dict[str, str] | None = None, declared: str = DECLARED) -> list[str]:
    files = {**BASE, deptable.FILE: declared, **(extra or {})}
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding='utf-8')
    decl = deptable.load(root)
    assert decl is not None
    return rustdeps.problems(root, decl, files)


def test_the_declared_workspace_passes(tmp_path: Path) -> None:
    """THE PLANTED CONTROL: build.rs reading env, a #[cfg(test)] env use and a dev-dep on a crate are all free."""
    assert _problems(tmp_path) == []


@pytest.mark.parametrize(
    ('extra', 'named'),
    [
        (
            {'rust/crates/base/Cargo.toml': _crate('base', deps='middle = { path = "../middle" }')},
            'crate base depends on middle, but [rust.crates] base does not list it',
        ),
        (
            {'rust/crates/base/Cargo.toml': _crate('base', deps='num = { package = "middle", path = "../middle" }')},
            'crate base depends on middle',
        ),
        (
            {'rust/crates/base/Cargo.toml': _crate('base', deps='faer = "0.20"')},
            'depends on faer (normal), which no [rust.external] row names',
        ),
        (
            {'rust/crates/base/Cargo.toml': _crate('base', deps='rayon = "1"')},
            '[rust.external] rayon allows it only in middle',
        ),
        (
            {'rust/crates/base/Cargo.toml': _crate('base', deps='serde_json = "1"')},
            '[rust.external] serde_json is kind dev',
        ),
        (
            {'rust/crates/base/Cargo.toml': _crate('base', dev='serde_json = { workspace = true }')},
            "without the required feature(s) ['float_roundtrip']",
        ),
        (
            {'rust/crates/base/src/lib.rs': 'use std::sync::{Arc, Mutex};\n'},
            'uses std::sync::Mutex, but [rust.std] std::sync allows it only in middle',
        ),
        (
            {'rust/crates/base/src/lib.rs': 'use core::sync::atomic::AtomicBool;\n'},
            'uses std::sync::atomic::AtomicBool, but [rust.std] std::sync',
        ),
        (
            {'rust/crates/middle/src/lib.rs': 'fn f() { let _ = std::env::var("X"); }\n'},
            '[rust.std] std::env allows it only in nowhere',
        ),
        (
            {'rust/crates/base/src/lib.rs': 'pub fn f() { unsafe { g() } }\n'},
            'uses unsafe, but [rust.std] unsafe allows it only in middle',
        ),
        ({'rust/crates/extra/Cargo.toml': _crate('extra')}, 'crate extra has no [rust.crates] row'),
    ],
)
def test_each_refusal_names_the_manifest_or_file_and_the_row(tmp_path: Path, extra: dict[str, str], named: str) -> None:
    found = _problems(tmp_path, extra)
    assert len(found) == 1, found
    assert named in found[0]
    assert found[0].startswith(next(iter(extra)))


def test_a_row_or_holder_naming_no_crate_is_refused(tmp_path: Path) -> None:
    stale = DECLARED.replace('binding = [', 'ghost = []\nbinding = [').replace(
        'crates = ["middle"], reason = "data', 'crates = ["gone"], reason = "data'
    )
    found = _problems(tmp_path, declared=stale)
    assert '[rust.crates] ghost names no crate in the tree' in found
    assert '[rust.external] rayon names crate gone, which is no crate in the tree' in found


def test_no_rust_table_means_rust_is_not_judged(tmp_path: Path) -> None:
    assert _problems(tmp_path, declared='[python.owners]\n') == []
