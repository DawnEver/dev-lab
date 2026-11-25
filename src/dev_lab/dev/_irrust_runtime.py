"""THE RUST IR RUNTIME, as text: :mod:`dev_lab.dev.irrust` writes it once at the head of every generated ``ir.rs``.

It is the Rust twin of :mod:`dev_lab.dev._ir_runtime`: the validation error, the bound-dims map, base64 arrays in
little-endian C order, ``[re, im]`` complex values and the canonical JSON writer (sorted keys, Python ``repr``
floats). The canonical JSON writer is its second half, :mod:`dev_lab.dev._irrust_canonical`, appended
inside the module. Kept as a Python string because the declared layout admits no ``.rs`` file under ``src/``.
"""

from __future__ import annotations

from typing import Final

from dev_lab.dev._irrust_canonical import CANONICAL_RS

__all__ = ['RUNTIME_RS']

RUNTIME_RS: Final = (
    r"""
#[allow(dead_code)]
pub mod ir_runtime {
    use serde::{de::Error as _, Deserialize, Deserializer, Serialize, Serializer};
    use serde_json::Value;
    use std::collections::BTreeMap;
    use std::fmt::Write as _;

    #[derive(Debug, Clone, PartialEq)]
    pub struct IrValidationError {
        pub path: String,
        pub expected: String,
        pub got: String,
    }

    impl std::fmt::Display for IrValidationError {
        fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            write!(f, "{}: expected {}, got {}", self.path, self.expected, self.got)
        }
    }

    impl std::error::Error for IrValidationError {}

    pub type Dims = BTreeMap<String, (usize, String)>;
    pub type Res = Result<(), IrValidationError>;

    pub fn fail(path: &str, expected: impl Into<String>, got: impl Into<String>) -> Res {
        Err(IrValidationError { path: path.into(), expected: expected.into(), got: got.into() })
    }

    pub type Bounds = [(&'static str, Option<usize>, Option<usize>)];

    pub fn bind(dims: &mut Dims, name: &str, extent: usize, path: &str, low: Option<usize>, high: Option<usize>)
        -> Res {
        if let Some(low) = low {
            if extent < low {
                return fail(path, format!("{name} >= {low}"), extent.to_string());
            }
        }
        if let Some(high) = high {
            if extent > high {
                return fail(path, format!("{name} <= {high}"), extent.to_string());
            }
        }
        if let Some((bound, at)) = dims.get(name) {
            if *bound != extent {
                return fail(path, format!("{name} = {bound} (bound at {at})"), extent.to_string());
            }
            return Ok(());
        }
        dims.insert(name.into(), (extent, path.into()));
        Ok(())
    }

    pub fn finite(path: &str, value: f64) -> Res {
        if value.is_finite() { Ok(()) } else { fail(path, "a finite float (IR-NON-FINITE)", format!("{value}")) }
    }

    #[derive(Debug, Clone, Copy, PartialEq, Default)]
    pub struct Complex {
        pub re: f64,
        pub im: f64,
    }

    impl Serialize for Complex {
        fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
            [self.re, self.im].serialize(s)
        }
    }

    impl<'de> Deserialize<'de> for Complex {
        fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
            let [re, im] = <[f64; 2]>::deserialize(d)?;
            Ok(Complex { re, im })
        }
    }

    pub trait Elem: Copy + Default {
        const SIZE: usize;
        fn put(&self, out: &mut Vec<u8>);
        fn take(bytes: &[u8]) -> Self;
        fn finite(&self) -> bool { true }
    }

    macro_rules! elem {
        ($t:ty, $n:expr, $fin:expr) => {
            impl Elem for $t {
                const SIZE: usize = $n;
                fn put(&self, out: &mut Vec<u8>) { out.extend_from_slice(&self.to_le_bytes()); }
                fn take(bytes: &[u8]) -> Self { <$t>::from_le_bytes(bytes.try_into().unwrap()) }
                fn finite(&self) -> bool { $fin(*self) }
            }
        };
    }
    elem!(i32, 4, |_| true);
    elem!(i64, 8, |_| true);
    elem!(f32, 4, |v: f32| v.is_finite());
    elem!(f64, 8, |v: f64| v.is_finite());

    impl Elem for bool {
        const SIZE: usize = 1;
        fn put(&self, out: &mut Vec<u8>) { out.push(u8::from(*self)); }
        fn take(bytes: &[u8]) -> Self { bytes[0] != 0 }
    }

    impl Elem for Complex {
        const SIZE: usize = 16;
        fn put(&self, out: &mut Vec<u8>) { self.re.put(out); self.im.put(out); }
        fn take(bytes: &[u8]) -> Self { Complex { re: f64::take(&bytes[..8]), im: f64::take(&bytes[8..]) } }
        fn finite(&self) -> bool { self.re.is_finite() && self.im.is_finite() }
    }

    const B64: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

    pub fn b64_encode(raw: &[u8]) -> String {
        let mut out = String::with_capacity(raw.len().div_ceil(3) * 4);
        for chunk in raw.chunks(3) {
            let b = [chunk[0], *chunk.get(1).unwrap_or(&0), *chunk.get(2).unwrap_or(&0)];
            let n = (u32::from(b[0]) << 16) | (u32::from(b[1]) << 8) | u32::from(b[2]);
            for i in 0..4 {
                if i <= chunk.len() {
                    out.push(B64[((n >> (18 - 6 * i)) & 63) as usize] as char);
                } else {
                    out.push('=');
                }
            }
        }
        out
    }

    pub fn b64_decode(text: &str) -> Result<Vec<u8>, String> {
        let mut out = Vec::with_capacity(text.len() / 4 * 3);
        let digits: Vec<u8> = text.bytes().filter(|c| *c != b'=').collect();
        let value = |c: u8| B64.iter().position(|d| *d == c).map(|p| p as u32).ok_or_else(|| format!("bad base64 {c}"));
        for chunk in digits.chunks(4) {
            let mut n = 0u32;
            for (i, c) in chunk.iter().enumerate() {
                n |= value(*c)? << (18 - 6 * i);
            }
            for i in 0..chunk.len().saturating_sub(1) {
                out.push((n >> (16 - 8 * i)) as u8);
            }
        }
        Ok(out)
    }

    #[derive(Serialize, Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Wire {
        data: String,
        shape: Vec<usize>,
    }

    pub mod array {
        use super::*;
        use ndarray::ArrayD;

        pub fn serialize<T: Elem, S: Serializer>(a: &ArrayD<T>, s: S) -> Result<S::Ok, S::Error> {
            let mut raw = Vec::with_capacity(a.len() * T::SIZE);
            for v in a.iter() {
                v.put(&mut raw);
            }
            Wire { data: b64_encode(&raw), shape: a.shape().to_vec() }.serialize(s)
        }

        pub fn deserialize<'de, T: Elem, D: Deserializer<'de>>(d: D) -> Result<ArrayD<T>, D::Error> {
            let wire = Wire::deserialize(d)?;
            let raw = b64_decode(&wire.data).map_err(D::Error::custom)?;
            if raw.len() != wire.shape.iter().product::<usize>() * T::SIZE {
                return Err(D::Error::custom("array data does not fill its shape"));
            }
            let values: Vec<T> = raw.chunks(T::SIZE).map(T::take).collect();
            ArrayD::from_shape_vec(wire.shape, values).map_err(D::Error::custom)
        }
    }

    pub mod opt_array {
        use super::*;
        use ndarray::ArrayD;

        pub fn serialize<T: Elem, S: Serializer>(a: &Option<ArrayD<T>>, s: S) -> Result<S::Ok, S::Error> {
            match a {
                Some(a) => super::array::serialize(a, s),
                None => s.serialize_none(),
            }
        }

        pub fn deserialize<'de, T: Elem, D: Deserializer<'de>>(d: D) -> Result<Option<ArrayD<T>>, D::Error> {
            super::array::deserialize(d).map(Some)
        }
    }

    pub fn check_array<T: Elem>(
        a: &ndarray::ArrayD<T>,
        path: &str,
        shape: &[(Option<usize>, &str)],
        dims: &mut Dims,
        bounds: &Bounds,
    ) -> Res {
        if a.ndim() != shape.len() {
            return fail(&format!("{path}.ndim"), shape.len().to_string(), a.ndim().to_string());
        }
        for (axis, ((fixed, name), got)) in shape.iter().zip(a.shape()).enumerate() {
            let at = format!("{path}.shape[{axis}]");
            match fixed {
                Some(want) if want != got => return fail(&at, want.to_string(), got.to_string()),
                Some(_) => {}
                None => {
                    let (low, high) = bounds.iter().find(|b| b.0 == *name).map_or((None, None), |b| (b.1, b.2));
                    bind(dims, name, *got, &at, low, high)?;
                }
            }
        }
        if a.iter().all(Elem::finite) { Ok(()) } else { fail(path, "finite values (IR-NON-FINITE)", "NaN or infinity") }
    }

    pub fn check_csr(offsets: &ndarray::ArrayD<i64>, values_len: usize, path: &str) -> Res {
        let o: Vec<i64> = offsets.iter().copied().collect();
        match o.first() {
            None => return fail(&format!("{path}[0]"), "0", "nothing"),
            Some(first) if *first != 0 => return fail(&format!("{path}[0]"), "0", first.to_string()),
            _ => {}
        }
        if o.windows(2).any(|w| w[1] < w[0]) {
            return fail(path, "non-decreasing offsets", "a decrease");
        }
        let last = *o.last().unwrap();
        if last == values_len as i64 {
            return Ok(());
        }
        fail(&format!("{path}[-1]"), values_len.to_string(), last.to_string())
    }

    pub fn check_unique<K: Ord + Clone + std::fmt::Debug>(keys: Vec<K>, path: &str, key: &str) -> Res {
        let mut sorted = keys.clone();
        sorted.sort();
        for w in sorted.windows(2) {
            if w[0] == w[1] {
                return fail(path, format!("unique {key}"), format!("duplicate {:?}", w[0]).replace('"', "'"));
            }
        }
        Ok(())
    }

    pub fn sort_by_key(value: &mut Value, field: &str, key: &str) {
        if let Some(Value::Array(items)) = value.get_mut(field) {
            items.sort_by(|a, b| match (a[key].as_str(), b[key].as_str()) {
                (Some(x), Some(y)) => x.cmp(y),
                _ => a[key].as_i64().cmp(&b[key].as_i64()),
            });
        }
    }
"""
    + CANONICAL_RS
    + '}'
    + chr(10)
)
