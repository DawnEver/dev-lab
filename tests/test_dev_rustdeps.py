"""OWNER-DAG over Rust: the crate graph DERIVED from crate paths, external crates by kind and feature, std uses."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dev_lab.dev import deptable, rustdeps
from dev_lab.dev._layout_table import Layout, declared_layout

if TYPE_CHECKING:
    from pathlib import Path

DECLARED = """
[python.owners]
base = []
middle = ["base"]

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
LAYOUT = (
    '[layout]\n"." = [".toml"]\n"src" = []\n"tests" = []\n"scratch" = []\n".claude" = []\n'
    '"docs-src" = []\n"output" = []\n"rust" = ["Cargo.toml"]\n"rust/crates" = []\n'
    '"rust/crates/planned" = []\n"rust/crates/planned/kernel" = ["Cargo.toml"]\n'
)
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


def _problems(
    root: Path, extra: dict[str, str] | None = None, declared: str = DECLARED, layout: Layout | None = None
) -> list[str]:
    files = {**BASE, deptable.FILE: declared, **(extra or {})}
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding='utf-8')
    decl = deptable.load(root)
    assert decl is not None
    return rustdeps.problems(root, decl, files, layout=layout)


def test_the_declared_workspace_passes(tmp_path: Path) -> None:
    """THE PLANTED CONTROL: build.rs reading env, a #[cfg(test)] env use and a dev-dep on a crate are all free."""
    assert _problems(tmp_path) == []


