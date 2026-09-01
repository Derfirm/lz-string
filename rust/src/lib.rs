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

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

/// The 62 characters both six-bit alphabets share, and "+", which is 62 in both.
///
/// Anything outside an alphabet reads as zero — including the 65th character each one has
/// ("=" and "$"), which the reference maps to 64, a value no six-bit read can return. Zero
/// bits, but still one character of the length the decoder may read: that difference is what
/// makes skipping such a character wrong.
fn shared_value(c: u32) -> u32 {
    match c {
        0x41..=0x5A => c - 0x41,      // A-Z
        0x61..=0x7A => c - 0x61 + 26, // a-z
        0x30..=0x39 => c - 0x30 + 52, // 0-9
        0x2B => 62,                   // "+"
        _ => 0,
    }
}

fn base64_value(unit: u16) -> u32 {
    match u32::from(unit) {
        0x2F => 63, // "/"
        c => shared_value(c),
    }
}

fn uri_value(unit: u16) -> u32 {
    match u32::from(unit) {
        0x2D => 63, // "-", where base64 has "/"
        // A payload that travelled through a query string has its "+" turned into a space.
        0x20 => 62,
        c => shared_value(c),
    }
}

fn utf16_value(unit: u16) -> u32 {
    // The wrapping subtraction is the point: a character below the +32 offset contributes
    // its two's complement, exactly as the reference's `value - 32` does in JavaScript. The
    // reader examines only the low 15 bits, like `value & position`.
    u32::from(unit).wrapping_sub(32)
}

/// UTF-16LE bytes in, code units out.
///
/// An odd length is refused rather than rounded down. `chunks_exact` would drop the stray
/// byte, and compressing "A" would then produce the compression of "" — a silent wrong
/// answer on a boundary the Python wrapper cannot currently produce but a caller of the
/// extension can.
fn code_units(buf: &[u8]) -> PyResult<impl Iterator<Item = u16> + '_> {
    if !buf.len().is_multiple_of(2) {
        return Err(PyValueError::new_err(
            "expected UTF-16LE bytes, whose length is even",
        ));
    }
    Ok(buf
        .chunks_exact(2)
        .map(|c| u16::from_le_bytes([c[0], c[1]])))
}

fn to_units(buf: &[u8]) -> PyResult<Vec<u16>> {
    Ok(code_units(buf)?.collect())
}

/// The same, widened to the decoder's value type in one pass rather than two.
fn to_values(buf: &[u8], value_of: fn(u16) -> u32) -> PyResult<Vec<u32>> {
    Ok(code_units(buf)?.map(value_of).collect())
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
fn compress(py: Python<'_>, data: &[u8]) -> PyResult<Py<PyBytes>> {
    let units = to_units(data)?;
    let out = py.detach(|| lz_str::compress(units));
    Ok(from_units(py, out))
}

#[pyfunction]
fn compress_to_base64(py: Python<'_>, data: &[u8]) -> PyResult<String> {
    let units = to_units(data)?;
    let packed = py.detach(|| lz_str::compress_to_base64(units));
    // lz-str appends one "=" too many; re-pad by the reference's rule.
    let packed = packed.trim_end_matches('=');
    let padding = (4 - packed.len() % 4) % 4;
    Ok(format!("{packed}{}", "=".repeat(padding)))
}

#[pyfunction]
fn compress_to_encoded_uri_component(py: Python<'_>, data: &[u8]) -> PyResult<String> {
    let units = to_units(data)?;
    Ok(py.detach(|| lz_str::compress_to_encoded_uri_component(units)))
}

#[pyfunction]
fn compress_to_utf16(py: Python<'_>, data: &[u8]) -> PyResult<String> {
    let units = to_units(data)?;
    Ok(py.detach(|| lz_str::compress_to_utf16(units)))
}

#[pyfunction]
fn decompress(py: Python<'_>, data: &[u8]) -> PyResult<Option<Py<PyBytes>>> {
    let values = to_values(data, u32::from)?;
    Ok(answer(py, py.detach(|| decode::decompress(values, 16))))
}

#[pyfunction]
fn decompress_from_base64(py: Python<'_>, data: &[u8]) -> PyResult<Option<Py<PyBytes>>> {
    let values = to_values(data, base64_value)?;
    Ok(answer(py, py.detach(|| decode::decompress(values, 6))))
}

#[pyfunction]
fn decompress_from_encoded_uri_component(
    py: Python<'_>,
    data: &[u8],
) -> PyResult<Option<Py<PyBytes>>> {
    let values = to_values(data, uri_value)?;
    Ok(answer(py, py.detach(|| decode::decompress(values, 6))))
}

#[pyfunction]
fn decompress_from_utf16(py: Python<'_>, data: &[u8]) -> PyResult<Option<Py<PyBytes>>> {
    let values = to_values(data, utf16_value)?;
    Ok(answer(py, py.detach(|| decode::decompress(values, 15))))
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
