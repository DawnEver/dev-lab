"""A GENERATED RUST RECORD'S METADATA: the admitted draft grammar as associated consts, read by a resolver.

Split out of :mod:`dev_lab.dev.irrust` (2026-11-28, MODULE-SIZE-ALARM): that module renders each record's type,
serde and ``validate()``; this one renders the consts (``REST`` ... ``DEFAULT_FROM``) beside them, and the Rust
string literal both spell text with. Enforcing the metadata is the resolver's, never ``validate``'s.
"""

from __future__ import annotations

import functools
import json
from typing import TYPE_CHECKING

from dev_lab.dev.ircheck import bounds, default_si

if TYPE_CHECKING:
    from dev_lab.dev.irmodel import IR, Record

__all__ = ['metadata', 'rust_str']


def rust_str(text: str) -> str:
    """*text* as a Rust string literal (catalogue text is one TOML line: only a backslash and a quote need escaping)."""
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _names(names: tuple[str, ...] | list[str]) -> str:
    return f'&[{", ".join(rust_str(n) for n in names)}]'


def _option(value: object) -> str:
    """``Some(<literal>)``, or ``None`` for an absent value (``None`` or an empty name)."""
    return (
        'None'
        if value is None or value == ''
        else f'Some({rust_str(value) if isinstance(value, str) else repr(value)})'
    )


def metadata(ir: IR, record: Record) -> list[str]:
    """The record's admitted metadata as associated consts: read by a resolver, never enforced by ``validate``."""
    text, names = "&'static str", "&'static [&'static str]"
    fields = record.fields

    def rows(items: list[tuple[object, ...]]) -> str:
        return '&[' + ', '.join('(' + ', '.join(_literal(v) for v in item) + ')' for item in items) + ']'

    limits = [(f.name, *bounds(ir, f)) for f in fields if f.minimum is not None or f.maximum is not None]
    canonical = functools.partial(json.dumps, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    consts = [
        ('The foreign type every undeclared key is kept as.', f'REST: Option<{text}>', _option(record.rest)),
        ('The field a bare string written for the record is.', f'STRING: Option<{text}>', _option(record.string)),
        ('The fields, in order, an entry written as an array is.', f'ARRAY: {names}', _names(record.array)),
        ('The fields a bare number written for the record fills.', f'FILL: {names}', _names(record.fill)),
        ('The optional fields of which exactly one is present.', f'ONE_OF: {names}', _names(record.one_of)),
        (
            '(field, the sibling it is written only beside).',
            f"REQUIRES: &'static [({text}, {text})]",
            rows([(f.name, f.requires) for f in fields if f.requires]),
        ),
        (
            'The list fields holding at least one entry.',
            f'NONEMPTY: {names}',
            _names([f.name for f in fields if f.nonempty]),
        ),
        (
            '(field, minimum, maximum) in absolute SI, either side open.',
            f"FIELD_BOUNDS: &'static [({text}, Option<f64>, Option<f64>)]",
            rows([(n, _option(lo), _option(hi)) for n, lo, hi in limits]),
        ),
        (
            '(field, its constant default as canonical JSON).',
            f"DEFAULTS: &'static [({text}, {text})]",
            rows([(f.name, canonical(default_si(ir, f))) for f in fields if f.default is not None]),
        ),
        (
            '(field, facet, scale, offset): an absent field is scale * facet + offset.',
            f"DEFAULT_FROM: &'static [({text}, {text}, f64, f64)]",
            rows([(f.name, d.facet, float(d.scale), float(d.offset)) for f in fields if (d := f.default_from)]),
        ),
    ]
    return [line for doc, decl, value in consts for line in (f'    /// {doc}', f'    pub const {decl} = {value};')]


def _literal(value: object) -> str:
    """A Rust literal: a str quoted, a float its round-trip ``repr``, a rendered ``Some(..)``/``None`` as is."""
    if isinstance(value, float):
        return repr(value)
    text = str(value)
    return text if text == 'None' or text.startswith('Some(') else rust_str(text)