@pytest.mark.parametrize(
    ('extra', 'named'),
    [
        (
            {'rust/crates/base/Cargo.toml': _crate('base', deps='middle = { path = "../middle" }')},
            'crate base depends on middle, but [python.owners] base does not list middle',
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
        (
            {'rust/crates/extra/Cargo.toml': _crate('extra')},
            'crate extra lies under rust/crates/extra, which no [python.owners] row names',
        ),
        (
            {'rust/crates/base/Cargo.toml': _crate('base', deps='binding = { path = "../../pybind/binding" }')},
            'crate base depends on binding, an exit to Python (rust/pybind/binding); no crate depends on an exit',
        ),
        (
            {'rust/crates/middle/inner/Cargo.toml': _crate('inner')},
            'crate inner lies at rust/crates/middle/inner, so it is named middle_inner',
        ),
    ],
)
def test_each_refusal_names_the_manifest_or_file_and_the_row(tmp_path: Path, extra: dict[str, str], named: str) -> None:
    found = _problems(tmp_path, extra)
    assert len(found) == 1, found
    assert named in found[0]
    assert found[0].startswith(next(iter(extra)))


def test_a_holder_naming_no_crate_is_refused(tmp_path: Path) -> None:
    stale = DECLARED.replace('crates = ["middle"], reason = "data', 'crates = ["middle", "gone"], reason = "data')
    found = _problems(tmp_path, declared=stale)
    nowhere = 'which is no crate in the tree and which no layout.toml <crate dir>/Cargo.toml row declares'
    assert found == [f'dependencies.toml [rust.external] rayon names crate gone, {nowhere}']


def test_a_crate_layout_toml_declares_but_the_tree_lacks_is_allowed(tmp_path: Path) -> None:
    """PLANTED CONTROL: a crate not created yet passes when layout.toml declares its Cargo.toml; a ghost is refused.

    The planned crate is named for its declared path (``rust/crates/planned/kernel`` -> ``planned_kernel``).
    """
    planned = DECLARED.replace(
        'crates = ["middle"], reason = "data', 'crates = ["middle", "planned_kernel", "ghost"], reason = "data'
    )
    (tmp_path / 'layout.toml').write_text(LAYOUT, encoding='utf-8')
    found = _problems(tmp_path, declared=planned, layout=declared_layout(tmp_path))
    assert found == [
        (
            'dependencies.toml [rust.external] rayon names crate ghost, which is no crate in the tree and which no '
            'layout.toml <crate dir>/Cargo.toml row declares'
        )
    ]
    assert rustdeps.stages(tmp_path, BASE, declared_layout(tmp_path))['planned_kernel'] == ('planned', 'kernel')


def test_no_crate_and_no_rust_row_means_rust_is_not_judged(tmp_path: Path) -> None:
    decl = deptable.Declared({}, {}, {}, {}, {}, {}, {})
    assert rustdeps.problems(tmp_path, decl, []) == []


#: The ONE graph at depth: owner stage with two Rust-owned children (no Python folder), b -> a declared.
NESTED = DECLARED.replace('middle = ["base"]', 'middle = ["base"]\nstage = []\n\n[python.siblings.stage]\nb = ["a"]')
NESTED_TREE = {
    'rust/crates/stage/Cargo.toml': _crate('stage'),
    'rust/crates/stage/a/Cargo.toml': _crate('stage_a', deps='stage = { path = ".." }'),
    'rust/crates/stage/b/Cargo.toml': _crate('stage_b', deps='stage_a = { path = "../a" }'),
}


def test_crate_edges_are_the_sibling_edges_of_their_paths(tmp_path: Path) -> None:
    """THE PLANTED CONTROL: b -> a (declared) and a -> its parent stage pass; the reverse sibling edge is refused."""
    assert _problems(tmp_path, NESTED_TREE, declared=NESTED) == []
    reverse = {**NESTED_TREE, 'rust/crates/stage/a/Cargo.toml': _crate('stage_a', deps='stage_b = { path = "../b" }')}
    assert _problems(tmp_path / 'reverse', reverse, declared=NESTED) == [
        (
            'rust/crates/stage/a/Cargo.toml: crate stage_a depends on stage_b, but [python.siblings."stage"] a '
            'does not list b'
        )
    ]


def test_a_parent_crate_depending_on_its_child_is_refused(tmp_path: Path) -> None:
    down = {**NESTED_TREE, 'rust/crates/stage/Cargo.toml': _crate('stage', deps='stage_a = { path = "a" }')}
    assert _problems(tmp_path, down, declared=NESTED) == [
        (
            'rust/crates/stage/Cargo.toml: crate stage depends on stage_a: stage stage depends on its own child '
            'stage/a; a parent never depends on its children'
        )
    ]


def test_a_crate_table_is_retired_with_its_door(tmp_path: Path) -> None:
    (tmp_path / deptable.FILE).write_text('[rust.crates]\nbase = []\n', encoding='utf-8')
    with pytest.raises(deptable.DependenciesError, match=r'\[rust.crates\] is retired: the crate graph derives'):
        deptable.load(tmp_path)


#: D113: one crate, NORMAL for some crates and DEV (tests only) for every crate.
SPLIT = DECLARED.replace(
    'serde_json = { crates = ["*"], kind = "dev", features = ["float_roundtrip"], reason = "goldens" }',
    'serde_json = { crates = ["middle"], dev_crates = ["*"], features = ["float_roundtrip"], reason = "goldens" }',
)


def test_a_dev_crates_grant_admits_tests_everywhere_and_normal_only_where_crates_says(tmp_path: Path) -> None:
    """THE PLANTED PAIR: base's dev-dependency passes under dev_crates; as base's normal one it is refused."""
    assert _problems(tmp_path, declared=SPLIT) == []
    normal = {
        'rust/crates/base/Cargo.toml': _crate(
            'base', deps='serde_json = { workspace = true, features = ["float_roundtrip"] }'
        )
    }
    found = _problems(tmp_path / 'normal', normal, declared=SPLIT)
    assert len(found) == 1, found
    assert (
        'crate base depends on serde_json (normal), but [rust.external] serde_json allows it only in middle' in found[0]
    )
    fine = {
        'rust/crates/middle/Cargo.toml': _crate(
            'middle',
            deps=(
                'base = { path = "../base" }\nrayon = "1"\n'
                'serde_json = { workspace = true, features = ["float_roundtrip"] }'
            ),
            build='cc = "1"',
        )
    }
    assert _problems(tmp_path / 'fine', fine, declared=SPLIT) == []


def test_dev_crates_is_refused_on_a_row_that_already_grants_dev_everywhere(tmp_path: Path) -> None:
    redundant = DECLARED.replace('kind = "dev", features', 'kind = "dev", dev_crates = ["*"], features')
    (tmp_path / deptable.FILE).write_text(redundant, encoding='utf-8')
    with pytest.raises(deptable.DependenciesError, match='dev_crates'):
        deptable.load(tmp_path)


#: A build-kind std row: ``std::fs`` in a build script, only in base's (FAM-03 b, D153 B1-09).
BUILD_STD = DECLARED.replace(
    'unsafe = {', '"std::fs" = { crates = ["base"], kind = "build", reason = "the build writes OUT_DIR" }\nunsafe = {'
)


def test_a_build_kind_std_row_judges_build_scripts_only(tmp_path: Path) -> None:
    """THE PLANTED CONTROL: base's build.rs and middle's src may use std::fs; middle's build.rs may not."""
    fs_build = 'fn main() { std::fs::write("x", "").unwrap(); }\n'
    allowed = {'rust/crates/base/build.rs': fs_build, 'rust/crates/middle/src/lib.rs': 'use std::fs;\n'}
    assert _problems(tmp_path / 'ok', allowed, declared=BUILD_STD) == []
    assert _problems(tmp_path / 'no', {'rust/crates/middle/build.rs': fs_build}, declared=BUILD_STD) == [
        'rust/crates/middle/build.rs: crate middle uses std::fs::write, but [rust.std] std::fs allows it only in base'
    ]


def test_a_normal_std_row_never_judges_a_build_script(tmp_path: Path) -> None:
    """build.rs reading OUT_DIR under the normal ``std::env`` row granting nowhere stays free (the base tree)."""
    assert _problems(tmp_path, {'rust/crates/middle/build.rs': 'fn main() { std::env::var("OUT_DIR"); }\n'}) == []
