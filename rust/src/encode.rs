//! The encoder, ported from the JavaScript reference rather than wrapped.
//!
//! The algorithm is LZW over UTF-16 code units, and the reference keys its dictionary by the
//! matched string: every step builds `w + c` and looks that up, which in a typed language
//! means allocating a growable buffer per prefix. The `lz-str` crate inherited that shape,
//! and it is what kept compression an order of magnitude behind decompression here.
//!
//! A prefix is always either a single unit or an entry already in the dictionary, so it is
//! identified by its code, and the lookup becomes `(code of w, c)` — two integers. Nothing
//! about the output changes: the bit stream is emitted in exactly the order the reference
//! emits it, which the golden corpus checks to the byte.

use std::collections::HashMap;

/// Token 0 introduces a unit below 256, token 1 one above it, token 2 ends the stream.
const NEW_UNIT_BELOW_256: u32 = 0;
const NEW_UNIT: u32 = 1;
const END_OF_STREAM: u32 = 2;

/// Packs values into characters of `width` bits, least significant bit of a value first.
struct BitWriter {
    width: u32,
    out: Vec<u32>,
    value: u32,
    filled: u32,
}

impl BitWriter {
    fn new(width: u32, hint: usize) -> Self {
        BitWriter {
            width,
            out: Vec::with_capacity(hint),
            value: 0,
            filled: 0,
        }
    }

    fn write(&mut self, mut value: u32, bits: u32) {
        for _ in 0..bits {
            self.value = (self.value << 1) | (value & 1);
            value >>= 1;
            if self.filled == self.width - 1 {
                self.filled = 0;
                self.out.push(self.value);
                self.value = 0;
            } else {
                self.filled += 1;
            }
        }
    }

    /// Flush, the way the reference does: shift until the character is full and emit it —
    /// unconditionally, so a stream that ends on a boundary still gets one all-zero
    /// character. Skip that and the reference decoder walks off the end of the payload.
    fn finish(mut self) -> Vec<u32> {
        loop {
            self.value <<= 1;
            if self.filled == self.width - 1 {
                self.out.push(self.value);
                break;
            }
            self.filled += 1;
        }
        self.out
    }
}

pub fn compress(units: &[u16], width: u32) -> Vec<u32> {
    let mut writer = BitWriter::new(width, units.len() / 2 + 4);
    if units.is_empty() {
        writer.write(END_OF_STREAM, 2);
        return writer.finish();
    }

    // Codes for single units, and for pairs (prefix, unit) — the two ways the reference's
    // string-keyed dictionary is ever consulted.
    let mut singles: HashMap<u16, u32> = HashMap::new();
    let mut pairs: HashMap<(u32, u16), u32> = HashMap::with_capacity(units.len() / 2);
    // Units seen but not yet written out. The reference keeps whole strings here; only
    // single units ever land in it.
    let mut unwritten: HashMap<u16, bool> = HashMap::new();

    let mut dict_size: u32 = 3;
    let mut num_bits: u32 = 2;
    let mut enlarge_in: u32 = 2; // compensates for the first entry, which must not count

    // The prefix: its code, and the unit it is if it is a single one.
    let mut w_code: u32 = 0;
    let mut w_unit: Option<u16> = None;
    let mut started = false;

    let emit = |writer: &mut BitWriter,
                w_code: u32,
                w_unit: Option<u16>,
                unwritten: &mut HashMap<u16, bool>,
                num_bits: &mut u32,
                enlarge_in: &mut u32| {
        let pending = w_unit.is_some_and(|unit| unwritten.remove(&unit).is_some());
        if pending {
            let unit = w_unit.expect("a pending prefix is a single unit");
            if unit < 256 {
                writer.write(NEW_UNIT_BELOW_256, *num_bits);
                writer.write(u32::from(unit), 8);
            } else {
                writer.write(NEW_UNIT, *num_bits);
                writer.write(u32::from(unit), 16);
            }
            *enlarge_in -= 1;
            if *enlarge_in == 0 {
                *enlarge_in = 1 << *num_bits;
                *num_bits += 1;
            }
        } else {
            writer.write(w_code, *num_bits);
        }
        *enlarge_in -= 1;
        if *enlarge_in == 0 {
            *enlarge_in = 1 << *num_bits;
            *num_bits += 1;
        }
    };

    for &unit in units {
        let unit_code = *singles.entry(unit).or_insert_with(|| {
            unwritten.insert(unit, true);
            dict_size += 1;
            dict_size - 1
        });

        if !started {
            w_code = unit_code;
            w_unit = Some(unit);
            started = true;
            continue;
        }

        if let Some(&code) = pairs.get(&(w_code, unit)) {
            w_code = code;
            w_unit = None;
            continue;
        }

        emit(
            &mut writer,
            w_code,
            w_unit,
            &mut unwritten,
            &mut num_bits,
            &mut enlarge_in,
        );
        pairs.insert((w_code, unit), dict_size);
        dict_size += 1;
        w_code = unit_code;
        w_unit = Some(unit);
    }

    if started {
        emit(
            &mut writer,
            w_code,
            w_unit,
            &mut unwritten,
            &mut num_bits,
            &mut enlarge_in,
        );
    }

    writer.write(END_OF_STREAM, num_bits);
    writer.finish()
}
