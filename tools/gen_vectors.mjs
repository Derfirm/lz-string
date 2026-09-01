// Builds the golden corpus with the reference JavaScript implementation of lz-string.
//
// The oracle is JavaScript itself: the files this exists to read are written by games
// running that very library. The PyPI Python package cannot be the oracle — it has bugs
// of its own (see SPEC.md, "Divergences in other implementations").
//
//   npm --prefix tools install       # once
//   node tools/gen_vectors.mjs       # -> tests/data/vectors.jsonl.gz
import { createRequire } from "node:module";
import { writeFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const LZ = require("lz-string");
const version = require("lz-string/package.json").version;
const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "tests", "data", "vectors.jsonl.gz");

// A deterministic PRNG: the corpus must reproduce byte for byte.
let seed = 20260901;
const rnd = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
const pick = (a) => a[Math.floor(rnd() * a.length)];
const times = (n, f) => Array.from({ length: n }, (_, i) => f(i));
const ch = (c) => String.fromCharCode(c);

const cases = [];
const add = (group, input) => cases.push({ group, input });

// 1. Degenerate inputs: empty, one character, repeats, control characters, boundaries.
["", "a", "aa", "ab", "aaa", "abab", "aab", " ", "a".repeat(64), "ab".repeat(64), " ".repeat(100)]
  .concat([0, 1, 9, 10, 13, 27, 127, 0x00ff, 0xfffe, 0xffff].map(ch))
  .forEach((s) => add("edge", s));

// 2. A sweep of all 65536 code units in blocks of 256 — which includes the lone
//    surrogates (0xD800..0xDFFF), ordinary input as far as lz-string is concerned.
for (let base = 0; base < 0x10000; base += 256) {
  add("codeunit-sweep", times(256, (i) => ch(base + i)).join(""));
}

// 3. Random ASCII and JSON-shaped strings of assorted lengths.
const words = ["gold", "hp", "mp", "level", "switches", "variables", "actors", "party",
               "true", "false", "null", "0", "1", "9999", "Marie", "Almaria"];
times(400, () => {
  const n = 1 + Math.floor(rnd() * 400);
  add("random-ascii", times(n, () => pick(words) + pick([":", ",", '"', "{", "}", "[", "]", " "])).join(""));
});

// 4. Highly compressible, and not compressible at all.
times(60, () => add("repetitive",
  pick(["ab", "hello world ", '{"a":1},']).repeat(1 + Math.floor(rnd() * 500))));
times(60, () => add("incompressible",
  times(1 + Math.floor(rnd() * 500), () => ch(32 + Math.floor(rnd() * 95))).join("")));

// 5. Unicode: CJK, emoji (surrogate pairs), RTL, combining marks.
const uni = ["中文字符", "日本語のテキスト", "한국어", "Привет", "مرحبا", "😀🎮🗡", "ȩ", "🌈"];
times(200, () => add("unicode",
  times(1 + Math.floor(rnd() * 60), () => pick(uni)).join(pick(["", " ", ","]))));

// 6. Lone surrogates — the reason the API works in code units rather than UTF-8.
times(100, () => {
  const lone = ch(0xd800 + Math.floor(rnd() * 0x800));
  const tail = ch(0xdc00 + Math.floor(rnd() * 0x400));
  add("lone-surrogate", pick([
    `{"journal":"abc${lone}def"}`,
    `${lone}`,
    `${tail}${lone}`,                       // a surrogate pair in the wrong order
    `x${lone}${lone}y`,
    `${"a".repeat(50)}${lone}${"b".repeat(50)}`,
  ]));
});

// 7. The shape of a real save: nested JSON with JsonEx @-markers and numbers.
const saveish = (n) => JSON.stringify({
  system: { "@": "Game_System", _saveCount: Math.floor(rnd() * 1000), _versionId: Math.floor(rnd() * 1e9) },
  party: { "@": "Game_Party", _gold: Math.floor(rnd() * 1e7),
           _items: Object.fromEntries(times(n, (i) => [i, Math.floor(rnd() * 99)])) },
  switches: { "@": "Game_Switches", _data: times(n, () => rnd() > 0.5) },
  variables: { "@": "Game_Variables", _data: times(n, () => Math.floor(rnd() * 1e6)) },
  text: times(Math.min(n, 40), () => pick(uni)).join(" "),
});
times(100, () => add("save-shaped", saveish(1 + Math.floor(rnd() * 200))));

// 8. A few large ones, where dictionary growth and the numBits steps show up.
[20000, 60000, 120000].forEach((n) => add("large", saveish(n / 40)));
add("large", times(6, () => saveish(3000)).join(""));   // ~250 KB: the dictionary really grows
add("large", (" " + ch(0xffff)).repeat(30000));

const rows = cases.map(({ group, input }, id) => ({
  id, group, input,
  base64: LZ.compressToBase64(input),
  uri: LZ.compressToEncodedURIComponent(input),
  utf16: LZ.compressToUTF16(input),
  raw: LZ.compress(input),
}));

const header = { generator: "lz-string", version, seed, count: rows.length };
const body = [JSON.stringify(header), ...rows.map((r) => JSON.stringify(r))].join("\n") + "\n";
const gz = gzipSync(Buffer.from(body, "utf8"), { level: 9 });
writeFileSync(OUT, gz);
const groups = rows.reduce((a, r) => ((a[r.group] = (a[r.group] || 0) + 1), a), {});
console.log(`lz-string ${version}: ${rows.length} vectors, ${(body.length / 1e6).toFixed(1)} MB`
            + ` -> gz ${(gz.length / 1e6).toFixed(2)} MB`);
console.log(groups);
