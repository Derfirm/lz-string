//! The decoder, ported from the JavaScript reference rather than wrapped.
//!
//! The obvious alternative, the `lz-str` crate, answers `None` for two different failures
//! that the reference keeps apart:
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

    fn len(&self) -> usize {
        self.values.len()
    }
}

/// `None` means "not an lz-string payload"; `Some(empty)` means the stream ran out.
pub fn decompress(values: Vec<u32>, width: u32) -> Option<Vec<u16>> {
    if values.is_empty() {
        return Some(Vec::new());
    }
    let mut stream = BitStream::new(values, width);

    // The dictionary holds ranges into `result` rather than copies of the entries. Every
    // entry is a run that has already been written out — the one defined each round is the
    // previous entry plus the first unit of this one, and those sit next to each other in
    // the output — so an entry is (offset, length) and never a buffer of its own. Cloning a
    // Vec per token instead costs an allocation and a copy on every one of the million-odd
    // tokens a large save decodes to.
    let mut result: Vec<u16> = Vec::with_capacity(stream.len() * 2);
    let mut dictionary: Vec<(usize, usize)> = vec![(0, 0), (0, 0), (0, 0)];

    let first = match stream.read(2) {
        0 => stream.read(8) as u16,
        1 => stream.read(16) as u16,
        2 => return Some(Vec::new()),
        // A header the format cannot produce. The reference carries a JavaScript
        // `undefined` into its dictionary from here and blunders on; see SPEC.md §4.
        _ => return None,
    };

    result.push(first);
    dictionary.push((0, 1));
    let mut w: (usize, usize) = (0, 1);
    let mut enlarge_in: u32 = 4;
    let mut dict_size: usize = 4;
    let mut num_bits: u32 = 3;

    loop {
        if stream.read_past_the_end() {
            return Some(Vec::new());
        }
        let mut code = stream.read(num_bits) as usize;
        let mut fresh_unit = None;
        match code {
            0 | 1 => {
                fresh_unit = Some(if code == 0 {
                    stream.read(8)
                } else {
                    stream.read(16)
                } as u16);
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

        // Write the entry this token stands for, and note where it landed.
        let at = result.len();
        if let Some(unit) = fresh_unit {
            // A unit seen for the first time: its entry is the single character itself.
            result.push(unit);
            dictionary.push((at, 1));
        } else if code < dictionary.len() {
            let (offset, length) = dictionary[code];
            result.extend_from_within(offset..offset + length);
        } else if code == dict_size {
            // The standard LZW case: the entry this very token is about to define.
            result.extend_from_within(w.0..w.0 + w.1);
            result.push(result[w.0]);
        } else {
            return None;
        }
        let entry = (at, result.len() - at);

        // The entry defined this round is the previous one plus the first unit of this one,
        // which is exactly the run starting where the previous entry did, one unit longer.
        dictionary.push((w.0, w.1 + 1));
        dict_size += 1;
        enlarge_in -= 1;
        w = entry;

        if enlarge_in == 0 {
            enlarge_in = 1 << num_bits;
            num_bits += 1;
        }
    }
}
