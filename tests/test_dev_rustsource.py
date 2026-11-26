"""The family's static Rust reader: literals and comments blanked, test items cut, use trees and items read."""

from __future__ import annotations

from dev_lab.dev.rustsource import FreeFn, code_of, free_functions, has_token, paths_used

SOURCE = r"""
//! std::env in a doc comment is not code
use std::sync::{Arc, Mutex as Lock};
use core::sync::atomic::*;
use std::fs as filesystem;
/* nested /* comment */ std::process */
const S: &str = "std::net and unsafe in a string";
const R: &str = r#"std::thread in a "raw" string"#;
const C: char = '"';
fn lifetimes<'a>(x: &'a str) -> &'a str { x }
extern "C" { fn shim(); }
pub fn read() -> u8 { filesystem::read("x").len() as u8 + std::env::args().count() as u8 }
#[cfg(test)]
mod tests {
    use std::path::PathBuf;
    fn f() { unsafe { std::process::exit(0) } }
}
"""


def test_comments_literals_and_test_items_are_not_code() -> None:
    code = code_of(SOURCE)
    used = paths_used(code)
    assert {'std::sync::Arc', 'std::sync::Mutex', 'std::sync::atomic::*', 'std::fs', 'std::env::args'} <= used
    assert 'std::fs::read' in used  # an inline path through the name `use ... as` binds
    for absent in ('std::net', 'std::thread', 'std::process', 'std::path::PathBuf'):
        assert not any(p.startswith(absent) for p in used), absent
    assert has_token(code, 'extern "C"')
    assert not has_token(code, 'unsafe')  # only in a string and a #[cfg(test)] module
    assert has_token(code_of('fn f() { unsafe { g() } }'), 'unsafe')  # planted control
    assert code.count('\n') == SOURCE.count('\n')  # offsets stay lines


def test_free_functions_reads_params_and_body_and_sees_other_public_items() -> None:
    code = code_of(
        'use other::run;\n'
        'pub fn go<T: Into<u8>>(a: T, mut b: Vec<u8>, (c, d): (u8, u8)) -> u8 where T: Copy { run(a, b) }\n'
        'impl X { pub fn method(&self) {} }\n'
        'pub(crate) fn hidden() {}\n'
        'pub const fn k() -> u8 { 1 }\n'
    )
    items = free_functions(code)
    assert items.functions == (FreeFn('go', ('a', 'b', None), 'run(a, b)'), FreeFn('k', (), '1'))
    assert not items.other_public
    assert free_functions(code_of('pub struct S;\npub fn f() {}\n')).other_public
    assert not free_functions(code_of('pub use a::b;\npub fn f() {}\n')).other_public
    body = free_functions(code_of('pub fn f(a: u8) -> bool { if a < 2 { true } else { a > 3 } }\n')).functions[0].body
    assert body == 'if a < 2 { true } else { a > 3 }'
