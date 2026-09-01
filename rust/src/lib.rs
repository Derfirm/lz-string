//! Compression comes from the `lz-str` crate; decompression is ours (see `decode`).
//!
//! The crate's compressor is byte-identical to the JavaScript reference on every payload
//! measured — 1202 golden vectors, 5000 fuzzed inputs, 38 real saves — apart from base64
//! padding, corrected below. Its decompressor is not: it skips characters outside the
//! alphabet where the reference reads them as zero bits and still counts them, and it
//! collapses the reference's two distinct failures into one answer. Both matter only on
//! damaged input, and both are invisible until you fuzz against node.
//!
//! Every string crosses the FFI boundary as UTF-16LE bytes, decoders included: pyo3 cannot
//! build a Rust `&str` from a Python string holding a lone surrogate, and would raise
//! UnicodeEncodeError where the reference simply answers. lz-string is defined over UTF-16 code
//! units and real saves carry lone surrogates — a Degrees of Lewdity journal is made of
//! them — so the crate returns `Vec<u16>` and Python does the decoding with
//! `errors="surrogatepass"`. `String::from_utf16_lossy` here would replace such a unit with
//! U+FFFD and destroy the save it was in.
mod decode;

use pyo3::prelude::*;
use pyo3::types::PyBytes;

/// Value of a character in a six-bit alphabet.
///
/// Anything outside it reads as zero — including the 65th character of each alphabet ("="
/// and "$"), which the reference maps to 64, a value no six-bit read can return. Zero bits,
/// but still one character of the length the decoder is allowed to read: that difference is
/// what makes skipping such a character wrong.
fn six_bit_value(unit: u16, uri: bool) -> u32 {
    let c = u32::from(unit);
    match c {
        0x41..=0x5A => c - 0x41,      // A-Z
        0x61..=0x7A => c - 0x61 + 26, // a-z
        0x30..=0x39 => c - 0x30 + 52, // 0-9
        0x2B => 62,                   // "+"
        // A payload that travelled through a query string has its "+" turned into a space.
        0x20 if uri => 62,
        0x2F if !uri => 63, // "/"
        0x2D if uri => 63,  // "-"
        _ => 0,
    }
}

fn to_units(buf: &[u8]) -> Vec<u16> {
    buf.chunks_exact(2)
        .map(|c| u16::from_le_bytes([c[0], c[1]]))
        .collect()
}

fn from_units(py: Python<'_>, units: Vec<u16>) -> Py<PyBytes> {
    let mut out = Vec::with_capacity(units.len() * 2);
    for u in units {
        out.extend_from_slice(&u.to_le_bytes());
    }
    PyBytes::new(py, &out).unbind()
}

/// The three answers of the format become two Python values: `None` for "not an lz-string
/// payload", and bytes — possibly empty — for everything the reference returns as a string.
fn answer(py: Python<'_>, units: Option<Vec<u16>>) -> Option<Py<PyBytes>> {
    units.map(|units| from_units(py, units))
}

// Every entry point below converts its argument into owned Rust data first and only then
// hands the work to `detach`. Holding the GIL through a multi-second compression
// would make the obvious remedy — running the call in a thread — do nothing at all: the
// worker thread would hold the interpreter and every other request would still wait.
#[pyfunction]
fn compress(py: Python<'_>, data: &[u8]) -> Py<PyBytes> {
    let units = to_units(data);
    let out = py.detach(|| lz_str::compress(units));
    from_units(py, out)
}

#[pyfunction]
fn compress_to_base64(py: Python<'_>, data: &[u8]) -> String {
    let units = to_units(data);
    let packed = py.detach(|| lz_str::compress_to_base64(units));
    // lz-str appends one "=" too many; re-pad by the reference's rule.
    let packed = packed.trim_end_matches('=');
    let padding = (4 - packed.len() % 4) % 4;
    format!("{packed}{}", "=".repeat(padding))
}

#[pyfunction]
fn compress_to_encoded_uri_component(py: Python<'_>, data: &[u8]) -> String {
    let units = to_units(data);
    py.detach(|| lz_str::compress_to_encoded_uri_component(units))
}

#[pyfunction]
fn compress_to_utf16(py: Python<'_>, data: &[u8]) -> String {
    let units = to_units(data);
    py.detach(|| lz_str::compress_to_utf16(units))
}

#[pyfunction]
fn decompress(py: Python<'_>, data: &[u8]) -> Option<Py<PyBytes>> {
    let values: Vec<u32> = to_units(data).into_iter().map(u32::from).collect();
    answer(py, py.detach(|| decode::decompress(values, 16)))
}

#[pyfunction]
fn decompress_from_base64(py: Python<'_>, data: &[u8]) -> Option<Py<PyBytes>> {
    let values: Vec<u32> = to_units(data)
        .into_iter()
        .map(|u| six_bit_value(u, false))
        .collect();
    answer(py, py.detach(|| decode::decompress(values, 6)))
}

#[pyfunction]
fn decompress_from_encoded_uri_component(py: Python<'_>, data: &[u8]) -> Option<Py<PyBytes>> {
    let values: Vec<u32> = to_units(data)
        .into_iter()
        .map(|u| six_bit_value(u, true))
        .collect();
    answer(py, py.detach(|| decode::decompress(values, 6)))
}

#[pyfunction]
fn decompress_from_utf16(py: Python<'_>, data: &[u8]) -> Option<Py<PyBytes>> {
    // The wrapping subtraction is the point: a character below the +32 offset contributes
    // its two's complement, exactly as the reference's `value - 32` does in JavaScript. No
    // masking to 15 bits — the reader examines only that many, like `value & position`.
    let values: Vec<u32> = to_units(data)
        .into_iter()
        .map(|u| u32::from(u).wrapping_sub(32))
        .collect();
    answer(py, py.detach(|| decode::decompress(values, 15)))
}

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(compress, m)?)?;
    m.add_function(wrap_pyfunction!(compress_to_base64, m)?)?;
    m.add_function(wrap_pyfunction!(compress_to_encoded_uri_component, m)?)?;
    m.add_function(wrap_pyfunction!(compress_to_utf16, m)?)?;
    m.add_function(wrap_pyfunction!(decompress, m)?)?;
    m.add_function(wrap_pyfunction!(decompress_from_base64, m)?)?;
    m.add_function(wrap_pyfunction!(decompress_from_encoded_uri_component, m)?)?;
    m.add_function(wrap_pyfunction!(decompress_from_utf16, m)?)?;
    Ok(())
}
