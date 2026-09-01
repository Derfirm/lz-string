//! The bindings. Both halves of the codec are ours: `encode` and `decode`.
//!
//! This module is the boundary and nothing more — it turns Python's bytes into code units,
//! hands them to the codec with the interpreter released, and turns the answer back. The
//! transports differ only in how many bits a character carries and which alphabet spells
//! them, so that mapping lives here too.
//!
//! Every string crosses the FFI boundary as UTF-16LE bytes, decoders included: pyo3 cannot
//! build a Rust `&str` from a Python string holding a lone surrogate, and would raise
//! UnicodeEncodeError where the reference simply answers. Lone surrogates are ordinary input
//! here — a Twine journal is made of them — so Python does the decoding with
//! `errors="surrogatepass"` rather than letting Rust rebuild a String and lose them. lz-string is defined over UTF-16 code
//! units and real saves carry lone surrogates — a Degrees of Lewdity journal is made of

mod decode;
mod encode;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

/// The 62 characters both six-bit alphabets share, and "+", which is 62 in both.
///
/// Anything outside an alphabet reads as zero — including the 65th character each one has
/// ("=" and "$"), which the reference maps to 64, a value no six-bit read can return. Zero
/// bits, but still one character of the length the decoder may read: that difference is what
/// makes skipping such a character wrong.
/// The alphabets, as tables for the encoder; `shared_value` below is their inverse.
const BASE64: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
const URI: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-";

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
/// An odd length is refused rather than rounded down. Chunking alone would drop the stray
/// byte, and compressing "A" would then produce the compression of "" — a silent wrong
/// answer on a boundary the Python wrapper cannot currently produce but a caller of the
/// extension can.
fn code_units(buf: &[u8]) -> PyResult<impl Iterator<Item = u16> + '_> {
    if !buf.len().is_multiple_of(2) {
        return Err(PyValueError::new_err(
            "expected UTF-16LE bytes, whose length is even",
        ));
    }
    let (pairs, rest) = buf.as_chunks::<2>();
    debug_assert!(rest.is_empty(), "the length was checked just above");
    Ok(pairs
        .iter()
        .map(|&[low, high]| u16::from_le_bytes([low, high])))
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
    // 16 bits per character: the values are the code units themselves.
    let values = py.detach(|| encode::compress(&units, 16));
    Ok(from_units(
        py,
        values.into_iter().map(|v| v as u16).collect(),
    ))
}

#[pyfunction]
fn compress_to_base64(py: Python<'_>, data: &[u8]) -> PyResult<String> {
    let units = to_units(data)?;
    let values = py.detach(|| encode::compress(&units, 6));
    let mut packed: String = values.iter().map(|&v| BASE64[v as usize] as char).collect();
    // Padded to a multiple of four, as the reference does, and for the same reason: what
    // comes out has to be valid base64.
    packed.push_str(&"=".repeat((4 - packed.len() % 4) % 4));
    Ok(packed)
}

#[pyfunction]
fn compress_to_encoded_uri_component(py: Python<'_>, data: &[u8]) -> PyResult<String> {
    let units = to_units(data)?;
    let values = py.detach(|| encode::compress(&units, 6));
    Ok(values.iter().map(|&v| URI[v as usize] as char).collect())
}

#[pyfunction]
fn compress_to_utf16(py: Python<'_>, data: &[u8]) -> PyResult<String> {
    let units = to_units(data)?;
    let values = py.detach(|| encode::compress(&units, 15));
    // The offset keeps every character printable, and the trailing space is part of the
    // format: the reference appends one unconditionally.
    let mut out: String = values
        .iter()
        .map(|&v| char::from_u32(v + 32).expect("15 bits plus 32 is always a character"))
        .collect();
    out.push(' ');
    Ok(out)
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
