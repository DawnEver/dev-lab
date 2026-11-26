"""The ``Cargo.toml`` tables the family OWNS: one ``[workspace.lints]`` base, rustc and clippy.

User-agreed 2026-11-25 (consumer v1 ledger D107). Measured that day: no family workspace declared any lint table
(a consumer's ``rust/Cargo.toml`` and numerics-lab's root ``Cargo.toml``), and famfiles rendered no ``Cargo.toml``
table at all -- so every lint level was each crate's silent default. The base is the floor the family agrees on;
:mod:`dev_lab.dev.cargolints` refuses a workspace whose tables drift from it, and a member crate that does not
inherit them (``[lints] workspace = true``), since a workspace table no member reads lints nothing.

WHY THESE KEYS. ``clippy::all`` denied is the lint set clippy itself calls correct-or-useless; ``pedantic`` warns,
never denies, because it is opinion. ``dbg_macro`` and ``todo`` are left-in debugging and unfinished code.
``unsafe_op_in_unsafe_fn`` makes every unsafe operation its own audited block (Rust 2024's default), and
``unused_must_use`` turns an ignored ``Result`` into an error. ``unsafe_code`` is NOT forbidden: a workspace's FFI
crates need it, and which crates may is ``dependencies.toml`` ``[rust.std] unsafe``'s (OWNER-DAG), not a lint's.
"""

from __future__ import annotations

from typing import Final

__all__ = ['CARGO_FILE', 'CARGO_SECTION_PREFIX', 'CARGO_SECTION_ROWS', 'CLIPPY_LINTS', 'RUST_LINTS']

CARGO_FILE: Final = 'Cargo.toml'
RUST_LINTS: Final = '[workspace.lints.rust]'
CLIPPY_LINTS: Final = '[workspace.lints.clippy]'
#: One home, as the pyproject tables: the tables live in the workspace manifest under their full path.
CARGO_SECTION_PREFIX: Final[tuple[str, ...]] = ()

#: ``(dotted path, EXACT scalars, SETS)``, the shape of every section rows table.
CARGO_SECTION_ROWS: Final[dict[str, tuple[tuple[str, ...], dict[str, object], dict[str, tuple[str, ...]]]]] = {
    RUST_LINTS: (
        ('workspace', 'lints', 'rust'),
        {'unsafe_op_in_unsafe_fn': 'deny', 'unused_must_use': 'deny'},
        {},
    ),
    CLIPPY_LINTS: (
        ('workspace', 'lints', 'clippy'),
        {
            'all': {'level': 'deny', 'priority': -1},
            'pedantic': {'level': 'warn', 'priority': -1},
            'dbg_macro': 'deny',
            'todo': 'deny',
        },
        {},
    ),
}
