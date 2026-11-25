"""THE RUST IR RUNTIME's second half, as text: the canonical JSON writer (sorted keys, Python ``repr`` floats).

:mod:`dev_lab.dev._irrust_runtime` appends it inside ``pub mod ir_runtime``; split out of that template (2026-11-25,
MODULE-SIZE-ALARM) at its own seam -- validation and arrays there, the byte-exact serialization here.
"""

from __future__ import annotations

from typing import Final

__all__ = ['CANONICAL_RS']

CANONICAL_RS: Final = r"""
    /// Python ``repr`` of a finite float: shortest round-trip digits, exponent form outside [1e-4, 1e16).
    pub fn py_float(x: f64) -> String {
        if x == 0.0 {
            return if x.is_sign_negative() { "-0.0".into() } else { "0.0".into() };
        }
        let sci = format!("{x:e}");
        let (mantissa, exp) = sci.split_once('e').unwrap();
        let exp: i32 = exp.parse().unwrap();
        let (sign, mantissa) = mantissa.strip_prefix('-').map_or(("", mantissa), |m| ("-", m));
        let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
        if (-4..16).contains(&exp) {
            let point = exp + 1;
            let body = if point <= 0 {
                format!("0.{}{}", "0".repeat((-point) as usize), digits)
            } else if point as usize >= digits.len() {
                format!("{}{}.0", digits, "0".repeat(point as usize - digits.len()))
            } else {
                format!("{}.{}", &digits[..point as usize], &digits[point as usize..])
            };
            format!("{sign}{body}")
        } else {
            let head = if digits.len() > 1 { format!("{}.{}", &digits[..1], &digits[1..]) } else { digits };
            format!("{sign}{head}e{}{:02}", if exp < 0 { '-' } else { '+' }, exp.abs())
        }
    }

    fn write_str(out: &mut String, s: &str) {
        out.push('"');
        for c in s.chars() {
            match c {
                '"' => out.push_str("\\\""),
                '\\' => out.push_str("\\\\"),
                '\n' => out.push_str("\\n"),
                '\r' => out.push_str("\\r"),
                '\t' => out.push_str("\\t"),
                '\u{08}' => out.push_str("\\b"),
                '\u{0c}' => out.push_str("\\f"),
                c if (c as u32) < 0x20 => { let _ = write!(out, "\\u{:04x}", c as u32); }
                c => out.push(c),
            }
        }
        out.push('"');
    }

    /// The canonical bytes of a JSON tree (docs-src/dev/ir-schema.md, "Canonical serialization").
    pub fn canonical(value: &Value, out: &mut String) {
        match value {
            Value::Null => out.push_str("null"),
            Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
            Value::Number(n) => match (n.as_i64(), n.as_u64()) {
                (Some(i), _) if !n.is_f64() => { let _ = write!(out, "{i}"); }
                (_, Some(u)) if !n.is_f64() => { let _ = write!(out, "{u}"); }
                _ => out.push_str(&py_float(n.as_f64().unwrap())),
            },
            Value::String(s) => write_str(out, s),
            Value::Array(items) => {
                out.push('[');
                for (i, v) in items.iter().enumerate() {
                    if i > 0 { out.push(','); }
                    canonical(v, out);
                }
                out.push(']');
            }
            Value::Object(map) => {
                let mut keys: Vec<&String> = map.keys().collect();
                keys.sort();
                out.push('{');
                for (i, k) in keys.into_iter().enumerate() {
                    if i > 0 { out.push(','); }
                    write_str(out, k);
                    out.push(':');
                    canonical(&map[k], out);
                }
                out.push('}');
            }
        }
    }
"""
