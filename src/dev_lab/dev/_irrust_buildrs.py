"""THE CONSUMING CRATE'S ``build.rs``, as text: printed by ``python -m dev_lab.dev.irschema build-rs``.

Split out of :mod:`dev_lab.dev.irrust` (2026-11-28, MODULE-SIZE-ALARM): that module renders ``ir.rs``; this is the
build script that finds the checkout's venv interpreter by every :data:`dev_lab.dev.venvpath.VENV_LAYOUTS` spelling
and runs the generator into ``OUT_DIR``. Kept as a Python string because the declared layout admits no ``.rs`` file
under ``src/``.
"""

from __future__ import annotations

from typing import Final

from dev_lab.dev.venvpath import VENV_LAYOUTS

__all__ = ['build_rs']

_BUILD_RS: Final = """// build.rs -- printed by `python -m dev_lab.dev.irschema build-rs`; edit there, not here.
use std::path::PathBuf;
use std::process::Command;

/// Every venv layout, probed rather than switched on (dev_lab.dev.venvpath.VENV_LAYOUTS).
const VENV_PYTHONS: [&str; __COUNT__] = [__PYTHONS__];

/// The checkout holding a venv at or above this crate, and its interpreter.
fn venv_python() -> (PathBuf, PathBuf) {
    let here = std::env::current_dir().expect("Cargo runs a build script in its crate's directory");
    for dir in here.ancestors() {
        for rel in VENV_PYTHONS {
            let candidate = dir.join(rel);
            if candidate.is_file() {
                return (dir.to_path_buf(), candidate);
            }
        }
    }
    panic!(
        concat!(
            "no venv interpreter ({}) at or above {}: bootstrap the checkout with ",
            "`<any python with dev-lab> -m dev_lab.dev.dep --bootstrap <checkout>`",
        ),
        VENV_PYTHONS.join(", "),
        here.display()
    );
}

fn main() {
    let out = std::env::var("OUT_DIR").expect("Cargo sets OUT_DIR for a build script");
    let (root, python) = venv_python();
    let status = Command::new(&python)
        .args(["-m", "dev_lab.dev.irschema", "--root"])
        .arg(&root)
        .args(["rust", "--out", &out])
        .status()
        .expect("python -m dev_lab.dev.irschema rust");
    assert!(status.success(), "IR generation failed; the line above names why");
    println!("cargo:rerun-if-changed={}", root.join("ir").display());
    println!("cargo:rerun-if-changed={}", root.join("pyproject.toml").display());
}
// lib.rs: include!(concat!(env!("OUT_DIR"), "/ir.rs"));
"""


def build_rs() -> str:
    """The consuming crate's ``build.rs``: the venv interpreter found by layout, the IR written into ``OUT_DIR``."""
    pythons = ', '.join(f'"{"/".join(parts)}"' for parts in VENV_LAYOUTS.values())
    return _BUILD_RS.replace('__COUNT__', str(len(VENV_LAYOUTS))).replace('__PYTHONS__', pythons)
