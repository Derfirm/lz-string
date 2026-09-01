// The oracle for differential checks: reads file paths (or a JSONL of strings) and prints
// hashes of what the real JavaScript library produced.
//
//   node tools/differential.mjs files  FILE...     # each file is a base64 lz-string payload
//   node tools/differential.mjs inputs FILE.jsonl  # one {"id":..,"input":..} per line
//
// Hashes are taken over the UTF-16LE form: the result need not be valid UTF-8, which is the
// whole reason lone surrogates are worth the trouble.
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";

const require = createRequire(import.meta.url);
const LZ = require("lz-string");

const sha = (s) => createHash("sha256").update(Buffer.from(s, "utf16le")).digest("hex").slice(0, 16);
const [mode, ...args] = process.argv.slice(2);

if (mode === "files") {
  for (const path of args) {
    const payload = readFileSync(path, "utf8");
    const text = LZ.decompressFromBase64(payload);
    process.stdout.write(JSON.stringify({
      path,
      decompressed: text === null ? null : sha(text),
      recompressed: text === null ? null : sha(LZ.compressToBase64(text)),
      length: text === null ? 0 : text.length,
    }) + "\n");
  }
} else if (mode === "inputs") {
  for (const line of readFileSync(args[0], "utf8").split("\n")) {
    if (!line.trim()) continue;
    const { id, input } = JSON.parse(line);
    process.stdout.write(JSON.stringify({
      id,
      base64: sha(LZ.compressToBase64(input)),
      uri: sha(LZ.compressToEncodedURIComponent(input)),
      utf16: sha(LZ.compressToUTF16(input)),
      raw: sha(LZ.compress(input)),
    }) + "\n");
  }
} else {
  console.error("usage: differential.mjs files FILE... | inputs FILE.jsonl");
  process.exit(2);
}
