//! The decoder, ported from the JavaScript reference rather than wrapped.
//!
//! `lz-str` is kept for compression, where it is byte-identical to the reference, but its
//! decoder answers `None` for two different failures that the reference keeps apart:
//!
//!   * the stream ran out before the end marker — a truncated or nonsense payload, `""`;
//!   * a token named a dictionary entry no encoder could have written — not an lz-string
//!     payload at all, `null`.
//!
//! Callers care which, and the distinction cannot be recovered from outside the loop. So
//! the loop lives here, structured the way the original is: bits are read one at a time
//! through a mask, reading past the end yields zeros, and the decoder stops when it has
//! fetched more characters than the input has — which is what lets a payload whose final,
//! all-padding character was trimmed still decode.

/// Reads the bit stream exactly as the reference does: most significant bit of each
/// character first, least significant bit of each value first.
struct BitStream {
    values: Vec<u32>,
    width: u32,
    index: usize,
    val: u32,
    position: u32,
}

impl BitStream {
    fn new(values: Vec<u32>, width: u32) -> Self {
        let val = values.first().copied().unwrap_or(0);
        BitStream {
            values,
            width,
            index: 1,
            val,
            position: 1 << (width - 1),
        }
    }

    /// Only the low `width` bits of a character are ever examined, which is what the
    /// reference's `value & position` amounts to: a character outside the transport's range
    /// contributes its low bits and nothing more.
    fn read(&mut self, bits: u32) -> u32 {
        let mut value = 0;
        let mut power = 1;
        for _ in 0..bits {
            let bit = self.val & self.position;
            self.position >>= 1;
            if self.position == 0 {
                self.position = 1 << (self.width - 1);
                // Past the end the reference reads `undefined`, which ANDs to zero. It does
                // not stop here; it stops at the length check between tokens.
                self.val = self.values.get(self.index).copied().unwrap_or(0);
                self.index += 1;
            }
            if bit > 0 {
                value |= power;
            }
            power <<= 1;
        }
        value
    }

    fn read_past_the_end(&self) -> bool {
        self.index > self.values.len()
    }
}

/// `None` means "not an lz-string payload"; `Some(empty)` means the stream ran out.
pub fn decompress(values: Vec<u32>, width: u32) -> Option<Vec<u16>> {
    if values.is_empty() {
        return Some(Vec::new());
    }
    let mut stream = BitStream::new(values, width);

    // Entries 0..2 are the reserved tokens and are never looked up as text.
    let mut dictionary: Vec<Vec<u16>> = vec![Vec::new(), Vec::new(), Vec::new()];
    let first = match stream.read(2) {
        0 => stream.read(8) as u16,
        1 => stream.read(16) as u16,
        2 => return Some(Vec::new()),
        // A header the format cannot produce. The reference carries a JavaScript
        // `undefined` into its dictionary from here and blunders on; see SPEC.md §4.
        _ => return None,
    };

    dictionary.push(vec![first]);
    let mut result: Vec<u16> = vec![first];
    let mut w: Vec<u16> = vec![first];
    let mut enlarge_in: u32 = 4;
    let mut dict_size: usize = 4;
    let mut num_bits: u32 = 3;

    loop {
        if stream.read_past_the_end() {
            return Some(Vec::new());
        }
        let mut code = stream.read(num_bits) as usize;
        match code {
            0 | 1 => {
                let unit = if code == 0 {
                    stream.read(8)
                } else {
                    stream.read(16)
                } as u16;
                dictionary.push(vec![unit]);
                code = dict_size;
                dict_size += 1;
                enlarge_in -= 1;
            }
            2 => return Some(result),
            _ => {}
        }

        if enlarge_in == 0 {
            enlarge_in = 1 << num_bits;
            num_bits += 1;
        }

        let entry = if code < dictionary.len() {
            dictionary[code].clone()
        } else if code == dict_size {
            // The standard LZW case: the entry being defined by this very token.
            let mut entry = w.clone();
            entry.push(w[0]);
            entry
        } else {
            return None;
        };

        result.extend_from_slice(&entry);
        let mut new_entry = w;
        new_entry.push(entry[0]);
        dictionary.push(new_entry);
        dict_size += 1;
        enlarge_in -= 1;
        w = entry;

        if enlarge_in == 0 {
            enlarge_in = 1 << num_bits;
            num_bits += 1;
        }
    }
}
